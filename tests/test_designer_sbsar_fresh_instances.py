"""Only the new fresh-root phase/order gates; SDK remains unexecuted."""
from pathlib import Path
import ast,hashlib,importlib.util,runpy,tempfile,types,unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_sbsar_fresh_instances.py'

class FreshInstances(unittest.TestCase):
    def test_phase_actual_function_uses_three_fresh_roots_and_releases_before_next(self):
        for failure in (None,'layout','cleanup'):
            spec=importlib.util.spec_from_file_location('pure_fresh',SOURCE);p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
            events=[];counts=dict(new_package=0,save=0,disorder_set=0,compute=0);ledger=dict(owned=[],root_unload_calls=0,ambiguous=False);summary=dict(steps=[],observations=[],root_cleanup=[],raw_count=1);files=types.SimpleNamespace(used=524288);active={};pins={}
            def create(E,path):
                self.assertFalse(active);counts['new_package']+=1;counts['save']+=1;uid='root'+str(counts['new_package']);events.append(('create',uid));path.write_bytes(b'owned source disk0');role=dict(identity=dict(uid=uid,path=str(path)),graph_url='url-'+uid,ids={'noise_instance':'node-'+uid});active.update(role=role,value=0.,modified=False);ledger['owned'].append(dict(name='source',identity=role['identity'],state='adopted'));return role
            def view(E,role,expected):
                self.assertEqual(active['value'],expected)
                return dict(source_modified=active['modified'],view=dict(Disorder=dict(current={'value':expected},declaration='fixedFloat'),identity=role['identity']),archive_modified=False)
            def set_input(name,value):events.append(('set',active['role']['identity']['uid'],value));active['modified']=active['modified'] or active['value']!=value;active['value']=value
            def compute(*args):events.append(('compute',active['role']['identity']['uid']))
            def read(*args):
                events.append(('read',active['role']['identity']['uid']))
                if failure=='layout':raise ValueError('Actual layout unsupported')
                summary['raw_count']+=2;files.used+=1048576;return bytes([int(active['value'])]),{'distinct_words_at_least2':True}
            def remove(manager,record,*args):
                events.append(('unload',record['identity']['uid']))
                if failure=='cleanup':ledger['ambiguous']=True;raise ValueError('Ambiguous unload')
                ledger['root_unload_calls']+=1;record['state']='removed';active.clear();return {'status':'removed','identity':record['identity']}
            S=runpy.run_path(str(ROOT/'tests/designer_full_stock_reference.py'));D={'create_source':create,'source_view':view,'digest':lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()}
            E=dict(D=D,C={'root':lambda *args:types.SimpleNamespace(getNodeFromId=lambda _:types.SimpleNamespace(setInputPropertyValueFromId=set_input)),'item':lambda *args:next(r for r in ledger['owned'] if r['state']=='adopted')},P={'remove':remove},S=S,summary=summary,manager=None,ledger=ledger,before=[],counts=counts,float_value=lambda v:v,checkpoint=lambda:None,lane={'compute_once':compute,'read_terminal':read},L={'before_read':lambda *args:None,'FX_LAYOUT':'pinned'},files=files)
            tree=ast.parse(SOURCE.read_text(encoding='utf8'));main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main');loop=next(n for n in ast.walk(main) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple))
            with tempfile.TemporaryDirectory() as directory:
                namespace=dict(D={'STEPS':(('N0',0.),('N50',50.),('NR0',0.))},work=Path(directory),images={},step=p.step,E=E,capture=lambda *args:None,artifact=lambda *args:{'owned':'plain'},pins=pins)
                if failure:
                    with self.assertRaises(ValueError):exec(compile(ast.Module(body=[loop],type_ignores=[]),str(SOURCE),'exec'),namespace)
                    self.assertEqual((counts['new_package'],counts['compute']),(1,1));self.assertEqual(summary['raw_count'],1 if failure=='layout' else 3)
                else:
                    exec(compile(ast.Module(body=[loop],type_ignores=[]),str(SOURCE),'exec'),namespace)
                    self.assertEqual(counts,dict(new_package=3,save=3,disorder_set=3,compute=3));self.assertEqual((summary['raw_count'],files.used,ledger['root_unload_calls']),(7,3670016,3));self.assertFalse(active)
                    self.assertEqual([e for e in events if e[0]=='set'],[('set','root1',0.),('set','root2',50.),('set','root3',0.)])
                    self.assertLess(events.index(('unload','root1')),events.index(('create','root2')));self.assertLess(events.index(('unload','root2')),events.index(('create','root3')))
                    self.assertEqual(len({r['ids']['noise_instance'] for r in summary['steps']}),3)
            self.assertEqual(hashlib.sha256(p.DRIVER.read_bytes()).hexdigest(),p.REUSED_DRIVER_SHA)
            self.assertEqual(hashlib.sha256((p.CONTINUOUS/'summary.json').read_bytes()).hexdigest(),p.CONT_SUMMARY_SHA)
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['sbsar_fresh_instances'],SOURCE.name)

if __name__=='__main__':unittest.main()
