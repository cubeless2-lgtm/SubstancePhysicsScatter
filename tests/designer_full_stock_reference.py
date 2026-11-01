"""Root-only fixed full-stock controls; source input writes only, no kernel edits."""
from pathlib import Path
import copy,hashlib,json,runpy,struct,traceback,uuid,re
from xml.etree import ElementTree as ET
from xml.parsers import expat

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/noise-function-free-compute-probe/b2514d41190146ff8edbaea39ca70aac'
ORIGINAL=ROOT/'output/evidence/noise-function-free-preparation-probe/42f42ddc9f404adf8f4607c7ee02e050/runs/35d49c656f554c65999c7c0f3c238fe9/PrivateNoiseFX32.sbs'
ORIGINAL_SHA='433ed9fd6c081be2e21162e766fae406f70040c2f5d48c44cf28b7e9c655656f'
FIXTURE_SHAS={'original':ORIGINAL_SHA,'unique_function_ids':'3b98271cb3f1f0e32b341fcb72523f1735fae5aabe4b8b912e142479a67816a7','split_shared_data':'297805b59ecdfedd706b1bef2b898e36da1c37744dce06dc0166306ab727d1a2','cut_after_first_gaussian':'71b6c586d67fbef755f51af4091a88c50a765cdc0baffa8aadb90820c020d56c'}
PREPARATION=ORIGINAL.parents[2]/'preparation.json'
FIXTURE_SHAS['cut_after_second_gaussian']='2cf834d8155d7e4f5d73eb1c79f9a6988267c1982633acdf5699f147501fb76f'
FIXTURE_SHAS['cut_after_third_gaussian']='f1ef7ae532d6f23c603861ed8dd9805f162165eb3e2b24b1ead25e3eebc1d0eb'
FIXTURE_SHAS['last_gaussian_one_branch']='95f7187ad4b71bc338d03a1a82761d4be0a2b740fdec774c8b75b083f7ab930e'
FIXTURE_SHAS['full_stock_repeat_cycles']=ORIGINAL_SHA
FIXTURE_SHAS['last_owner_split_baseline']='63bda9160b2d16d70f5d15dd11bf20154ec6d50b7c4de72b94e85bdf1947fb4e'
FIXTURE_SHAS['last_owner_split_none']='9beaf6ce6ba4e33b5d348a81d5c3872868d76dcab66e6bfb2c2277ce755a7958'
FIXTURE_SHAS['last_owner_none_zero_offset']='0b60975d391002dddfc3ed4f1493f7c73151f231be5291ff153db439fe215a86'
FIXTURE_SHAS['last_owner_none_half_opacity']='eb86ee70033a895d498f9a2ceba66d8844913866fa0ca6a11ed0e297a205f21c'
KERNEL_UID='be1340f5-0184-4cc6-836b-ee3367d35028'
SCHEDULE=(('N0',0.),('N50',50.),('NR0',0.))
FX_FIXTURE_MODE=globals().get('FX_FIXTURE_MODE','original')
if type(FX_FIXTURE_MODE) is not str or FX_FIXTURE_MODE not in ('original','unique_function_ids','split_shared_data','cut_after_first_gaussian','cut_after_second_gaussian','cut_after_third_gaussian','last_gaussian_one_branch','full_stock_repeat_cycles','last_owner_split_baseline','last_owner_split_none','last_owner_none_zero_offset','last_owner_none_half_opacity'):raise ValueError('Only twelve fixed FX fixture modes are supported')
if FX_FIXTURE_MODE=='full_stock_repeat_cycles':SCHEDULE=(('N0',0.),('N50',50.),('NR0',0.),('N50_2',50.),('NR0_2',0.))
SCOPED_CPU=globals().get('SCOPED_CPU',False)
if type(SCOPED_CPU) is not bool or SCOPED_CPU and FX_FIXTURE_MODE!='original':raise ValueError('Scoped CPU is a fixed original-only control')
TRANSACTION_CPU=globals().get('TRANSACTION_CPU',False)
if type(TRANSACTION_CPU) is not bool or TRANSACTION_CPU and (FX_FIXTURE_MODE!='original' or SCOPED_CPU):raise ValueError('Transaction CPU is a separate fixed original-only control')

def scoped_compute_once(C,manager,ledger,before,role):
    from substance_physics_scatter.evaluation import compute_graph
    compute_graph(C['root'](manager,ledger,before,role))

def repeat_before_read(count,used,layouts,limits):
    fixed=(limits['K_LAYOUT'],)+(limits['FX_LAYOUT'],)*10
    if type(count) is not int or type(used) is not int or not 0<=count<=11:raise ValueError('Invalid fixed11 raw prefix')
    sizes=[w*h*bpp for w,h,bpp,_ in fixed]
    if sum(sizes)!=5767168 or used!=sum(sizes[:count]):raise ValueError('Fixed11 total/prefix bytes differ')
    if not layouts or tuple(layouts)!=fixed[count:count+len(layouts)] or count+len(layouts)>11:raise ValueError('Fixed11 raw layout/count differs')
    if used+sum(w*h*bpp for w,h,bpp,_ in layouts)>5767168:raise ValueError('Fixed11 raw budget exhausted')

def repeat_comparisons(images,compare):
    rows=dict(first_return=compare(images['N0'],images['NR0']),second_return_from_first=compare(images['NR0'],images['NR0_2']),second_return_from_initial=compare(images['N0'],images['NR0_2']),same_50=compare(images['N50'],images['N50_2']),second_input_effect=compare(images['NR0'],images['N50_2']))
    return dict(comparisons=rows,math_pass=all(rows[k]['exact'] for k in ('first_return','second_return_from_first','second_return_from_initial','same_50')),first_return_failed=not rows['first_return']['exact'],prior_failures_reclassified=False)

def function_scopes(raw,mode='original'):
    if mode not in FIXTURE_SHAS:raise ValueError('Unknown fixed function-scope mode')
    tree=ET.fromstring(raw);graph=next(tree.iter('paramsGraph'));owners={}
    for n in graph.findall('paramsGraphNodes/paramsGraphNode'):owners.setdefault(n.find('data').get('v'),[]).append(n.find('uid').get('v'))
    scopes=[]
    for data in graph.findall('paramsGraphDatas/paramsGraphData'):
        for prop in data.findall('parameters/parameter'):
            dynamic=prop.find('paramValue/dynamicValue')
            if dynamic is None:continue
            nodes=dynamic.findall('paramNodes/paramNode');ids=[n.find('uid').get('v') for n in nodes]
            if len(ids)!=len(set(ids)) or dynamic.find('rootnode').get('v') not in ids:raise ValueError('Function scope duplicate/unowned root UID')
            edges=[(c.find('connRef').get('v'),n.find('uid').get('v'),c.find('identifier').get('v')) for n in nodes for c in n.findall('connections/connection')]
            if any(s not in ids for s,_,_ in edges):raise ValueError('Function external UID reference forbidden')
            scopes.append(dict(owner_data=data.find('uid').get('v'),property=prop.find('name').get('v'),owners=sorted(owners[data.find('uid').get('v')]),root=dynamic.find('rootnode').get('v'),nodes=[dict(uid=n.find('uid').get('v'),definition=n.find('function').get('v')) for n in nodes],edges=edges))
    count,node_count=(9,43) if mode=='split_shared_data' else (7,35) if mode in ('last_owner_split_baseline','last_owner_split_none') else (6,31) if mode=='last_owner_none_zero_offset' else (5,27)
    if len(scopes)!=count or sum(len(s['nodes']) for s in scopes)!=node_count:raise ValueError('Fixed function/paramNode counts differ')
    return scopes

