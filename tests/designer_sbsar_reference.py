"""Root-only same-SBSAR instance attempt: declared32F gate, then measured layout gate."""
from pathlib import Path
import copy,hashlib,json,runpy,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/noise-function-free-compute-probe/b2514d41190146ff8edbaea39ca70aac'
CLI=ROOT/'output/evidence/cli-d3d-float-reference/b77051c9cfcd481b9daba2404dff7588'
ARCHIVE=CLI/'cooked/archive.sbsar';ARCHIVE_SHA='9f2ad4bb1d372cb666c328a673d5559ee84c58874e54633373608639872f2ad2'
CLI_SUMMARY_SHA='24c18742c263a074e04e76412b957b915033960802201602a12bc0f7f5575417'
SDK=ROOT/'output/evidence/full-stock-reference-probe/e9ef7b8f26c6453e8a3d690754ac9a13'
SDK_SHA={'N0':'23777bdd22a2978088a70a78237bfb1a90e99b4ba4bae06481fbe0fff8b827a3','N50':'001f9252c43a2ac0934d140289eecaa4d59047612d60792a37340881745bd19a','NR0':'d02677b5482cd69636897dba8a77d5ed3416d3160512402078623956020f071c'}
CLI_SHA={'N0':'a8729ddf2e63b9be27f500335f1642062d26034625a60d03e21fc341d65bb368','N50':'910b34fdb1a6fc3e84a8f7e9f78c2d5508e3378ba3eceb3df28b4c33750ae582','NR0':'a8729ddf2e63b9be27f500335f1642062d26034625a60d03e21fc341d65bb368'}
STEPS=(('N0',0.),('N50',50.),('NR0',0.))

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def adoptable(path,before,actual,after,order):
    return actual['path']==str(path) and actual['uid'] and not any(p['uid']==actual['uid'] for p in before) and after==order(before+[actual])

def declared_gate(view):
    if view['output']['id']!='Vertical_Noise' or view['output']['types']!=[dict(class_name='SDTypeTexture',id='SDTypeTexture',modifier=dict(name='Auto',value=0))]:raise ValueError('Exact declared archive output Texture required; not a pixel-format measurement')
    if view['Disorder']['property']['flags']['read_only'] or view['Disorder']['property']['flags']['function_only']:raise ValueError('Disorder is not a writable literal Input')
    for row in view['common']:
        expected=[9,9] if row['property']=='$outputsize' else 0 if row['property']=='$randomseed' else 3
        if row['value']['value']!=expected or row['inheritance']!='Absolute':raise ValueError('Private size/seed/declared format3 gate failed')
        if row['property']=='$format' and row['value'].get('value_id')!='hdr_high_precision':raise ValueError('Exact format3 enum ID required')
    if {(r['owner'],r['property']) for r in view['common']}!={(o,p) for o in ('root','instance') for p in ('$outputsize','$format','$randomseed')} or len(view['common'])!=6:raise ValueError('Complete private format/size/seed gate required')

def resource(E):
    P,C=E['P'],E['C'];record=C['item'](E['ledger'],'kernel');package=P['canonical'](E['manager'],record,E['ledger'],E['before']);failure=None;resources=[]
    try:
        resources=list(package.getChildrenResources(False))
        if len(resources)!=1 or resources[0].getIdentifier()!='vertical_noise' or P['package_id'](resources[0].getPackage())!=record['identity'] or list(package.getDependencies() or []):raise ValueError('Archive unique graph/owner/dependencies gate failed')
    except E['ERRORS'] as error:
        failure=dict(error_class=type(error).__name__,error=str(error));error.__traceback__=error.__cause__=error.__context__=None
    if failure is not None:
        package=None;resources=[]
        raise E['A']['OwnerError'](failure) from None
    return resources[0] # Internal phase helper only; never stored in a returned/plain ledger.

