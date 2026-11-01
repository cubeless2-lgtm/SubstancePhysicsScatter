"""Product N/F0/T/F1 exact comparison. Actual SDK execution belongs to root only."""
from pathlib import Path
import copy, hashlib, json, runpy, struct, sys, traceback, uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output/evidence/h2-first-capture-probe/a72703984c254876a32475cbb336a1da'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(a, b, invert=False):
    if len(a) != 524288 or len(b) != len(a):
        raise ValueError('Exact512x512 uint16 comparison required')
    delta = {}; mismatches = 0
    for (x,), (y,) in zip(struct.iter_unpack('>H', a), struct.iter_unpack('>H', b)):
        d = y - (65535 - x if invert else x)
        delta[str(d)] = delta.get(str(d), 0) + 1
        mismatches += d != 0
    return dict(mismatches=mismatches, delta=delta, tolerance=0)


def main():
    router = runpy.run_path(str(ROOT / 'tests/designer_smoke_routes.py'))
    router['project_root']()
    work = router['owned'](ROOT, ROOT / 'output/designer_bridge/pixel773-product' / uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=False)
    report = work / 'report.json'
    def own(path):
        path = router['owned'](ROOT, path)
        if path == work or not path.is_relative_to(work):
            raise ValueError('Outside exact private work')
        return path
    ledger = dict(owned=[], ambiguous=False, load_calls=0, final_unload_calls=0)
    E = dict(status='running',work=str(work),worker=0,compute=0,PNG=0,cook=0,render=0,copies=0,inspect_attempts=0,capture_attempts=0,
             ledger=ledger,outputs={},tolerance=0,computer_use=False,counts_complete=True,
             limits=dict(load=3,unload=3,inspect=4,capture=4,copies=36,compute=0,PNG=4,vendor_children=8),
             scope='Actual product API, fixed N/F0/T/F1. No SDK compute or intermediate readback. Product subprocess timeout applies; no retries; historical failures preserved.')
    def save():
        temporary=own(work/'report.tmp')
        temporary.write_bytes((json.dumps(E,indent=2,allow_nan=False)+'\n').encode('utf8'))
        temporary.replace(report)
    save()
    P=runpy.run_path(str(BASE/'ownership.py'))
    F=runpy.run_path(str(BASE/'probe_files.py'))
    PNG=runpy.run_path(str(BASE/'png_pixels.py'))
    errors=(Exception,);manager=None;before=None;protected=None;watch={};disks={}
    panel=None;affinity=None;initial_mask=None
    def panel_state():
        return dict(pointer=id(panel),target=copy.deepcopy(panel._target_identity),phase=panel._phase,
                    token=panel._token,process=panel.process is not None,
                    selected=copy.deepcopy(panel.source_choices.currentData()),
                    source_index=panel.source_choices.currentIndex(),
                    assets=copy.deepcopy(panel.asset_rows()),mask=copy.deepcopy(panel.mask_config()),
                    settings={k:getattr(panel,k).value() for k in ('count','width','depth','seed','seconds','height')},
                    edges=panel.edges.currentText(),resolution=panel.resolution.currentText(),normal=panel.normal.currentText())
    def packages():
        result=[]
        for package in manager.getPackages():
            identity=P['package_id'](package)
            if identity not in before:continue
            modified=package.isModified()
            if type(modified) is not bool:raise ValueError('Protected modified flag unavailable')
            result.append(dict(identity=identity,modified=modified))
        return sorted(result,key=lambda x:(x['identity']['uid'],x['identity']['path'] or ''))
    def failure(error,field='error'):
        E['status']='FAILED'
        E[field]=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
        if isinstance(getattr(error,'record',None),dict):
            E[field]['product_failure']=copy.deepcopy(error.record)
            E['counts_complete']=False  # Failed operation counts remain verbatim in product_failure.
        error.__traceback__=None;error.__cause__=None;error.__context__=None
    def graph():
        try:
            record=next(r for r in P['active'](ledger) if r['name']=='source')
            package=P['canonical'](manager,record,ledger,before)
            found=[g for g in package.getChildrenResources(False) if type(g) is SDSBSCompGraph and g.getIdentifier()=='NativeMaskSource']
            if len(found)!=1:raise ValueError('Private graph not unique')
            return found[0]
        except errors:
            P['ambiguous'](ledger,'Private trial graph owner unverified');raise
    def set_choice(choice):
        g=graph();node=g.getNodeFromId('1585448170');prop=node.getPropertyFromId('invert',Category.Input)
        if prop is None or node.getPropertyGraph(prop) is not None or list(node.getPropertyConnections(prop)):
            raise ValueError('Private invert must be unbound Input')
        node.setPropertyValue(prop,SDValueBool.sNew(choice))
        value=node.getPropertyValue(prop)
        if type(value) is not SDValueBool or value.get() is not choice:raise ValueError('Private bool setter/readback differs')
    def account(result,inspection):
        counts=result['counts']
        for key in ('copies','compute','PNG','worker'):
            if type(counts.get(key)) is not int or counts[key]<0:raise ValueError('Invalid actual count '+key)
        if counts['compute']!=0 or counts['worker']!=0:raise ValueError('Unexpected SDK compute or worker')
        if inspection:
            if counts['PNG']!=0 or counts['copies']>3:raise ValueError('Inspector count differs')
        elif counts['PNG']!=1 or counts.get('cook')!=1 or counts.get('render')!=1 or counts['copies']>6:
            raise ValueError('Capture must execute one cook/render/PNG')
        for key in ('copies','compute','PNG','worker','cook','render'):
            E[key]+=counts.get(key,0)
        if E['copies']>36 or E['cook']+E['render']>8 or E['PNG']>4:raise ValueError('Aggregate budget exceeded')
    def step(label,choice,graph_id,terminal_id):
        set_choice(choice)
        P['context'](manager,ledger,before)
        selection=dict(package_path=identities['source']['path'],package_uid=identities['source']['uid'],
                       graph_identifier=graph_id,terminal_identifier=terminal_id)
        row=dict(selection=selection,choice=choice);E['outputs'][label]=row
        if E['inspect_attempts']>=4:raise ValueError('Inspection budget exhausted')
        E['inspect_attempts']+=1;save()
        inspection=terminal_capture.inspect_terminal_selection(selection,uuid.uuid4().hex,str(operations),[])
        row['inspection']=inspection;save();account(inspection,True)
        if E['capture_attempts']>=4:raise ValueError('Capture budget exhausted')
        E['capture_attempts']+=1;save()
        result=terminal_capture.capture_terminal(selection,inspection['selected_context'],uuid.uuid4().hex,str(operations),[])
        row['result']=result;save();account(result,False)
        ev=mask_source.evaluator(result['capture']['evaluator'])
        if ev['backend']!='designer_cli_d3d11_cpu1' or ev['cpu_count']!=1 or ev['engine']!='D3D11':
            raise ValueError('Unexpected actual evaluator')
        if ev['graph_identifier']!=graph_id or ev['terminal_identifier']!=terminal_id:raise ValueError('Evaluator endpoint differs')
        path=own(Path(result['png']['path']))
        if not path.is_relative_to(operations) or not 33<=path.stat().st_size<=2*1024*1024:raise ValueError('PNG ownership/budget')
        digest=sha(path)
        if digest!=result['png']['sha256'] or digest!=ev['output_png_sha256']:raise ValueError('PNG byte binding differs')
        shape,pixel=PNG['png_signature'](path,True)
        if shape!=[512,512,16,0]:raise ValueError('Expected512LUM16 PNG')
        decoded=hashlib.sha256(pixel).hexdigest()
        if decoded!=result['png']['decoded_u16be_sha256']:raise ValueError('PNG decoded binding differs')
        row.update(path=str(path),sha256=digest,shape=shape,decoded_sha256=decoded)
        save();return pixel
    try:
        if str(ROOT/'plugin') not in sys.path:sys.path.insert(0,str(ROOT/'plugin'))
        import sd,substance_physics_scatter
        from sd.api.apiexception import APIException
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        from sd.api.sdproperty import SDPropertyCategory as Category
        from sd.api.sdvaluebool import SDValueBool
        from substance_physics_scatter import evaluation,terminal_capture,mask_source
        errors=(Exception,APIException)
        evaluation._assert_environment();affinity=evaluation._ProcessAffinity();initial_mask=affinity.get()
        E['affinity_before']=initial_mask
        if initial_mask!=65535:raise ValueError('Expected original affinity65535')
        panel=substance_physics_scatter._panel
        if panel is None or panel._phase!='idle' or panel._token is not None or panel.process is not None:
            raise ValueError('Canonical panel must be idle')
        panel_before=panel_state();E['canonical_panel_before']=panel_before
        manager=sd.getContext().getSDApplication().getPackageMgr();before=P['inventory'](manager)
        protected=packages();E['inventory_before']=before;E['protected_packages']=protected
        locator=json.loads((ROOT/'output/GraphMaskReview/latest.json').read_bytes())
        paths=[Path(locator[k]) for k in ('source','report')]
        paths += [Path(locator['directory'])/'source/stock'/name for name in ('vertical_noise.sbs','invert.sbs')]
        paths += [Path(panel.jobs.directory)/'current.json']
        for path in paths:watch[str(path)]=sha(path)
        E['protected_files']=watch
        with evaluation.evaluation_scope():
            try:
                prep=F['read_json'](BASE/'preparation.json');prepared={};identities={}
                for role in ('noise','invert','source'):
                    meta=copy.deepcopy(prep['packages'][role]);original=BASE/'prepared'/meta['relative_path']
                    if sha(original)!=meta['sha256']:raise ValueError('Accepted fixture bytes differ')
                    uid=str(uuid.uuid4());raw,proof=F['replace_top_uid'](original.read_bytes(),uid)
                    target=own(work/'source'/meta['relative_path']);target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as stream:stream.write(raw)
                    meta.update(uid=uid,sha256=sha(target));prepared[role]=meta;identities[role]=dict(path=str(target),uid=uid)
                    disks[str(target)]=sha(target);E.setdefault('uid_proofs',{})[role]=proof
                for role in ('noise','invert','source'):
                    E.setdefault('loads',{})[role]=P['load_one'](manager,role,identities[role],prepared[role],identities,ledger,before)
                operations=own(work/'operations');operations.mkdir(exist_ok=False)
                outputs={}
                schedule=(('N',False,'NativeNoiseReference','reference_noise'),('F0',False,'NativeMaskSource','native_mask'),
                          ('T',True,'NativeMaskSource','native_mask'),('F1',False,'NativeMaskSource','native_mask'))
                for args in schedule:outputs[args[0]]=step(*args)
                E['comparisons']={label:compare(outputs['N'],outputs[label],label=='T') for label in ('F0','T','F1')}
                E['math_exact']=all(row['mismatches']==0 for row in E['comparisons'].values())
                E['status']='PASS' if E['math_exact'] else 'FAIL_MATH'

            except errors as error:failure(error)
            finally:
                E['cleanup']=P['cleanup'](manager,ledger,before,errors);save()
        E['inventory_after']=P['inventory'](manager)
        E['private_disks_unchanged']=all(sha(path)==digest for path,digest in disks.items())
        E['protection_verified']=P['trust_final'](ledger,E['inventory_after'],before)
        if E['protection_verified']:
            E['canonical_panel_unchanged']=substance_physics_scatter._panel is panel and panel_state()==panel_before
            E['protected_packages_unchanged']=packages()==protected
            E['protected_files_unchanged']=all(sha(path)==digest for path,digest in watch.items())
            if not all(E[k] for k in ('canonical_panel_unchanged','protected_packages_unchanged','protected_files_unchanged','private_disks_unchanged')):
                raise ValueError('Protected current/source/panel/package state changed')
        else:raise ValueError('Ownership ambiguous; protection unverified; no further node readers')
    except BaseException as error:failure(error)
    finally:
        if affinity is not None:
            try:
                E['affinity_after']=affinity.get();E['affinity_restored']=E['affinity_after']==initial_mask
                if not E['affinity_restored']:raise ValueError('Exact original affinity restoration failed')
            except BaseException as error:failure(error,'affinity_error')
        save()
    return report


if __name__=='__main__':
    REPORT=main()
