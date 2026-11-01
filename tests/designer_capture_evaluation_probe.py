"""Fixed canonical product inspector/capture pair. Root owns all actual execution.

Reuses a727 source/stock preparation, ownership/user protection and raw observer.
No widget, worker, bake, private product alias, source edit or outer affinity set.
"""
from pathlib import Path
import copy,hashlib,json,runpy,traceback,uuid

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/h2-first-capture-probe/a72703984c254876a32475cbb336a1da'
EXPECTED_MASK=65535


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture_pair(designer,adapter,model,observer_api,caller,ownership,manager,ledger,before,
                 selection,work,artifact,affinity,summary):
    """Two independent fresh inspector contexts; no reuse after unload or capture."""
    def mask(stage):
        actual=affinity.get();summary.setdefault('affinity_observations',[]).append(dict(stage=stage,mask=actual))
        if actual!=EXPECTED_MASK:raise ValueError('Expected original process affinity65535 at '+stage)
    original=ownership['states'](manager,ledger,before)
    summary['operations']=[];decoded=[]
    for index in (1,2):
        row=dict(index=index);summary['operations'].append(row)
        mask('before_inspector_'+str(index))
        inspection_id=uuid.uuid4().hex;capture_id=uuid.uuid4().hex
        if inspection_id==capture_id:raise ValueError('Distinct operation IDs required')
        root=work/('operation-'+str(index));root.mkdir(exist_ok=False)
        inspection_dir=root/'inspection';inspection_dir.mkdir()
        values=dict(selection=copy.deepcopy(selection),operation_id=inspection_id,
                    owned_directory=str(inspection_dir),forbidden_bitmap_paths=[])
        row['inspector_arguments']=artifact('inspector-arguments-'+str(index),values)
        local_counts=dict(inspector=0,capture=0)
        summary['inspector_attempts']+=1
        inspection=caller['call_once'](designer,adapter,values,local_counts,lambda n,v:artifact(n+'-'+str(index),v))
        row['inspection_validation']=caller['verify_result'](inspection,values,model,ownership['inventory'](manager))
        mask('after_inspector_'+str(index))
        if ownership['states'](manager,ledger,before)!=original:raise ValueError('Inspector changed original source/stock')
        raw_dir=root/'raw';raw_dir.mkdir();raw_summary={};row['raw_observation']=raw_summary
        observer=observer_api['Observer'](raw_dir,raw_summary,lambda n,v:artifact(n+'-'+str(index),v))
        observer.calibrate()  # One accepted K per observer; no graph computation.
        capture_dir=root/'capture';capture_dir.mkdir()
        capture_values=dict(selection=copy.deepcopy(selection),selected_context=inspection['selected_context'],
                            operation_id=capture_id,owned_directory=str(capture_dir),forbidden_bitmap_paths=[])
        row['capture_arguments']=artifact('capture-arguments-'+str(index),capture_values)
        summary['capture_attempts']+=1
        captured=observer.invoke(designer,adapter,capture_values,local_counts)
        row['capture_validation']=observer_api['verify'](captured,capture_values,inspection,model,observer)
        # Preserve product return before any final equality assertion.
        row['captured']=artifact('product-capture-'+str(index),captured)
        mask('after_capture_'+str(index))
        if ownership['states'](manager,ledger,before)!=original:raise ValueError('Capture changed original source/stock')
        pixels,descriptor=observer_api['decode'](captured['png']['path']);decoded.append(pixels)
        row['png']=descriptor;row['counts']=captured['counts']
        if captured['counts']!=dict(copies=6,copy_limit=6,compute=1,PNG=1,worker=0):raise ValueError('Fixed capture bounds differ')
    summary['two_capture_decoded_comparison']=dict(exact=decoded[0]==decoded[1],pixel_count=262144,
        mismatch_count=sum(decoded[0][i:i+2]!=decoded[1][i:i+2] for i in range(0,len(decoded[0]),2)),
        first_sha256=hashlib.sha256(decoded[0]).hexdigest(),second_sha256=hashlib.sha256(decoded[1]).hexdigest(),tolerance=0)
    if decoded[0]!=decoded[1]:raise ValueError('Two fresh product captures differ at exact0')
    summary.update(compute=2,PNG=2,saveCopy=18,raw=6,raw_bytes=3145728)


