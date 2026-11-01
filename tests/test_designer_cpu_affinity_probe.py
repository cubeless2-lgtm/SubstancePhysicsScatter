"""Pure controller tests. No real Win32, SDK, bridge request or smoke execution."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('affinity_probe_pure', ROOT / 'scripts/designer_cpu_affinity_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
CREATION = 134377654696513755


class Process:
    def __init__(self, *, restore_failure=False, partial_set_failure=False, creation=CREATION):
        self.mask = 65535
        self.calls = []
        self.restore_failure = restore_failure
        self.partial_set_failure = partial_set_failure
        self.creation = creation
        self.closed = False

    def identity(self):
        return dict(pid=86996, exe=str(probe.EXE), creation_filetime=self.creation)

    def affinity(self):
        return self.mask, 65535

    def set_affinity(self, mask):
        self.calls.append(mask)
        if mask == 65535 and self.restore_failure:
            raise OSError('TEST_ONLY restore denied')
        self.mask = mask
        if mask == 1 and self.partial_set_failure:
            raise OSError('TEST_ONLY setter affected target then raised')

    def close(self):
        self.closed = True


class Bridge:
    def __init__(self, process, *, outcome='ok', busy=False):
        self.process = process
        self.outcome = outcome
        self.busy = busy
        self.pending = False
        self.lanes = []
        self.operations = []

    def ready(self):
        if self.pending:
            raise ValueError('Pending request preserved')

    def select(self, lane):
        self.ready()
        self.lanes.append(lane)

    def request(self, operation, deadline):
        self.operations.append(operation)
        if operation == 'ui_status':
            assert self.process.mask == 65535
            ui = dict(status='observed', ui_thread=True, registry=dict(failure=None),
                      panel=dict(present=False), shutdown_process=dict(present=False))
            if self.busy:
                ui['panel'] = dict(present=True, valid=True, operation_contract_available=True,
                                    operation_pending=True, operation_phase='capture', closing=False,
                                    lifecycle_stopping=False)
                ui['process'] = dict(present=False)
            return dict(status='completed', result=ui)
        assert operation == 'smoke' and self.process.mask == 1
        if self.outcome == 'timeout':
            self.pending = True
            raise TimeoutError('TEST_ONLY no response; do not replay')
        if self.outcome == 'error':
            return dict(status='error', traceback='TEST_ONLY request failed')
        return dict(status='completed', result=dict(status='full_stock_reference_observation_complete',
                    fixture_mode='original', counts=dict(compute=3), raw_count=7, raw_bytes=3670016,
                    PNG=0, worker=0, user_unchanged=True, inventory_unchanged=True,
                    original_disks_unchanged=True, math_pass=False))


class AffinityControl(unittest.TestCase):
    def test_success_restricts_only_fixed_process_and_restores_exact_mask(self):
        process = Process()
        bridge = Bridge(process)
        result = probe.execute(process, bridge, CREATION, {}, clock=lambda: 100.)
        self.assertEqual(result['status'], 'observation_complete')
        self.assertEqual(process.calls, [1, 65535])
        self.assertTrue(process.closed)
        self.assertTrue(result['restoration']['exact'])
        self.assertEqual(bridge.operations, ['ui_status', 'smoke'])
        self.assertEqual(bridge.lanes, ['full_stock_original', 'file_mask'])
        self.assertFalse(result['smoke_response']['result']['math_pass'])  # No math FAIL promotion.
        self.assertEqual(result['request_seconds_maximum'], 60)

    def test_request_error_timeout_and_partially_raising_setter_restore_in_finally(self):
        for outcome in ('error', 'timeout', 'partial_set_failure'):
            with self.subTest(outcome=outcome):
                process = Process(partial_set_failure=outcome == 'partial_set_failure')
                bridge = Bridge(process, outcome=outcome)
                result = probe.execute(process, bridge, CREATION, {})
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(process.calls, [1, 65535])
                self.assertEqual(process.mask, 65535)
                self.assertTrue(process.closed)
                self.assertTrue(result['restoration']['exact'])
                self.assertLessEqual(bridge.operations.count('smoke'), 1)
                if outcome == 'timeout':
                    self.assertTrue(bridge.pending)
                    self.assertEqual(bridge.lanes, ['full_stock_original'])
                    self.assertFalse(result['default_lane_restoration']['restored'])

    def test_restore_failure_is_explicit_and_identity_or_busy_rejects_before_mutation(self):
        process = Process(restore_failure=True)
        result = probe.execute(process, Bridge(process), CREATION, {})
        self.assertEqual(result['status'], 'failed_restoration')
        self.assertFalse(result['restoration']['exact'])
        self.assertTrue(process.closed)
        for reason in ('creation', 'busy', 'mask'):
            with self.subTest(reason=reason):
                process = Process(creation=CREATION + (reason == 'creation'))
                if reason == 'mask':
                    process.mask = 7
                bridge = Bridge(process, busy=reason == 'busy')
                result = probe.execute(process, bridge, CREATION, {})
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(process.calls, [])
                self.assertEqual(bridge.lanes, [])
                self.assertNotIn('smoke', bridge.operations)
                self.assertTrue(process.closed)


if __name__ == '__main__':
    unittest.main()
