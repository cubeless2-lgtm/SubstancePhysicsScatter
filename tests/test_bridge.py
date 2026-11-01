from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter.bridge import FileQueue
from substance_physics_scatter import bridge
from substance_physics_scatter.testing import isolated_panel

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.calls=[]
        self.queue=FileQueue(self.root,lambda operation:self.calls.append(operation) or {"ok":True})
    def tearDown(self):self.temp.cleanup()
    def submit(self,job,op,**extra):
        (self.queue.directory/"request.json").write_text(json.dumps({"job_id":job,"operation":op,**extra}),encoding="utf-8")
        self.queue.tick()
    def test_health_and_duplicate(self):
        self.submit("one","health");response=self.queue.responses/"one.json";before=response.read_bytes()
        self.submit("one","health");self.assertEqual(self.calls,["health"]);self.assertEqual(response.read_bytes(),before)
    def test_no_code_or_path_or_traversal(self):
        self.submit("bad","smoke",code="print(1)")
        self.assertEqual(self.calls,[]);self.assertEqual(json.loads((self.queue.responses/"bad.json").read_text())["status"],"error")
        self.submit("../../escaped","health");self.assertFalse((self.root/"escaped.json").exists());self.assertEqual(self.calls,[])
    def test_busy_stop_and_limit(self):
        self.queue.busy=True;self.submit("later","inspect");self.assertEqual(self.calls,[])
        self.queue.busy=False;self.queue.tick();self.assertEqual(self.calls,["inspect"])
        self.submit("end","stop");self.submit("after","health");self.assertEqual(self.calls,["inspect"])
        q=FileQueue(self.root/"limit",self.calls.append,maximum=0);q.tick();self.assertTrue(q.stopped)
    def test_handler_exception_keeps_queue_usable(self):
        def fail(operation):raise RuntimeError("test")
        self.queue.handler=fail;self.submit("failure","smoke")
        response=json.loads((self.queue.responses/"failure.json").read_text());self.assertEqual(response["status"],"error");self.assertIn("RuntimeError",response["traceback"]);self.assertFalse(self.queue.busy)

    def test_sdk_baseexception_is_reported_without_stopping_queue(self):
        error_class=bridge.HOST_ERRORS[1]
        self.assertTrue(issubclass(error_class,BaseException));self.assertFalse(issubclass(error_class,Exception))
        def fail(operation):raise error_class('SDK poison')
        self.queue.handler=fail;self.submit('sdk_failure','health')
        self.assertEqual(json.loads((self.queue.responses/'sdk_failure.json').read_text())['status'],'error');self.assertFalse(self.queue.busy);self.assertFalse(self.queue.stopped)

    def test_unknown_processing_and_pending_are_preserved(self):
        incoming=self.queue.directory/'request.json';processing=self.queue.directory/'processing.json'
        incoming.write_bytes(b'pending');processing.write_bytes(b'unknown active handler');self.queue.tick()
        self.assertEqual(incoming.read_bytes(),b'pending');self.assertEqual(processing.read_bytes(),b'unknown active handler');self.assertEqual(self.calls,[]);self.assertEqual(self.queue.stop_reason,'inflight_unknown')

    def test_control_names_are_safe_response_ids(self):
        for job in ("request","processing","bridge_status","rejection"):
            self.submit(job,"health")
            self.assertEqual(json.loads((self.queue.responses/(job+".json")).read_text())["status"],"completed")
            self.assertFalse((self.queue.directory/"request.json").exists())
        self.assertEqual(self.calls,["health"]*4)

    def test_oversized_request_is_consumed_and_next_request_runs(self):
        incoming=self.queue.directory/"request.json";incoming.write_bytes(b"x"*4097)
        self.queue.tick()
        self.assertFalse(incoming.exists());self.assertEqual(len(list(self.queue.quarantine.iterdir())),1)
        self.submit("valid_after_large","health");self.assertEqual(self.calls,["health"])

    def test_symlink_request_never_touches_target_and_next_request_runs(self):
        target=self.root/"external.txt";target.write_text("untouched")
        link=self.queue.directory/"request.json"
        try:link.symlink_to(target)
        except OSError as error:self.skipTest("OS does not allow symlink creation: "+str(error))
        self.queue.tick()
        self.assertFalse(link.is_symlink());self.assertEqual(target.read_text(),"untouched")
        quarantined=list(self.queue.quarantine.iterdir());self.assertEqual(len(quarantined),1);self.assertTrue(quarantined[0].is_symlink())
        self.submit("valid_after_link","health");self.assertEqual(self.calls,["health"])

    def test_symlink_validation_branch_quarantines_without_read(self):
        # Portable branch test in addition to the real OS symlink test above.
        incoming=self.queue.directory/"request.json";incoming.write_text("must not read")
        original_link=Path.is_symlink
        original_read=Path.read_text
        def link(path):
            return True if path.name=="processing.json" and path.exists() else original_link(path)
        def read(path,*args,**kwargs):
            if path.name=="processing.json":raise AssertionError("Rejected link payload was opened")
            return original_read(path,*args,**kwargs)
        with mock.patch.object(Path,"is_symlink",link),mock.patch.object(Path,"read_text",read):
            self.queue.tick()
        self.assertFalse(incoming.exists());self.assertEqual(len(list(self.queue.quarantine.iterdir())),1)
        self.submit("after_mock_link","health");self.assertEqual(self.calls,["health"])

    def test_isolated_panel_cleanup_preserves_user_state_on_failure(self):
        class FakePanel:
            def __init__(self):self.closed=False;self.deleted=False
            def close(self):self.closed=True
            def deleteLater(self):self.deleted=True
        user_state={"selected":"user_scatter","mesh":"user.obj","count":97}
        before=dict(user_state);user=FakePanel();test=FakePanel()
        with self.assertRaises(RuntimeError):
            with isolated_panel(lambda:test):raise RuntimeError("injected smoke failure")
        self.assertTrue(test.closed);self.assertTrue(test.deleted)
        self.assertFalse(user.closed);self.assertFalse(user.deleted);self.assertEqual(user_state,before)

