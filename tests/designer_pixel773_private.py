"""Fixed private F0/T/F1 readback. Actual SDK execution belongs to root only."""
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
    work = router['owned'](ROOT, ROOT / 'output/designer_bridge/pixel773-private' / uuid.uuid4().hex)
    work.mkdir(parents=True, exist_ok=False)
    report = work / 'report.json'
    def own(path):
        path = router['owned'](ROOT, path)
        if path == work or not path.is_relative_to(work):
            raise ValueError('Outside exact private work')
        return path
    ledger = dict(owned=[], ambiguous=False, load_calls=0, final_unload_calls=0)
    E = dict(status='running',work=str(work),worker=0,compute=0,PNG=0,raw_reads=0,
             ledger=ledger,outputs={},tolerance=0,computer_use=False,
             limits=dict(load=3,unload=3,compute=3,PNG=9,raw_reads=18),
             scope='Same private trial graph, F0/T/F1; intermediate texture availability/format is an actual gate. No format changes or extra computes; historical failures preserved.')
    def save():
        temporary=own(work/'report.tmp')
        temporary.write_bytes((json.dumps(E,indent=2,allow_nan=False)+'\n').encode('utf8'))
        temporary.replace(report)
    save()
    P=runpy.run_path(str(BASE/'ownership.py'))
    F=runpy.run_path(str(BASE/'probe_files.py'))
    RAW=runpy.run_path(str(BASE/'raw_texture.py'))
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
    def step(label,choice):
        g=graph();node=g.getNodeFromId('1585448170');prop=node.getPropertyFromId('invert',Category.Input)
        if prop is None or node.getPropertyGraph(prop) is not None or list(node.getPropertyConnections(prop)):
            raise ValueError('Private invert must be unbound Input')
        node.setPropertyValue(prop,SDValueBool.sNew(choice))
        value=node.getPropertyValue(prop)
        if type(value) is not SDValueBool or value.get() is not choice:raise ValueError('Private bool setter/readback differs')
        P['context'](manager,ledger,before)
        if E['compute']>=3:raise ValueError('Compute budget exhausted')
        E['compute']+=1;save();g.compute()
        E['outputs'][label]={};pixels={}
        for role,node_id,output_id in (('noise','1585448168','Vertical_Noise'),('invert','1585448170','Invert_Grayscale'),('terminal','1585448173','native_mask')):
            n=g.getNodeFromId(node_id);props=list(n.getProperties(Category.Output) or [])
            if len(props)!=1 or props[0].getId()!=output_id:raise ValueError('Exact output descriptor differs')
            current=n.getPropertyValue(props[0]);row=dict(node=node_id,output=output_id,value_none=current is None)
            E['outputs'][label][role]=row;save()
            if current is None:
                row['status']='unavailable';save()
                if role=='terminal':raise ValueError('Terminal output value None')
                continue
            row['value_class']=current.getClassName()
            if type(current) is not SDValueTexture:raise ValueError('Output not SDValueTexture: '+role)
            typ=current.getType();modifier=typ.getModifier()
            row['type']=dict(class_name=typ.getClassName(),id=typ.getId(),modifier=dict(name=modifier.name,value=modifier.value))
            texture=current.get();row['texture_none']=texture is None;save()
            if texture is None and role!='terminal':
                row['status']='unavailable';save();continue
            if not isinstance(texture,SDTexture):raise ValueError('No actual SDTexture: '+role)
            size=texture.getSize();row['layout']=dict(size=[size.x,size.y],bpp=texture.getBytesPerPixel(),format=str(texture.getPixelFormat()))
            save()
            if row['type']!=dict(class_name='SDTypeCustom',id='SDTexture',modifier=dict(name='Auto',value=0)):
                raise ValueError('Actual texture value type differs: '+role)
            if [size.x,size.y]!=[512,512] or texture.getBytesPerPixel()!=2 or texture.getPixelFormat()!=SBSPixelFormat.LUM16:
                raise ValueError('Record-only unsupported layout; no raw read/save: '+role)
            if E['PNG']>=9 or E['raw_reads']+2>18:raise ValueError('Read/export budget exhausted')
            E['raw_reads']+=1;raw0,meta0=RAW['capture'](texture)
            path=own(work/(label+'-'+role+'.png'))
            if path.exists():raise FileExistsError('Exclusive PNG target')
            E['PNG']+=1;texture.save(str(path),'')
            E['raw_reads']+=1;raw1,meta1=RAW['capture'](texture)
            if not 33<=path.stat().st_size<=2*1024*1024:raise ValueError('PNG budget')
            shape,pixel=PNG['png_signature'](path,True)
            row.update(path=str(path),sha256=sha(path),shape=shape,raw_before=meta0,raw_after=meta1,
                       decoded_sha256=hashlib.sha256(pixel).hexdigest(),raw_PNG_exact=raw0==raw1 and RAW['canonical'](raw0)==pixel)
            save()
            if shape!=[512,512,16,0] or not row['raw_PNG_exact']:raise ValueError('Raw-before/PNG/raw-after differs')
            pixels[role]=pixel
        E.setdefault('comparisons',{})[label]=dict(
            noise_invert=compare(pixels['noise'],pixels['invert'],choice) if {'noise','invert'}<=pixels.keys() else dict(status='unavailable'),
            invert_terminal=compare(pixels['invert'],pixels['terminal']) if 'invert' in pixels else dict(status='unavailable'))
        return pixels
    try:
        if str(ROOT/'plugin') not in sys.path:sys.path.insert(0,str(ROOT/'plugin'))
        import sd,substance_physics_scatter
        from sd.api.apiexception import APIException
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        from sd.api.sdproperty import SDPropertyCategory as Category
        from sd.api.sdvaluebool import SDValueBool
        from sd.api.sdvaluetexture import SDValueTexture
        from sd.api.sdtexture import SDTexture,SBSPixelFormat
        from substance_physics_scatter import evaluation
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
                outputs={}
                for label,choice in (('F0',False),('T',True),('F1',False)):
                    outputs[label]=step(label,choice)
                E['return_comparisons']={role:compare(outputs['F0'][role],outputs['F1'][role]) if role in outputs['F0'] and role in outputs['F1'] else dict(status='unavailable') for role in ('noise','invert','terminal')}
                E['terminal_true_complement_false']=compare(outputs['F0']['terminal'],outputs['T']['terminal'],True)
                E['status']='OBSERVED'
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