def unique_function_ids(raw):
    xml_shape(raw);scopes=function_scopes(raw);tree=ET.fromstring(raw)
    if max(int(n.get('v')) for n in tree.iter('uid'))!=1146345843:raise ValueError('Fixed original maximum UID differs')
    next_uid=1146345844;maps={}
    for scope in scopes:
        key=(scope['owner_data'],scope['property']);mapping={}
        for old in sorted((n['uid'] for n in scope['nodes']),key=int):mapping[old]=str(next_uid);next_uid+=1
        maps[key]=mapping
    stack=[];edits=[];active=None;seen=[];parser=expat.ParserCreate()
    def start(name,attrs):
        nonlocal active
        if name=='uid' and stack and stack[-1]['tag']=='paramsGraphData':stack[-1]['uid']=attrs['v']
        if name=='name' and stack and stack[-1]['tag']=='parameter':stack[-1]['name']=attrs['v']
        if name=='dynamicValue':
            data=[f for f in stack if f['tag']=='paramsGraphData'];prop=[f for f in stack if f['tag']=='parameter']
            if active is not None or len(data)!=1 or not prop:raise ValueError('Unexpected dynamic function nesting')
            active=(data[0]['uid'],prop[-1]['name'])
            if active not in maps or active in seen:raise ValueError('Unknown/duplicate function scope')
            seen.append(active)
        if active is not None and name in ('uid','rootnode','connRef'):
            parent=stack[-1]['tag']
            if (name,parent) not in (('uid','paramNode'),('rootnode','dynamicValue'),('connRef','connection')):raise ValueError('Unexpected UID field within dynamic scope')
            old=attrs['v']
            if old not in maps[active]:raise ValueError('External function UID token')
            begin=parser.CurrentByteIndex;end=raw.index(b'>',begin)+1;tag=raw[begin:end];matches=list(re.finditer(rb'\bv="([0-9]+)"',tag))
            if len(matches)!=1 or matches[0].group(1).decode('ascii')!=old:raise ValueError('Exact numeric UID attribute bytes required')
            match=matches[0];edits.append((begin+match.start(1),begin+match.end(1),maps[active][old].encode('ascii')))
        stack.append(dict(tag=name))
    def end(name):
        nonlocal active
        if name=='dynamicValue':active=None
        stack.pop()
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(raw,True)
    if set(seen)!=set(maps):raise ValueError('Missing function scope patch')
    parts=[];inverse=[];position=0;output_position=0
    for begin,end,replacement in edits:
        prefix=raw[position:begin];parts.extend((prefix,replacement));output_position+=len(prefix);inverse.append((output_position,output_position+len(replacement),raw[begin:end]));output_position+=len(replacement);position=end
    parts.append(raw[position:]);derived=b''.join(parts);restored=[];position=0
    for begin,end,old in inverse:restored.extend((derived[position:begin],old));position=end
    restored.append(derived[position:])
    if b''.join(restored)!=raw:raise ValueError('Inverse full raw byte proof failed')
    expected=ET.fromstring(raw)
    for data in expected.iter('paramsGraphData'):
        for prop in data.findall('parameters/parameter'):
            dynamic=prop.find('paramValue/dynamicValue')
            if dynamic is None:continue
            mapping=maps[(data.find('uid').get('v'),prop.find('name').get('v'))]
            for n in dynamic.iter():
                if n.tag in ('uid','rootnode','connRef'):n.set('v',mapping[n.get('v')])
    if ET.tostring(expected)!=ET.tostring(ET.fromstring(derived)):raise ValueError('Tree differs beyond scoped3 UID field kinds')
    after=function_scopes(derived);all_ids=[n['uid'] for s in after for n in s['nodes']]
    if len(set(all_ids))!=27:raise ValueError('Derived function IDs are not globally unique')
    return derived,dict(original_sha256=hashlib.sha256(raw).hexdigest(),derived_sha256=hashlib.sha256(derived).hexdigest(),max_original_uid=1146345843,first_new_uid=1146345844,last_new_uid=next_uid-1,param_node_count=27,changed_attribute_occurrences=len(edits),inverse_raw_exact=True,only_scoped_uid_rootnode_connRef_tree_changes=True,mapping=[dict(owner_data=s['owner_data'],property=s['property'],nodes=maps[(s['owner_data'],s['property'])]) for s in scopes]),after

def split_shared_data(raw):
    xml_shape(raw);stack=[];block=None;uid_span=None;references={};parser=expat.ParserCreate()
    owners={'1028376909':'1146345844','1028376922':'1146345845'}
    def attribute_span():
        begin=parser.CurrentByteIndex;end=raw.index(b'>',begin)+1;matches=list(re.finditer(rb'\bv="([0-9]+)"',raw[begin:end]))
        if len(matches)!=1:raise ValueError('Exact numeric data UID attribute required')
        m=matches[0];return begin+m.start(1),begin+m.end(1)
    def start(name,attrs):
        nonlocal uid_span
        if name=='uid' and stack and stack[-1]['tag'] in ('paramsGraphData','paramsGraphNode'):
            stack[-1]['uid']=attrs['v']
            if stack[-1]['tag']=='paramsGraphData' and attrs['v']=='1028058599':uid_span=attribute_span()
        if name=='data' and stack and stack[-1]['tag']=='paramsGraphNode' and stack[-1]['uid'] in owners:
            owner=stack[-1]['uid']
            if attrs['v']!='1028058599' or owner in references:raise ValueError('Exact original shared data reference required')
            references[owner]=attribute_span()
        stack.append(dict(tag=name,begin=parser.CurrentByteIndex))
    def end(name):
        nonlocal block
        frame=stack.pop()
        if name=='paramsGraphData' and frame['uid']=='1028058599':
            if block is not None:raise ValueError('Duplicate source physical data8599')
            block=(frame['begin'],raw.index(b'>',parser.CurrentByteIndex)+1)
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(raw,True)
    if block is None or uid_span is None or set(references)!=set(owners):raise ValueError('Missing exact physical data/owner span')
    begin,end=block;original_block=raw[begin:end];clones=[];clone_rows=[]
    for owner,new_uid in owners.items():
        clone=raw[begin:uid_span[0]]+new_uid.encode('ascii')+raw[uid_span[1]:end]
        if clone.replace(('v="'+new_uid+'"').encode(),b'v="1028058599"',1)!=original_block:raise ValueError('Clone changed beyond its data UID')
        clones.append(clone);clone_rows.append(dict(owner=owner,data_uid=new_uid,sha256=hashlib.sha256(clone).hexdigest(),bytes=len(clone)))
    edits=[(end,end,b''.join(clones))]+[(references[o][0],references[o][1],n.encode('ascii')) for o,n in owners.items()]
    parts=[];inverse=[];position=0;output_position=0
    for first,last,replacement in sorted(edits):
        prefix=raw[position:first];parts.extend((prefix,replacement));output_position+=len(prefix);inverse.append((output_position,output_position+len(replacement),raw[first:last]));output_position+=len(replacement);position=last
    parts.append(raw[position:]);derived=b''.join(parts);restored=[];position=0
    for first,last,old in inverse:restored.extend((derived[position:first],old));position=last
    restored.append(derived[position:])
    if b''.join(restored)!=raw:raise ValueError('Clone deletion/reference inverse whole byte proof failed')
    expected=ET.fromstring(raw);datas=next(expected.iter('paramsGraphDatas'));source=next(d for d in datas if d.find('uid').get('v')=='1028058599');index=list(datas).index(source)
    for offset,new_uid in enumerate(owners.values(),1):
        clone=copy.deepcopy(source);clone.find('uid').set('v',new_uid);datas.insert(index+offset,clone)
    for node in expected.iter('paramsGraphNode'):
        if node.find('uid').get('v') in owners:node.find('data').set('v',owners[node.find('uid').get('v')])
    if ET.tostring(expected)!=ET.tostring(ET.fromstring(derived)):raise ValueError('Tree changed beyond two clone UIDs/two data references')
    scopes=function_scopes(derived,'split_shared_data')
    return derived,dict(original_sha256=hashlib.sha256(raw).hexdigest(),derived_sha256=hashlib.sha256(derived).hexdigest(),source_block_sha256=hashlib.sha256(original_block).hexdigest(),clones=clone_rows,insertion_order=['1028058599','1146345844','1146345845'],original_data_blocks_unchanged=True,only_two_owner_data_references_changed=True,clone_content_except_uid_exact=True,inverse_raw_exact=True,function_local_UIDs_unchanged=True),scopes

