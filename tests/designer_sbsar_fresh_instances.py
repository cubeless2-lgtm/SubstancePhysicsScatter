"""Root-only same-session archive1, fresh root/instance per0/50/0; no live-output claim."""
from pathlib import Path
import copy,hashlib,json,runpy,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
DRIVER=ROOT/'tests/designer_sbsar_reference.py'
REUSED_DRIVER_SHA='ba19f3f2c279773a7cd21244a9a73c7679a1428775a411a25ee2810ea67e58a7'
CONTINUOUS=ROOT/'output/evidence/sbsar-sdk-reference/34fdaa811cd748dfb614f788e7e50ca7'
CONT_SUMMARY_SHA='81a32097e2a1a2dd7b8324677ec946893edf5a9f16e5e74a372d8a5c90c5529c'
CONT_SHA={'N0':'6978d16061704e6ebbd020c3da2c3b9f0ee1d7d17aac60c8bd3b904d148ae446','N50':'3c521df4a51924854f615dc7c703b877f14123dc1570219019dab1c53dc2f09f','NR0':'4290ed70c9625c4e5d17464322dd7c32471f2baa0b99c8109a6fd3bcad752a3e'}

def project(view):
    result=copy.deepcopy(view);result.pop('source_modified');result['view']['Disorder'].pop('current');return result

def step(E,work,label,value,capture,artifact,pins):
    D,C,P,S=E['D'],E['C'],E['P'],E['S'];summary=E['summary'];manager=E['manager'];ledger=E['ledger'];before=E['before']
    role=D['create_source'](E,work/(label+'-fresh.sbs'));source_path=Path(role['identity']['path']);pins[source_path]=D['digest'](source_path);flags=dict(rows=[])
    def check(expected,stage):
        view=D['source_view'](E,role,expected);S['source_flag'](flags,view,stage)
        if baseline is not None and project(view)!=baseline:raise ValueError('Fresh root authored/default/archive state changed')
        if any(D['digest'](p)!=s for p,s in pins.items()):raise ValueError('Frozen/source file changed')
        return view
    baseline=None;initial=check(0.,'before_only_setter');baseline=project(initial)
    node=C['root'](manager,ledger,before,role).getNodeFromId(role['ids']['noise_instance']);E['counts']['disorder_set']+=1
    if E['counts']['disorder_set']>3:raise ValueError('Exactly one setter per root, max3')
    node.setInputPropertyValueFromId('Disorder',E['float_value'](value));node=None
    after=D['source_view'](E,role,value);S['source_flag'](flags,after,'after_only_setter',True)
    if project(after)!=baseline:raise ValueError('Other state changed during fresh root input setter')
    summary['steps'].append(dict(label=label,identity=role['identity'],graph_url=role['graph_url'],ids=role['ids'],declared_gate=artifact(label+'-declared-gate',after),source_modified_observations=flags['rows']));E['checkpoint']()
    check(value,'before_first_compute');E['counts']['compute']+=1
    if E['counts']['compute']>3:raise ValueError('Fixed max3 computes')
    E['checkpoint']();E['lane']['compute_once'](manager,ledger,before,role);check(value,'after_first_compute')
    E['L']['before_read'](summary['raw_count'],E['files'].used,(E['L']['FX_LAYOUT'],)*2)
    data,row=E['lane']['read_terminal'](manager,ledger,before,role,label,capture);check(value,'after_raw')
    if not row['distinct_words_at_least2']:raise ValueError('Nonuniform fresh output required; no extra compute')
    # read_terminal returned bytes/JSON and released its SDValueTexture/SDTexture.
    summary['steps'][-1]['measured_texture_verified']=True;summary['observations'].append(row)
    record=C['item'](ledger,'source');summary['root_cleanup'].append(P['remove'](manager,record,ledger,before,'root'));E['checkpoint']()
    return data

