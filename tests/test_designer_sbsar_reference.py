"""Pure archive ownership/declaration/loop gates; no actual SDK import or compute."""
from pathlib import Path
import ast,copy,runpy,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_sbsar_reference.py'

class SBSARReference(unittest.TestCase):
    def setUp(self):self.p=runpy.run_path(str(SOURCE))
    def test_archive_identity_adoption_is_observed_delta_not_inferred_source_uid(self):
        p=self.p;before=[dict(uid='protected',path='user.sbs')];order=lambda rows:sorted(rows,key=lambda r:r['uid']);actual=dict(uid='observed-private',path='owned/archive.sbsar')
        self.assertTrue(p['adoptable']('owned/archive.sbsar',before,actual,order(before+[actual]),order))
        for changed,after in ((dict(actual,uid='protected'),before),(dict(actual,path='user.sbs'),order(before+[actual])),(actual,before)):
            self.assertFalse(p['adoptable']('owned/archive.sbsar',before,changed,after,order))
        self.assertEqual(p['digest'](p['ARCHIVE']),p['ARCHIVE_SHA']);self.assertEqual(p['digest'](p['CLI']/'summary.json'),p['CLI_SUMMARY_SHA'])
        for label in p['SDK_SHA']:
            self.assertEqual(p['digest'](p['SDK']/(label+'-before.raw')),p['SDK_SHA'][label]);self.assertEqual(p['digest'](p['CLI']/'rendered'/label/(label+'.raw')),p['CLI_SHA'][label])
    def test_declared_gate_requires_actual_input_and_explicit_format3_not_texture_measurement(self):
        p=self.p;view=dict(output=dict(id='Vertical_Noise',types=[dict(class_name='SDTypeTexture',id='SDTypeTexture',modifier=dict(name='Auto',value=0))]),Disorder=dict(property=dict(flags=dict(read_only=False,function_only=False))),common=[dict(owner=owner,property=name,inheritance='Absolute',value=dict(value=[9,9] if name=='$outputsize' else 0 if name=='$randomseed' else 3,**({'value_id':'hdr_high_precision'} if name=='$format' else {}))) for owner in ('root','instance') for name in ('$outputsize','$format','$randomseed')])
        p['declared_gate'](view)
        for change in (lambda v:v['output']['types'][0].update(class_name='SDTypeCustom'),lambda v:v['Disorder']['property']['flags'].update(read_only=True),lambda v:v['common'][1]['value'].update(value=1),lambda v:v['common'][1]['value'].update(value_id='16_bits_per_channel'),lambda v:v['common'].pop()):
            bad=copy.deepcopy(view);change(bad)
            with self.assertRaises(ValueError):p['declared_gate'](bad)
        self.assertIn('precompute_texture_measured=False',SOURCE.read_text(encoding='utf8'))
    def test_actual_loop_stops_before_compute_on_bad_gate_and_after_first_bad_layout(self):
        p=self.p;tree=ast.parse(SOURCE.read_text(encoding='utf8'));main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main');loop=next(n for n in ast.walk(main) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple) and isinstance(n.target.elts[0],ast.Name) and n.target.elts[0].id=='index')
        with tempfile.TemporaryDirectory() as directory:
            for failure,expected_computes in (('declaration',0),('layout',1),(None,3)):
                counts=dict(compute=0,disorder_set=1);summary=dict(first_texture_verified=False,observations=[],raw_count=1);events=[]
                def check(value,stage):
                    events.append(('gate',stage))
                    if failure=='declaration':raise ValueError('format3 declaration missing')
                def read(*args):
                    events.append(('layout','measured'))
                    if failure=='layout':raise ValueError('Actual texture is not512x256LUM32F')
                    summary['raw_count']+=2;return b'copied bytes',dict(distinct_words_at_least2=True)
                namespace=dict(STEPS=p['STEPS'],work=Path(directory),setter=lambda *args:counts.update(disorder_set=counts['disorder_set']+1),check=check,counts=counts,checkpoint=lambda:None,lane={'compute_once':lambda *args:events.append(('compute',counts['compute'])),'read_terminal':read},manager=None,ledger={},before=[],role={},L={'before_read':lambda *args:None,'FX_LAYOUT':'pinned'},summary=summary,files=type('Files',(),{'used':524288})(),capture=lambda *args:None,images={})
                if failure:
                    with self.assertRaises(ValueError):exec(compile(ast.Module(body=[loop],type_ignores=[]),str(SOURCE),'exec'),namespace)
                else:exec(compile(ast.Module(body=[loop],type_ignores=[]),str(SOURCE),'exec'),namespace)
                self.assertEqual(counts['compute'],expected_computes)
                if failure=='layout':self.assertFalse(summary['first_texture_verified']);self.assertEqual(summary['raw_count'],1)
                if failure is None:self.assertEqual((counts['disorder_set'],summary['raw_count']),(3,7))
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['sbsar_reference'],SOURCE.name)

if __name__=='__main__':unittest.main()