def last_owner_split(raw,disable_pattern=False):
    if type(disable_pattern) is not bool:raise ValueError('Only fixed baseline/None arms are supported')
    xml_shape(raw);stack=[];block=None;uid_span=None;pattern_span=None;reference=None;parser=expat.ParserCreate()
    def span():
        begin=parser.CurrentByteIndex;end=raw.index(b'>',begin)+1;matches=list(re.finditer(rb'\bv="([0-9]+)"',raw[begin:end]))
        if len(matches)!=1:raise ValueError('Exact numeric attribute required')
        m=matches[0];return begin+m.start(1),begin+m.end(1)
    def start(name,attrs):
        nonlocal uid_span,pattern_span,reference
        if name=='uid' and stack and stack[-1]['tag'] in ('paramsGraphData','paramsGraphNode'):
            stack[-1]['uid']=attrs['v']
            if stack[-1]['tag']=='paramsGraphData' and attrs['v']=='1028058599':uid_span=span()
        if name=='name' and stack and stack[-1]['tag']=='parameter':stack[-1]['name']=attrs['v']
        if name=='constantValueInt32':
            data=[f for f in stack if f['tag']=='paramsGraphData'];props=[f for f in stack if f['tag']=='parameter']
            if data and data[-1].get('uid')=='1028058599' and props[-1].get('name')=='patterntype':
                if attrs['v']!='6' or pattern_span is not None:raise ValueError('Exact unique Gaussian6 pattern field required')
                pattern_span=span()
        if name=='data' and stack and stack[-1]['tag']=='paramsGraphNode' and stack[-1]['uid']=='1028376922':
            if attrs['v']!='1028058599' or reference is not None:raise ValueError('Last owner original data reference differs')
            reference=span()
        stack.append(dict(tag=name,begin=parser.CurrentByteIndex))
    def end(name):
        nonlocal block
        frame=stack.pop()
        if name=='paramsGraphData' and frame['uid']=='1028058599':
            if block is not None:raise ValueError('Duplicate physical data8599')
            block=(frame['begin'],raw.index(b'>',parser.CurrentByteIndex)+1)
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(raw,True)
    if None in (block,uid_span,pattern_span,reference):raise ValueError('Missing fixed clone/pattern/owner span')
    begin,end=block;source=raw[begin:end];new_uid=b'1146345844'
    base_clone=raw[begin:uid_span[0]]+new_uid+raw[uid_span[1]:end]
    if base_clone.replace(b'v="1146345844"',b'v="1028058599"',1)!=source:raise ValueError('Baseline clone differs beyond data UID')
    relative=pattern_span[0]-begin
    clone=base_clone[:relative]+b'0'+base_clone[relative+1:] if disable_pattern else base_clone
    if disable_pattern and clone[:relative]+b'6'+clone[relative+1:]!=base_clone:raise ValueError('None arm changed beyond one pattern token')
    edits=sorted(((end,end,clone),(reference[0],reference[1],new_uid)));parts=[];inverse=[];position=0;output_position=0
    for first,last,value in edits:
        prefix=raw[position:first];parts.extend((prefix,value));output_position+=len(prefix);inverse.append((output_position,output_position+len(value),raw[first:last]));output_position+=len(value);position=last
    parts.append(raw[position:]);derived=b''.join(parts);restored=[];position=0
    for first,last,value in inverse:restored.extend((derived[position:first],value));position=last
    restored.append(derived[position:])
    if b''.join(restored)!=raw:raise ValueError('Last-owner clone deletion/reference inverse bytes failed')
    expected=ET.fromstring(raw);datas=next(expected.iter('paramsGraphDatas'));source_data=next(d for d in datas if d.find('uid').get('v')=='1028058599');copy_data=copy.deepcopy(source_data);copy_data.find('uid').set('v','1146345844')
    if disable_pattern:
        props=[p for p in copy_data.findall('parameters/parameter') if p.find('name').get('v')=='patterntype']
        if len(props)!=1:raise ValueError('Unique cloned pattern parameter required')
        props[0].find('paramValue/constantValueInt32').set('v','0')
    datas.insert(list(datas).index(source_data)+1,copy_data)
    for n in expected.iter('paramsGraphNode'):
        if n.find('uid').get('v')=='1028376922':n.find('data').set('v','1146345844')
    if ET.tostring(expected)!=ET.tostring(ET.fromstring(derived)):raise ValueError('Last-owner arm changed outside allowed XML fields')
    mode='last_owner_split_none' if disable_pattern else 'last_owner_split_baseline'
    return derived,dict(original_sha256=hashlib.sha256(raw).hexdigest(),derived_sha256=hashlib.sha256(derived).hexdigest(),owner='1028376922',data_uid='1146345844',source_block_sha256=hashlib.sha256(source).hexdigest(),clone_sha256=hashlib.sha256(clone).hexdigest(),clone_pattern='None0' if disable_pattern else 'Gaussian6',pattern_token_changed=disable_pattern,baseline_clone_except_uid_exact=True,none_arm_only_one_extra_pattern_token=True,inverse_raw_exact=True,original_data_blocks_unchanged=True,function_local_UIDs_unchanged=True),function_scopes(derived,mode)

