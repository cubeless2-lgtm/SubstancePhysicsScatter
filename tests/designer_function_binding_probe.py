"""Root-owned, fixed three-compute diagnostic; only private packages are mutated."""
from pathlib import Path
import copy
import hashlib
import json
import runpy
import struct
import traceback
import uuid
from xml.etree import ElementTree as ET

MODE=globals().get('PROBE_MODE','patternsize')
if type(MODE) is not str or MODE not in ('patternsize','branchoffset','rng_offset','large_pattern','repeat_pattern','repeat_rng','disorder_repeat'):
    raise ValueError('Only seven fixed diagnostic modes are supported')
PATTERN_Y=8. if MODE in ('large_pattern','repeat_pattern','repeat_rng','disorder_repeat') else .5
INITIAL_PATTERN_X=1.25 if MODE in ('large_pattern','repeat_pattern','repeat_rng','disorder_repeat') else .5
SCHEDULE=(('N0',0.),('N50',50.),('NR0',0.)) if MODE=='disorder_repeat' else (('L125',1.25),('L150',1.5),('LR125',1.25)) if MODE in ('large_pattern','repeat_pattern','repeat_rng') else (('P0',0.),('P025',.25),('PR0',0.)) if MODE=='branchoffset' else (('G05',.5),('G075',.75),('GR05',.5))

ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH=Path(__file__).resolve()
DRIVER_SHA=hashlib.sha256(DRIVER_PATH.read_bytes()).hexdigest()
BASE = ROOT / 'output/evidence/noise-function-free-compute-probe/b2514d41190146ff8edbaea39ca70aac'
WORK = ROOT / 'output/evidence/function-binding-probe' / uuid.uuid4().hex
WORK.mkdir(parents=True, exist_ok=False)
REPORT = WORK / 'summary.json'
F = runpy.run_path(str(BASE / 'probe_files.py'))
C = runpy.run_path(str(BASE / 'context.py'))
P, A = C['P'], C['A']
RAW = runpy.run_path(str(BASE / 'raw_texture.py'))
COMPARE = runpy.run_path(str(BASE / 'lane.py'))['compare']
ledger = dict(owned=[], ambiguous=False, load_calls=0, final_unload_calls=0)
counts = dict(new_package=0, save=0, pattern_set=0, branchoffset_set=0, compute=0)
summary = dict(status='running', work=str(WORK), ledger=ledger, counts=counts,
               tolerance=0, PNG=0, worker=0, raw_count=0, raw_bytes=0,
               original_stock_failure_resolved=False,
               mode=MODE,schedule=list(SCHEDULE),
               scope=('one Gaussian: patternsize const_float2 .5→.75→.5' if MODE=='patternsize' else 'one Gaussian: patternsize const_float2 fixed(.5,.5); branchoffset literal(0,0)→(.25,0)→(0,0)'))
summary['driver_source']=dict(path=str(DRIVER_PATH),before_sha256=DRIVER_SHA)
if MODE in ('rng_offset','repeat_rng','disorder_repeat'):
    summary['scope']='one Gaussian: stock branchoffset operation structure recreated by public SDK; new node UIDs/implicit RNG context do not establish the original random stream'
    summary['original_RNG_stream_equivalence_claimed']=False
    summary['RNG_output_oracle']=None
if MODE=='large_pattern':
    summary['scope']='one Gaussian: large stock footprint const_float2(1.25,8)→(1.5,8)→(1.25,8); actual self-wrap multiple accumulation is not established'
    summary['self_wrap_accumulation_established']=False
if MODE in ('repeat_pattern','repeat_rng','disorder_repeat'):
    summary['scope']='large single Gaussian plus three None-pattern four-branch parents; expected64 leaf visits is topology only, not measured internal stamp executions'
    summary.update(expected_leaf_visits=64,actual_stamp_executions_measured=False)
    counts.update(fx_new=0,flow_connect=0,root_unset=0,root_set=0)
if MODE=='repeat_rng':summary['scope']='successful large four-branch partial topology plus one stock-operation RNG function on the Gaussian keeper; original stream equivalence and measured internal stamp count are not claimed'
if MODE=='disorder_repeat':
    summary['scope']='reduced repeated large Gaussian with Gaussian RNG plus lowest-parent stock Disorder function and source input0→50→0; coupled authoring/input reconstruction does not establish get_float1 as the cause'
    counts['disorder_set']=0;summary['source_modified_observations']=[];summary['disorder_input_observations']=[]

def report():
    temporary = REPORT.with_suffix('.tmp')
    temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(REPORT)

def artifact(name, value):
    path = WORK / (name + '.json')
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

report()
import sd
from sd.api.apiexception import APIException
from sd.api.sdproperty import SDPropertyCategory as Category,SDPropertyInheritanceMethod as Inherit
from sd.api.sdvaluefloat2 import SDValueFloat2
from sd.api.sdvaluefloat import SDValueFloat
from sd.api.sdvaluestring import SDValueString
from sd.api.sdbasetypes import float2
from sd.api.sdtexture import SDTexture
from PySide6 import QtCore, QtWidgets

ERRORS = (Exception, APIException)
mgr = sd.getContext().getSDApplication().getPackageMgr()
G = runpy.run_path(str(BASE / 'user_guard.py'))
S = runpy.run_path(str(BASE / 'enum_scope.py'))
guard_spec=F['read_json'](BASE/'enum_expected.json')
before = None
user_before = None
source_baseline = None
kernel_baseline = None
role = None
original = BASE / 'FunctionFreeNoise.sbs'
original_sha = 'ce8d0619c0b3aa7c17149799ce7266aa1b7f5a804e1fc2e70d635a357c9b5713'
disk = {}
rng_ids=None
repeat_ids=None
disorder_ids=None
last_source_flag=None
LINKS=runpy.run_path(str(ROOT/'plugin/substance_physics_scatter/connections.py'))

