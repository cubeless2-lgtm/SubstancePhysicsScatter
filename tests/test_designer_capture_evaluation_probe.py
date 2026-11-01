"""Focused capture-pair control tests; no SDK, Qt, Win32 or raw pointer reads."""
from pathlib import Path
import ast,runpy,tempfile,types,unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_capture_evaluation_probe.py'


class CapturePair(unittest.TestCase):
    def execute(self,work,*,different=False,mask=65535):
        probe=runpy.run_path(str(SOURCE));summary=dict(inspector_attempts=0,capture_attempts=0)
        calls=[];inspections=[];captures=[];pixels=b'\x12\x34'*262144
        selection=dict(package_path='own/source.sbs',package_uid='ownuid',graph_identifier='NativeMaskSource',terminal_identifier='native_mask')
        def inspect(**values):
            calls.append('inspect');inspections.append(values)
            return dict(selected_context=dict(fresh=values['operation_id']))
        def capture(**values):
            self.assertEqual(values['selected_context'],{'fresh':inspections[-1]['operation_id']})
            calls.append('capture');captures.append(values)
            return dict(png=dict(path='png'+str(len(captures))),counts=dict(copies=6,copy_limit=6,compute=1,PNG=1,worker=0))
        designer=types.SimpleNamespace(inspect_terminal_selection=inspect,capture_terminal=capture)
        def call_once(d,adapter,values,counts,artifact):
            self.assertEqual(counts,dict(inspector=0,capture=0));counts['inspector']+=1
            return d.inspect_terminal_selection(**values)
        class Observer:
            def __init__(self,root,row,artifact):calls.append('observer');self.row=row
            def calibrate(self):calls.append('K')
            def invoke(self,d,adapter,values,counts):
                if counts['capture']:raise AssertionError('Observer/context reused')
                counts['capture']+=1;return d.capture_terminal(**values)
        def decode(path):
            data=pixels if not different or path=='png1' else pixels[:-2]+b'\x12\x35'
            return data,dict(path=path)
        observer=dict(Observer=Observer,verify=lambda *args:dict(exact_uint16=True),decode=decode)
        caller=dict(call_once=call_once,verify_result=lambda *args:dict(verified=True))
        ownership=dict(states=lambda *args:dict(unchanged=True),inventory=lambda *args:[])
        affinity=types.SimpleNamespace(get=lambda:mask)
        def invoke():
            probe['capture_pair'](designer,object(),object(),observer,caller,ownership,None,{},[],selection,
                                  work,lambda name,value:dict(name=name),affinity,summary)
        return invoke,summary,calls,inspections,captures

    def test_two_fresh_inspector_capture_operations_exact_and_same_source(self):
        with tempfile.TemporaryDirectory() as directory:
            invoke,summary,calls,inspections,captures=self.execute(Path(directory));invoke()
        self.assertEqual(calls,['inspect','observer','K','capture']*2)
        ids=[r['operation_id'] for r in inspections+captures]
        self.assertEqual(len(set(ids)),4)
        self.assertEqual(inspections[0]['selection'],inspections[1]['selection'])
        self.assertEqual(summary['two_capture_decoded_comparison']['mismatch_count'],0)
        self.assertTrue(summary['two_capture_decoded_comparison']['exact'])
        self.assertEqual((summary['compute'],summary['PNG'],summary['raw'],summary['raw_bytes']),(2,2,6,3145728))
        self.assertEqual(len(summary['affinity_observations']),6)

    def test_changed_pixel_is_failure_and_wrong_original_affinity_stops_before_inspector(self):
        with tempfile.TemporaryDirectory() as directory:
            invoke,summary,calls,_,_=self.execute(Path(directory),different=True)
            with self.assertRaisesRegex(ValueError,'Two fresh product captures differ'):invoke()
            self.assertEqual(summary['two_capture_decoded_comparison']['mismatch_count'],1)
            self.assertEqual(calls.count('capture'),2)
        with tempfile.TemporaryDirectory() as directory:
            invoke,summary,calls,_,_=self.execute(Path(directory),mask=1)
            with self.assertRaisesRegex(ValueError,'affinity65535'):invoke()
            self.assertEqual(calls,[]);self.assertEqual(summary['inspector_attempts'],0)

    def test_fixed_route_and_canonical_product_calls_no_affinity_set_ui_or_worker(self):
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'))
        self.assertEqual(router['ROUTES']['product_capture_pair'],SOURCE.name)
        tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        forbidden={'compute','set_affinity','set','QProcess','QWidget','processEvents','load_private','newUserPackage'}
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr in forbidden for n in calls))
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and (n.module or '').startswith('PySide6') for n in ast.walk(tree)))
        self.assertEqual(sum(isinstance(n.func,ast.Subscript) and isinstance(n.func.slice,ast.Constant)
                             and n.func.slice.value=='protected_snapshot' for n in calls),1) # Called before/final only.
        self.assertIn('from substance_physics_scatter import designer,terminal_capture,mask_source,evaluation',SOURCE.read_text(encoding='utf8'))


if __name__=='__main__':unittest.main()