def load_archive(E,path):
    P=E['P'];P['context'](E['manager'],E['ledger'],E['before']);E['ledger']['load_calls']+=1
    try:
        package=E['manager'].loadUserPackage(str(path),False,False)
        if package is None:raise ValueError('SBSAR load returned None')
        actual=P['package_id'](package)
        if not adoptable(str(E['F']['logical'](path)),E['before'],actual,P['inventory'](E['manager']),P['order']):raise ValueError('SBSAR return did not add exact private path/unique UID')
    except E['ERRORS']:
        P['ambiguous'](E['ledger'],'Archive load unadopted; no cleanup/full-user reader');raise
    E['ledger']['owned'].append(dict(name='kernel',identity=actual,state='adopted'))
    graph=resource(E)
    return dict(identity=copy.deepcopy(actual),resource_class=graph.getClassName(),identifier=graph.getIdentifier(),url=graph.getUrl(),UID_basis='actual private load return plus inventory delta; not inferred from opaque archive bytes')

def configure(obj,is_graph,E):
    from sd.api.sdvalueint import SDValueInt
    from sd.api.sdvalueint2 import SDValueInt2
    from sd.api.sdvalueenum import SDValueEnum
    from sd.api.sdbasetypes import int2
    for name in ('$outputsize','$format','$randomseed'):
        prop=obj.getPropertyFromId(name,E['Category'].Input)
        if prop is None or prop.isReadOnly() or prop.isFunctionOnly() or not is_graph and (obj.getPropertyGraph(prop) is not None or list(obj.getPropertyConnections(prop))):raise ValueError('Unbound writable common Input required')
        obj.setPropertyInheritanceMethod(prop,E['Inherit'].Absolute)
        value=SDValueInt2.sNew(int2(9,9)) if name=='$outputsize' else SDValueInt.sNew(0) if name=='$randomseed' else SDValueEnum.sFromValueId('sbs::compositing::format','hdr_high_precision')
        obj.setPropertyValue(prop,value)

def create_source(E,path):
    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
    from sd.api.sdvaluestring import SDValueString
    P,C=E['P'],E['C'];P['context'](E['manager'],E['ledger'],E['before']);E['counts']['new_package']+=1;expected=P['expected'](E['ledger'],E['before'])
    try:
        package=E['manager'].newUserPackage();identity=P['package_id'](package)
        if identity['path'] is not None or any(p['uid']==identity['uid'] for p in expected) or P['inventory'](E['manager'])!=P['order'](expected+[identity]):raise ValueError('Fresh root return ownership differs')
    except E['ERRORS']:P['ambiguous'](E['ledger'],'Unadopted new private root');raise
    record=dict(name='source',identity=identity,state='adopted');E['ledger']['owned'].append(record)
    graph=SDSBSCompGraph.sNew(package)
    if graph is None or P['package_id'](graph.getPackage())!=identity:raise E['A']['OwnerError'](dict(error_class='RootOwner',error='New root owner differs'))
    graph.setIdentifier('SBSARNoiseReference');archive=resource(E);node=graph.newInstanceNode(archive)
    if node is None or node.getClassName()!='SDSBSCompNode':raise ValueError('Archive instance node unsupported; compute0')
    terminal=graph.newNode('sbs::compositing::output');terminal.setAnnotationPropertyValueFromId('identifier',SDValueString.sNew('sbsar_noise'))
    configure(graph,True,E);configure(node,False,E)
    output=node.getProperties(E['Category'].Output)
    if output is None or len(output)!=1 or output[0].getId()!='Vertical_Noise':raise ValueError('Archive instance output mapping differs; compute0')
    composition=runpy.run_path(str(BASE/'composition.py'))
    composition['connect'](graph,node.getIdentifier(),'Vertical_Noise',terminal.getIdentifier(),'inputNodeOutput',lambda:P['canonical'](E['manager'],record,E['ledger'],E['before']))
    ids=dict(noise_instance=node.getIdentifier(),terminal=terminal.getIdentifier())
    if len(set(ids.values()))!=2 or len(graph.getNodes())!=2:raise ValueError('Private root2nodes gate failed')
    E['counts']['save']+=1
    try:
        E['manager'].savePackageAs(package,str(path));actual=P['package_id'](package);wanted=dict(uid=identity['uid'],path=str(E['F']['logical'](path)))
        if actual!=wanted or P['inventory'](E['manager'])!=P['order'](expected+[wanted]):raise ValueError('Root save path/UID/inventory differs')
    except E['ERRORS']:P['ambiguous'](E['ledger'],'Private root save identity ambiguous');raise
    record['identity']=actual
    return dict(identity=copy.deepcopy(actual),graph_id=graph.getIdentifier(),graph_url=graph.getUrl(),ids=ids,output='sbsar_noise')