def main():
    router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));router['project_root']()
    work=router['owned'](ROOT,ROOT/'output/designer_bridge/capture-evaluation'/uuid.uuid4().hex)
    work.mkdir(parents=True,exist_ok=False);report=work/'summary.json'
    def own(path):
        path=router['owned'](ROOT,path)
        if path==work or not path.is_relative_to(work):raise ValueError('Outside private capture work')
        return path
    def save():
        temporary=own(work/(uuid.uuid4().hex+'.tmp'))
        temporary.write_bytes((json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8'))
        temporary.replace(report)
    def artifact(name,value):
        path=own(work/(name+'.json'))
        with path.open('x',encoding='utf8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        return dict(path=str(path),sha256=sha(path),bytes=path.stat().st_size)
    ledger=dict(owned=[],ambiguous=False,load_calls=0,final_unload_calls=0)
    summary=dict(status='running',work=str(work),ledger=ledger,inspector_attempts=0,capture_attempts=0,
        worker=0,widgets=0,native=0,bake=0,product_acceptance=False,tolerance=0,
        limits=dict(inspectors=2,captures=2,copies=18,compute=2,PNG=2,raw=6,raw_bytes=3145728,load=3,unload=3),
        scope='Canonical designer inspector→capture twice; independent fresh contexts, raw-before=PNG=raw-after and decoded PNG pair exact0. Product transaction scope only; preparation is not under an outer affinity guard. Existing failures preserved.')
    save();errors=(Exception,);before=None;user_before=None;original=None;disks={};affinity=None;manager=None
    P=runpy.run_path(str(BASE/'ownership.py'));F=runpy.run_path(str(BASE/'probe_files.py'))
    G=None;S=runpy.run_path(str(BASE/'enum_scope.py'))
    O=runpy.run_path(str(BASE/'capture_observer.py'));C=runpy.run_path(str(BASE/'caller.py'))
    O['F']['own']=own  # Local runpy namespace adapter only; frozen helper bytes unchanged.
    spec=F['read_json'](BASE/'enum_expected.json');prep=F['read_json'](BASE/'preparation.json')
    def saved():
        if len(spec['saved_files'])!=13:raise ValueError('Exact13 saved-file protection required')
        for path,expected in spec['saved_files'].items():
            if Path(path).stat().st_size!=expected['size'] or sha(path)!=expected['sha256']:raise ValueError('Protected saved13 changed')
    def user(label):
        raw=G['protected_snapshot']();artifact(label+'-user-raw',raw);saved()
        if user_before is not None:
            comparison=S['compare'](user_before,raw,spec);artifact(label+'-user-comparison',comparison)
            if not comparison['semantic_protection_equal']:raise ValueError('User authored state changed')
        return raw
    try:
        import sd
        from sd.api.apiexception import APIException
        from substance_physics_scatter import designer,terminal_capture,mask_source,evaluation
        errors=(Exception,APIException)
        G=runpy.run_path(str(BASE/'user_guard.py'))
        evaluation._assert_environment();affinity=evaluation._ProcessAffinity()
        summary['affinity_before']=affinity.get()
        if summary['affinity_before']!=EXPECTED_MASK:raise ValueError('Original mask must be65535; no affinity setter in this lane')
        for module in (designer,terminal_capture,evaluation):
            if Path(module.__file__).resolve()!=ROOT/'plugin/substance_physics_scatter'/(module.__name__.rsplit('.',1)[-1]+'.py'):raise ValueError('Canonical product module path differs')
        if designer.compute_graph is not evaluation.compute_graph or 'evaluation_scope' not in terminal_capture.capture_terminal.__code__.co_names:
            raise ValueError('Transaction evaluation code is not loaded; explicit root reload required')
        manager=sd.getContext().getSDApplication().getPackageMgr()
        before=P['inventory'](manager);summary['inventory_before']=artifact('inventory-before',before)
        if len(before)!=20:raise ValueError('Expected original user20 inventory')
        G['configure'](manager,ledger['owned']);user_before=user('before')
        identities={};prepared={}
        for role in ('noise','invert','source'):
            meta=copy.deepcopy(prep['packages'][role]);source=BASE/'prepared'/meta['relative_path']
            if sha(source)!=meta['sha256']:raise ValueError('Accepted a727 preparation changed')
            uid=str(uuid.uuid4());raw,proof=F['replace_top_uid'](source.read_bytes(),uid)
            path=own(work/'source'/meta['relative_path']);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(raw)
            meta.update(uid=uid,sha256=sha(path));prepared[role]=meta;identities[role]=dict(path=str(path),uid=uid)
            disks[str(path)]=sha(path);artifact('uid-'+role,proof)
        if len({r['uid'] for r in identities.values()})!=3 or any(r['uid']==b['uid'] for r in identities.values() for b in before):raise ValueError('Fresh UID collision; load0')
        for role in ('noise','invert','source'):
            summary['load_'+role]=P['load_one'](manager,role,identities[role],prepared[role],identities,ledger,before)
        original=P['states'](manager,ledger,before);artifact('own-before',original)
        selection=dict(package_path=identities['source']['path'],package_uid=identities['source']['uid'],
                       graph_identifier='NativeMaskSource',terminal_identifier='native_mask')
        capture_pair(designer,terminal_capture,mask_source,O,C,P,manager,ledger,before,selection,work,artifact,affinity,summary)
        summary['status']='product_capture_pair_observation_complete'
    except errors as error:
        summary.update(status='failed',error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
        error.__traceback__=None;error.__cause__=None;error.__context__=None
    finally:
        if manager is not None and before is not None:
            try:
                if original is not None and not ledger['ambiguous']:
                    current=P['states'](manager,ledger,before);artifact('own-precleanup',current)
                    if current!=original:raise ValueError('Original source/stock changed')
            except errors as error:
                summary.update(status='failed_preservation',own_error=dict(type=type(error).__name__,message=str(error)))
                error.__traceback__=None;error.__cause__=None;error.__context__=None
            try:
                summary['cleanup']=P['cleanup'](manager,ledger,before,errors)
                final=P['inventory'](manager);summary['inventory_after']=artifact('inventory-after',final)
                summary['inventory_unchanged']=final==before;saved()
                summary['user_guard']=P['finish_guard'](ledger,final,before,user_before is not None,lambda:user('final'))
                if not summary['user_guard']['verified'] or not summary['inventory_unchanged']:raise ValueError('Full user preservation unverified; safe inventory/saved13 only')
                summary['private_disks_unchanged']=all(sha(path)==digest for path,digest in disks.items())
                if not summary['private_disks_unchanged']:raise ValueError('Private original disks changed')
            except errors as error:
                summary.update(status='failed_preservation',protection_error=dict(type=type(error).__name__,message=str(error)))
                error.__traceback__=None;error.__cause__=None;error.__context__=None
        if affinity is not None:
            try:
                summary['affinity_after']=affinity.get();summary['affinity_restored']=summary['affinity_after']==EXPECTED_MASK
                if not summary['affinity_restored']:raise ValueError('Product transaction failed to restore original mask65535')
            except errors as error:summary.update(status='failed_affinity',affinity_error=str(error))
        summary['context_valid_after_cleanup']=False
        save()
    return report


if __name__=='__main__':REPORT=main()
