"""Closed smoke lanes. Selection contains one enum, never a path or source code."""
from pathlib import Path
import json
import runpy
import os,stat

ROOT=Path(__file__).resolve().parents[1]
ROUTES={
    'file_mask':'designer_file_mask.py',
    'managed_bridge_actual':'designer_bridge_managed_actual.py',
    'full_stock_original':'designer_full_stock_reference.py',
    'full_stock_scoped_cpu':'designer_full_stock_scoped_cpu.py',
    'full_stock_transaction_cpu':'designer_full_stock_transaction_cpu.py',
    'product_capture_pair':'designer_capture_evaluation_probe.py',
    'graph_mask_final':'designer_graph_mask_final.py',
    'prepare_graph_review':'designer_prepare_graph_review.py',
    'viewer_live':'designer_viewer_live.py',
    'viewer_readback':'designer_viewer_readback.py',
    'pixel773_reference':'designer_pixel773_reference.py',
    'pixel773_private':'designer_pixel773_private.py',
    'pixel773_repeat':'designer_pixel773_repeat.py',
    'reload_deterministic':'designer_reload_deterministic.py',
    'pixel773_ui':'designer_pixel773_ui.py',
    'pixel773_product':'designer_pixel773_product.py',
    'window_inspect':'designer_window_inspect.py',
    'window_apply':'designer_window_apply.py',
    'motion_actual':'designer_motion_actual.py',
    'motion_saved':'designer_motion_saved.py',
    'live_actual':'designer_live_actual.py',
    'original_pixel_scoped':'designer_original_pixel_scoped.py',
    'reload_evaluation':'designer_reload_evaluation.py',
    'unique_function_ids':'designer_full_stock_unique_fn_ids.py',
    'split_shared_data':'designer_full_stock_split_data.py',
    'cut_after_first_gaussian':'designer_full_stock_cut_first.py',
    'cut_after_second_gaussian':'designer_full_stock_cut_second.py',
    'cut_after_third_gaussian':'designer_full_stock_cut_third.py',
    'last_gaussian_one_branch':'designer_full_stock_last_one_branch.py',
    'full_stock_repeat_cycles':'designer_full_stock_repeat_cycles.py',
    'fourth_gaussian_contribution':'designer_full_stock_fourth_contribution.py',
    'last_owner_none_zero_offset':'designer_full_stock_last_none_zero_offset.py',
    'last_owner_none_half_opacity':'designer_full_stock_last_none_half_opacity.py',
    'sbsar_reference':'designer_sbsar_reference.py',
    'sbsar_fresh_instances':'designer_sbsar_fresh_instances.py',
}
MAX_SELECTION_BYTES=512

def owned(root,path):
    root=Path(root).resolve();path=Path(path).absolute()
    if not path.is_relative_to(root):raise ValueError('Smoke path escapes project')
    current=root
    for part in path.relative_to(root).parts:
        current=current/part
        junction=getattr(current,'is_junction',None)
        if current.is_symlink() or callable(junction) and junction():raise ValueError('Smoke symlink/junction path forbidden')
        if os.name=='nt':
            try:attributes=getattr(current.lstat(),'st_file_attributes',None)
            except FileNotFoundError:continue # Owned staging directories may not exist yet.
            if type(attributes) is not int or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:raise ValueError('Smoke Windows reparse point/unknown attributes forbidden')
    if not path.resolve().is_relative_to(root):raise ValueError('Smoke resolved path escapes project')
    return path

def project_root():
    root=ROOT.resolve()
    for name in ('CMakeLists.txt','tests/designer_smoke.py','tests/designer_smoke_routes.py'):
        if not owned(root,root/name).is_file():raise ValueError('Not the Physics Scatter development root')
    return root

def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate smoke selection key')
        result[key]=value
    return result

def selection(root):
    path=owned(root,Path(root)/'output/designer_bridge/smoke_selection.json')
    if not path.exists():return 'file_mask'
    if not path.is_file() or path.stat().st_size>MAX_SELECTION_BYTES:raise ValueError('Invalid/oversized smoke selection')
    with path.open('rb') as stream:raw=stream.read(MAX_SELECTION_BYTES+1)
    if len(raw)>MAX_SELECTION_BYTES:raise ValueError('Oversized smoke selection')
    value=json.loads(raw.decode('utf8'),object_pairs_hook=_unique_object)
    if type(value) is not dict or set(value)!={'lane'} or type(value['lane']) is not str or value['lane'] not in ROUTES:raise ValueError('Exactly one allowlisted smoke lane string required')
    return value['lane']

def target(root,lane):
    if type(lane) is not str or lane not in ROUTES:raise ValueError('Unknown fixed smoke lane')
    path=owned(root,Path(root)/'tests'/ROUTES[lane])
    if not path.is_file():raise ValueError('Fixed smoke lane is unavailable')
    return path

def run():
    root=project_root();lane=selection(root)
    result=runpy.run_path(str(target(root,lane)),run_name='__main__')
    return result['REPORT']

if __name__=='__main__':REPORT=run()