class ManagedBridgeTests(unittest.TestCase):
    def setUp(self):
        import types
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();(self.root/'tests').mkdir();(self.root/'tests/designer_smoke.py').write_text('# fixed owned test')
        class Object:
            valid=True
            def __init__(self,parent=None):self.parent=parent
            def setObjectName(self,name):self.name=name
        class Signal:
            def __init__(self):self.callbacks=[]
            def connect(self,f):self.callbacks.append(f)
        class Timer(Object):
            def __init__(self,parent=None):super().__init__(parent);self.timeout=Signal();self.active=False
            def start(self,ms):self.active=True
            def stop(self):self.active=False
            def isActive(self):return self.active
        class App(Object):
            def __init__(self):self.properties={}
            def thread(self):return 'UI'
            def property(self,key):return self.properties.get(key)
            def setProperty(self,key,value):self.properties[key]=value
        self.app=App();qt=types.SimpleNamespace(QtCore=types.SimpleNamespace(QObject=Object,QTimer=Timer,QThread=types.SimpleNamespace(currentThread=lambda:'UI')),QtWidgets=types.SimpleNamespace(QApplication=types.SimpleNamespace(instance=lambda:self.app)))
        self.patch=mock.patch.dict(sys.modules,{'PySide6':qt,'shiboken6':types.SimpleNamespace(isValid=lambda o:getattr(o,'valid',True))});self.patch.start()
        self.root_patch=mock.patch.object(bridge,'development_root',return_value=self.root);self.root_patch.start()
    def tearDown(self):
        manager=bridge._manager()
        if manager is not None:
            if manager.queue is not None:manager.queue.busy=False
            manager.stop()
        self.root_patch.stop();self.patch.stop();self.temp.cleanup()
    def test_anchor_reused_and_auto_expiry_limit_renew(self):
        first=bridge.ensure_auto();manager=bridge._manager();timer=manager.timer;session=first['session']
        self.assertEqual(bridge.ensure_auto()['session'],session);self.assertIs(bridge._manager().timer,timer);self.assertEqual(len(timer.timeout.callbacks),1)
        response=manager.queue.responses/'immutable.json';response.write_bytes(b'old response')
        manager.queue.expires=0;manager.poll();self.assertNotEqual(manager.session,session);self.assertEqual(manager.last_session['reason'],'expired');self.assertEqual(response.read_bytes(),b'old response')
        session=manager.session;manager.queue.attempts=128;manager.poll();self.assertNotEqual(manager.session,session);self.assertEqual(manager.last_session['reason'],'request_limit')
        state=json.loads((manager.root/'output/designer_bridge/bridge_status.json').read_text());self.assertIn('heartbeat_utc',state);self.assertEqual(state['pid'],bridge.os.getpid());self.assertTrue(bridge.status()['qt_validated'])
    def test_manual_compatibility_stop_latch_and_explicit_resume(self):
        q=bridge.start(self.root);manager=bridge._manager();self.assertFalse(manager.managed)
        q.expires=0;manager.poll();self.assertFalse(manager.timer.isActive());self.assertEqual(bridge.ensure_auto()['session'],manager.session)
        old=manager.session;bridge.resume_auto(self.root);self.assertTrue(manager.managed);self.assertNotEqual(manager.session,old)
        bridge.stop('plugin_unload');old=manager.session;self.assertTrue(bridge.ensure_auto()['stop_latched']);self.assertEqual(manager.session,old)
    def test_stop_during_handler_waits_for_response_and_busy_replace_rejected(self):
        bridge.ensure_auto();manager=bridge._manager();q=manager.queue;inside=[]
        def handler(op):
            with self.assertRaises(RuntimeError):bridge.resume_auto(self.root)
            bridge.stop();inside.append((q.busy,q.stopped,manager.timer.isActive()));return {'done':True}
        q.handler=handler;(q.directory/'request.json').write_text(json.dumps(dict(job_id='running',operation='health')))
        manager.poll();self.assertEqual(inside,[(True,False,True)]);self.assertFalse(manager.timer.isActive());self.assertEqual(json.loads((q.responses/'running.json').read_text())['status'],'completed');self.assertIs(manager.queue,q);self.assertTrue(bridge.ensure_auto()['stop_latched'])
    def test_unknown_inflight_blocks_start_and_preserves_both_files(self):
        directory=self.root/'output/designer_bridge';directory.mkdir(parents=True);(directory/'request.json').write_bytes(b'pending');(directory/'processing.json').write_bytes(b'unknown')
        state=bridge.ensure_auto();self.assertEqual(state['reason'],'inflight_unknown');self.assertFalse(bridge._manager().timer.isActive());self.assertEqual((directory/'request.json').read_bytes(),b'pending');self.assertEqual((directory/'processing.json').read_bytes(),b'unknown')
    def test_foreign_lease_does_not_overwrite_status(self):
        bridge.ensure_auto();manager=bridge._manager();path=manager.root/'output/designer_bridge/bridge_status.json';before=path.read_bytes()
        with self.assertRaises(RuntimeError):bridge.Lease(self.root)
        self.assertEqual(path.read_bytes(),before)
    def test_invalid_qt_and_auto_failure_are_explicit(self):
        bridge.ensure_auto();manager=bridge._manager();manager.timer.valid=False
        with self.assertRaises(RuntimeError):bridge.status()
        with self.assertWarns(RuntimeWarning):result=bridge.ensure_auto()
        self.assertTrue(result['automatic_start_failed']);manager.timer.valid=True
    def test_request_helper_rejects_stale_stopped_and_legacy_without_writes(self):
        import ast
        from datetime import datetime,timezone,timedelta
        path=ROOT/'scripts/designer_request.py';tree=ast.parse(path.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ready');namespace=dict(Path=Path,json=json,datetime=datetime,timezone=timezone);exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),namespace);ready=namespace['ready']
        bridge.ensure_auto();manager=bridge._manager();path=manager.root/'output/designer_bridge/bridge_status.json';self.assertEqual(ready(self.root)['session'],manager.session)
        original=path.read_bytes();state=json.loads(original);state['heartbeat_utc']=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat();path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'stale'):ready(self.root)
        self.assertFalse((path.parent/'request.json').exists());path.write_bytes(original);bridge.stop()
        with self.assertRaisesRegex(ValueError,'not ready'):ready(self.root)
        path.write_text('{"status":"listening"}')
        with self.assertRaisesRegex(ValueError,'Legacy'):ready(self.root)

    def test_explicit_bootstrap_stops_reload_then_managed_resume_and_busy_rejects(self):
        import importlib
        path=ROOT/'scripts/start_designer_bridge.py';calls=[]
        with mock.patch.object(bridge,'_queue',None),mock.patch.object(bridge,'status',return_value={'busy':False}),mock.patch.object(bridge,'stop',side_effect=lambda:calls.append('stop')),mock.patch.object(importlib,'reload',side_effect=lambda m:calls.append('reload') or m),mock.patch.object(bridge,'resume_auto',side_effect=lambda root:calls.append(('managed',root)) or {'managed':True}),mock.patch.object(sys,'path',list(sys.path)),mock.patch('builtins.print'):
            exec(compile(path.read_text(),str(path),'exec'),{'__file__':str(path)})
        self.assertEqual(calls,['stop','reload',('managed',ROOT)])
        calls=[]
        with mock.patch.object(bridge,'_queue',None),mock.patch.object(bridge,'status',return_value={'busy':True}),mock.patch.object(bridge,'stop',side_effect=lambda:calls.append('stop')),mock.patch.object(sys,'path',list(sys.path)):
            with self.assertRaisesRegex(RuntimeError,'executing'):exec(compile(path.read_text(),str(path),'exec'),{'__file__':str(path)})
        self.assertEqual(calls,[])

    def test_implicit_ensure_inside_handler_stop_preserves_latch_without_error(self):
        bridge.ensure_auto();manager=bridge._manager();q=manager.queue;session=manager.session;observed=[]
        def handler(op):
            observed.append(bridge.ensure_auto())
            bridge.stop('verification_stop');observed.append(bridge.ensure_auto())
            self.assertIs(manager.queue,q);self.assertEqual(manager.session,session)
            with self.assertRaises(RuntimeError):bridge.resume_auto(self.root)
            return {'done':True}
        q.handler=handler;(q.directory/'request.json').write_text(json.dumps(dict(job_id='deferred',operation='health')));manager.poll()
        self.assertTrue(observed[0]['busy']);self.assertFalse(observed[0]['stop_latched']);self.assertEqual(observed[1]['status'],'stopping');self.assertTrue(observed[1]['stop_latched'])
        final=bridge.status();self.assertEqual(final['status'],'stopped');self.assertIsNone(final['error']);self.assertFalse(final['timer_active'])
        self.assertEqual(json.loads((q.responses/'deferred.json').read_text())['status'],'completed')

    def test_request_errors_keep_fresh_health_and_stop_ready(self):
        import ast
        from datetime import datetime,timezone
        path=ROOT/'scripts/designer_request.py';tree=ast.parse(path.read_text(encoding='utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='ready');namespace=dict(Path=Path,json=json,datetime=datetime,timezone=timezone);exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),namespace);ready=namespace['ready']
        bridge.ensure_auto();manager=bridge._manager();q=manager.queue;calls=[]
        def submit(job,op):
            ready(self.root);(q.directory/'request.json').write_text(json.dumps(dict(job_id=job,operation=op)));manager.poll()
            return (q.responses/(job+'.json')).read_bytes()
        for index,error_class in enumerate((RuntimeError,bridge.HOST_ERRORS[1])):
            def handler(op):
                calls.append(op)
                if op=='smoke':raise error_class('request failure poison')
                return {'healthy':True}
            q.handler=handler;failed=submit('failure'+str(index),'smoke')
            self.assertEqual(json.loads(failed)['status'],'error');state=ready(self.root);self.assertEqual(state['status'],'listening');self.assertIsNone(state['error']);self.assertIn('request failure poison',state['last_request_error']);self.assertTrue(manager.timer.isActive())
            self.assertEqual(json.loads(submit('fresh'+str(index),'health'))['status'],'completed');self.assertEqual((q.responses/('failure'+str(index)+'.json')).read_bytes(),failed)
        self.assertEqual(calls,['smoke','health','smoke','health'])
        self.assertEqual(json.loads(submit('stop_after_errors','stop'))['status'],'completed');self.assertEqual(bridge.status()['status'],'stopped')

if __name__=="__main__":unittest.main(verbosity=2)