def repeat_parent_state(parent):
    props=[p for category in (Category.Input,Category.Output,Category.Annotation) for p in parent.getProperties(category)]
    metadata=[A['descriptor'](p) for p in props]
    if metadata!=F['read_json'](BASE/'expected_metadata.json')['keeper_descriptors']:raise ValueError('Parent paramset declaration differs')
    literals=[]
    function_count=0
    for prop in props:
        binding=parent.getPropertyGraph(prop)
        if binding is not None:
            if MODE!='disorder_repeat' or repeat_ids is None or parent.getIdentifier()!=repeat_ids[0] or prop.getId()!='branchoffset':raise ValueError('Parent functions forbidden')
            default=C['scalar'](prop.getDefaultValue())
            if default['wrapper']!='SDValueFloat2' or default['value']!=[0.,0.] or default['bits']!=[struct.pack('=f',0.).hex()]*2:raise ValueError('Bound branch default changed')
            if list(parent.getPropertyConnections(prop)):raise ValueError('Bound branch cannot have a flow connection')
            literals.append(dict(id=prop.getId(),default=default,binding=disorder_state(parent)));function_count+=1;continue
        if prop.getCategory()!=Category.Input or prop.getId() in ('output0','output1','output2','output3'):continue
        if list(parent.getPropertyConnections(prop)):raise ValueError('Parent scalar must remain an unbound literal')
        default=C['scalar'](prop.getDefaultValue());current=C['scalar'](parent.getPropertyValue(prop));declared=A['descriptor'](prop)['types']
        if sum(t==default['type'] for t in declared)!=1 or current!=default:
            summary['parent_default_mismatch']=dict(node_id=parent.getIdentifier(),property=prop.getId(),declared=declared,default=default,current=current)
            raise ValueError('Parent current/default must match one fixed declared type')
        if prop.getId()=='patterntype' and (default['wrapper']!='SDValueEnum' or default.get('value_id')!='null' or default['value']!=0):raise ValueError('Parent pattern must be None/null')
        literals.append(dict(id=prop.getId(),default=default,current=current))
    return dict(node_id=parent.getIdentifier(),definition=parent.getDefinition().getId(),metadata=metadata,literals=literals,function_count=function_count)

def restore_repeat():
    global repeat_ids
    _,_,_,child,leaf=A['scope'](mgr,C['item'](ledger,'kernel')['identity'])
    if [n.getIdentifier() for n in child.getNodes()]!=[leaf.getIdentifier()] or [n.getIdentifier() for n in child.getOutputNodes()]!=[leaf.getIdentifier()]:raise ValueError('Exact single Gaussian root required before repeat')
    parents=[]
    for _ in range(3):
        counts['fx_new']+=1
        parent=child.newNode('sbs::fxmap::paramset')
        if parent.getDefinition().getId()!='sbs::fxmap::paramset':raise ValueError('New parent definition differs')
        repeat_parent_state(parent);parents.append(parent)
    counts['root_unset']+=1;child.setOutputNode(leaf,False)
    if list(child.getOutputNodes()):raise ValueError('Gaussian root did not clear')
    lower=leaf
    for parent in parents:
        outputs=list(lower.getProperties(Category.Output))
        if len(outputs)!=1 or outputs[0].getId()!='unique_filter_output':raise ValueError('Exact FX flow output missing')
        for port in ('output0','output1','output2','output3'):
            prop=parent.getPropertyFromId(port,Category.Input)
            if prop is None or list(parent.getPropertyConnections(prop)):raise ValueError('Fresh parent flow input required')
            counts['flow_connect']+=1;lower.newPropertyConnectionFromId('unique_filter_output',parent,port)
        lower=parent
    counts['root_set']+=1;child.setOutputNode(parents[-1],True);repeat_ids=[p.getIdentifier() for p in parents]

def repeat_state():
    _,_,_,child,leaf=A['scope'](mgr,C['item'](ledger,'kernel')['identity']);leaf_id=leaf.getIdentifier()
    nodes=list(child.getNodes());roots=list(child.getOutputNodes())
    if repeat_ids is None or len(repeat_ids)!=3 or len(set([leaf_id]+repeat_ids))!=4 or len(nodes)!=4 or {n.getIdentifier() for n in nodes}!=set([leaf_id]+repeat_ids) or len(roots)!=1 or roots[0].getIdentifier()!=repeat_ids[-1]:raise ValueError('Exact repeat FX node/root closure differs')
    rows=[];edges=[]
    for index,node_id in enumerate([leaf_id]+repeat_ids):
        node=child.getNodeFromId(node_id)
        if node is None or node.getDefinition().getId()!='sbs::fxmap::paramset':raise ValueError('Repeat node definition differs')
        if index:rows.append(repeat_parent_state(node))
        for port in ('output0','output1','output2','output3'):
            incoming=LINKS['incoming_sources'](child,node_id,port)
            if index==0:
                if incoming:raise ValueError('Gaussian must remain a leaf')
            else:
                expected=([leaf_id]+repeat_ids)[index-1]
                if len(incoming)!=1 or incoming[0][0].getIdentifier()!=expected or incoming[0][1].getId()!='unique_filter_output':raise ValueError('Exact four-way child→parent FX flow differs')
                edges.append(dict(source=expected,output='unique_filter_output',target=node_id,input=port))
    if len(edges)!=12:raise ValueError('Exactly12 FX flow edges required')
    return dict(node_count=4,root=repeat_ids[-1],root_count=1,flow_count=12,leaf=leaf_id,parent_nodes=rows,edges=edges,expected_leaf_visits=64,actual_stamp_executions_measured=False)