def last_owner_none_zero_offset(raw):
    base,source_proof,_=last_owner_split(raw,True);xml_shape(base,'last_owner_split_none')
    stack=[];region=None;parser=expat.ParserCreate()
    def start(name,attrs):
        if name=='uid' and stack and stack[-1]['tag']=='paramsGraphData':stack[-1]['uid']=attrs['v']
        if name=='name' and stack and stack[-1]['tag']=='parameter':stack[-1]['name']=attrs['v']
        data=[f for f in stack if f['tag']=='paramsGraphData'];props=[f for f in stack if f['tag']=='parameter']
        selected=name=='paramValue' and stack[-1]['tag']=='parameter' and data[-1].get('uid')=='1146345844' and props[-1].get('name')=='branchoffset' if data and props else False
        stack.append(dict(tag=name,begin=parser.CurrentByteIndex,selected=selected))
    def end(name):
        nonlocal region
        frame=stack.pop()
        if frame['selected']:
            if region is not None:raise ValueError('Duplicate target cloned branch paramValue')
            region=(frame['begin'],base.index(b'>',parser.CurrentByteIndex)+1)
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(base,True)
    if region is None:raise ValueError('Missing target cloned branch paramValue')
    begin,end=region;old=base[begin:end];value=ET.fromstring(old);children=list(value)
    if len(children)!=1 or children[0].tag!='dynamicValue' or len(children[0].findall('paramNodes/paramNode'))!=4:raise ValueError('Exact target4node dynamic subtree required')
    literal=b'<paramValue><constantValueFloat2 v="0 0"/></paramValue>';derived=base[:begin]+literal+base[end:]
    if derived[:begin]+old+derived[begin+len(literal):]!=base:raise ValueError('Exact original None-fixture subtree reinsertion failed')
    expected=ET.fromstring(base);data=next(d for d in expected.iter('paramsGraphData') if d.find('uid').get('v')=='1146345844');props=[p for p in data.findall('parameters/parameter') if p.find('name').get('v')=='branchoffset']
    if len(props)!=1:raise ValueError('Unique cloned branch parameter required')
    prop=props[0];old_value=prop.find('paramValue');index=list(prop).index(old_value);prop.remove(old_value);prop.insert(index,ET.fromstring(literal))
    if ET.tostring(expected)!=ET.tostring(ET.fromstring(derived)):raise ValueError('XML changed beyond selected branch paramValue')
    proof=dict(original_sha256=hashlib.sha256(raw).hexdigest(),base_none_fixture_sha256=hashlib.sha256(base).hexdigest(),derived_sha256=hashlib.sha256(derived).hexdigest(),source_clone_proof=source_proof,owner='1028376922',data_uid='1146345844',property='branchoffset',original_param_value_offset=begin,original_param_value_xml=old.decode('utf8'),replacement_xml=literal.decode('ascii'),inverse_none_fixture_raw_exact=True,target_function_definition_removed=True,removed_function_node_uids=[n.find('uid').get('v') for n in children[0].findall('paramNodes/paramNode')],other_function_definitions_unchanged=True,literal_float2=[0.,0.],literal_bits=[struct.pack('=f',0.).hex()]*2)
    return derived,proof,function_scopes(derived,'last_owner_none_zero_offset')

def last_owner_none_half_opacity(raw):
    base,source_proof,_=last_owner_none_zero_offset(raw);xml_shape(base,'last_owner_none_zero_offset')
    stack=[];region=None;parser=expat.ParserCreate()
    def start(name,attrs):
        if name=='uid' and stack and stack[-1]['tag']=='paramsGraphData':stack[-1]['uid']=attrs['v']
        if name=='name' and stack and stack[-1]['tag']=='parameter':stack[-1]['name']=attrs['v']
        data=[f for f in stack if f['tag']=='paramsGraphData'];props=[f for f in stack if f['tag']=='parameter']
        selected=name=='paramValue' and stack[-1]['tag']=='parameter' and data[-1].get('uid')=='1146345844' and props[-1].get('name')=='opacity' if data and props else False
        stack.append(dict(tag=name,begin=parser.CurrentByteIndex,selected=selected))
    def end(name):
        nonlocal region
        frame=stack.pop()
        if frame['selected']:
            if region is not None:raise ValueError('Duplicate target cloned opacity paramValue')
            region=(frame['begin'],base.index(b'>',parser.CurrentByteIndex)+1)
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(base,True)
    if region is None:raise ValueError('Missing target cloned opacity paramValue')
    begin,end=region;old=base[begin:end];value=ET.fromstring(old);children=list(value)
    if len(children)!=1 or children[0].tag!='dynamicValue' or len(children[0].findall('paramNodes/paramNode'))!=4:raise ValueError('Exact target4node opacity dynamic subtree required')
    literal=b'<paramValue><constantValueFloat4 v="0.5 0.5 0.5 0.5"/></paramValue>';derived=base[:begin]+literal+base[end:]
    if derived[:begin]+old+derived[begin+len(literal):]!=base:raise ValueError('Exact zero-offset fixture opacity reinsertion failed')
    expected=ET.fromstring(base);data=next(d for d in expected.iter('paramsGraphData') if d.find('uid').get('v')=='1146345844');props=[p for p in data.findall('parameters/parameter') if p.find('name').get('v')=='opacity']
    if len(props)!=1:raise ValueError('Unique cloned opacity parameter required')
    prop=props[0];old_value=prop.find('paramValue');index=list(prop).index(old_value);prop.remove(old_value);prop.insert(index,ET.fromstring(literal))
    if ET.tostring(expected)!=ET.tostring(ET.fromstring(derived)):raise ValueError('XML changed beyond selected opacity paramValue')
    proof=dict(original_sha256=hashlib.sha256(raw).hexdigest(),base_zero_offset_fixture_sha256=hashlib.sha256(base).hexdigest(),derived_sha256=hashlib.sha256(derived).hexdigest(),source_zero_offset_proof=source_proof,owner='1028376922',data_uid='1146345844',property='opacity',original_param_value_offset=begin,original_param_value_xml=old.decode('utf8'),replacement_xml=literal.decode('ascii'),inverse_zero_offset_fixture_raw_exact=True,target_function_definition_removed=True,removed_function_node_uids=[n.find('uid').get('v') for n in children[0].findall('paramNodes/paramNode')],other_function_definitions_unchanged=True,literal_type='Float4',literal_type_basis='accepted keeper_descriptors.opacity SDTypeFloat4; bound scalar output is not a Float1 literal declaration',literal_float4=[.5]*4,literal_bits=[struct.pack('=f',.5).hex()]*4)
    return derived,proof,function_scopes(derived,'last_owner_none_half_opacity')

def cut_after_first_gaussian(raw):
    return _cut_gaussian(raw,'first')

def cut_after_second_gaussian(raw):
    return _cut_gaussian(raw,'second')

def cut_after_third_gaussian(raw):
    return _cut_gaussian(raw,'third')

def last_gaussian_one_branch(raw):
    return _cut_gaussian(raw,'last_one_branch')

def _cut_gaussian(raw,cut):
    ports={'output0','output1','output2','output3'}
    if cut=='first':cut_node,cut_child,expected_unreachable='1028055564','1028058598',{'1028058598','1028376909','1028376922'}
    elif cut=='second':cut_node,cut_child,expected_unreachable='1028058598','1028376909',{'1028376909','1028376922'}
    elif cut=='third':cut_node,cut_child,expected_unreachable='1028376909','1028376922',{'1028376922'}
    elif cut=='last_one_branch':cut_node,cut_child,expected_unreachable='1028376909','1028376922',set();ports={'output1','output2','output3'}
    else:raise ValueError('Only four fixed Gaussian edge selections are supported')
    xml_shape(raw);stack=[];removed=[];parser=expat.ParserCreate()
    def start(name,attrs):
        if name=='uid' and stack and stack[-1]['tag']=='paramsGraphNode':stack[-1]['uid']=attrs['v']
        if name in ('identifier','connRef') and stack and stack[-1]['tag']=='connection':stack[-1][name]=attrs['v']
        owner=next((f.get('uid') for f in reversed(stack) if f['tag']=='paramsGraphNode'),None)
        stack.append(dict(tag=name,begin=parser.CurrentByteIndex,owner=owner))
    def end(name):
        frame=stack.pop()
        if name=='connection' and frame['owner']==cut_node:
            if frame['identifier'] not in ('output0','output1','output2','output3') or frame['connRef']!=cut_child:raise ValueError('Unexpected fixed Gaussian edge')
            if frame['identifier'] in ports:removed.append(dict(begin=frame['begin'],end=raw.index(b'>',parser.CurrentByteIndex)+1,input=frame['identifier']))
    parser.StartElementHandler=start;parser.EndElementHandler=end;parser.Parse(raw,True)
    if len(removed)!=len(ports) or {r['input'] for r in removed}!=ports:raise ValueError('Exact fixed Gaussian edge subset required')
    parts=[];position=0;inverse=[];output_position=0
    for row in removed:
        prefix=raw[position:row['begin']];parts.append(prefix);output_position+=len(prefix);inverse.append((output_position,raw[row['begin']:row['end']]));position=row['end']
    parts.append(raw[position:]);derived=b''.join(parts);restored=[];position=0
    for offset,deleted in inverse:restored.extend((derived[position:offset],deleted));position=offset
    restored.append(derived[position:])
    if b''.join(restored)!=raw:raise ValueError('Exact original edge reinsertion byte proof failed')
    expected=ET.fromstring(raw);node=next(n for n in expected.iter('paramsGraphNode') if n.find('uid').get('v')==cut_node);connections=node.find('connections')
    for child in list(connections):
        if child.find('identifier').get('v') in ports:connections.remove(child)
    actual=ET.fromstring(derived)
    if ET.tostring(expected)!=ET.tostring(actual):raise ValueError('Tree changed beyond fixed removed edges')
    graph=next(actual.iter('paramsGraph'));nodes=graph.findall('paramsGraphNodes/paramsGraphNode');adjacency={n.find('uid').get('v'):[c.find('connRef').get('v') for c in n.findall('connections/connection')] for n in nodes};reachable=set();todo=[graph.find('rootnode').get('v')]
    while todo:
        current=todo.pop()
        if current not in adjacency:raise ValueError('Unowned root reachability edge')
        if current in reachable:continue
        reachable.add(current);todo.extend(adjacency[current])
    unreachable=set(adjacency)-reachable
    if unreachable!=expected_unreachable or reachable!=set(adjacency)-expected_unreachable:raise ValueError('Fixed XML reachability differs')
    return derived,dict(original_sha256=hashlib.sha256(raw).hexdigest(),derived_sha256=hashlib.sha256(derived).hexdigest(),**({'only_three_connections_removed':True} if len(ports)==3 else {'only_four_connections_removed':True}),inverse_raw_exact=True,removed_connections=[dict(original_byte_offset=r['begin'],input=r['input'],xml=raw[r['begin']:r['end']].decode('utf8')) for r in removed],root_reachable_XML=sorted(reachable),not_root_reachable_XML=sorted(unreachable),nodes_removed=0,internal_execution_count_measured=False),function_scopes(derived)

