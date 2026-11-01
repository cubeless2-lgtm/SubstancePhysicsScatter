"""Pure routing/selection boundaries; no smoke lane, SDK or Qt is executed."""
import ast,importlib.util,json,runpy,tempfile,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class SmokeRoutes(unittest.TestCase):
    def setUp(self):
        self.router=load('pure_smoke_routes',ROOT/'tests/designer_smoke_routes.py');self.selector=load('pure_smoke_selector',ROOT/'scripts/select_designer_smoke.py')
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();(self.root/'tests').mkdir();(self.root/'CMakeLists.txt').write_bytes(b'owned test marker')
        for name in ('designer_smoke.py','designer_smoke_routes.py',*self.router.ROUTES.values()):(self.root/'tests'/name).write_bytes(b'not executed')
        self.router.ROOT=self.root;self.selector.ROOT=self.root;self.selector.ROUTER=self.router.__dict__
        self.directory=self.root/'output/designer_bridge';self.directory.mkdir(parents=True);self.selection=self.directory/'smoke_selection.json'
    def tearDown(self):self.temp.cleanup()
    def test_default_and_all_fixed_routes_never_accept_a_caller_path(self):
        self.assertEqual(self.router.selection(self.root),'file_mask');self.assertEqual(len(self.router.ROUTES),22)
        calls=[]
        with mock.patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'owned-report'}):
            self.assertEqual(self.router.run(),'owned-report')
            for lane,filename in self.router.ROUTES.items():
                self.selection.write_text(json.dumps({'lane':lane}),encoding='utf8');self.assertEqual(self.router.run(),'owned-report');self.assertEqual(calls[-1],(str(self.root/'tests'/filename),{'run_name':'__main__'}))
        for lane in ('../anything.py','designer_file_mask.py',True,None):
            with self.assertRaises(ValueError):self.router.target(self.root,lane)
    def test_selection_rejects_duplicate_extra_type_size_and_symlink(self):
        invalid=(b'{"lane":"file_mask","lane":"file_mask"}',b'{"lane":"file_mask","path":"x"}',b'{"lane":true}',b'{"lane":null}',b'{"lane":[]}',b'[]',b'{"lane":"../x"}',b'x'*513)
        for raw in invalid:
            self.selection.write_bytes(raw)
            with self.assertRaises(ValueError):self.router.selection(self.root)
        self.selection.write_bytes(b'{"lane":"file_mask"}');original=Path.is_symlink
        with mock.patch.object(Path,'is_symlink',lambda p:p==self.selection or original(p)):
            with self.assertRaisesRegex(ValueError,'symlink'):self.router.selection(self.root)
        with self.assertRaisesRegex(ValueError,'escapes'):self.router.owned(self.root,self.root/'..'/'outside.json')
    def test_selector_only_changes_json_and_busy_preserves_previous_selection(self):
        source_bytes={p:p.read_bytes() for p in (self.root/'tests').iterdir()}
        result=self.selector.select('cut_after_third_gaussian');self.assertEqual(result['lane'],'cut_after_third_gaussian');before=self.selection.read_bytes()
        for name in ('request.json','processing.json'):
            path=self.directory/name;path.write_bytes(b'pending')
            with self.assertRaisesRegex(ValueError,'pending/running'):self.selector.select('file_mask')
            self.assertEqual(path.read_bytes(),b'pending');self.assertEqual(self.selection.read_bytes(),before);path.unlink()
        # A request appearing while the temp file is flushed is checked again.
        def fsync(_): (self.directory/'processing.json').write_bytes(b'unknown inflight')
        with mock.patch.object(self.selector.os,'fsync',side_effect=fsync):
            with self.assertRaises(ValueError):self.selector.select('file_mask')
        self.assertEqual(self.selection.read_bytes(),before);self.assertEqual(list(self.directory.glob('*.tmp')),[])
        self.assertEqual({p:p.read_bytes() for p in source_bytes},source_bytes)
    def test_root_and_target_boundary_and_stable_entry(self):
        (self.root/'CMakeLists.txt').unlink()
        with self.assertRaisesRegex(ValueError,'development root'):self.selector.select('file_mask')
        self.assertFalse(self.selection.exists())
        entry=ROOT/'tests/designer_smoke.py';calls=[]
        with mock.patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'owned-report'}):
            namespace={'__file__':str(entry)};exec(compile(entry.read_text(encoding='utf8'),str(entry),'exec'),namespace)
        self.assertEqual(calls,[(str(ROOT/'tests/designer_smoke_routes.py'),{'run_name':'__main__'})]);self.assertEqual(namespace['REPORT'],'owned-report')
        for file in (ROOT/'tests/designer_smoke_routes.py',ROOT/'scripts/select_designer_smoke.py'):
            tree=ast.parse(file.read_text(encoding='utf8'));modules=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]+[a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(m and (m.startswith('sd') or m.startswith('PySide')) for m in modules))
        self.assertNotIn('--root',(ROOT/'scripts/select_designer_smoke.py').read_text(encoding='utf8'))

    def test_old_python_reparse_fallback_rejects_junction_but_allows_missing(self):
        import types
        target=self.root/'internal_junction';target.mkdir();original=Path.lstat
        def lstat(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if path==target:return types.SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400)
            return value
        with mock.patch.object(self.router,'os',types.SimpleNamespace(name='nt')),mock.patch.object(Path,'is_junction',None,create=True),mock.patch.object(Path,'lstat',lstat):
            with self.assertRaisesRegex(ValueError,'reparse'):self.router.owned(self.root,target/'selection.json')
            missing=self.root/'not_created'/'selection.json';self.assertEqual(self.router.owned(self.root,missing),missing)

if __name__=='__main__':unittest.main()