def stock_branch(raw):
    if hashlib.sha256(raw).hexdigest()!='47116c37a2e0d59dfc149760d1b999f19323272e23d3164af01da918b0112cc4':raise ValueError('Original vertical_noise bytes differ')
    tree=ET.fromstring(raw);owners=[n for n in tree.iter('paramsGraphData') if n.find('uid') is not None and n.find('uid').get('v')=='1028055563']
    if len(owners)!=1:raise ValueError('Exact physical owner data required')
    parameters=[p for p in owners[0].findall('parameters/parameter') if p.find('name').get('v')=='branchoffset']
    if len(parameters)!=1:raise ValueError('Unique stock branchoffset required')
    dynamic=parameters[0].find('paramValue/dynamicValue');nodes=dynamic.findall('paramNodes/paramNode');root=dynamic.find('rootnode').get('v')
    rows={n.find('uid').get('v'):dict(definition=n.find('function').get('v'),type=n.find('type').get('v'),inputs={c.find('identifier').get('v'):c.find('connRef').get('v') for c in n.findall('connections/connection')}) for n in nodes}
    expected={'1028056125':dict(definition='const_float1',type='256',inputs={}), '1028056132':dict(definition='rand',type='256',inputs={'a':'1028056125'}),'1028056163':dict(definition='rand',type='256',inputs={'a':'1028056125'}),'1028056139':dict(definition='vector2',type='512',inputs={'componentsin':'1028056132','componentslast':'1028056163'})}
    if len(nodes)!=4 or rows!=expected or root!='1028056139':raise ValueError('Exact stock four-node/four-edge function differs')
    constant=next(n for n in nodes if n.find('uid').get('v')=='1028056125').find('funcDatas/funcData/constantValue/constantValueFloat1')
    if constant is None or constant.get('v')!='0.400000006':raise ValueError('Original random range token differs')
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),owner_data='1028055563',root=root,nodes=rows,constant_token=constant.get('v'),xml=ET.tostring(parameters[0],encoding='unicode'))

def stock_pattern(raw):
    if hashlib.sha256(raw).hexdigest()!='47116c37a2e0d59dfc149760d1b999f19323272e23d3164af01da918b0112cc4':raise ValueError('Original vertical_noise bytes differ')
    owners=[n for n in ET.fromstring(raw).iter('paramsGraphData') if n.find('uid') is not None and n.find('uid').get('v')=='1028055563']
    if len(owners)!=1:raise ValueError('Exact pattern owner required')
    params=[p for p in owners[0].findall('parameters/parameter') if p.find('name').get('v')=='patternsize']
    if len(params)!=1 or params[0].find('paramValue/constantValueFloat2') is None or params[0].find('paramValue/constantValueFloat2').get('v')!='1.25 8':raise ValueError('Original large Float2 literal differs')
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),owner_data='1028055563',pattern_token='1.25 8',xml=ET.tostring(params[0],encoding='unicode'))

DISORDER_NODES=(('get','get_float1','1030099976'),('radius','rand','1030099998'),('angle','rand','1035574854'),('tau','const_float1','1035574861'),('x','mul','1035574946'),('cos','cos','1035574947'),('y','mul','1035574948'),('sin','sin','1035574949'),('scale','const_float1','1035575019'),('amount','mul','1035575030'),('vector','vector2','1035575058'))
DISORDER_EDGES=(('get','amount','a'),('scale','amount','b'),('amount','radius','a'),('tau','angle','a'),('angle','cos','a'),('angle','sin','a'),('radius','x','a'),('cos','x','b'),('radius','y','a'),('sin','y','b'),('x','vector','componentsin'),('y','vector','componentslast'))

def stock_disorder(raw):
    if hashlib.sha256(raw).hexdigest()!='47116c37a2e0d59dfc149760d1b999f19323272e23d3164af01da918b0112cc4':raise ValueError('Original stock changed')
    owners=[n for n in ET.fromstring(raw).iter('paramsGraphData') if n.find('uid') is not None and n.find('uid').get('v')=='1028376472']
    if len(owners)!=1:raise ValueError('Exact Disorder owner data required')
    params=[p for p in owners[0].findall('parameters/parameter') if p.find('name').get('v')=='branchoffset']
    if len(params)!=1:raise ValueError('Unique Disorder branch required')
    dynamic=params[0].find('paramValue/dynamicValue');nodes=dynamic.findall('paramNodes/paramNode');by_id={n.find('uid').get('v'):n for n in nodes}
    ids={r:i for r,_,i in DISORDER_NODES}
    if len(nodes)!=11 or set(by_id)!=set(ids.values()) or dynamic.find('rootnode').get('v')!=ids['vector']:raise ValueError('Exact Disorder11/root closure differs')
    edges=[];constants={}
    for role,definition,node_id in DISORDER_NODES:
        n=by_id[node_id]
        if n.find('function').get('v')!=definition or n.find('type').get('v')!=('512' if role=='vector' else '256'):raise ValueError('Disorder XML definition/type differs')
        for c in n.findall('connections/connection'):edges.append((c.find('connRef').get('v'),node_id,c.find('identifier').get('v')))
        if role in ('get','tau','scale'):
            v=n.find('funcDatas/funcData/constantValue');children=list(v)
            if len(children)!=1:raise ValueError('Single XML constant required')
            constants[role]=dict(tag=children[0].tag,token=children[0].get('v'))
    if sorted(edges)!=sorted((ids[s],ids[d],p) for s,d,p in DISORDER_EDGES) or constants!={'get':{'tag':'constantValueString','token':'Disorder'},'tau':{'tag':'constantValueFloat1','token':'6.28000021'},'scale':{'tag':'constantValueFloat1','token':'0.00999999978'}}:raise ValueError('Exact Disorder edges/constants differ')
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),owner_data='1028376472',nodes=list(DISORDER_NODES),edges=list(DISORDER_EDGES),constants=constants,root='vector',xml=ET.tostring(params[0],encoding='unicode'))

