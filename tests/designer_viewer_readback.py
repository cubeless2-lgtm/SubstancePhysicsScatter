"""Fixed, idle-only direct selected-terminal readback; no graph edits/copy/worker."""
from pathlib import Path
import json,uuid,traceback
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/viewer-readback'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
result=dict(status='running',compute=1,worker=0,package_mutations=0)
try:
    import substance_physics_scatter
    from substance_physics_scatter import terminal_capture as cap,evaluation,mask_source
    panel=substance_physics_scatter._panel
    latest=json.loads((ROOT/'output/GraphMaskReview/latest.json').read_text(encoding='utf8'))
    if panel is None or panel._token is not None or panel.process is not None or panel._target_identity!=latest['target'] or panel._phase!='idle':raise ValueError('Owned example must be selected and idle')
    current=panel.jobs.current
    selected=panel.source_choices.currentData()
    if selected is None or selected['graph_identifier']!='NativeMaskSource' or selected['terminal_identifier']!='native_mask':raise ValueError('Fixed terminal selection required')
    selected=mask_source.selection(selected,historical=True)
    sdk=cap._SDK();sdk.assert_thread()
    before=evaluation._ProcessAffinity().get();path=WORK/'direct-canonical-terminal.png'
    with evaluation.evaluation_scope():sdk.compute(selected);sdk.save(selected,path)
    after=evaluation._ProcessAffinity().get()
    original=cap._png(Path(current['request']['scatter_mask']['path']));direct=cap._png(path)
    exact=original['decoded_u16be_sha256']==direct['decoded_u16be_sha256']
    result.update(status='PASS' if exact and before==after else 'FAIL',job_id=current['job_id'],cached=original,direct=direct,decoded_exact=exact,affinity_restored=before==after)
except BaseException:result.update(status='FAILED',traceback=traceback.format_exc())
REPORT.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
