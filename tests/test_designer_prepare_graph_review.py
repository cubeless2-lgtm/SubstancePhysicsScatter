"""Focused preparation controls. No SDK/Qt/native process is executed."""
from pathlib import Path
import copy,json,runpy,tempfile,types,unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_prepare_graph_review.py'


class ReviewPreparation(unittest.TestCase):
    def setUp(self):self.p=runpy.run_path(str(SOURCE))

    def test_exact_real_brick_input_and_bad_bytes_rejected_without_source_change(self):
        raw,info=self.p['brick_asset'](self.p['LIBRARY'],self.p['BRICK'])
        self.assertEqual(info['triangles'],4998);self.assertEqual(info['sha256'],self.p['BRICK_SHA'])
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'brick.obj';source.write_bytes(raw+b'\n')
            library=json.loads(self.p['LIBRARY'].read_text(encoding='utf8'))
            row=next(r for r in library['assets'] if r['asset_id']=='brick_red')
            row['files']['obj'].update(path=str(source),bytes=source.stat().st_size)
            path=Path(directory)/'library.json';path.write_text(json.dumps(library),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'bytes differ'):self.p['brick_asset'](path,source)
        self.assertEqual(self.p['sha'](self.p['BRICK']),self.p['BRICK_SHA'])

    def test_previous_panel_snapshot_contains_plain_settings_and_rejects_wrapper_data(self):
        class Value:
            def __init__(self,v):self.v=v
            def value(self):return self.v
            def currentText(self):return str(self.v)
        choice=types.SimpleNamespace(count=lambda:1,itemText=lambda i:'source',itemData=lambda i:{'plain':'selection'},currentIndex=lambda:0)
        panel=types.SimpleNamespace(_target_identity={'plain':'target'},asset_rows=lambda:[{'path':'original.obj','weight':2,'scale':.3}],
            mask_config=lambda:{'enabled':False},source_choices=choice,jobs=None)
        for key,value in dict(count=20,width=1.5,depth=1.5,seed=1,seconds=6,edges='walls',resolution='128',normal='OpenGL',height=1,mask_mode='Graph terminal').items():setattr(panel,key,Value(value))
        snapshot=self.p['panel_snapshot'](panel);json.dumps(snapshot)
        self.assertEqual(snapshot['assets'][0]['weight'],2);self.assertEqual(snapshot['simulation']['width'],1.5)
        choice.itemData=lambda i:object()
        with self.assertRaises(TypeError):self.p['panel_snapshot'](panel)

    def test_instance_prepare_override_and_global_qt_proxy_restore_on_error(self):
        lane=self.p['Prepare']();original=object();events=[]
        ui=types.SimpleNamespace(QtCore=original)
        class Process:pass
        class Panel:
            def _prepare_and_start(self,*args):
                if args[0]['id']=='foreign':
                    self_test.assertIs(ui.QtCore,original);events.append('foreign canonical prepare');return 'foreign result'
                self_test.assertIsNot(ui.QtCore,original);events.append('canonical prepare')
                raise RuntimeError('TEST_ONLY prepare error')
        self_test=self;panel=Panel();lane.panel=panel;lane.ui=ui
        lane.QtCore=types.SimpleNamespace(QProcess=Process,QTimer=object(),Qt=object());lane.owned_tokens={'owned'}
        lane.install_process_counter()
        self.assertEqual(panel._prepare_and_start({'id':'foreign'}),'foreign result')
        self.assertIs(ui.QtCore,original)
        with self.assertRaisesRegex(RuntimeError,'prepare error'):panel._prepare_and_start({'id':'owned'})
        self.assertIs(ui.QtCore,original);lane.restore_counter()
        self.assertNotIn('_prepare_and_start',panel.__dict__);self.assertIs(panel._prepare_and_start.__func__,Panel._prepare_and_start)
        self.assertEqual(events,['foreign canonical prepare','canonical prepare'])

    def test_success_keeps_four_owned_packages_selected_idle_and_does_not_cleanup(self):
        lane=self.p['Prepare']();events=[];identity={'plain':'target'}
        lane.inventory_before=[];lane.manager=object();lane.target=identity;lane.source_before=['unchanged']
        lane.panel=types.SimpleNamespace(_token=None,process=None,_target_identity=identity)
        lane.source_states=lambda:['unchanged'];lane.user=lambda label:events.append('user '+label)
        lane.verify_previous_current=lambda:events.append('old current exact');lane.affinity=lambda label:events.append('mask exact')
        lane.report=lambda:events.append('report')
        records=[dict(name=name,state='adopted',identity={'uid':name,'path':name+'.sbs'}) for name in ('noise','invert','source','target')]
        lane.ledger['owned']=records
        def no_cleanup(*_):raise AssertionError('Success must keep example packages loaded')
        lane.P=dict(context=lambda *args:events.append('context'),active=lambda ledger:records,
                    expected=lambda ledger,before:[r['identity'] for r in records],cleanup=no_cleanup)
        lane.finish(True)
        self.assertEqual(self.p['E']['status'],'GRAPH_MASK_REVIEW_READY')
        self.assertEqual(self.p['E']['packages_left_loaded'],4);self.assertFalse(self.p['E']['pending'])
        self.assertIs(lane.panel._target_identity,identity);self.assertEqual([r['state'] for r in records],['adopted']*4)
        self.assertEqual(events,['context','user after','old current exact','mask exact','report'])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'))
        self.assertEqual(router['ROUTES']['prepare_graph_review'],SOURCE.name)


if __name__=='__main__':unittest.main()