def disorder_port(node,identifier,category,kind):
    prop=typed_port(node,identifier,category,kind)
    t=prop.getType();m=t.getModifier()
    if (t.getClassName(),t.getId(),m.name,m.value)!=('SDType'+kind,kind.lower(),'Auto',0):raise ValueError('Disorder first declared port type differs from fixed profile')
    return prop

def restore_disorder_branch():
    global disorder_ids
    stock=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages/vertical_noise.sbs');spec=stock_disorder(stock.read_bytes());disk[str(stock)]=spec['source_sha256'];summary['disorder_stock']=artifact('disorder-stock',spec)
    _,_,_,child,_=A['scope'](mgr,C['item'](ledger,'kernel')['identity']);parent=child.getNodeFromId(repeat_ids[0]);prop=parent.getPropertyFromId('branchoffset',Category.Input)
    if parent.getPropertyGraph(prop) is not None or list(parent.getPropertyConnections(prop)):raise ValueError('Lowest parent branch must start unbound')
    fn=parent.newPropertyGraph(prop,'SDSBSFunctionGraph')
    if fn is None or fn.getClassName()!='SDSBSFunctionGraph' or list(fn.getNodes()):raise ValueError('Empty Disorder function required')
    nodes={role:fn.newNode('sbs::function::'+definition) for role,definition,_ in DISORDER_NODES}
    nodes['get'].setInputPropertyValueFromId('__constant__',SDValueString.sNew('Disorder'))
    for role in ('tau','scale'):
        value=struct.unpack('=f',struct.pack('=f',float(spec['constants'][role]['token'])))[0]
        nodes[role].setInputPropertyValueFromId('__constant__',SDValueFloat.sNew(value))
    # Wire generic nodes before checking the exact connected-profile declarations.
    # SDProperty.getType() returns the first declaration, not an evaluated type.
    for source,destination,port in DISORDER_EDGES:
        outputs=list(nodes[source].getProperties(Category.Output));target=nodes[destination].getPropertyFromId(port,Category.Input)
        if len(outputs)!=1 or outputs[0].getId()!='unique_filter_output' or target is None:raise ValueError('Exact Disorder port missing')
        nodes[source].newPropertyConnectionFromId('unique_filter_output',nodes[destination],port)
    fn.setOutputNode(nodes['vector'],True);disorder_ids={r:n.getIdentifier() for r,n in nodes.items()}
    disorder_state(parent)

def disorder_state(parent):
    prop=parent.getPropertyFromId('branchoffset',Category.Input);fn=parent.getPropertyGraph(prop)
    if fn is None or fn.getClassName()!='SDSBSFunctionGraph' or len(fn.getNodes())!=11 or disorder_ids is None or len(set(disorder_ids.values()))!=11 or {n.getIdentifier() for n in fn.getNodes()}!=set(disorder_ids.values()) or len(fn.getOutputNodes())!=1 or fn.getOutputNodes()[0].getIdentifier()!=disorder_ids['vector']:raise ValueError('Disorder function11/root closure differs')
    rows=[];edges=[];values={}
    for role,definition,_ in DISORDER_NODES:
        node=fn.getNodeFromId(disorder_ids[role])
        if node is None or node.getDefinition().getId()!='sbs::function::'+definition:raise ValueError('Disorder node definition differs')
        wanted={p:s for s,d,p in DISORDER_EDGES if d==role}
        if role in ('get','tau','scale'):wanted={'__constant__':None}
        inputs=list(node.getProperties(Category.Input))
        if {p.getId() for p in inputs}!=set(wanted) or len(inputs)!=len(wanted):raise ValueError('Exact Disorder inputs differ')
        for p in inputs:
            disorder_port(node,p.getId(),Category.Input,'String' if role=='get' else 'Float')
            if node.getPropertyGraph(p) is not None:raise ValueError('Nested Disorder function forbidden')
            links=LINKS['incoming_sources'](fn,node.getIdentifier(),p.getId());source=wanted[p.getId()]
            if source is None:
                if links:raise ValueError('Disorder constant must be unbound')
            elif len(links)!=1 or links[0][0].getIdentifier()!=disorder_ids[source] or links[0][1].getId()!='unique_filter_output':raise ValueError('Disorder edge mapping differs')
            else:edges.append(dict(source=disorder_ids[source],target=node.getIdentifier(),input=p.getId(),output='unique_filter_output'))
        outputs=list(node.getProperties(Category.Output))
        if len(outputs)!=1 or outputs[0].getId()!='unique_filter_output':raise ValueError('Exact Disorder output differs')
        disorder_port(node,'unique_filter_output',Category.Output,'Float2' if role=='vector' else 'Float')
        if role=='get':
            value=node.getInputPropertyValueFromId('__constant__')
            if type(value).__name__!='SDValueString' or value.getClassName()!='SDValueString':raise ValueError('Typed Disorder variable name required')
            t=value.getType();m=t.getModifier();text=value.get()
            if (t.getClassName(),t.getId(),m.name,m.value)!=('SDTypeString','string','Auto',0) or text!='Disorder':raise ValueError('Exact Disorder variable string differs')
            values[role]=dict(wrapper=value.getClassName(),type=dict(class_name=t.getClassName(),id=t.getId(),modifier=dict(name=m.name,value=m.value)),value=text)
        elif role in ('tau','scale'):
            value=C['scalar'](node.getInputPropertyValueFromId('__constant__'));expected=6.28000021 if role=='tau' else .00999999978
            if value['wrapper']!='SDValueFloat' or value['bits']!=[struct.pack('=f',expected).hex()]:raise ValueError('Exact Disorder float constant bits differ')
            values[role]=value
        rows.append(dict(role=role,node_id=node.getIdentifier(),definition=node.getDefinition().getId(),properties=[A['descriptor'](p) for c in (Category.Input,Category.Output,Category.Annotation) for p in node.getProperties(c)]))
    if len(edges)!=12:raise ValueError('Exactly12 Disorder edges required')
    return dict(owner_node=parent.getIdentifier(),owner_property='branchoffset',node_count=11,edge_count=12,root=disorder_ids['vector'],nodes=rows,edges=sorted(edges,key=lambda e:(e['target'],e['input'])),constants=values)