def source_view(E,role,value):
    C,P=E['C'],E['P'];graph=C['root'](E['manager'],E['ledger'],E['before'],role);node=graph.getNodeFromId(role['ids']['noise_instance']);archive=resource(E);ref=None;failure=None
    try:
        ref=node.getReferencedResource()
        if ref is None or ref.getIdentifier()!=archive.getIdentifier() or ref.getUrl()!=archive.getUrl() or P['package_id'](ref.getPackage())!=C['item'](E['ledger'],'kernel')['identity']:raise ValueError('Instance archive reference differs')
    except E['ERRORS'] as error:
        failure=dict(error_class=type(error).__name__,error=str(error));error.__traceback__=error.__cause__=error.__context__=None
    if failure is not None:
        graph=node=archive=ref=None
        raise E['A']['OwnerError'](failure) from None
    common=[]
    for obj,label in ((graph,'root'),(node,'instance')):
        for name,wrapper,type_class,type_id in (('$outputsize','SDValueInt2','SDTypeInt2','int2'),('$format','SDValueEnum','SDTypeEnum','sbs::compositing::format'),('$randomseed','SDValueInt','SDTypeInt','int')):
            prop=obj.getPropertyFromId(name,E['Category'].Input)
            if prop is None or obj.getPropertyInheritanceMethod(prop)!=E['Inherit'].Absolute or label=='instance' and (obj.getPropertyGraph(prop) is not None or list(obj.getPropertyConnections(prop))):raise ValueError('Private common property binding differs')
            scalar=C['scalar'](obj.getPropertyValue(prop))
            if scalar['wrapper']!=wrapper or scalar['type']!=dict(class_name=type_class,id=type_id,modifier=dict(name='Auto',value=0)):raise ValueError('Private common typed value differs')
            common.append(dict(owner=label,property=name,value=scalar,inheritance='Absolute'))
    outputs=list(node.getProperties(E['Category'].Output))
    if len(outputs)!=1:raise ValueError('Exactly one archive output declaration required')
    view=dict(common=common,output=E['A']['descriptor'](outputs[0]),Disorder=E['S']['source_input'](C,E['A'],E['manager'],E['ledger'],E['before'],role,value,E['Category'],E['Inherit']))
    declared_gate(view)
    links=E['links']['incoming_sources'](graph,role['ids']['terminal'],'inputNodeOutput')
    if len(links)!=1 or links[0][0].getIdentifier()!=role['ids']['noise_instance'] or links[0][1].getId()!='Vertical_Noise':raise ValueError('Private terminal edge differs')
    package=P['canonical'](E['manager'],C['item'](E['ledger'],'source'),E['ledger'],E['before']);modified=package.isModified()
    if type(modified) is not bool:raise ValueError('Actual source modified bool required')
    return dict(source_modified=modified,view=view,archive_modified=P['canonical'](E['manager'],C['item'](E['ledger'],'kernel'),E['ledger'],E['before']).isModified())

