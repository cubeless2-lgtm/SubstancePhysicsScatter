"""Scoped-compute controls with fake affinity/Qt/graph; real Win32 and SDK zero."""
import ast
import importlib.util
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'plugin/substance_physics_scatter/evaluation.py'
spec=importlib.util.spec_from_file_location('pure_evaluation',SOURCE)
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)


class Affinity:
    def __init__(self, mask=65535, failure=None):
        self.mask=mask;self.calls=[];self.failure=failure
    def get(self):return self.mask
    def set(self,value):
        self.calls.append(value)
        if value==65535 and self.failure=='restore':raise OSError('restore denied')
        self.mask=value
        if value==1 and self.failure=='restrict':raise OSError('setter mutated then raised')
        if value==1 and self.failure=='readback':self.mask=3


class Evaluation(unittest.TestCase):
    def run_graph(self,affinity,compute):
        with patch.object(E,'_assert_environment'),patch.object(E,'_ProcessAffinity',return_value=affinity):
            return E.compute_graph(types.SimpleNamespace(compute=compute))

    def test_exact_restore_and_existing_single_cpu_no_set(self):
        for original in (65535,8):
            with self.subTest(original=original):
                affinity=Affinity(original);calls=[]
                def compute():
                    self.assertEqual(affinity.mask,original & -original);calls.append('compute');return 'original_return'
                self.assertEqual(self.run_graph(affinity,compute),'original_return')
                self.assertEqual(calls,['compute']);self.assertEqual(affinity.mask,original)
                self.assertEqual(affinity.calls,[] if original==8 else [1,65535])

    def test_sdk_baseexception_and_process_control_restore_without_swallowing(self):
        class APIException(BaseException):pass
        for kind in (RuntimeError,APIException,KeyboardInterrupt,SystemExit):
            with self.subTest(kind=kind.__name__):
                affinity=Affinity();original=kind('poison')
                def compute():raise original
                with self.assertRaises(kind) as caught:self.run_graph(affinity,compute)
                self.assertIs(caught.exception,original)
                self.assertEqual(affinity.calls,[1,65535]);self.assertEqual(affinity.mask,65535)

    def test_setter_readback_failures_never_compute_and_restoration_failure_is_explicit(self):
        for failure in ('restrict','readback'):
            with self.subTest(failure=failure):
                affinity=Affinity(failure=failure);calls=[]
                with self.assertRaises((OSError,RuntimeError)):self.run_graph(affinity,lambda:calls.append('forbidden'))
                self.assertEqual(calls,[]);self.assertEqual(affinity.calls,[1,65535]);self.assertEqual(affinity.mask,65535)
        affinity=Affinity(failure='restore')
        with self.assertRaisesRegex(E.AffinityRestorationError,'65535 restoration failed'):
            self.run_graph(affinity,lambda:None)
        self.assertEqual(affinity.calls,[1,65535])
        class SDKError(BaseException):pass
        original=SDKError('original SDK failure')
        def compute():raise original
        with self.assertRaises(E.AffinityRestorationError) as caught:self.run_graph(Affinity(failure='restore'),compute)
        self.assertIs(caught.exception.__cause__.__context__,original)

    def test_windows_ui_thread_and_graph_type_are_required_before_affinity(self):
        graph_type=type('SDSBSCompGraph',(),{})
        thread=object();app=types.SimpleNamespace(thread=lambda:thread)
        qtcore=types.ModuleType('PySide6.QtCore');qtcore.QThread=types.SimpleNamespace(currentThread=lambda:thread)
        qtwidgets=types.ModuleType('PySide6.QtWidgets');qtwidgets.QApplication=types.SimpleNamespace(instance=lambda:app)
        sdk=types.ModuleType('sd.api.sbs.sdsbscompgraph');sdk.SDSBSCompGraph=graph_type
        modules={'PySide6':types.ModuleType('PySide6'),'PySide6.QtCore':qtcore,'PySide6.QtWidgets':qtwidgets,
                 'sd':types.ModuleType('sd'),'sd.api':types.ModuleType('sd.api'),'sd.api.sbs':types.ModuleType('sd.api.sbs'),
                 'sd.api.sbs.sdsbscompgraph':sdk}
        with patch.dict(sys.modules,modules),patch.object(E.os,'name','nt'):
            E._assert_environment(graph_type())
            with self.assertRaises(TypeError):E._assert_environment(object())
            qtcore.QThread.currentThread=lambda:object()
            with self.assertRaisesRegex(RuntimeError,'UI thread'):E._assert_environment(graph_type())
            qtwidgets.QApplication.instance=lambda:None
            with self.assertRaises(RuntimeError):E._assert_environment(graph_type())
        with patch.object(E.os,'name','unsupported'),patch.object(E,'_ProcessAffinity') as win:
            with self.assertRaisesRegex(RuntimeError,'Windows'):E.compute_graph(object())
            win.assert_not_called()

    def test_product_four_calls_use_helper_without_direct_compute(self):
        for name,wanted in (('designer.py',3),('terminal_capture.py',1)):
            tree=ast.parse((SOURCE.parent/name).read_text(encoding='utf8'))
            calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
            self.assertEqual(sum(isinstance(n.func,ast.Name) and n.func.id=='compute_graph' for n in calls),wanted)
            self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr=='compute'
                                 and isinstance(n.func.value,ast.Name) and n.func.value.id=='graph' for n in calls))

    def test_fixed_original_lane_changes_only_compute_dispatch_and_preserves_default(self):
        driver=ROOT/'tests/designer_full_stock_reference.py'
        default=runpy.run_path(str(driver));scoped=runpy.run_path(str(driver),init_globals={'SCOPED_CPU':True})
        self.assertFalse(default['SCOPED_CPU']);self.assertTrue(scoped['SCOPED_CPU'])
        self.assertEqual(scoped['FX_FIXTURE_MODE'],'original')
        self.assertEqual(default['SCHEDULE'],scoped['SCHEDULE'])
        self.assertEqual(default['ORIGINAL_SHA'],scoped['ORIGINAL_SHA'])
        for invalid in (1,'yes',None):
            with self.assertRaises(ValueError):runpy.run_path(str(driver),init_globals={'SCOPED_CPU':invalid})
        with self.assertRaises(ValueError):runpy.run_path(str(driver),init_globals={'SCOPED_CPU':True,'FX_FIXTURE_MODE':'cut_after_first_gaussian'})
        calls=[];graph=object()
        module=types.ModuleType('substance_physics_scatter.evaluation');module.compute_graph=lambda g:calls.append(g)
        with patch.dict(sys.modules,{'substance_physics_scatter':types.ModuleType('substance_physics_scatter'),
                                    'substance_physics_scatter.evaluation':module}):
            scoped['scoped_compute_once']({'root':lambda *args:graph},None,{},[],{})
        self.assertEqual(calls,[graph])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'))
        self.assertEqual(router['ROUTES']['full_stock_scoped_cpu'],'designer_full_stock_scoped_cpu.py')
        forward=ast.parse((ROOT/'tests/designer_full_stock_scoped_cpu.py').read_text(encoding='utf8'))
        invoke=next(n for n in ast.walk(forward) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='run_path')
        self.assertEqual(ast.literal_eval(next(k.value for k in invoke.keywords if k.arg=='init_globals')),
                         {'FX_FIXTURE_MODE':'original','SCOPED_CPU':True})

    def test_transaction_scope_has_no_graph_and_nested_compute_preserves_outer_mask(self):
        affinity=Affinity();stages=[]
        class SDKError(BaseException):pass
        with patch.object(E,'_assert_environment') as validate,patch.object(E,'_ProcessAffinity',return_value=affinity):
            with self.assertRaises(SDKError):
                with E.evaluation_scope():
                    stages.append(('load_create_configure',affinity.mask))
                    E.compute_graph(types.SimpleNamespace(compute=lambda:stages.append(('compute',affinity.mask))))
                    stages.append(('save_cleanup',affinity.mask))
                    with E.evaluation_scope():
                        self.assertEqual(affinity.mask,1)
                        raise SDKError('transaction SDK poison')
            self.assertEqual(validate.call_args_list[0].args,())
        self.assertEqual(stages,[('load_create_configure',1),('compute',1),('save_cleanup',1)])
        self.assertEqual(affinity.calls,[1,65535]);self.assertEqual(affinity.mask,65535)

    def test_capture_function_entire_operate_and_runtime_creation_are_inside_scope(self):
        source=ast.parse((SOURCE.parent/'terminal_capture.py').read_text(encoding='utf8'))
        function=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='capture_terminal')
        affinity=Affinity();stages=[];runtime=object();handoff={'plain':'handoff'}
        class SDKError(BaseException):pass
        for failure in (False,True):
            def runtime_factory():
                self.assertEqual(affinity.mask,1);stages.append('runtime');return runtime
            def operate(**kwargs):
                self.assertEqual(affinity.mask,1)
                self.assertEqual(kwargs,dict(selection='selection',selected_context='context',operation_id='operation',
                    owned_directory='owned',forbidden_bitmap_paths=('blocked',),runtime=runtime,inspection=False))
                stages.append('operate')
                if failure:raise SDKError('capture poison')
                return handoff
            module=types.ModuleType('pure_capture.evaluation');module.evaluation_scope=E.evaluation_scope
            env=dict(__package__='pure_capture',_SDK=runtime_factory,_operate=operate)
            exec(compile(ast.Module(body=[function],type_ignores=[]),'<actual capture function>','exec'),env)
            with patch.dict(sys.modules,{'pure_capture.evaluation':module}),patch.object(E,'_assert_environment'),patch.object(E,'_ProcessAffinity',return_value=affinity):
                if failure:
                    with self.assertRaises(SDKError):env['capture_terminal']('selection','context','operation','owned',('blocked',))
                else:self.assertIs(env['capture_terminal']('selection','context','operation','owned',('blocked',)),handoff)
            self.assertEqual(affinity.mask,65535)
        self.assertEqual(stages,['runtime','operate','runtime','operate'])

    def test_transaction_fixed_flag_and_main_entry_wrap_without_changing_original_modes(self):
        driver=ROOT/'tests/designer_full_stock_reference.py'
        original=runpy.run_path(str(driver));transaction=runpy.run_path(str(driver),init_globals={'TRANSACTION_CPU':True})
        self.assertFalse(original['TRANSACTION_CPU']);self.assertFalse(transaction['SCOPED_CPU'])
        self.assertEqual(original['SCHEDULE'],transaction['SCHEDULE'])
        self.assertEqual(original['ORIGINAL_SHA'],transaction['ORIGINAL_SHA'])
        for flags in ({'TRANSACTION_CPU':1},{'TRANSACTION_CPU':True,'SCOPED_CPU':True},
                      {'TRANSACTION_CPU':True,'FX_FIXTURE_MODE':'split_shared_data'}):
            with self.assertRaises(ValueError):runpy.run_path(str(driver),init_globals=flags)
        events=[]
        @contextmanager
        def scope():
            events.append('enter')
            try:yield
            finally:events.append('restore')
        def main():events.append('main');return 'report'
        module=types.ModuleType('pure_transaction.evaluation');module.evaluation_scope=scope
        # Execute the actual fixed main entry AST, without its SDK-bearing main.
        entry=ast.parse(driver.read_text(encoding='utf8')).body[-1]
        for enabled,wanted in ((False,['main']),(True,['enter','main','restore'])):
            events.clear();env=dict(__name__='__main__',TRANSACTION_CPU=enabled,main=main,print=lambda *_:None)
            with patch.dict(sys.modules,{'substance_physics_scatter.evaluation':module}):
                exec(compile(ast.Module(body=[entry],type_ignores=[]),'<actual driver entry>','exec'),env)
            self.assertEqual(events,wanted);self.assertEqual(env['REPORT'],'report')
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'))
        self.assertEqual(router['ROUTES']['full_stock_transaction_cpu'],'designer_full_stock_transaction_cpu.py')
        forward=ast.parse((ROOT/'tests/designer_full_stock_transaction_cpu.py').read_text(encoding='utf8'))
        invoke=next(n for n in ast.walk(forward) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='run_path')
        self.assertEqual(ast.literal_eval(next(k.value for k in invoke.keywords if k.arg=='init_globals')),
                         {'FX_FIXTURE_MODE':'original','TRANSACTION_CPU':True})


if __name__=='__main__':unittest.main()
