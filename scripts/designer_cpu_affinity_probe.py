"""Root-run OS scheduling control. No SDK imports; one fixed smoke, no replay.

Requires the independently observed GetProcessTimes creation FILETIME. CPU affinity
is an OS scheduling restriction, NOT an engine-thread-count/determinism guarantee.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import runpy
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PID = 86996
EXE = Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/Adobe Substance 3D Designer.exe')
EXPECTED_MASK = 65535
SECONDS = 60


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


class WindowsProcess:
    """Retain one handle from identity validation through verified restoration."""
    def __init__(self, pid):
        if os.name != 'nt':
            raise RuntimeError('Windows only')
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        definitions = {
            'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            'GetProcessId': ([wintypes.HANDLE], wintypes.DWORD),
            'GetExitCodeProcess': ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            'QueryFullProcessImageNameW': ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            'GetProcessTimes': ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
            'GetProcessAffinityMask': ([wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
            'SetProcessAffinityMask': ([wintypes.HANDLE, ctypes.c_size_t], wintypes.BOOL),
            'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in definitions.items():
            function = getattr(api, name)
            function.argtypes, function.restype = arguments, result
        self.api = api
        self.handle = api.OpenProcess(0x0400 | 0x0200, False, pid)
        self.check(self.handle)

    @staticmethod
    def check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def identity(self):
        code = wintypes.DWORD()
        self.check(self.api.GetExitCodeProcess(self.handle, ctypes.byref(code)))
        if code.value != 259:
            raise RuntimeError('Original Designer process has exited; never reopen PID')
        length = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(length.value)
        self.check(self.api.QueryFullProcessImageNameW(self.handle, 0, image, ctypes.byref(length)))
        times = [wintypes.FILETIME() for _ in range(4)]
        self.check(self.api.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)))
        creation = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
        return dict(pid=int(self.api.GetProcessId(self.handle)), exe=image.value, creation_filetime=creation)

    def affinity(self):
        process, system = ctypes.c_size_t(), ctypes.c_size_t()
        self.check(self.api.GetProcessAffinityMask(self.handle, ctypes.byref(process), ctypes.byref(system)))
        return process.value, system.value

    def set_affinity(self, mask):
        self.check(self.api.SetProcessAffinityMask(self.handle, mask))

    def close(self):
        if self.handle:
            self.check(self.api.CloseHandle(self.handle))
            self.handle = None


def verify_identity(process, creation):
    value = process.identity()
    if (type(creation) is not int or creation <= 0 or value['pid'] != PID
            or value['creation_filetime'] != creation
            or os.path.normcase(os.path.abspath(value['exe'])) != os.path.normcase(os.path.abspath(EXE))):
        raise ValueError('Designer PID/executable/creation time differs')
    return value


def idle_ui(response):
    if response.get('status') != 'completed':
        raise ValueError('ui_status request failed')
    ui = response.get('result')
    if type(ui) is not dict or ui.get('status') != 'observed' or ui.get('ui_thread') is not True:
        raise ValueError('UI ownership is unobserved')
    if ui.get('registry', {}).get('failure') is not None:
        raise ValueError('UI registry failure')
    for key in ('shutdown_process', 'process'):
        row = ui.get(key)
        if row is not None and (type(row) is not dict or row.get('present') is not False):
            raise ValueError('UI process present or unknown')
    if type(ui.get('shutdown_process')) is not dict:
        raise ValueError('Shutdown process unobserved')
    panel = ui.get('panel')
    if type(panel) is not dict or type(panel.get('present')) is not bool:
        raise ValueError('Panel presence unobserved')
    if panel['present']:
        if (panel.get('valid') is not True or panel.get('operation_contract_available') is not True
                or panel.get('operation_pending') is not False or panel.get('operation_phase') != 'idle'
                or panel.get('closing') is not False or panel.get('lifecycle_stopping') is not False
                or type(ui.get('process')) is not dict):
            raise ValueError('User panel is busy or operation contract unknown')
    return ui


class Bridge:
    def __init__(self, root, creation):
        self.root = Path(root)
        # Existing fixed selector/router are reused; no target from caller input.
        self.selector = runpy.run_path(str(self.root / 'scripts/select_designer_smoke.py'))
        self.router = self.selector['ROUTER']
        if self.router['project_root']() != self.root.resolve():
            raise ValueError('Project identity differs')
        self.directory = self.router['owned'](self.root, self.root / 'output/designer_bridge')
        self.creation = creation
        self.requests = []

    def read(self, path, limit):
        path = self.router['owned'](self.root, path)
        if not path.is_file() or path.stat().st_size > limit:
            raise ValueError('Missing/oversized bridge JSON')
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Oversized bridge JSON')
        return json.loads(raw.decode('utf8'), object_pairs_hook=unique)

    def ready(self):
        for name in ('request.json', 'processing.json'):
            path = self.router['owned'](self.root, self.directory / name)
            if path.exists() or path.is_symlink():
                raise ValueError('Pending/unknown inflight request; never remove or replay')
        state = self.read(self.directory / 'bridge_status.json', 32768)
        heartbeat = datetime.fromisoformat(state['heartbeat_utc'])
        if heartbeat.tzinfo is None or not -2 <= (datetime.now(timezone.utc) - heartbeat).total_seconds() <= 5:
            raise ValueError('Stale bridge heartbeat')
        if (state.get('version') != 2 or state.get('pid') != PID or state.get('status') != 'listening'
                or state.get('busy') is not False or state.get('stop_latched') is not False
                or Path(state.get('root', '')).resolve() != self.root.resolve()
                or type(state.get('session')) is not str or len(state['session']) != 32):
            raise ValueError('Bridge identity/ready state differs')
        return state

    def select(self, lane):
        self.ready()
        return self.selector['select'](lane)

    def request(self, operation, deadline):
        if operation not in ('ui_status', 'smoke'):
            raise ValueError('Only fixed observation/smoke operations permitted')
        state = self.ready()
        if time.monotonic() >= deadline:
            raise TimeoutError('Shared 60 second request deadline exhausted')
        job = uuid.uuid4().hex
        path = self.router['owned'](self.root, self.directory / 'request.json')
        temporary = self.router['owned'](self.root, self.directory / ('affinity_' + job + '.tmp'))
        response = self.router['owned'](self.root, self.directory / 'responses' / (job + '.json'))
        raw = json.dumps(dict(job_id=job, operation=operation), separators=(',', ':')).encode('utf8')
        row = dict(job_id=job, operation=operation, response=str(response), session=state['session'])
        self.requests.append(row)  # Record the attempted identity before publishing.
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.ready()
            os.link(temporary, path)  # CreateNew; never replace pending work.
            row['published'] = True
        finally:
            if temporary.exists():
                temporary.unlink()
        while time.monotonic() < deadline:
            if response.exists():
                result = self.read(response, 2 * 1024 * 1024)
                if result.get('job_id') != job or (result.get('status') == 'completed' and result.get('operation') != operation):
                    raise ValueError('Response identity differs')
                row['response_status'] = result.get('status')
                return result
            time.sleep(.1)
        raise TimeoutError('No response in 60s; pending/processing preserved; never replay')


def execute(process, bridge, creation, report, clock=time.monotonic):
    """Injectable controller; fake process/bridge tests exercise this same finally."""
    original = None
    changed = False
    selected = False
    deadline = clock() + SECONDS
    report.update(status='failed', scope='OS affinity only; no engine thread1/determinism guarantee',
                  compute_maximum=3, raw_maximum=7, raw_bytes_maximum=3670016,
                  request_seconds_maximum=SECONDS, restoration={}, default_lane_restoration={})
    try:
        report['identity'] = verify_identity(process, creation)
        original, system = process.affinity()
        if type(original) is not int or original != EXPECTED_MASK or original & system != original:
            raise ValueError('Original affinity differs from independently observed 65535')
        report.update(original_mask=original, system_mask=system, restricted_mask=original & -original)
        bridge.ready()
        report['ui_before'] = idle_ui(bridge.request('ui_status', deadline))
        verify_identity(process, creation)
        if process.affinity()[0] != original:
            raise ValueError('Affinity changed during UI observation')
        bridge.select('full_stock_original')
        selected = True
        bridge.ready()
        verify_identity(process, creation)
        changed = True  # Even a raising setter may have affected the target: restore.
        process.set_affinity(original & -original)
        if process.affinity()[0] != original & -original:
            raise RuntimeError('Single CPU affinity readback differs')
        result = bridge.request('smoke', deadline)
        report['smoke_response'] = result
        if result.get('status') != 'completed':
            raise RuntimeError('Smoke request failed; response preserved, no retry')
        observed = result.get('result')
        if (type(observed) is not dict or observed.get('status') != 'full_stock_reference_observation_complete'
                or observed.get('fixture_mode') != 'original' or observed.get('counts', {}).get('compute') != 3
                or observed.get('raw_count') != 7 or observed.get('raw_bytes') != 3670016
                or observed.get('PNG') != 0 or observed.get('worker') != 0
                or any(observed.get(key) is not True for key in
                       ('user_unchanged', 'inventory_unchanged', 'original_disks_unchanged'))):
            raise RuntimeError('Fixed smoke result/counts/preservation gate failed; original response retained')
        report['status'] = 'observation_complete'  # Math result remains the driver result.
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
    finally:
        if changed:
            try:
                verify_identity(process, creation)
                process.set_affinity(original)
                actual, _ = process.affinity()
                report['restoration'] = dict(attempted=True, expected=original, actual=actual, exact=actual == original)
                if actual != original:
                    raise RuntimeError('Original affinity restoration readback differs')
            except Exception as error:
                report.update(status='failed_restoration', restoration=dict(attempted=True, exact=False,
                              error=dict(type=type(error).__name__, message=str(error))))
        else:
            report['restoration'] = dict(attempted=False, reason='Affinity setter was not reached')
        if selected:
            try:
                bridge.ready()
                bridge.select('file_mask')
                report['default_lane_restoration'] = dict(restored=True)
            except Exception as error:
                report['default_lane_restoration'] = dict(restored=False, reason=str(error), pending_preserved=True)
        else:
            report['default_lane_restoration'] = dict(restored=False, reason='Selection was not changed')
        try:
            process.close()
        except Exception as error:
            report['handle_close_error'] = str(error)
            report['status'] = 'failed'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--creation-filetime', type=int, required=True,
                        help='Independently observed Windows process creation FILETIME (integer)')
    args = parser.parse_args()
    if args.creation_filetime <= 0:
        parser.error('Positive creation FILETIME required')
    selector = runpy.run_path(str(ROOT / 'scripts/select_designer_smoke.py'))
    owned = selector['ROUTER']['owned']
    work = owned(ROOT, ROOT / 'output/evidence/designer-cpu-affinity-probe' / uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=False)
    path = work / 'summary.json'
    report = dict(status='started', pid=PID, expected_exe=str(EXE), creation_filetime=args.creation_filetime)
    def save():
        temporary = owned(ROOT, work / (uuid.uuid4().hex + '.tmp'))
        with temporary.open('xb') as stream:
            stream.write((json.dumps(report, ensure_ascii=True, indent=2) + '\n').encode('utf8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    save()
    process = None
    try:
        bridge = Bridge(ROOT, args.creation_filetime)
        process = WindowsProcess(PID)
        report = execute(process, bridge, args.creation_filetime, report)
        report['requests'] = bridge.requests
    except Exception as error:
        report.update(status='failed_before_affinity', error=dict(type=type(error).__name__, message=str(error)))
        if process is not None:
            process.close()
    finally:
        save()
    print(str(path))
    return 0 if report['status'] == 'observation_complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
