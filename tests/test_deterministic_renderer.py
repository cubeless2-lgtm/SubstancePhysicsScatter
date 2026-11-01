"""Pure closed mapper/evaluator protocol tests. No SDK or actual CLI children."""
import copy, hashlib, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import deterministic_renderer as render,mask_source,terminal_capture as cap
from test_terminal_capture import Replay,png


class Process:
    def __init__(self,data=b'ok',timeout=False,interrupt=False):
        self.stdout=io.BytesIO(data);self.returncode=None;self.timeout=timeout;self.interrupt=interrupt;self.killed=False
    def poll(self):return self.returncode
    def wait(self,timeout=None):
        if self.killed:return self.returncode
        if self.interrupt:self.interrupt=False;raise KeyboardInterrupt('cancel fixture')
        if self.timeout:raise subprocess.TimeoutExpired('TEST_ONLY',timeout)
        self.returncode=0;return 0
    def kill(self):self.killed=True;self.returncode=-9


class DeterministicRenderer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def tools(self):
        install=self.root/'installation';pins={}
        for key,name in render.TOOL_NAMES.items():
            path=install/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(key.encode())
            pins[key]=hashlib.sha256(path.read_bytes()).hexdigest()
        return install,pins
    def evaluator(self,r,install,commands):
        def evaluate(pre,selected,owned,target,counts):
            counts.update(cook=0,render=0)
            def attempt(name):counts[name]+=1
            return render.render(packages=pre['packages'],serialization_base=pre['serialization_base'],selection=selected,installation=install,work=owned.work,target=target,attempt=attempt,evidence=owned.evidence)
        r.evaluate_copies=evaluate
        def child(argv,cwd,log):
            args=[str(x) for x in argv];commands.append(args)
            if args[0].endswith('sbscooker.exe'):
                self.assertNotIn('--no-optimization',args)
                (Path(args[args.index('--output-path')+1])/'Source.sbsar').write_bytes(b'TEST_ONLY archive; not ABI proof')
            else:
                self.assertEqual(args[args.index('--engine')+1],str(install/render.TOOL_NAMES['engine_sha256']))
                self.assertEqual(args[args.index('--cpu-count')+1],'1')
                self.assertEqual(args[args.index('--memory-budget')+1],'256')
                self.assertEqual(args[args.index('--input-graph')+1],'pkg://'+r.selected['graph_identifier'])
                self.assertEqual(args[args.index('--input-graph-output')+1],r.selected['terminal_identifier'])
                png(Path(args[args.index('--output-path')+1])/'terminal.png')
            return dict(argv=args,exit_code=0,log_bytes=0)
        return child
    def test_mapper_native_relative_locators_inverse_and_closed_paths(self):
        r=Replay(self.root,'two_graphs');op=self.root/'copy';op.mkdir()
        packages=copy.deepcopy(r.data['packages'])
        for p in packages:
            target=op/('pre-'+p['role']+'.sbs');r.copy(p,target);p['copy_xml']=target.read_bytes()
        before=packages[0]['copy_xml'];mapped,proof=render.map_dependencies(before,packages,str(op))
        self.assertEqual([p['role'] for p in proof],['noise','invert'])
        self.assertIn(b'stock/noise.sbs',mapped);self.assertIn(b'stock/invert.sbs',mapped)
        self.assertEqual(packages[0]['copy_xml'],before)
        for fault in ('wrongbase','unknown','duplicate'):
            bad=copy.deepcopy(packages);base=str(op)
            if fault=='wrongbase':base=str(self.root/'wrong'/'nested')
            elif fault=='unknown':bad[0]['copy_xml']=before.replace(b'vertical_noise.sbs',b'unknown.sbs')
            else:bad[0]['copy_xml']=before.replace(b'invert.sbs',b'vertical_noise.sbs')
            with self.subTest(fault=fault),self.assertRaises(ValueError):render.map_dependencies(bad[0]['copy_xml'],bad,base)
    def test_adapter_real_branch_closed_evaluator_handoff_and_legacy_capture(self):
        r=Replay(self.root,'two_graphs');selection=r.run(True);install,pins=self.tools();commands=[]
        child=self.evaluator(r,install,commands)
        with patch.dict(mask_source.EVALUATOR_TOOLS,pins,clear=True),patch.object(render,'run_child',side_effect=child):
            result=r.run(False,selection['selected_context'])
            self.assertEqual(r.calls['compute'],0);self.assertEqual(r.calls['save'],0)
            self.assertEqual(result['counts'],dict(copies=6,copy_limit=6,compute=0,PNG=1,worker=0,cook=1,render=1))
            ev=result['capture']['evaluator'];self.assertEqual(ev['backend'],'designer_cli_d3d11_cpu1')
            self.assertEqual(ev['output_png_sha256'],result['png']['sha256'])
            self.assertEqual(mask_source.capture(json.loads(json.dumps(result['capture'])),historical=True),result['capture'])
            legacy=copy.deepcopy(result['capture']);del legacy['evaluator']
            self.assertEqual(mask_source.capture(legacy,historical=True),legacy)
            for field,value in (('cpu_count',True),('cpu_count',16),('engine','SSE2'),('backend','designer_preview'),('cooker_optimization','disabled'),('unknown',1),('renderer_sha256','0'*64)):
                bad=copy.deepcopy(ev);bad[field]=value
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):mask_source.evaluator(bad)
            bad=copy.deepcopy(result['capture']);bad['evaluator']['graph_identifier']='other'
            with self.assertRaises(ValueError):mask_source.capture(bad,historical=True)
        self.assertEqual(len(commands),2)
        self.assertTrue((Path(result['png']['path']).parent/'handoff.json').is_file())
    def test_evaluator_failure_no_fallback_no_handoff_and_original_preserved(self):
        r=Replay(self.root);selected=r.run(True);install,pins=self.tools();commands=[]
        self.evaluator(r,install,commands)
        before={p['path']:Path(p['path']).read_bytes() for p in r.data['packages']}
        with patch.dict(mask_source.EVALUATOR_TOOLS,pins,clear=True),patch.object(render,'run_child',side_effect=RuntimeError('injected official child failure')):
            with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected['selected_context'])
        self.assertEqual(caught.exception.record['counts']['compute'],0)
        self.assertEqual(caught.exception.record['counts']['cook'],1)
        self.assertEqual(caught.exception.record['counts']['render'],0)
        self.assertEqual(r.calls['compute'],0);self.assertEqual(r.calls['save'],0)
        self.assertFalse((Path(caught.exception.record['work_directory'])/'handoff.json').exists())
        self.assertEqual(before,{p:Path(p).read_bytes() for p in before})
    def test_postflight_failure_keeps_evaluator_raw_and_no_handoff(self):
        r=Replay(self.root);selected=r.run(True);install,pins=self.tools();commands=[]
        child=self.evaluator(r,install,commands)
        original=r.collect
        def changed(snapshot,packages,partial):
            result,evidence=original(snapshot,packages,partial)
            if r.calls['collect']>=4:evidence['literals'][0]['default']['value']=[7,8]
            return result,evidence
        r.collect=changed
        with patch.dict(mask_source.EVALUATOR_TOOLS,pins,clear=True),patch.object(render,'run_child',side_effect=child):
            with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected['selected_context'])
        work=Path(caught.exception.record['work_directory'])
        self.assertTrue((work/'terminal.png').is_file());self.assertTrue((work/'evaluator.json').is_file())
        self.assertFalse((work/'handoff.json').exists());self.assertEqual(r.calls['compute'],0)
    def test_child_bounded_log_timeout_control_exception_cleanup(self):
        for label,process,error in (('ok',Process(),None),('overflow',Process(b'x'*(render.LOG_CAP+1)),ValueError),('timeout',Process(timeout=True),TimeoutError),('control',Process(interrupt=True),KeyboardInterrupt)):
            log=self.root/(label+'.log')
            with self.subTest(label=label),patch.object(render.subprocess,'Popen',return_value=process),patch.object(render,'TIMEOUT',.01 if label=='timeout' else 30):
                if error:
                    with self.assertRaises(error):render.run_child(['TEST_ONLY'],self.root,log)
                else:self.assertEqual(render.run_child(['TEST_ONLY'],self.root,log)['exit_code'],0)
            self.assertLessEqual(log.stat().st_size,render.LOG_CAP)
            self.assertIsNotNone(process.poll());self.assertTrue(process.stdout.closed)
            if label in ('timeout','control'):self.assertTrue(process.killed)
        with patch.object(render.subprocess,'Popen',side_effect=OSError('launch denied')):
            with self.assertRaises(OSError):render.run_child(['TEST_ONLY'],self.root,self.root/'launch.log')
    def test_tool_pin_output_and_ownership_rejections(self):
        r=Replay(self.root);selected=r.run(True);install,pins=self.tools();commands=[]
        child=self.evaluator(r,install,commands)
        (install/'sbsrender.exe').write_bytes(b'wrong tool')
        with patch.dict(mask_source.EVALUATOR_TOOLS,pins,clear=True),patch.object(render,'run_child',side_effect=child):
            with self.assertRaisesRegex(cap.CaptureError,'tool SHA'):r.run(False,selected['selected_context'])
        self.assertEqual(commands,[])
        (install/'sbsrender.exe').write_bytes(b'renderer_sha256')
        def bad_output(argv,cwd,log):
            result=child(argv,cwd,log)
            if str(argv[0]).endswith('sbsrender.exe'):
                output=Path(argv[argv.index('--output-path')+1])/'terminal.png'
                output.write_bytes(b'TEST_ONLY wrong PNG, no format fallback')
            return result
        with patch.dict(mask_source.EVALUATOR_TOOLS,pins,clear=True),patch.object(render,'run_child',side_effect=bad_output):
            with self.assertRaisesRegex(cap.CaptureError,'grayscale16 PNG') as caught:r.run(False,selected['selected_context'])
        self.assertFalse((Path(caught.exception.record['work_directory'])/'handoff.json').exists())
        external=self.root/'outside';external.mkdir()
        with self.assertRaises(ValueError):render.safe(external,self.root/'inside')
        link=self.root/'link'
        try:link.symlink_to(external,target_is_directory=True)
        except OSError:pass
        else:
            with self.assertRaises(ValueError):render.safe(link/'file')


if __name__=='__main__':unittest.main()