def main():
    D=runpy.run_path(str(DRIVER));BASE=D['BASE'];C=runpy.run_path(str(BASE/'context.py'));P,A=C['P'],C['A'];S=runpy.run_path(str(ROOT/'tests/designer_full_stock_reference.py'));lane=runpy.run_path(str(BASE/'lane.py'));G=runpy.run_path(str(BASE/'user_guard.py'));semantic=runpy.run_path(str(BASE/'enum_scope.py'))
    work=ROOT/'output/evidence/sbsar-fresh-instances'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=False);report=work/'summary.json';driver=Path(__file__);driver_sha=D['digest'](driver)
    counts=dict(new_package=0,save=0,disorder_set=0,compute=0);ledger=dict(owned=[],ambiguous=False,load_calls=0,root_unload_calls=0,final_unload_calls=0)
    summary=dict(status='running',work=str(work),counts=counts,ledger=ledger,steps=[],observations=[],root_cleanup=[],raw_count=0,raw_bytes=0,PNG=0,CLI=0,tolerance=0,product_acceptance=False,original_failures_resolved=False,precompute_texture_measured=False,driver_source=dict(before_sha256=driver_sha),scope='Same Designer session and one unchanged CLI SBSAR load; each0/50/0 gets a fresh private root/instance, one explicit input setter before its first compute, then immediate root cleanup. Root/instance identities and RNG/cache context can differ. Exact fresh-root return would not prove preservation of the earlier live output or a product correction; no global cache reset is attempted.')
    def artifact(name,value):
        path=work/(name+'.json');path.write_text(json.dumps(value,indent=2),encoding='utf8');return dict(path=str(path),sha256=D['digest'](path))
    def checkpoint():
        temp=report.with_suffix('.tmp');temp.write_text(json.dumps(summary,indent=2),encoding='utf8');temp.replace(report)
    checkpoint();before=None;user=None;ERRORS=(Exception,)
    pins={DRIVER:REUSED_DRIVER_SHA,D['ARCHIVE']:D['ARCHIVE_SHA'],D['CLI']/'summary.json':D['CLI_SUMMARY_SHA'],CONTINUOUS/'summary.json':CONT_SUMMARY_SHA}
    for label in CONT_SHA:
        pins[CONTINUOUS/(label+'-before.raw')]=CONT_SHA[label];pins[D['CLI']/'rendered'/label/(label+'.raw')]=D['CLI_SHA'][label]
    try:
        if any(D['digest'](p)!=s for p,s in pins.items()):raise ValueError('Frozen archive/continuous/CLI input changed')
        import sd
        from sd.api.apiexception import APIException
        from sd.api.sdproperty import SDPropertyCategory as Category,SDPropertyInheritanceMethod as Inherit
        from sd.api.sdvaluefloat import SDValueFloat
        from PySide6 import QtCore,QtWidgets
        ERRORS=(Exception,APIException);app=QtWidgets.QApplication.instance()
        if app is None or QtCore.QThread.currentThread()!=app.thread():raise ValueError('Designer UI thread required')
        app=None;application=sd.getContext().getSDApplication()
        if application.getVersion()!='16.0.3':raise ValueError('Pinned Designer version differs')
        manager=application.getPackageMgr();application=None;before=P['inventory'](manager);summary['inventory_before']=artifact('inventory-before',before);G['configure'](manager,[]);user=G['protected_snapshot']();summary['user_before']=artifact('user-before',user)
        E=dict(D=D,C=C,P=P,A=A,S=S,F=C['F'],manager=manager,ledger=ledger,before=before,counts=counts,ERRORS=ERRORS,Category=Category,Inherit=Inherit,float_value=SDValueFloat.sNew,links=runpy.run_path(str(ROOT/'plugin/substance_physics_scatter/connections.py')),summary=summary,checkpoint=checkpoint,lane=lane,L=lane['L'])
        archive=work/'archive.sbsar'
        with archive.open('xb') as stream:stream.write(D['ARCHIVE'].read_bytes())
        pins[archive]=D['ARCHIVE_SHA'];summary['archive_load']=D['load_archive'](E,archive);checkpoint()
        RAW=lane['RAW'];L=lane['L'];F=dict(C['F'],own=lambda p:S['own_raw'](p,work,C['F']));files=RAW['Artifacts'](work,F);E['files']=files;L['before_read'](0,0,L['LAYOUTS'])
        def capture(name,texture,layout):
            L['before_read'](summary['raw_count'],files.used,(layout,));data,metadata=RAW['capture'](texture,expected_layout=layout);ref=files.save(name,data,metadata,expected_layout=layout);summary.update(raw_count=summary['raw_count']+1,raw_bytes=files.used,raw_artifacts=files.rows);return data,ref
        summary['K']=lane['calibrate'](capture);images={}
        for label,value in D['STEPS']:
            if (work/'CANCEL').exists():raise InterruptedError('Cancelled at safe boundary')
            images[label]=step(E,work,label,value,capture,artifact,pins)
        if counts!=dict(new_package=3,save=3,disorder_set=3,compute=3) or ledger['root_unload_calls']!=3 or summary['raw_count']!=7 or files.used!=3670016:raise ValueError('Fresh3root/3compute/7raw cardinality differs')
        summary['comparisons']={label:dict(CLI=lane['compare']((D['CLI']/'rendered'/label/(label+'.raw')).read_bytes(),images[label]),continuous_instance=lane['compare']((CONTINUOUS/(label+'-before.raw')).read_bytes(),images[label])) for label,_ in D['STEPS']};summary['return_comparison']=lane['compare'](images['N0'],images['NR0']);summary['input_effect']=lane['compare'](images['N0'],images['N50']);summary['math_pass']=summary['return_comparison']['exact'];summary['status']='fresh_instance_observation_complete'
    except ERRORS as error:
        if isinstance(error,A['OwnerError']):P['ambiguous'](ledger,'Fresh archive/resource owner unverified')
        summary.update(status='failed',error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()));error.__traceback__=error.__cause__=error.__context__=None
    finally:
        if before is not None:
            try:
                summary['cleanup']=P['cleanup'](manager,ledger,before,ERRORS);final=P['inventory'](manager);summary['inventory_after']=artifact('inventory-after',final);summary['inventory_unchanged']=final==before
                if user is not None and P['trust_final'](ledger,final,before):
                    after=G['protected_snapshot']();summary['user_after']=artifact('user-after',after);comparison=semantic['compare'](user,after,C['F']['read_json'](BASE/'enum_expected.json'));summary['user_comparison']=artifact('user-comparison',comparison);summary['user_unchanged']=comparison['semantic_protection_equal']
                if not summary.get('user_unchanged') or not summary['inventory_unchanged']:summary['status']='failed_preservation'
            except ERRORS as error:summary.update(status='failed_preservation',protection_error=str(error));error.__traceback__=error.__cause__=error.__context__=None
        summary['frozen_inputs_unchanged']=all(D['digest'](p)==s for p,s in pins.items());summary['driver_source'].update(after_sha256=D['digest'](driver));summary['driver_source']['unchanged']=D['digest'](driver)==driver_sha
        if not summary['frozen_inputs_unchanged'] or not summary['driver_source']['unchanged']:summary['status']='failed_preservation'
        checkpoint()
    return report

if __name__=='__main__':
    REPORT=main()
    print(str(REPORT))