def source_projection(view):
    result=copy.deepcopy(view)
    if MODE=='disorder_repeat':result.pop('source_modified')
    return result

def observe_source_flag(view,label,allow_setter=False):
    global last_source_flag
    flag=view['source_modified']
    if type(flag) is not bool:raise ValueError('Source modified flag must be an actual bool')
    if last_source_flag is not None and flag!=last_source_flag and (not allow_setter or last_source_flag):raise ValueError('Source modified changed outside an allowed setter or True→False')
    summary['source_modified_observations'].append(dict(label=label,actual=flag,previous=last_source_flag,setter_transition_allowed=allow_setter));last_source_flag=flag

def disorder_input(expected):
    graph=C['root'](mgr,ledger,before,role);node=graph.getNodeFromId(role['ids']['noise_instance']);prop=node.getPropertyFromId('Disorder',Category.Input)
    if prop is None or prop.getCategory()!=Category.Input or node.getPropertyGraph(prop) is not None or list(node.getPropertyConnections(prop)) or node.getPropertyInheritanceMethod(prop)!=Inherit.Absolute:raise ValueError('Exact unbound Absolute source Disorder Input required')
    descriptor=A['descriptor'](prop);typ=dict(class_name='SDTypeFloat',id='float',modifier=dict(name='Auto',value=0))
    current=C['scalar'](node.getPropertyValue(prop));default=C['scalar'](prop.getDefaultValue())
    if descriptor['types']!=[typ] or current['wrapper']!='SDValueFloat' or default['wrapper']!='SDValueFloat' or current['type']!=typ or default['type']!=typ or default['value']!=0. or default['bits']!=[struct.pack('=f',0.).hex()] or current['bits']!=[struct.pack('=f',expected).hex()] or current['value']!=expected:raise ValueError('Source Disorder declared/default/current typed bits differ')
    return dict(node_id=node.getIdentifier(),property=descriptor,current=current,default=default,inheritance=dict(name=Inherit.Absolute.name,value=Inherit.Absolute.value),function=None,connections=[])

def set_disorder(value,previous):
    summary['disorder_input_observations'].append(dict(stage='before_set',input=disorder_input(previous)))
    first=C['source_view'](mgr,ledger,before,role);observe_source_flag(first,'before_set',False)
    node=C['root'](mgr,ledger,before,role).getNodeFromId(role['ids']['noise_instance'])
    counts['disorder_set']+=1
    if counts['disorder_set']>3:raise ValueError('Exactly3 source Disorder setters maximum')
    node.setInputPropertyValueFromId('Disorder',SDValueFloat.sNew(value))
    second=C['source_view'](mgr,ledger,before,role);observe_source_flag(second,'after_set',True)
    if source_projection(first)!=source_projection(second):raise ValueError('Other source fields changed during Disorder setter')
    summary['disorder_input_observations'].append(dict(stage='after_set',input=disorder_input(value)))

def typed_port(node,identifier,category,kind):
    prop=node.getPropertyFromId(identifier,category)
    if prop is None:raise ValueError('Required function port missing: '+identifier)
    types=list(prop.getTypes())
    if len(types)!=1:raise ValueError('Ambiguous function port type')
    t=types[0];m=t.getModifier()
    if (t.getClassName(),t.getId(),m.name,m.value)!=('SDType'+kind,kind.lower(),'Auto',0):raise ValueError('Function port type/modifier differs')
    return prop

def output_port(node,kind):
    props=list(node.getProperties(Category.Output))
    if len(props)!=1 or props[0].getId()!='unique_filter_output':raise ValueError('Exact unique_filter_output function port required')
    typed_port(node,props[0].getId(),Category.Output,kind)
    return props[0].getId()

def restore_rng_offset():
    global rng_ids
    stock=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages/vertical_noise.sbs');raw=stock.read_bytes();spec=stock_branch(raw);disk[str(stock)]=spec['source_sha256']
    summary['rng_stock_block']=artifact('rng-stock-block',spec)
    node=keeper();prop=typed_port(node,'branchoffset',Category.Input,'Float2')
    if node.getPropertyGraph(prop) is not None or list(node.getPropertyConnections(prop)):raise ValueError('Original branchoffset must be unbound')
    fn=node.newPropertyGraph(prop,'SDSBSFunctionGraph')
    if fn is None or fn.getClassName()!='SDSBSFunctionGraph' or list(fn.getNodes()):raise ValueError('Empty branch function unavailable; compute0')
    nodes={name:fn.newNode('sbs::function::'+definition) for name,definition in (('constant','const_float1'),('xrand','rand'),('yrand','rand'),('vector','vector2'))}
    value=struct.unpack('=f',struct.pack('=f',float(spec['constant_token'])))[0]
    typed_port(nodes['constant'],'__constant__',Category.Input,'Float')
    nodes['constant'].setInputPropertyValueFromId('__constant__',SDValueFloat.sNew(value))
    for source,destination,port in (('constant','xrand','a'),('constant','yrand','a'),('xrand','vector','componentsin'),('yrand','vector','componentslast')):
        typed_port(nodes[destination],port,Category.Input,'Float')
        nodes[source].newPropertyConnectionFromId(output_port(nodes[source],'Float'),nodes[destination],port)
    output_port(nodes['vector'],'Float2');fn.setOutputNode(nodes['vector'],True)
    rng_ids={name:n.getIdentifier() for name,n in nodes.items()}