def xml_shape(raw,mode='original'):
    if mode not in FIXTURE_SHAS or hashlib.sha256(raw).hexdigest()!=FIXTURE_SHAS[mode]:raise ValueError('Fixed full-stock source SHA differs; load0')
    tree=ET.fromstring(raw)
    if tree.find('fileUID').get('v').strip('{}')!=KERNEL_UID:raise ValueError('Original full-stock UID differs')
    graphs=list(tree.iter('paramsGraph'))
    if len(graphs)!=1:raise ValueError('Exactly one full FX graph required')
    graph=graphs[0];nodes=graph.findall('paramsGraphNodes/paramsGraphNode');data=graph.findall('paramsGraphDatas/paramsGraphData')
    rows=[dict(node_id=n.find('uid').get('v'),data=n.find('data').get('v'),type=n.find('type').get('v')) for n in nodes]
    edges=sorted([dict(source=c.find('connRef').get('v'),target=n.find('uid').get('v'),input=c.find('identifier').get('v'),output='unique_filter_output') for n in nodes for c in n.findall('connections/connection')],key=lambda e:(e['target'],e['input']))
    data_count,function_count=(8,9) if mode=='split_shared_data' else (7,7) if mode in ('last_owner_split_baseline','last_owner_split_none') else (7,6) if mode=='last_owner_none_zero_offset' else (7,5) if mode=='last_owner_none_half_opacity' else (6,5)
    edge_count=25 if mode=='last_gaussian_one_branch' else 24 if mode in ('cut_after_first_gaussian','cut_after_second_gaussian','cut_after_third_gaussian') else 28
    if len(nodes)!=8 or len({r['node_id'] for r in rows})!=8 or len(data)!=data_count or len(edges)!=edge_count or graph.find('rootnode').get('v')!='1028056080' or len(list(tree.iter('dynamicValue')))!=function_count or any(r['type']!='paramset' for r in rows):raise ValueError('Fixed mode full FX8/root/flow/data/function count differs')
    if set(r['data'] for r in rows)!={n.find('uid').get('v') for n in data}:raise ValueError('Shared physical data mapping differs')
    return dict(source_sha256=FIXTURE_SHAS[mode],file_uid=KERNEL_UID,root='1028056080',nodes=sorted(rows,key=lambda r:r['node_id']),edges=edges,physical_data_count=data_count,function_count=function_count,function_uids=[n.find('uid').get('v') for n in tree.iter('paramNode')])

def source_projection(view):
    result=copy.deepcopy(view);result.pop('source_modified');return result

def source_flag(state,view,stage,setter=False):
    flag=view['source_modified'];previous=state.get('last')
    if type(flag) is not bool:raise ValueError('Actual source modified bool required')
    if previous is not None and flag!=previous and (not setter or previous):raise ValueError('Unexpected source modified transition')
    state['rows'].append(dict(stage=stage,previous=previous,actual=flag,setter=setter));state['last']=flag

def own_raw(path,work,file_helper):
    path=file_helper['logical'](path);root=file_helper['logical'](work)
    if path==root or not path.is_relative_to(root):raise ValueError('Raw artifact outside this WORK')
    return path

def source_input(C,A,manager,ledger,before,role,expected,Category,Inherit):
    node=C['root'](manager,ledger,before,role).getNodeFromId(role['ids']['noise_instance']);prop=node.getPropertyFromId('Disorder',Category.Input)
    if prop is None or prop.getCategory()!=Category.Input or node.getPropertyGraph(prop) is not None or list(node.getPropertyConnections(prop)) or node.getPropertyInheritanceMethod(prop)!=Inherit.Absolute:raise ValueError('Disorder must be unbound Absolute Input')
    descriptor=A['descriptor'](prop);typ=dict(class_name='SDTypeFloat',id='float',modifier=dict(name='Auto',value=0))
    current=C['scalar'](node.getPropertyValue(prop));default=C['scalar'](prop.getDefaultValue())
    if descriptor['types']!=[typ] or current['type']!=typ or default['type']!=typ or current['wrapper']!='SDValueFloat' or default['wrapper']!='SDValueFloat' or default['value']!=0. or default['bits']!=[struct.pack('=f',0.).hex()] or current['value']!=expected or current['bits']!=[struct.pack('=f',expected).hex()]:raise ValueError('Disorder Float/default/current bits differ')
    return dict(node_id=node.getIdentifier(),property=descriptor,current=current,default=default,inheritance=dict(name=Inherit.Absolute.name,value=Inherit.Absolute.value))

