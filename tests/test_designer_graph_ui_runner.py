"""Runner-only pure checks. Does not import Qt/SDK or execute the actual lane."""
import ast,json,sys,tempfile,time,types,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_graph_ui_actual.py'

class Runner(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.work=Path(self.temp.name);self.tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        nodes=[n for n in self.tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and getattr(n,'name',None) in ('owned','budget','load_private','Lane')]
        self.ns=dict(Path=Path,WORK=self.work,ROOT=ROOT,sys=sys,types=types,time=time,uuid=uuid,json=json,E={})
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),self.ns)
    def tearDown(self):self.temp.cleanup()
    def test_owned_root_and_strict_small_actor_budget(self):
        self.assertEqual(self.ns['owned'](self.work/'file'),self.work/'file')
        with self.assertRaises(ValueError):self.ns['owned'](self.work.parent/'external')
        for value in (True,3,-1):
            with self.assertRaises(ValueError):self.ns['budget'](value,2,'native')
        self.ns['budget'](2,2,'native')
    def test_private_exact_source_loader_never_executes_plugin_init(self):
        (self.work/'__init__.py').write_bytes(b'raise AssertionError("must not initialize")\n')
        (self.work/'one.py').write_bytes(b'VALUE=17\n')
        (self.work/'two.py').write_bytes(b'from .one import VALUE\ndef get():return VALUE\n')
        alias='_pure_graph_runner_'+uuid.uuid4().hex
        try:
            package=self.ns['load_private'](alias,self.work,('one','two'))
            self.assertEqual(package.two.get(),17);self.assertEqual(package.two.__file__,str(self.work/'two.py'))
            with self.assertRaises(ValueError):self.ns['load_private'](alias,self.work,('one',))
        finally:
            for name in list(sys.modules):
                if name==alias or name.startswith(alias+'.'):del sys.modules[name]
    def test_failed_pending_waits_for_ack_without_timer_disposal(self):
        for process in (None,object()):
            lane=self.ns['Lane']();panel=types.SimpleNamespace(_token={'pending':True},process=process)
            lane.panel=panel;lane.state=dict(panel=panel,phase='ready');lane.shiboken=types.SimpleNamespace(isValid=lambda _:True)
            calls=[];lane.session=types.SimpleNamespace(shutdown=lambda:calls.append('shutdown'));lane.report=lambda:None;lane.finish=lambda success:calls.append(('finish',success))
            lane.fail('injected');self.assertEqual(calls,['shutdown']);self.assertEqual(lane.phase,'failed_wait')
            lane.tick();self.assertEqual(calls,['shutdown'])
            lane.state.update(panel=None,phase='hidden');lane.tick();self.assertEqual(calls,['shutdown',('finish',False)])
    def test_target_save_precedes_create_and_async_contract_is_closed(self):
        lane=next(n for n in self.tree.body if isinstance(n,ast.ClassDef) and n.name=='Lane')
        create=next(n for n in lane.body if isinstance(n,ast.FunctionDef) and n.name=='make_target')
        calls=[n for n in ast.walk(create) if isinstance(n,ast.Call)]
        save=next(n.lineno for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='savePackageAs')
        scatter=next(n.lineno for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='create')
        self.assertLess(save,scatter)
        forbidden=[n for n in ast.walk(self.tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('processEvents','exec','exec_')]
        self.assertEqual(forbidden,[])
        text=SOURCE.read_text(encoding='utf8');self.assertIn("budget(E['native_attempts'],2",text);self.assertIn('120000',text);self.assertIn('4*1024*1024',text)
        self.assertIn("dump(REPORT,E) # The file bridge reads this immediately",text)

if __name__=='__main__':unittest.main()