def rng_state(node):
    prop=typed_port(node,'branchoffset',Category.Input,'Float2');fn=node.getPropertyGraph(prop)
    if fn is None or fn.getClassName()!='SDSBSFunctionGraph' or list(node.getPropertyConnections(prop)):raise ValueError('Exact branch function binding required')
    nodes=list(fn.getNodes());outputs=list(fn.getOutputNodes())
    if rng_ids is None or len(set(rng_ids.values()))!=4 or len(nodes)!=4 or {n.getIdentifier() for n in nodes}!=set(rng_ids.values()) or len(outputs)!=1 or outputs[0].getIdentifier()!=rng_ids['vector']:raise ValueError('Exact branch node/root closure differs')
    views=[];edges=[]
    for role,definition in (('constant','const_float1'),('xrand','rand'),('yrand','rand'),('vector','vector2')):
        current=fn.getNodeFromId(rng_ids[role])
        if current is None or current.getDefinition().getId()!='sbs::function::'+definition:raise ValueError('Branch node definition differs')
        wanted_inputs={'constant':{'__constant__'},'xrand':{'a'},'yrand':{'a'},'vector':{'componentsin','componentslast'}}[role]
        inputs=list(current.getProperties(Category.Input))
        if {p.getId() for p in inputs}!=wanted_inputs or len(inputs)!=len(wanted_inputs):raise ValueError('Exact branch input port set differs')
        for p in inputs:
            typed_port(current,p.getId(),Category.Input,'Float')
            if current.getPropertyGraph(p) is not None:raise ValueError('Nested function forbidden')
            incoming=LINKS['incoming_sources'](fn,current.getIdentifier(),p.getId())
            if role=='constant':
                if incoming:raise ValueError('Constant must be unbound')
            else:
                source='constant' if role in ('xrand','yrand') else ('xrand' if p.getId()=='componentsin' else 'yrand')
                if len(incoming)!=1 or incoming[0][0].getIdentifier()!=rng_ids[source] or incoming[0][1].getId()!=output_port(incoming[0][0],'Float'):raise ValueError('Stock RNG wiring differs')
                edges.append(dict(source=rng_ids[source],output=incoming[0][1].getId(),target=current.getIdentifier(),input=p.getId()))
        output_port(current,'Float2' if role=='vector' else 'Float')
        views.append(dict(role=role,node_id=current.getIdentifier(),definition=current.getDefinition().getId(),properties=[A['descriptor'](p) for category in (Category.Input,Category.Output,Category.Annotation) for p in current.getProperties(category)]))
    value=C['scalar'](fn.getNodeFromId(rng_ids['constant']).getInputPropertyValueFromId('__constant__'))
    if value['wrapper']!='SDValueFloat' or value['bits']!=[struct.pack('=f',.400000006).hex()]:raise ValueError('Original typed RNG constant differs')
    if len(edges)!=4:raise ValueError('Exactly four branch edges required')
    return dict(owner_property=A['descriptor'](prop),graph_class=fn.getClassName(),function_count=1,node_count=4,edge_count=4,root=rng_ids['vector'],nodes=views,edges=sorted(edges,key=lambda e:(e['target'],e['input'])),constant=value)

def keeper():
    P['context'](mgr, ledger, before)
    record = C['item'](ledger, 'kernel')
    P['canonical'](mgr, record, ledger, before)
    return A['scope'](mgr, record['identity'])[-1]

def strict_scheduled_values(state,pattern,offset,pattern_y=PATTERN_Y):
    constant=state['constant'];branches=[p['value'] for p in state['keeper_literals'] if p['id']=='branchoffset']
    if MODE in ('rng_offset','repeat_rng','disorder_repeat'):
        if branches or 'rng_offset' not in state:raise ValueError('Bound RNG branch must be structural, not a literal current')
        if constant['wrapper']!='SDValueFloat2' or constant['value']!=[pattern,pattern_y] or constant['bits']!=[struct.pack('=f',v).hex() for v in (pattern,pattern_y)]:raise ValueError('Exact pattern constant differs')
        return
    if len(branches)!=1:raise ValueError('Exactly one branchoffset literal required')
    for payload,expected in ((constant,[pattern,pattern_y]),(branches[0],[offset,0.])):
        if payload['wrapper']!='SDValueFloat2' or payload['value']!=expected or payload['bits']!=[struct.pack('=f',v).hex() for v in expected]:raise ValueError('Exact scheduled Float2 value/bits differ')