def kernel_metadata(C,P,A,manager,ledger,before,shape,Category,links,errors=(Exception,)):
    record=C['item'](ledger,'kernel');package=P['canonical'](manager,record,ledger,before)
    resources=list(package.getChildrenResources(False))
    if len(resources)!=1 or resources[0].getClassName()!='SDSBSCompGraph' or resources[0].getIdentifier()!='vertical_noise' or {n.getIdentifier() for n in resources[0].getNodes()}!={'1041349787','1094664715','1094664716'}:raise ValueError('Full-stock comp metadata differs')
    graph=resources[0];fx=graph.getNodeFromId('1094664716')
    if fx.getDefinition().getId()!='sbs::compositing::fxmaps':raise ValueError('Full-stock FX definition differs')
    child=None;failure=None
    try:
        child=fx.getReferencedResource()
        if child is None or child.getClassName()!='SDSBSFxMapGraph':raise ValueError('No exact public referenced FX graph')
        if P['package_id'](child.getPackage())!=record['identity']:raise ValueError('Foreign FX owner')
    except errors as error:
        failure=dict(error_class=type(error).__name__,error=str(error)[:512]);error.__traceback__=None;error.__cause__=None;error.__context__=None
    if failure is not None:
        package=graph=fx=child=None;resources=[]
        raise A['OwnerError'](failure) from None
    nodes=list(child.getNodes());roots=list(child.getOutputNodes());wanted={r['node_id'] for r in shape['nodes']}
    if len(nodes)!=8 or {n.getIdentifier() for n in nodes}!=wanted or len(roots)!=1 or roots[0].getIdentifier()!=shape['root']:raise ValueError('Full FX runtime node/root metadata differs')
    edges=[];rows=[]
    for node in nodes:
        if node.getDefinition().getId()!='sbs::fxmap::paramset':raise ValueError('Full FX node definition differs')
        rows.append(dict(node_id=node.getIdentifier(),definition=node.getDefinition().getId(),properties=[A['descriptor'](p) for c in (Category.Input,Category.Output,Category.Annotation) for p in node.getProperties(c)]))
        for port in ('output0','output1','output2','output3'):
            for source,prop in links['incoming_sources'](child,node.getIdentifier(),port):edges.append(dict(source=source.getIdentifier(),target=node.getIdentifier(),input=port,output=prop.getId()))
    if sorted(edges,key=lambda e:(e['target'],e['input']))!=shape['edges']:raise ValueError('Fixed FX runtime flow metadata differs')
    modified=package.isModified()
    if type(modified) is not bool:raise ValueError('Actual kernel modified bool required')
    return dict(root=roots[0].getIdentifier(),nodes=sorted(rows,key=lambda r:r['node_id']),edges=sorted(edges,key=lambda e:(e['target'],e['input'])),kernel_modified=modified,physical_data_mapping_evidence='fixed original XML; no public shared-data UID getter claimed')

def post_function_metadata(C,P,A,manager,ledger,before,expected,Category,errors):
    record=C['item'](ledger,'kernel');package=P['canonical'](manager,record,ledger,before);child=None;failure=None
    try:
        child=package.getChildrenResources(False)[0].getNodeFromId('1094664716').getReferencedResource()
        if child is None or child.getClassName()!='SDSBSFxMapGraph' or P['package_id'](child.getPackage())!=record['identity']:raise ValueError('Post-observation FX owner differs')
    except errors as error:
        failure=dict(error_class=type(error).__name__,error=str(error)[:512]);error.__traceback__=None;error.__cause__=None;error.__context__=None
    if failure is not None:
        package=child=None
        raise A['OwnerError'](failure) from None
    rows=[]
    for scope in expected:
        wanted=sorted([dict(uid=n['uid'],definition='sbs::function::'+n['definition']) for n in scope['nodes']],key=lambda n:int(n['uid']))
        for owner in scope['owners']:
            node=child.getNodeFromId(owner);prop=node.getPropertyFromId(scope['property'],Category.Input);fn=node.getPropertyGraph(prop)
            if fn is None or fn.getClassName()!='SDSBSFunctionGraph':raise ValueError('Post-observation function binding differs')
            nodes=list(fn.getNodes());roots=list(fn.getOutputNodes());actual=sorted([dict(uid=n.getIdentifier(),definition=n.getDefinition().getId()) for n in nodes],key=lambda n:int(n['uid']))
            if actual!=wanted or len(roots)!=1 or roots[0].getIdentifier()!=scope['root']:raise ValueError('Post-observation loaded function UID/definition/root differs')
            rows.append(dict(owner_data_XML=scope['owner_data'],owner_FX_node=owner,property=scope['property'],root=scope['root'],nodes=actual))
    return dict(stage='after_all3compute7raw',bindings=rows,shared_data_claim_basis='unchanged XML mapping only; no public physical data UID getter',evaluated_function_getters=0)

