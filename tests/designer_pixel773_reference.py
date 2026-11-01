"""Fixed read-only N/T/N experiment in the existing owned review package."""
from pathlib import Path
import hashlib,json,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/pixel773-reference'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
E=dict(status='running',computer_use=False,package_mutations=0,worker=0,compute=0,outputs={})
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
try:
    import substance_physics_scatter
    from substance_physics_scatter import evaluation,terminal_capture as cap,mask_source
    p=substance_physics_scatter._panel
    locator=json.loads((ROOT/'output/GraphMaskReview/latest.json').read_text(encoding='utf8'))
    if p is None or p._token is not None or p.process is not None or p._phase!='idle' or p._target_identity!=locator['target']:raise ValueError('Owned canonical panel must be idle')
    selected=mask_source.selection(p.source_choices.currentData(),historical=True)
    if selected['graph_identifier']!='NativeMaskSource' or selected['terminal_identifier']!='native_mask':raise ValueError('Fixed source selection')
    sdk=cap._SDK();sdk.assert_thread();manager=sdk._manager()
    source=sdk._canonical(manager,dict(path=selected['package_path'],uid=selected['package_uid']),True)
    modified=source.isModified();inventory=sdk._inventory(manager)
    watch={str(Path(locator[k])):sha(locator[k]) for k in ('source',)}
    watch[str(Path(p.jobs.directory)/'current.json')]=sha(Path(p.jobs.directory)/'current.json')
    affine=evaluation._ProcessAffinity().get()
    with evaluation.evaluation_scope():
        for label,g,t in (('N0','NativeNoiseReference','reference_noise'),('T','NativeMaskSource','native_mask'),('N1','NativeNoiseReference','reference_noise')):
            choice=dict(selected,graph_identifier=g,terminal_identifier=t)
            sdk.compute(choice);E['compute']+=1
            path=WORK/(label+'.png');sdk.save(choice,path);E['outputs'][label]=cap._png(path)
    if any(sha(path)!=h for path,h in watch.items()) or source.isModified()!=modified or sdk._inventory(manager)!=inventory:raise ValueError('Owned/user state changed')
    E.update(status='OBSERVED',affinity_restored=evaluation._ProcessAffinity().get()==affine,current_job=p.jobs.current['job_id'])
except BaseException:E.update(status='FAILED',traceback=traceback.format_exc())
REPORT.write_bytes((json.dumps(E,indent=2)+'\n').encode('utf8'))