def function_state(expected,pattern_y=PATTERN_Y,offset=0.):
    node = keeper()
    prop = node.getPropertyFromId('patternsize', Category.Input)
    fn = node.getPropertyGraph(prop)
    if fn is None or fn.getClassName() != 'SDSBSFunctionGraph':
        raise ValueError('Exact patternsize function binding missing')
    nodes = list(fn.getNodes())
    outputs = list(fn.getOutputNodes())
    if len(nodes) != 1 or len(outputs) != 1 or nodes[0].getIdentifier() != outputs[0].getIdentifier():
        raise ValueError('Exactly one function node/output required')
    constant = nodes[0]
    if constant.getDefinition().getId() != 'sbs::function::const_float2':
        raise ValueError('Only const_float2 is allowed')
    value = constant.getInputPropertyValueFromId('__constant__')
    scalar = C['scalar'](value)
    if scalar['wrapper'] != 'SDValueFloat2' or scalar['value'] != [expected, pattern_y]:
        raise ValueError('Function constant effective typed value differs')
    literals = []
    for p in node.getProperties(Category.Input):
        if p.getId() in ('output0', 'output1', 'output2', 'output3'):
            continue
        if list(node.getPropertyConnections(p)):
            raise ValueError('No keeper flow connections allowed')
        if p.getId() not in ('patternsize','branchoffset') and node.getPropertyGraph(p) is not None:
            raise ValueError('Unexpected extra function')
        if p.getId()=='branchoffset':
            if MODE in ('rng_offset','repeat_rng','disorder_repeat'):continue # Never evaluate a bound random result.
            if node.getPropertyGraph(p) is not None:raise ValueError('Unexpected branch function in literal mode')
        if p.getId() != 'patternsize':
            literals.append(dict(id=p.getId(), value=C['scalar'](node.getPropertyValue(p))))
    state=dict(node_id=constant.getIdentifier(), definition=constant.getDefinition().getId(),
                constant=scalar, keeper_literals=literals)
    if MODE in ('rng_offset','repeat_rng','disorder_repeat'):state['rng_offset']=rng_state(node)
    if MODE in ('repeat_pattern','repeat_rng','disorder_repeat'):state['repeat_pattern']=repeat_state()
    strict_scheduled_values(state,expected,offset,pattern_y)
    return state

def fixed_view(state):
    result = copy.deepcopy(state)
    if MODE!='branchoffset':result.pop('constant')
    else:
        branches=[p['value'] for p in result['keeper_literals'] if p['id']=='branchoffset']
        if len(branches)!=1:raise ValueError('Exactly one branchoffset comparison slot required')
        branches[0]['value'][0]=0.;branches[0]['bits'][0]=struct.pack('=f',0.).hex()
    return result

def check(expected,stage='check'):
    P['context'](mgr, ledger, before)
    view=C['source_view'](mgr, ledger, before, role)
    if MODE=='disorder_repeat':
        observe_source_flag(view,stage,False);summary['disorder_input_observations'].append(dict(stage=stage,input=disorder_input(expected)))
    if source_projection(view) != source_projection(source_baseline):
        raise ValueError('Source authored values changed')
    pattern=INITIAL_PATTERN_X if MODE=='disorder_repeat' else expected if MODE!='branchoffset' else .5
    state = function_state(pattern,PATTERN_Y,expected if MODE=='branchoffset' else 0.)
    if fixed_view(state) != kernel_baseline:
        raise ValueError('Unexpected keeper/function changes')
    for path, digest in disk.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('Original disk input changed')
    return state