def main():
    work=ROOT/'output/evidence/sbsar-sdk-reference'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=False);report=work/'summary.json';driver=Path(__file__);driver_sha=digest(driver)
    C=runpy.run_path(str(BASE/'context.py'));P,A=C['P'],C['A'];lane=runpy.run_path(str(BASE/'lane.py'));S=runpy.run_path(str(ROOT/'tests/designer_full_stock_reference.py'));G=runpy.run_path(str(BASE/'user_guard.py'));semantic=runpy.run_path(str(BASE/'enum_scope.py'))
    counts=dict(new_package=0,save=0,disorder_set=0,compute=0);ledger=dict(owned=[],ambiguous=False,load_calls=0,final_unload_calls=0);summary=dict(status='running',work=str(work),counts=counts,ledger=ledger,PNG=0,CLI=0,tolerance=0,raw_count=0,raw_bytes=0,product_acceptance=False,original_failures_resolved=False,precompute_texture_measured=False,first_texture_verified=False,scope='Same CLI SBSAR bytes, continuous Designer instance. Precompute format3 is declared/assigned only, not a measured texture or inferred from EXR export. Actual first output must be512x256 LUM32F before remaining computes/raws; no fallback/resize/retry. Different source wrapper/format context may affect results; no original-stock correction claim.',driver_source=dict(before_sha256=driver_sha))
    def artifact(name,value):
        path=work/(name+'.json');path.write_text(json.dumps(value,indent=2),encoding='utf8');return dict(path=str(path),sha256=digest(path))
    def checkpoint():
        temp=report.with_suffix('.tmp');temp.write_text(json.dumps(summary,indent=2),encoding='utf8');temp.replace(report)
    checkpoint();before=None;user=None;ERRORS=(Exception,);pins={ARCHIVE:ARCHIVE_SHA,CLI/'summary.json':CLI_SUMMARY_SHA}
    for label in SDK_SHA:
        pins[SDK/(label+'-before.raw')]=SDK_SHA[label];pins[CLI/'rendered'/label/(label+'.raw')]=CLI_SHA[label]
    try:
        if any(digest(p)!=s for p,s in pins.items()):raise ValueError('Frozen CLI/archive/SDK comparison input changed')
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
        E=dict(C=C,P=P,A=A,S=S,F=C['F'],manager=manager,ledger=ledger,before=before,counts=counts,ERRORS=ERRORS,Category=Category,Inherit=Inherit,links=runpy.run_path(str(ROOT/'plugin/substance_physics_scatter/connections.py')))
        archive=work/'archive.sbsar'
        with archive.open('xb') as stream:stream.write(ARCHIVE.read_bytes())
        if digest(archive)!=ARCHIVE_SHA:raise ValueError('Private archive copy differs')
        pins[archive]=ARCHIVE_SHA;summary['archive_load']=load_archive(E,archive);checkpoint();role=create_source(E,work/'SBSARReference.sbs');pins[Path(role['identity']['path'])]=digest(role['identity']['path'])
        flags=dict(rows=[]);baseline=None
        def project(view):
            projected=copy.deepcopy(view);projected.pop('source_modified');projected['view']['Disorder'].pop('current');return projected
        def check(value,stage):
            view=source_view(E,role,value);S['source_flag'](flags,view,stage)
            projected=project(view)
            if baseline is not None and projected!=baseline:raise ValueError('Other source/archive metadata changed')
            if type(view['archive_modified']) is not bool:raise ValueError('Actual archive modified bool required')
            if any(digest(p)!=s for p,s in pins.items()):raise ValueError('Frozen/copy disk input changed')
            return projected
        def setter(value,old):
            first=check(old,'before_set');node=C['root'](manager,ledger,before,role).getNodeFromId(role['ids']['noise_instance']);counts['disorder_set']+=1
            if counts['disorder_set']>3:raise ValueError('Three setter budget exceeded')
            node.setInputPropertyValueFromId('Disorder',SDValueFloat.sNew(value));view=source_view(E,role,value);S['source_flag'](flags,view,'after_set',True)
            if project(view)!=first:raise ValueError('Other authored/default/archive state changed during setter')
        setter(0.,0.);baseline=check(0.,'declared_gate_before_first_compute');summary['declared_precompute_gate']=artifact('declared-precompute-gate',source_view(E,role,0.));checkpoint()
        RAW=lane['RAW'];L=lane['L'];F=dict(C['F'],own=lambda p:S['own_raw'](p,work,C['F']));files=RAW['Artifacts'](work,F);L['before_read'](0,0,L['LAYOUTS'])
        def capture(name,texture,layout):
            L['before_read'](summary['raw_count'],files.used,(layout,));data,metadata=RAW['capture'](texture,expected_layout=layout);ref=files.save(name,data,metadata,expected_layout=layout);summary.update(raw_count=summary['raw_count']+1,raw_bytes=files.used,raw_artifacts=files.rows);return data,ref
        summary['K']=lane['calibrate'](capture);images={};summary['observations']=[]
        for index,(label,value) in enumerate(STEPS):
            if (work/'CANCEL').exists():raise InterruptedError('Cancelled at safe boundary')
            if index:setter(value,STEPS[index-1][1])
            check(value,'before_compute');counts['compute']+=1;checkpoint();lane['compute_once'](manager,ledger,before,role);check(value,'after_compute');L['before_read'](summary['raw_count'],files.used,(L['FX_LAYOUT'],)*2)
            data,row=lane['read_terminal'](manager,ledger,before,role,label,capture);summary['first_texture_verified']=True;summary['observations'].append(row);images[label]=data;check(value,'after_raw');checkpoint()
            if not row['distinct_words_at_least2']:raise ValueError('Nonuniform compiled output required; remaining computes stopped')
        if counts['compute']!=3 or counts['disorder_set']!=3 or summary['raw_count']!=7 or files.used!=3670016:raise ValueError('Fixed3compute7raw count differs')
        summary['comparisons']={label:dict(CLI=lane['compare']((CLI/'rendered'/label/(label+'.raw')).read_bytes(),images[label]),original_SDK=lane['compare']((SDK/(label+'-before.raw')).read_bytes(),images[label])) for label,_ in STEPS};summary['return_comparison']=lane['compare'](images['N0'],images['NR0']);summary['input_effect']=lane['compare'](images['N0'],images['N50']);summary['math_pass']=summary['return_comparison']['exact'];summary['status']='SBSAR_instance_observation_complete'
    except ERRORS as error:
        if isinstance(error,A['OwnerError']):P['ambiguous'](ledger,'Archive/resource owner unverified')
        summary.update(status='failed',error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()));error.__traceback__=error.__cause__=error.__context__=None
    finally:
        if before is not None:
            try:
                summary['cleanup']=P['cleanup'](manager,ledger,before,ERRORS);final=P['inventory'](manager);summary['inventory_after']=artifact('inventory-after',final);summary['inventory_unchanged']=final==before
                if user is not None and P['trust_final'](ledger,final,before):
                    after=G['protected_snapshot']();summary['user_after']=artifact('user-after',after);comparison=semantic['compare'](user,after,C['F']['read_json'](BASE/'enum_expected.json'));summary['user_comparison']=artifact('user-comparison',comparison);summary['user_unchanged']=comparison['semantic_protection_equal']
                if not summary.get('user_unchanged') or not summary['inventory_unchanged']:summary['status']='failed_preservation'
            except ERRORS as error:summary.update(status='failed_preservation',protection_error=str(error));error.__traceback__=error.__cause__=error.__context__=None
        summary['frozen_inputs_unchanged']=all(digest(p)==s for p,s in pins.items());summary['source_modified_observations']=locals().get('flags',{}).get('rows',[]);summary['driver_source'].update(after_sha256=digest(driver));summary['driver_source']['unchanged']=digest(driver)==driver_sha
        if not summary['frozen_inputs_unchanged'] or not summary['driver_source']['unchanged']:summary['status']='failed_preservation'
        checkpoint()
    return report

if __name__=='__main__':
    REPORT=main()
    print(str(REPORT))
