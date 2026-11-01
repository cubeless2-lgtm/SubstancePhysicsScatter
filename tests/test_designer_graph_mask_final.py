"""New final-lane boundaries only; no Qt/SDK/native execution or runtime files."""
from pathlib import Path
import ast,copy,gc,runpy,tempfile,types,unittest,weakref
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_graph_mask_final.py'


class FinalLane(unittest.TestCase):
    def setUp(self):self.p=runpy.run_path(str(SOURCE))

    def test_source_file_hold_partial_failure_rolls_back_reverse_with_write_ahead_journal(self):
        for fail_second in (False,True):
            with self.subTest(fail_second=fail_second),tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();rows=[];snapshots=[];moves=[]
                for role in ('noise','invert','source'):
                    path=root/'source'/('stock' if role!='source' else '')/(role+'.sbs');path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(('original-'+role).encode());hold=path.with_name(path.name+'.hold-'+role)
                    rows.append(dict(role=role,original=str(path),hold=str(hold),sha256=self.p['sha'](path),state='planned'))
                journal=dict(version=1,status='preparing',rollback_attempted=False,files=rows)
                def own(path):
                    path=Path(path).resolve()
                    if not path.is_relative_to(root):raise ValueError('Outside owned test path')
                    return path
                def publish(value):snapshots.append(copy.deepcopy(value))
                rename=Path.rename
                def move(source,destination):
                    source=Path(source);destination=Path(destination)
                    self.assertTrue(source.is_file());self.assertEqual(source.parent,destination.parent)
                    row=next(r for r in snapshots[-1]['files'] if str(source) in (r['original'],r['hold']))
                    self.assertEqual(row['state'],'moving' if str(source)==row['original'] else 'restoring')
                    moves.append((str(source),str(destination)))
                    if fail_second and str(source)==rows[1]['original']:raise PermissionError('TEST_ONLY WinError5 second file')
                    return rename(source,destination)
                with patch.object(Path,'rename',new=move):
                    if fail_second:
                        with self.assertRaisesRegex(PermissionError,'WinError5'):self.p['hold_source_files'](journal,own,publish)
                        self.assertTrue(journal['rollback_attempted']);self.assertEqual(journal['status'],'restored')
                        self.assertEqual(moves[-1],(rows[0]['hold'],rows[0]['original']))
                    else:
                        self.p['hold_source_files'](journal,own,publish)
                        self.assertTrue(all(not Path(r['original']).exists() and Path(r['hold']).is_file() for r in rows))
                        self.p['restore_held_files'](journal,own,publish)
                        self.assertEqual(moves[-3:],[(r['hold'],r['original']) for r in reversed(rows)])
                self.assertEqual(snapshots[0]['status'],'planned')
                self.assertTrue(all(Path(r['original']).is_file() and self.p['sha'](r['original'])==r['sha256'] and not Path(r['hold']).exists() for r in rows))
                self.assertTrue(all(r['state']=='restored' for r in journal['files']))
                # Unload and hold are different branches of the actual timer state machine.
                tree=ast.parse(SOURCE.read_text(encoding='utf8'))
                absence=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='source_absence')
                self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='hold_source_files' for n in ast.walk(absence)))
                self.assertIn("self.phase='wait_source_hold'",SOURCE.read_text(encoding='utf8'))

    def test_sdk_wrapper_fields_released_before_unload_and_pending_is_rejected(self):
        class Wrapper:pass
        class Combo:
            def __init__(self,value):self.items=[value];self.blocked=False
            def blockSignals(self,flag):self.blocked=flag
            def clear(self):self.items.clear()
        graph=Wrapper();reference=weakref.ref(graph)
        panel=types.SimpleNamespace(_token=None,process=None,graph=graph,_target_identity={'plain':'identity'},jobs=object(),
                                    nodes=Combo(graph),source_choices=Combo({'plain':'selection'}))
        panel.invalidate_source=lambda:setattr(panel,'_source_context',None)
        del graph;self.p['clear_panel_wrappers'](panel);gc.collect()
        self.assertIsNone(reference());self.assertIsNone(panel.jobs);self.assertIsNone(panel.graph)
        self.assertEqual(panel.nodes.items,[]);self.assertFalse(panel.nodes.blocked)
        panel._token=object();panel.graph='preserved'
        with self.assertRaisesRegex(ValueError,'pending'):self.p['clear_panel_wrappers'](panel)
        self.assertEqual(panel.graph,'preserved')

    def test_saved128_and_saved64_keep_exact_physics_origin_and_original_maps(self):
        first=dict(job_id='sim',request=dict(bake=dict(resolution=64)),
                   result=dict(poses=[{'id':1}],pose_origin={'source':'sim'}),files={})
        saved=copy.deepcopy(first);saved['job_id']='saved';saved['request']['bake']['resolution']=128
        saved['result']['execution']=dict(physics_executed=False,body_count=0,steps=0)
        self.p['require_saved'](first,saved,128)
        wrong=copy.deepcopy(saved);wrong['result']['pose_origin']={'source':'other'}
        with self.assertRaisesRegex(ValueError,'origin'):self.p['require_saved'](first,wrong,128)
        saved['request']['bake']['resolution']=64;self.p['require_saved'](first,saved,64)
        with tempfile.TemporaryDirectory() as directory:
            for name in ('height','normal','coverage'):
                a=Path(directory)/(name+'-sim.png');b=Path(directory)/(name+'-saved.png')
                a.write_bytes(name.encode());b.write_bytes(a.read_bytes());first['files'][name]=str(a);saved['files'][name]=str(b)
            self.assertEqual(set(self.p['require_maps_exact'](first,saved)),{'height','normal','coverage'})
            Path(saved['files']['normal']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'byte-exact0'):self.p['require_maps_exact'](first,saved)

    def test_reopen_adopts_only_exact_package_graph_and_metadata_unknown_latches(self):
        class Graph:
            def getIdentifier(self):return 'scatter_own'
        graph=Graph();identity=dict(uid='target',path='own/target.sbs');metadata={'current':{'job_id':'saved128'}}
        fresh=dict(package_path=identity['path'],package_uid=identity['uid'],graph_identifier='scatter_own',graph_url='fresh-runtime-url')
        def make(wrong=False):
            lane=self.p['Lane']();lane.before_inventory=[]
            package=types.SimpleNamespace(identity=dict(identity,uid='foreign') if wrong else dict(identity),getChildrenResources=lambda recursive:[graph])
            packages=[]
            class Manager:
                def loadUserPackage(self,path,update,reload):
                    self_test.assertEqual((path,update,reload),(identity['path'],False,False));packages.append(package);return package
            self_test=self;lane.manager=Manager()
            lane.P=dict(context=lambda *args:None,package_id=lambda p:p.identity,inventory=lambda m:[p.identity for p in packages],
                        expected=lambda ledger,before:[r['identity'] for r in ledger['owned'] if r['state']=='adopted'],order=lambda rows:rows,
                        ambiguous=lambda ledger,reason:ledger.update(ambiguous=True,ambiguity_reason=reason))
            lane.product=types.SimpleNamespace(designer=types.SimpleNamespace(SDSBSCompGraph=Graph,settings=lambda g:copy.deepcopy(metadata),scatter_identity=lambda g:dict(fresh)))
            self.p['E']['target_reload']=0
            return lane
        lane=make();self.assertEqual(lane.reload_target(identity,'scatter_own',metadata),fresh)
        self.assertEqual(lane.ledger['owned'],[dict(name='target',identity=identity,state='adopted')])
        lane=make(True)
        with self.assertRaisesRegex(ValueError,'Unadopted'):lane.reload_target(identity,'scatter_own',metadata)
        self.assertTrue(lane.ledger['ambiguous']);self.assertEqual(lane.ledger['owned'],[])
        ownership=runpy.run_path(str(self.p['BASE']/'ownership.py'));callbacks=[]
        result=ownership['finish_guard'](lane.ledger,[],[],True,lambda:callbacks.append('forbidden'))
        self.assertFalse(result['verified']);self.assertEqual(callbacks,[])

    def test_qprocess_instrumentation_restores_canonical_global_before_return_or_raise(self):
        tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        klass=next(n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name=='TrialPanel')
        original=object();process=object();calls=[]
        ui=types.SimpleNamespace(QtCore=original)
        class Base:
            def _prepare_and_start(self,*args):
                self_test.assertIs(ui.QtCore.QProcess,process);calls.append(args)
                if args[0]=='error':raise RuntimeError('TEST_ONLY prepare failure')
                return 'canonical handler'
        self_test=self;ui.Panel=Base
        namespace=dict(ui=ui,QtCore=types.SimpleNamespace(QTimer=object(),Qt=object()),CountedProcess=process,lane=object(),designer=object(),types=types)
        exec(compile(ast.Module(body=[klass],type_ignores=[]),'<actual TrialPanel>','exec'),namespace)
        panel=namespace['TrialPanel']()
        self.assertEqual(panel._prepare_and_start('ok'),'canonical handler');self.assertIs(ui.QtCore,original)
        with self.assertRaisesRegex(RuntimeError,'prepare failure'):panel._prepare_and_start('error')
        self.assertIs(ui.QtCore,original);self.assertEqual(calls,[('ok',),('error',)])

    def test_fixed_route_and_own_session_do_not_execute_legacy_setup_or_show_ui(self):
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'))
        self.assertEqual(router['ROUTES']['graph_mask_final'],SOURCE.name)
        tree=ast.parse(SOURCE.read_text(encoding='utf8'));calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        forbidden={'processEvents','grab','show','newDockWidget','initializeSDPlugin','reload','setProperty'}
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr in forbidden for n in calls))
        self.assertEqual([name for name in self.p['Lane'].__mro__[1].__dict__ if not name.startswith('__')],
                         ['current','freeze_current','assert_same','metadata_rollback'])
        raw=SOURCE.read_text(encoding='utf8')
        self.assertIn("(('simulate_bake',64),('bake',128),('bake',64))",raw)
        self.assertIn('self.session=lifecycle.Session(self.state,OwnHost(TrialPanel,None))',raw)
        self.assertIn("self.product.designer.resolve_scatter(self.target)",raw)


if __name__=='__main__':unittest.main()