try:
    qt = QtWidgets.QApplication.instance()
    if qt is None or QtCore.QThread.currentThread() != qt.thread():
        raise ValueError('Designer UI thread required')
    app = sd.getContext().getSDApplication()
    if app.getVersion() != '16.0.3':
        raise ValueError('Accepted Designer environment differs')
    summary['environment'] = dict(designer=app.getVersion(), qt=QtCore.qVersion())
    before = P['inventory'](mgr)
    summary['inventory_before'] = artifact('inventory-before', before)
    G['configure'](mgr, [])
    user_before = G['protected_snapshot']()
    summary['user_before'] = artifact('user-before', user_before)
    raw = original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != original_sha:
        raise ValueError('Accepted function-free kernel changed')
    target = WORK / 'FunctionBindingNoise.sbs'
    target.write_bytes(raw)
    disk[str(original)] = original_sha
    disk[str(target)] = original_sha
    C['load_kernel'](mgr, target, '78a10744-010c-4e3f-a4ec-e257a87dcaf4', ledger, before)
    role = C['create_source'](mgr, WORK / 'FunctionBindingSource.sbs', ledger, before, counts)
    disk[role['identity']['path']] = hashlib.sha256(Path(role['identity']['path']).read_bytes()).hexdigest()
    if MODE=='disorder_repeat':set_disorder(0.,0.)
    source_baseline = C['source_view'](mgr, ledger, before, role)
    summary['literal_before'] = artifact('literal-before', C['kernel_view'](mgr, ledger, before, .5))
    if MODE in ('large_pattern','repeat_pattern','repeat_rng','disorder_repeat'):
        stock=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages/vertical_noise.sbs');spec=stock_pattern(stock.read_bytes());disk[str(stock)]=spec['source_sha256'];summary['stock_pattern']=artifact('stock-pattern',spec)
    node = keeper()
    prop = node.getPropertyFromId('patternsize', Category.Input)
    fn = node.newPropertyGraph(prop, 'SDSBSFunctionGraph')
    if fn is None or list(fn.getNodes()):
        raise ValueError('Empty new function unavailable; compute0')
    constant = fn.newNode('sbs::function::const_float2')
    constant.setInputPropertyValueFromId('__constant__', SDValueFloat2.sNew(float2(INITIAL_PATTERN_X, PATTERN_Y)))
    fn.setOutputNode(constant, True)
    if MODE in ('rng_offset','repeat_rng','disorder_repeat'):restore_rng_offset()
    if MODE in ('repeat_pattern','repeat_rng','disorder_repeat'):restore_repeat()
    if MODE=='disorder_repeat':restore_disorder_branch()
    kernel_baseline = fixed_view(function_state(INITIAL_PATTERN_X,PATTERN_Y))
    summary['function_initial'] = artifact('function-initial', function_state(INITIAL_PATTERN_X,PATTERN_Y))
    del node, prop, fn, constant
    images = {}
    rows = []
    def capture(name, texture, layout):
        if summary['raw_count'] >= 7 or summary['raw_bytes'] + 524288 > 3670016:
            raise ValueError('Fixed raw budget exhausted')
        data, metadata = RAW['capture'](texture, expected_layout=layout)
        path = WORK / (name + '.raw')
        with path.open('xb') as stream:
            stream.write(data)
        summary['raw_count'] += 1
        summary['raw_bytes'] += len(data)
        rows.append(dict(path=str(path), bytes=len(data), metadata=metadata))
        summary['raw_artifacts'] = rows
        return data
    calibration = capture('K', SDTexture.sFromFile(str(BASE / 'K.png')), RAW['K_LAYOUT'])
    if RAW['canonical'](calibration, expected_layout=RAW['K_LAYOUT']) != RAW['expected']():
        raise ValueError('K16 raw calibration failed')
    summary['observations'] = []
    for step,(label, x) in enumerate(SCHEDULE):
        if (WORK / 'CANCEL').exists():
            raise InterruptedError('Cancelled at safe boundary')
        node = keeper()
        if MODE=='disorder_repeat':
            if step>0:set_disorder(x,SCHEDULE[step-1][1])
        elif MODE!='branchoffset':
            current = node.getPropertyGraph(node.getPropertyFromId('patternsize', Category.Input))
            counts['pattern_set'] += 1
            current.getNodes()[0].setInputPropertyValueFromId('__constant__', SDValueFloat2.sNew(float2(x, PATTERN_Y)))
            del current
        else:
            counts['branchoffset_set'] += 1
            node.setInputPropertyValueFromId('branchoffset',SDValueFloat2.sNew(float2(x,0.)))
        del node
        check(x,'before_compute')
        counts['compute'] += 1
        C['root'](mgr, ledger, before, role).compute()
        check(x,'after_compute')
        graph = C['root'](mgr, ledger, before, role)
        terminal = graph.getNodeFromId(role['ids']['terminal'])
        props = terminal.getProperties(Category.Output)
        if len(props) != 1 or props[0].getId() != role['output']:
            raise ValueError('Exact terminal output required')
        value = terminal.getPropertyValue(props[0])
        if value.getClassName() != 'SDValueTexture':
            raise ValueError('Terminal texture wrapper differs')
        texture = value.get()
        first = capture(label + '-before', texture, RAW['FX_LAYOUT'])
        second = capture(label + '-after', texture, RAW['FX_LAYOUT'])
        if first != second:
            raise ValueError('Consecutive raw pair changed')
        if len({first[i:i+4] for i in range(0, len(first), 4)}) < 2:
            raise ValueError('Nonuniform output required')
        images[label] = first
        summary['observations'].append(dict(label=label, function_state=check(x), sha256=hashlib.sha256(first).hexdigest()))
        del graph, terminal, props, value, texture
    summary['input_effect'] = COMPARE(images[SCHEDULE[0][0]], images[SCHEDULE[1][0]])
    summary['return_comparison'] = COMPARE(images[SCHEDULE[0][0]], images[SCHEDULE[2][0]])
    if summary['input_effect']['exact']:
        raise ValueError('Scheduled input has no output effect')
    if MODE=='disorder_repeat' and not summary['return_comparison']['exact']:raise ValueError('Return raw differs from required exact0')
    summary['status'] = 'diagnostic_observation_complete'
except ERRORS as error:
    if isinstance(error, A['OwnerError']):
        P['ambiguous'](ledger, 'FX owner unverifiable; no related cleanup/user reader')
    summary['status'] = 'failed'
    summary['error'] = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
finally:
    # No owned SDK graph/node/value wrapper survives into package cleanup or the
    # runpy namespace returned to the bridge. Re-resolve cleanup by canonical ID.
    for name in ('node', 'prop', 'fn', 'constant', 'current', 'graph', 'terminal',
                 'props', 'value', 'texture', 'qt', 'app'):
        globals().pop(name, None)
    if before is not None:
        summary['cleanup'] = P['cleanup'](mgr, ledger, before, ERRORS)
        final = P['inventory'](mgr)
        summary['inventory_after'] = artifact('inventory-after', final)
        summary['inventory_unchanged'] = final == before
        if user_before is not None and P['trust_final'](ledger, final, before):
            after = G['protected_snapshot']()
            summary['user_after'] = artifact('user-after', after)
            comparison=S['compare'](user_before,after,guard_spec)
            summary['user_comparison']=artifact('user-comparison',comparison)
            summary['user_raw_equal']=comparison['raw_equal']
            summary['user_unchanged'] = comparison['semantic_protection_equal']
        if not summary.get('inventory_unchanged') or not summary.get('user_unchanged'):
            summary['status'] = 'failed_preservation'
    summary['original_disks_unchanged'] = all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in disk.items())
    if not summary['original_disks_unchanged']:
        summary['status'] = 'failed_preservation'
    summary['driver_source'].update(after_sha256=hashlib.sha256(DRIVER_PATH.read_bytes()).hexdigest())
    summary['driver_source']['unchanged']=summary['driver_source']['after_sha256']==DRIVER_SHA
    if not summary['driver_source']['unchanged']:summary['status']='failed_driver_changed'
    report()
print(str(REPORT))