def main():
    driver=Path(__file__).resolve();driver_sha=hashlib.sha256(driver.read_bytes()).hexdigest()
    work=ROOT/'output/evidence/full-stock-reference-probe'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=False);report=work/'summary.json'
    counts=dict(new_package=0,save=0,disorder_set=0,compute=0)
    ledger=dict(owned=[],ambiguous=False,load_calls=0,final_unload_calls=0)
    summary=dict(status='running',work=str(work),counts=counts,ledger=ledger,schedule=list(SCHEDULE),fixture_mode=FX_FIXTURE_MODE,product_acceptance=False,original_stock_failure_resolved=False,PNG=0,worker=0,kernel_mutations=0,raw_count=0,raw_bytes=0,tolerance=0,driver_source=dict(path=str(driver),before_sha256=driver_sha),scope='Full stock original UID/functions/shared-data preserved; single reference root2nodes, no Invert, no private stock evaluated-property getters. This changes the old2graphs5nodes+Invert context; old result equivalence is not claimed.')
    if SCOPED_CPU:summary.update(scoped_cpu=True,scope=summary['scope']+' Only each blocking compute uses evaluation.compute_graph with temporary lowest-bit OS affinity and exact restoration. This is not an engine thread1 guarantee; original failures remain unchanged.')
    if TRANSACTION_CPU:summary.update(transaction_cpu=True,scope=summary['scope']+' Entire synchronous main, including owned package load/create/configure, compute/raw and cleanup, uses evaluation_scope. SCOPED_CPU remains false. OS scheduling restriction only, not engine thread1 or an established product correction; original and compute-only failures remain unchanged.')
    if FX_FIXTURE_MODE=='unique_function_ids':summary['scope']='Original full-stock top fileUID/function operations/literals/shared-data retained, with offline scope-local function UID renumbering only. Same single reference root2nodes/no Invert/no private evaluated-property getters. Identifiers may affect RNG stream/cache identity; neither equivalent product patch nor UID collision causation is established. Old2graphs5nodes+Invert context equivalence is not claimed.'
    if FX_FIXTURE_MODE=='split_shared_data':summary['scope']='Original433 fixture only: offline physical data8599 cloned twice for owners6909/6922, with all local function UIDs/literals/order preserved. SDK kernel mutation0, same single reference root/no Invert. Calculation uses this split XML; engine re-sharing, original RNG stream equivalence, alias bug causation and product correction are not established. No public physical-data UID getter is claimed.'
    if FX_FIXTURE_MODE=='cut_after_first_gaussian':summary['scope']='Original433 fixture only: remove4 child8598 flow edges from first Gaussian5564, keeping all8 nodes/6 physical data/5 functions and fileUID/root/literals/functionUIDs/order. XML root reaches5 nodes;3 remain unused by that XML path, not deleted. Internal execution count is unmeasured. Data1/2 image contribution and sampling/accumulation conditions also change; layer-count causation, original pattern equivalence and a product patch are not established.'
    if FX_FIXTURE_MODE=='cut_after_second_gaussian':summary['scope']='Original433 fixture only: remove4 child6909 flow edges from second Gaussian8598, keeping all8 nodes/6 physical data/5 functions and fileUID/root/literals/functionUIDs/order. XML root reaches6 nodes;2 remain unused by that XML path, not deleted. Internal execution count is unmeasured. Next Gaussian contribution and sampling/accumulation conditions also change; hierarchy-count causation, original pattern equivalence and a product patch are not established.'
    if FX_FIXTURE_MODE=='cut_after_third_gaussian':summary['scope']='Original433 fixture only: remove4 child6922 flow edges from third Gaussian6909, keeping all8 nodes/6 physical data/5 functions and fileUID/root/literals/functionUIDs/order. XML root reaches7 nodes;1 remains unused by that XML path, not deleted. Internal execution count is unmeasured. Next Gaussian contribution and sampling/accumulation conditions also change; hierarchy-count causation, original pattern equivalence and a product patch are not established.'
    if FX_FIXTURE_MODE=='last_gaussian_one_branch':summary['scope']='Original433 fixture only: retain output0 and remove output1/2/3 child6922 edges at Gaussian6909. All8 nodes stay root-reachable; fourth-Gaussian depth,6 physical data/5 functions/fileUID/root/literals/functionUIDs/order are retained. Branch4→1 also changes contribution/sampling/RNG context/accumulation; actual stamp/GPU execution counts and a single cause or product patch are not established.'
    if FX_FIXTURE_MODE=='full_stock_repeat_cycles':summary['scope']='Unmodified original433 full4-Gaussian fixture, all connections/functions/shared data retained: source Disorder0→50→0→50→0,5 setters/5 computes/11 raw5767168bytes. First return comparison remains separate and cannot be replaced by a later equality. Later returns/same-value observations do not establish a cause or product correction.'
    if FX_FIXTURE_MODE in ('last_owner_split_baseline','last_owner_split_none'):summary['scope']='Original433: only last owner6922 uses an adjacent clone of data8599; original6 blocks and all8 nodes/28 edges remain. Baseline clone changes only data UID/reference; None arm additionally changes only cloned patterntype6→None0. Function-local UIDs/literals/operation order are otherwise preserved. Clone/RNG context/optimization can affect behavior; engine re-sharing, equivalent original stream, a single pattern cause and a product correction are not established. Physical data sharing is XML evidence, not a public SDK measurement.'
    if FX_FIXTURE_MODE=='last_owner_none_zero_offset':summary['scope']='From original433→last-owner6922 clone+patternNone fixture9bea: replace only cloned branchoffset paramValue/dynamicValue with literalFloat2(+0,+0). This removes the target4node function definition as well as its binding; original5 functions and cloned opacity function remain. All8 nodes/28 edges/7 data blocks and other fields remain. RNG consumption/compilation context can change; original semantic equivalence, binding-only change, a single cause and product correction are not established.'
    if FX_FIXTURE_MODE=='last_owner_none_half_opacity':summary['scope']='From original433→None9bea→zero-offset0b6097 fixture: replace only cloned last-owner opacity paramValue/dynamicValue with declared Float4 literal(.5,.5,.5,.5). The target4node opacity function definition is also removed; the original5 functions and all other owners/fields/8nodes/28edges/7data remain. This is a reduced fixture, not original-stock semantics or a correction. RNG consumption/compilation context and optimization can change; a single cause or product fix is not established.'
    def write_report():
        temp=report.with_suffix('.tmp');temp.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(report)
    def artifact(name,value):
        path=work/(name+'.json')
        with path.open('x',encoding='utf8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    write_report()
    F=runpy.run_path(str(BASE/'probe_files.py'));C=runpy.run_path(str(BASE/'context.py'));P,A=C['P'],C['A']
    G=runpy.run_path(str(BASE/'user_guard.py'));S=runpy.run_path(str(BASE/'enum_scope.py'));lane=runpy.run_path(str(BASE/'lane.py'));RAW=lane['RAW'];limits=lane['L'];links=runpy.run_path(str(ROOT/'plugin/substance_physics_scatter/connections.py'))
    before=None;user_before=None;disk={};flags=dict(rows=[]);role=None;ERRORS=(Exception,)
    try:
        # This fixed SHA gate precedes all package loading and source creation.
        raw=ORIGINAL.read_bytes();summary['source_before_sha256']=hashlib.sha256(raw).hexdigest();shape=xml_shape(raw);preparation=json.loads(PREPARATION.read_bytes())
        if preparation['uid']!=KERNEL_UID or preparation['prepared_sha256']!=ORIGINAL_SHA:raise ValueError('Accepted preparation UID/SHA differs; load0')
        summary['original_shape']=artifact('original-shape',shape)
        summary['preparation']=dict(path=str(PREPARATION),sha256=hashlib.sha256(PREPARATION.read_bytes()).hexdigest(),uid=preparation['uid'],prepared_sha256=preparation['prepared_sha256'])
        loaded_functions=None
        if FX_FIXTURE_MODE=='unique_function_ids':
            raw,proof,loaded_functions=unique_function_ids(raw);summary['offline_function_uid_patch']=artifact('offline-function-uid-patch',proof)
        elif FX_FIXTURE_MODE=='split_shared_data':
            raw,proof,loaded_functions=split_shared_data(raw);summary['offline_shared_data_split']=artifact('offline-shared-data-split',proof)
        elif FX_FIXTURE_MODE=='cut_after_first_gaussian':
            raw,proof,loaded_functions=cut_after_first_gaussian(raw);summary['offline_first_gaussian_cut']=artifact('offline-first-gaussian-cut',proof)
        elif FX_FIXTURE_MODE=='cut_after_second_gaussian':
            raw,proof,loaded_functions=cut_after_second_gaussian(raw);summary['offline_second_gaussian_cut']=artifact('offline-second-gaussian-cut',proof)
        elif FX_FIXTURE_MODE=='cut_after_third_gaussian':
            raw,proof,loaded_functions=cut_after_third_gaussian(raw);summary['offline_third_gaussian_cut']=artifact('offline-third-gaussian-cut',proof)
        elif FX_FIXTURE_MODE=='last_gaussian_one_branch':
            raw,proof,loaded_functions=last_gaussian_one_branch(raw);summary['offline_last_gaussian_one_branch']=artifact('offline-last-gaussian-one-branch',proof)
        elif FX_FIXTURE_MODE in ('last_owner_split_baseline','last_owner_split_none'):
            raw,proof,loaded_functions=last_owner_split(raw,FX_FIXTURE_MODE=='last_owner_split_none');summary['offline_last_owner_split']=artifact('offline-last-owner-split',proof)
        elif FX_FIXTURE_MODE=='last_owner_none_zero_offset':
            raw,proof,loaded_functions=last_owner_none_zero_offset(raw);summary['offline_last_owner_none_zero_offset']=artifact('offline-last-owner-none-zero-offset',proof)
        elif FX_FIXTURE_MODE=='last_owner_none_half_opacity':
            raw,proof,loaded_functions=last_owner_none_half_opacity(raw);summary['offline_last_owner_none_half_opacity']=artifact('offline-last-owner-none-half-opacity',proof)
        if FX_FIXTURE_MODE not in ('original','full_stock_repeat_cycles'):shape=xml_shape(raw,FX_FIXTURE_MODE);summary['loaded_shape']=artifact('loaded-shape',shape)
        target_sha=hashlib.sha256(raw).hexdigest();summary['loaded_fixture_sha256']=target_sha
        import sd
        from sd.api.apiexception import APIException
        ERRORS=(Exception,APIException)
        from sd.api.sdproperty import SDPropertyCategory as Category,SDPropertyInheritanceMethod as Inherit
        from sd.api.sdvaluefloat import SDValueFloat
        from PySide6 import QtCore,QtWidgets
        qt=QtWidgets.QApplication.instance()
        if qt is None or QtCore.QThread.currentThread()!=qt.thread():raise ValueError('Designer UI thread required')
        app=sd.getContext().getSDApplication()
        if app.getVersion()!='16.0.3':raise ValueError('Accepted Designer version differs')
        manager=app.getPackageMgr();del qt,app
        before=P['inventory'](manager);summary['inventory_before']=artifact('inventory-before',before)
        G['configure'](manager,[]);user_before=G['protected_snapshot']();summary['user_before']=artifact('user-before',user_before)
        target=work/'PrivateNoiseFX32.sbs'
        with target.open('xb') as stream:stream.write(raw)
        disk={str(ORIGINAL):ORIGINAL_SHA,str(target):target_sha,str(PREPARATION):summary['preparation']['sha256']}
        C['load_kernel'](manager,target,KERNEL_UID,ledger,before)
        role=C['create_source'](manager,work/'FullStockReference.sbs',ledger,before,counts)
        disk[role['identity']['path']]=hashlib.sha256(Path(role['identity']['path']).read_bytes()).hexdigest()
        metadata=kernel_metadata(C,P,A,manager,ledger,before,shape,Category,links,ERRORS);summary['kernel_metadata_before']=artifact('kernel-metadata-before',metadata)
        inputs=[];source_baseline=None
        def set_input(value,old):
            inputs.append(dict(stage='before_set',input=source_input(C,A,manager,ledger,before,role,old,Category,Inherit)))
            first=C['source_view'](manager,ledger,before,role);source_flag(flags,first,'before_set')
            node=C['root'](manager,ledger,before,role).getNodeFromId(role['ids']['noise_instance']);counts['disorder_set']+=1
            if counts['disorder_set']>len(SCHEDULE):raise ValueError('Disorder setter budget exceeded')
            node.setInputPropertyValueFromId('Disorder',SDValueFloat.sNew(value))
            second=C['source_view'](manager,ledger,before,role);source_flag(flags,second,'after_set',True)
            if source_projection(first)!=source_projection(second):raise ValueError('Other source fields changed during setter')
            inputs.append(dict(stage='after_set',input=source_input(C,A,manager,ledger,before,role,value,Category,Inherit)))
        def check(value,stage):
            P['context'](manager,ledger,before);view=C['source_view'](manager,ledger,before,role);source_flag(flags,view,stage)
            if source_projection(view)!=source_projection(source_baseline):raise ValueError('Other source authored fields changed')
            inputs.append(dict(stage=stage,input=source_input(C,A,manager,ledger,before,role,value,Category,Inherit)))
            if kernel_metadata(C,P,A,manager,ledger,before,shape,Category,links,ERRORS)!=metadata:raise ValueError('Full FX metadata/modified flag changed')
            if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha for p,sha in disk.items()):raise ValueError('Original disk changed')
        set_input(0.,0.);source_baseline=C['source_view'](manager,ledger,before,role)
        files=RAW['Artifacts'](work,dict(F,own=lambda path:own_raw(path,work,F)))
        repeated=FX_FIXTURE_MODE=='full_stock_repeat_cycles'
        collectors=[files]+([RAW['Artifacts'](work,dict(F,own=lambda path:own_raw(path,work,F)))] if repeated else [])
        def read_budget(layouts):
            used=sum(f.used for f in collectors)
            if repeated:repeat_before_read(summary['raw_count'],used,layouts,limits)
            else:limits['before_read'](summary['raw_count'],used,layouts)
        read_budget((limits['K_LAYOUT'],)+(limits['FX_LAYOUT'],)*(10 if repeated else 6))
        def capture(name,texture,layout):
            read_budget((layout,));data,meta=RAW['capture'](texture,expected_layout=layout)
            collector=collectors[1] if repeated and summary['raw_count']>=7 else files
            ref=collector.save(name,data,meta,expected_layout=layout);summary.update(raw_count=summary['raw_count']+1,raw_bytes=sum(f.used for f in collectors),raw_artifacts=[row for f in collectors for row in f.rows]);return data,ref
        check(0.,'before_calibration');summary['K']=lane['calibrate'](capture);images={};summary['observations']=[]
        for step,(label,value) in enumerate(SCHEDULE):
            if (work/'CANCEL').exists():raise InterruptedError('Cancelled at safe boundary')
            if step:set_input(value,SCHEDULE[step-1][1])
            check(value,'before_compute');counts['compute']+=1
            if SCOPED_CPU:scoped_compute_once(C,manager,ledger,before,role)
            else:lane['compute_once'](manager,ledger,before,role)
            check(value,'after_compute')
            read_budget((limits['FX_LAYOUT'],)*2)
            data,row=lane['read_terminal'](manager,ledger,before,role,label,capture);check(value,'after_raw');summary['observations'].append(row);images[label]=data
            if not row['distinct_words_at_least2']:raise ValueError('Nonuniform output required')
        if counts['compute']!=len(SCHEDULE) or counts['disorder_set']!=len(SCHEDULE) or summary['raw_count']!=1+2*len(SCHEDULE) or summary['raw_bytes']!=(5767168 if repeated else 3670016):raise ValueError('Fixed setter/compute/raw budget differs')
        if FX_FIXTURE_MODE in ('unique_function_ids','split_shared_data','cut_after_first_gaussian','cut_after_second_gaussian','cut_after_third_gaussian','last_gaussian_one_branch','last_owner_split_baseline','last_owner_split_none','last_owner_none_zero_offset','last_owner_none_half_opacity'):summary['loaded_function_metadata']=artifact('loaded-function-metadata-after-observation',post_function_metadata(C,P,A,manager,ledger,before,loaded_functions,Category,ERRORS))
        summary['input_effect']=lane['compare'](images['N0'],images['N50']);summary['return_comparison']=lane['compare'](images['N0'],images['NR0'])
        if summary['input_effect']['exact']:raise ValueError('Disorder has no observed input effect')
        summary['math_pass']=summary['return_comparison']['exact'];summary['status']='full_stock_reference_observation_complete'
        if repeated:
            summary['repeat_cycle_comparisons']=repeat_comparisons(images,lane['compare']);summary['math_pass']=summary['repeat_cycle_comparisons']['math_pass']
    except ERRORS as error:
        if isinstance(error,A['OwnerError']):P['ambiguous'](ledger,'Full FX owner unverifiable; no related cleanup/full-user reader')
        summary.update(status='failed',error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
        error.__traceback__=None;error.__cause__=None;error.__context__=None
    finally:
        # Phase helpers return only bytes/JSON. No source/FX node is retained here.
        if before is not None:
            try:
                summary['cleanup']=P['cleanup'](manager,ledger,before,ERRORS);final=P['inventory'](manager);summary['inventory_after']=artifact('inventory-after',final);summary['inventory_unchanged']=final==before
                if user_before is not None and P['trust_final'](ledger,final,before):
                    user_after=G['protected_snapshot']();summary['user_after']=artifact('user-after',user_after);comparison=S['compare'](user_before,user_after,F['read_json'](BASE/'enum_expected.json'));summary['user_comparison']=artifact('user-comparison',comparison);summary['user_unchanged']=comparison['semantic_protection_equal']
                if not summary.get('user_unchanged') or not summary['inventory_unchanged']:summary['status']='failed_preservation'
            except ERRORS as error:
                summary.update(status='failed_preservation',protection_error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
                error.__traceback__=None;error.__cause__=None;error.__context__=None
        summary['source_modified_observations']=flags['rows'];summary['disorder_input_observations']=locals().get('inputs',[])
        summary['original_disks_unchanged']=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in disk.items())
        summary['source_after_sha256']=hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()
        if 'target' in locals() and target.exists():summary['loaded_fixture_after_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
        if not summary['original_disks_unchanged']:summary['status']='failed_preservation'
        summary['driver_source'].update(after_sha256=hashlib.sha256(driver.read_bytes()).hexdigest());summary['driver_source']['unchanged']=summary['driver_source']['after_sha256']==driver_sha
        if not summary['driver_source']['unchanged']:summary['status']='failed_driver_changed'
        write_report()
    return report

if __name__=='__main__':
    if TRANSACTION_CPU:
        from substance_physics_scatter.evaluation import evaluation_scope
        with evaluation_scope():REPORT=main()
    else:REPORT=main()
    print(str(REPORT))
