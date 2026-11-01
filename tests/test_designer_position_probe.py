"""Fixed-mode/source-projection tests only; never execute Designer or raw reads."""
import ast,copy,hashlib,runpy,struct,types,unittest
from xml.etree import ElementTree as ET
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_function_binding_probe.py'

def pure(mode=None):
    tree=ast.parse(SOURCE.read_text(encoding='utf8'));namespace=dict(copy=copy,struct=struct,hashlib=hashlib,ET=ET,summary={})
    if mode is not None:namespace['PROBE_MODE']=mode
    nodes=[]
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('MODE','SCHEDULE','PATTERN_Y','INITIAL_PATTERN_X','DISORDER_NODES','DISORDER_EDGES') for t in n.targets):nodes.append(n)
        elif isinstance(n,ast.If) and any(isinstance(x,ast.Name) and x.id=='MODE' for x in ast.walk(n)) and n.lineno<25:nodes.append(n)
        elif isinstance(n,ast.FunctionDef) and n.name in ('strict_scheduled_values','fixed_view','stock_branch','stock_pattern','typed_port','output_port','rng_state','function_state','repeat_parent_state','repeat_state','stock_disorder','disorder_port','disorder_state','source_projection','observe_source_flag','disorder_input','set_disorder'):nodes.append(n)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),namespace)
    return namespace

def f2(x,y):return dict(wrapper='SDValueFloat2',type={'class_name':'SDTypeFloat2','modifier':'Auto'},value=[x,y],bits=[struct.pack('=f',v).hex() for v in (x,y)])
def state(x=0.):return dict(node_id='fixed-function-node',definition='sbs::function::const_float2',constant=f2(.5,.5),keeper_literals=[dict(id='branchoffset',value=f2(x,0.)),dict(id='rotation',value={'value':0.})])

class Position(unittest.TestCase):
    def test_only_fixed_modes_and_original_schedule(self):
        self.assertEqual(pure()['SCHEDULE'],(('G05',.5),('G075',.75),('GR05',.5)))
        self.assertEqual(pure('branchoffset')['SCHEDULE'],(('P0',0.),('P025',.25),('PR0',0.)))
        self.assertEqual(pure('rng_offset')['SCHEDULE'],pure()['SCHEDULE'])
        for mode in (True,'arbitrary'):
            with self.assertRaises(ValueError):pure(mode)
    def test_position_projection_only_removes_exact_x_and_bits(self):
        p=pure('branchoffset');a=state();b=state(.25)
        p['strict_scheduled_values'](b,.5,.25)
        self.assertEqual(p['fixed_view'](a),p['fixed_view'](b))
        for mutate in (lambda s:s['constant'].update(value=[.75,.5]),lambda s:s['keeper_literals'][0]['value'].update(value=[.25,.25]),lambda s:s['keeper_literals'][0]['value'].update(wrapper='SDValueFloat4'),lambda s:s['keeper_literals'][0]['value'].update(bits=[struct.pack('=f',.25).hex(),struct.pack('=f',-0.).hex()])):
            bad=copy.deepcopy(b);mutate(bad)
            with self.assertRaises(ValueError):p['strict_scheduled_values'](bad,.5,.25)
        bad=copy.deepcopy(b);bad['keeper_literals'][0]['value']['type']['modifier']='Changed'
        self.assertNotEqual(p['fixed_view'](a),p['fixed_view'](bad))
        bad=copy.deepcopy(b);bad['keeper_literals'][1]['value']['value']=1
        self.assertNotEqual(p['fixed_view'](a),p['fixed_view'](bad))
        self.assertEqual(b,state(.25)) # Raw observation/proof is never normalized in place.
    def test_default_projection_and_fixed_forwarder_semantic_guard(self):
        p=pure();a=state();b=copy.deepcopy(a);b['constant']=f2(.75,.5)
        self.assertEqual(p['fixed_view'](a),p['fixed_view'](b))
        b['keeper_literals'][0]['value']=f2(.25,0.)
        self.assertNotEqual(p['fixed_view'](a),p['fixed_view'](b))
        forward=ROOT/'tests/designer_position_probe.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):
            namespace={'__file__':str(forward)};exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),namespace)
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'PROBE_MODE':'branchoffset'}))])
        text=SOURCE.read_text(encoding='utf8')
        self.assertIn("comparison=S['compare'](user_before,after,guard_spec)",text)
        self.assertIn("summary['user_unchanged'] = comparison['semantic_protection_equal']",text)
        self.assertIn("summary['raw_count'] >= 7",text);self.assertIn('3670016',text)
    def test_large_pattern_has_its_own_fixed_y_bits_and_forwarder(self):
        p=pure('large_pattern');self.assertEqual(p['SCHEDULE'],(('L125',1.25),('L150',1.5),('LR125',1.25)))
        self.assertEqual((p['INITIAL_PATTERN_X'],p['PATTERN_Y']),(1.25,8.))
        for mode in ('patternsize','branchoffset','rng_offset'):self.assertEqual(pure(mode)['PATTERN_Y'],.5)
        a=state();a['constant']=f2(1.25,8.);b=copy.deepcopy(a);b['constant']=f2(1.5,8.)
        p['strict_scheduled_values'](a,1.25,0.);p['strict_scheduled_values'](b,1.5,0.)
        self.assertEqual(p['fixed_view'](a),p['fixed_view'](b))
        bad=copy.deepcopy(b);bad['constant']=f2(1.5,.5)
        with self.assertRaises(ValueError):p['strict_scheduled_values'](bad,1.5,0.)
        stock=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages/vertical_noise.sbs')
        self.assertEqual(p['stock_pattern'](stock.read_bytes())['pattern_token'],'1.25 8')
        forward=ROOT/'tests/designer_large_pattern_probe.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'PROBE_MODE':'large_pattern'}))])
        self.assertIn("C['kernel_view'](mgr, ledger, before, .5)",SOURCE.read_text(encoding='utf8'))

class Rng(unittest.TestCase):
    def test_original_stock_block_and_fixed_forwarder(self):
        p=pure('rng_offset');path=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages/vertical_noise.sbs')
        spec=p['stock_branch'](path.read_bytes())
        self.assertEqual(spec['constant_token'],'0.400000006');self.assertEqual(len(spec['nodes']),4)
        self.assertEqual(spec['nodes']['1028056139']['inputs'],dict(componentsin='1028056132',componentslast='1028056163'))
        forward=ROOT/'tests/designer_rng_offset_probe.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'PROBE_MODE':'rng_offset'}))])
    def test_actual_four_node_checker_never_reads_random_or_bound_current(self):
        p=pure('rng_offset');category=types.SimpleNamespace(Input='Input',Output='Output',Annotation='Annotation')
        class Prop:
            def __init__(self,name,kind,cat):self.name=name;self.kind=kind;self.cat=cat
            def getId(self):return self.name
            def getTypes(self):return [types.SimpleNamespace(getClassName=lambda:'SDType'+self.kind,getId=lambda:self.kind.lower(),getModifier=lambda:types.SimpleNamespace(name='Auto',value=0))]
        class Node:
            def __init__(self,role,definition,inputs,kind):self.role=role;self.definition=definition;self.inputs={i:Prop(i,'Float','Input') for i in inputs};self.output=Prop('unique_filter_output',kind,'Output')
            def getIdentifier(self):return self.role
            def getDefinition(self):return types.SimpleNamespace(getId=lambda:'sbs::function::'+self.definition)
            def getProperties(self,c):return list(self.inputs.values()) if c=='Input' else [self.output] if c=='Output' else []
            def getPropertyFromId(self,i,c):return self.inputs.get(i) if c=='Input' else self.output if self.output.name==i else None
            def getPropertyGraph(self,prop):return None
            def getInputPropertyValueFromId(self,i):
                if self.role!='constant' or i!='__constant__':raise AssertionError('Random evaluation getter forbidden')
                return dict(wrapper='SDValueFloat',value=struct.unpack('=f',struct.pack('=f',.400000006))[0],bits=[struct.pack('=f',.400000006).hex()])
            def getPropertyValue(self,*_):raise AssertionError('Evaluation output getter forbidden')
        nodes=dict(constant=Node('constant','const_float1',['__constant__'],'Float'),xrand=Node('xrand','rand',['a'],'Float'),yrand=Node('yrand','rand',['a'],'Float'),vector=Node('vector','vector2',['componentsin','componentslast'],'Float2'))
        graph=types.SimpleNamespace(getClassName=lambda:'SDSBSFunctionGraph',getNodes=lambda:list(nodes.values()),getOutputNodes=lambda:[nodes['vector']],getNodeFromId=lambda i:nodes[i])
        links={('xrand','a'):'constant',('yrand','a'):'constant',('vector','componentsin'):'xrand',('vector','componentslast'):'yrand'}
        branch=Prop('branchoffset','Float2','Input')
        keeper=types.SimpleNamespace(getPropertyFromId=lambda i,c:branch,getPropertyGraph=lambda prop:graph,getPropertyConnections=lambda prop:[],getPropertyValue=lambda *_:(_ for _ in ()).throw(AssertionError('Bound branch current forbidden')))
        p.update(Category=category,rng_ids={r:r for r in nodes},C={'scalar':lambda v:v},A={'descriptor':lambda prop:dict(id=prop.name,kind=prop.kind)},LINKS={'incoming_sources':lambda graph,i,port:[] if i=='constant' else [(nodes[links[(i,port)]],nodes[links[(i,port)]].output)]})
        result=p['rng_state'](keeper)
        self.assertEqual((result['function_count'],result['node_count'],result['edge_count']),(1,4,4))
        old=links[('vector','componentsin')];links[('vector','componentsin')]='yrand'
        with self.assertRaises(ValueError):p['rng_state'](keeper)
        links[('vector','componentsin')]=old;nodes['xrand'].inputs['a'].kind='Float2'
        with self.assertRaises(ValueError):p['rng_state'](keeper)
        nodes['xrand'].inputs['a'].kind='Float';nodes['constant'].output.name='unknown'
        with self.assertRaises(ValueError):p['rng_state'](keeper)
        tree=ast.parse(SOURCE.read_text(encoding='utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='rng_state')
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='getPropertyValue' for n in ast.walk(fn)))

class Repeat(unittest.TestCase):
    def test_actual_enum_int_union_parent_default_regression(self):
        actual=__import__('json').loads((ROOT/'output/evidence/function-binding-probe/17b2b119cc8b406b80b1806206bfcaac/summary.json').read_bytes())['parent_default_mismatch']
        self.assertEqual(actual['property'],'patterntype');self.assertEqual(actual['current'],actual['default']);self.assertEqual(len(actual['declared']),2)
        expected=__import__('json').loads((ROOT/'output/evidence/noise-function-free-compute-probe/b2514d41190146ff8edbaea39ca70aac/expected_metadata.json').read_bytes())['keeper_descriptors']
        category=types.SimpleNamespace(Input='Input',Output='Output',Annotation='Annotation')
        class Prop:
            def __init__(self,meta):
                self.meta=copy.deepcopy(meta)
                if meta['id']=='patterntype':self.default=copy.deepcopy(actual['default'])
                elif meta['types']:
                    t=copy.deepcopy(meta['types'][0]);self.default=dict(type=t,wrapper=t['class_name'].replace('SDType','SDValue'),value=0)
                else:self.default=None
                self.current=copy.deepcopy(self.default)
            def getId(self):return self.meta['id']
            def getCategory(self):return self.meta['category']
            def getDefaultValue(self):return self.default
        props=[Prop(m) for m in expected]
        parent=types.SimpleNamespace(getProperties=lambda c:[p for p in props if p.meta['category']==c],getPropertyGraph=lambda p:None,getPropertyConnections=lambda p:[],getPropertyValue=lambda p:p.current,getIdentifier=lambda:'actual-union-parent',getDefinition=lambda:types.SimpleNamespace(getId=lambda:'sbs::fxmap::paramset'))
        namespace=pure('repeat_pattern');namespace.update(Category=category,BASE=ROOT,summary={},A={'descriptor':lambda p:p.meta},C={'scalar':lambda v:v},F={'read_json':lambda path:{'keeper_descriptors':expected}})
        result=namespace['repeat_parent_state'](parent)
        row=next(r for r in result['literals'] if r['id']=='patterntype')
        self.assertEqual(row['default'],actual['default']);self.assertEqual(row['current'],actual['current']);self.assertEqual(result['metadata'],expected)
    def test_repeat_rng_combines_existing_fixed_helpers_only(self):
        namespace=pure('repeat_rng');self.assertEqual(namespace['SCHEDULE'],pure('repeat_pattern')['SCHEDULE']);self.assertEqual(namespace['PATTERN_Y'],8.)
        a=dict(constant=f2(1.25,8.),keeper_literals=[],rng_offset={'constant_bits':struct.pack('=f',.400000006).hex()},repeat_pattern={'flow_count':12})
        namespace['strict_scheduled_values'](a,1.25,0.)
        b=copy.deepcopy(a);b['constant']=f2(1.5,8.);namespace['strict_scheduled_values'](b,1.5,0.)
        self.assertEqual(namespace['fixed_view'](a),namespace['fixed_view'](b))
        b['rng_offset']['constant_bits']='changed';self.assertNotEqual(namespace['fixed_view'](a),namespace['fixed_view'](b))
        tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        blocks=[n for n in ast.walk(tree) if isinstance(n,ast.If) and any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id in ('restore_rng_offset','restore_repeat') for stmt in n.body for x in ast.walk(stmt))]
        # Only the two immediate fixed mode branches, not their enclosing try.
        blocks=[n for n in blocks if len(n.body)==1 and isinstance(n.body[0],ast.Expr)]
        calls=[];exec(compile(ast.Module(body=sorted(blocks,key=lambda n:n.lineno),type_ignores=[]),str(SOURCE),'exec'),dict(MODE='repeat_rng',restore_rng_offset=lambda:calls.append('rng'),restore_repeat=lambda:calls.append('repeat')))
        self.assertEqual(calls,['rng','repeat'])
        forward=ROOT/'tests/designer_repeat_rng_probe.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'PROBE_MODE':'repeat_rng'}))])
    def test_fixed_repeat_forwarder_large_geometry_and_source_guard(self):
        p=pure('repeat_pattern');self.assertEqual(p['SCHEDULE'],pure('large_pattern')['SCHEDULE']);self.assertEqual(p['PATTERN_Y'],8.)
        forward=ROOT/'tests/designer_repeat_pattern_probe.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'PROBE_MODE':'repeat_pattern'}))])
        text=SOURCE.read_text(encoding='utf8');self.assertIn("counts['fx_new']+=1",text);self.assertIn("counts['flow_connect']+=1",text);self.assertIn("summary['driver_source']['unchanged']",text)
    def test_actual_repeat_checker_closes_twelve_edges_and_parent_defaults(self):
        p=pure('repeat_pattern');category=types.SimpleNamespace(Input='I',Output='O',Annotation='A')
        typ=dict(class_name='SDTypeEnum',id='sbs::fxmap::patterntype',modifier=dict(name='Auto',value=0))
        enum=dict(wrapper='SDValueEnum',type=typ,value=0,value_id='null')
        class Prop:
            def __init__(self,i,c,default=None):self.i=i;self.c=c;self.default=default;self.current=copy.deepcopy(default)
            def getId(self):return self.i
            def getCategory(self):return self.c
            def getDefaultValue(self):return copy.deepcopy(self.default)
        class Node:
            def __init__(self,i):self.i=i;self.props=[Prop('output'+str(n),'I') for n in range(4)]+[Prop('patterntype','I',enum),Prop('unique_filter_output','O')];self.fn=False
            def getIdentifier(self):return self.i
            def getDefinition(self):return types.SimpleNamespace(getId=lambda:'sbs::fxmap::paramset')
            def getProperties(self,c):return [x for x in self.props if x.c==c]
            def getPropertyGraph(self,prop):return object() if self.fn else None
            def getPropertyConnections(self,prop):return []
            def getPropertyValue(self,prop):return copy.deepcopy(prop.current)
        nodes={i:Node(i) for i in ('leaf','p0','p1','p2')};roots=['p2']
        graph=types.SimpleNamespace(getNodes=lambda:list(nodes.values()),getOutputNodes=lambda:[nodes[i] for i in roots],getNodeFromId=lambda i:nodes[i])
        edges={(target,'output'+str(n)):source for source,target in (('leaf','p0'),('p0','p1'),('p1','p2')) for n in range(4)}
        desc=lambda prop:dict(id=prop.i,category=prop.c,types=[] if prop.default is None else [prop.default['type']])
        metadata=[desc(x) for x in nodes['p0'].props]
        p.update(Category=category,BASE=ROOT,mgr=None,ledger={},before=[],repeat_ids=['p0','p1','p2'],C={'item':lambda *args:{'identity':{}},'scalar':lambda v:v},A={'scope':lambda *args:(None,None,None,graph,nodes['leaf']),'descriptor':desc},F={'read_json':lambda path:{'keeper_descriptors':metadata}},LINKS={'incoming_sources':lambda graph,target,port:[] if target=='leaf' else [(nodes[edges[(target,port)]],nodes[edges[(target,port)]].props[-1])]})
        state=p['repeat_state']();self.assertEqual((state['node_count'],state['root_count'],state['flow_count']),(4,1,12));self.assertFalse(state['actual_stamp_executions_measured'])
        edges[('p2','output3')]='leaf'
        with self.assertRaises(ValueError):p['repeat_state']()
        edges[('p2','output3')]='p1';nodes['p0'].props[4].current['value_id']='gaussian'
        with self.assertRaises(ValueError):p['repeat_state']()
        nodes['p0'].props[4].current=copy.deepcopy(enum);nodes['p1'].fn=True
        with self.assertRaises(ValueError):p['repeat_state']()
        nodes['p1'].fn=False;roots[:]=['leaf']
        with self.assertRaises(ValueError):p['repeat_state']()

class Disorder(unittest.TestCase):
    def test_fixed_stock_structure_schedule_and_forwarder(self):
        p=pure('disorder_repeat')
        self.assertEqual(p['SCHEDULE'],(('N0',0.),('N50',50.),('NR0',0.)))
        self.assertEqual((p['INITIAL_PATTERN_X'],p['PATTERN_Y']),(1.25,8.))
        stock=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages/vertical_noise.sbs')
        spec=p['stock_disorder'](stock.read_bytes())
        self.assertEqual((len(spec['nodes']),len(spec['edges'])),(11,12))
        self.assertEqual(spec['constants']['get'],dict(tag='constantValueString',token='Disorder'))
        forward=ROOT/'tests/designer_disorder_repeat_probe.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'PROBE_MODE':'disorder_repeat'}))])
        tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        baseline=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='source_baseline' for t in n.targets) and isinstance(n.value,ast.Call))
        initial=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and len(n.body)==1 and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Call) and isinstance(n.body[0].value.func,ast.Name) and n.body[0].value.func.id=='set_disorder')
        self.assertLess(initial.lineno,baseline.lineno)
        loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple) and isinstance(n.target.elts[0],ast.Name) and n.target.elts[0].id=='step')
        branch=next(n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=="MODE == 'disorder_repeat'")
        self.assertEqual(ast.unparse(branch.body[0].test),'step > 0')
        # Execute the actual setter branch: initial explicit0, then only50/0.
        calls=[]
        for step,(_,x) in enumerate(p['SCHEDULE']):
            exec(compile(ast.Module(body=[branch],type_ignores=[]),str(SOURCE),'exec'),dict(MODE='disorder_repeat',step=step,x=x,SCHEDULE=p['SCHEDULE'],set_disorder=lambda *v:calls.append(v)))
        self.assertEqual(calls,[(50.,0.),(0.,50.)])

    def test_modified_flag_is_separate_monotonic_and_setter_scoped(self):
        p=pure('disorder_repeat');p.update(last_source_flag=None,summary={'source_modified_observations':[]})
        for flag,allowed in ((False,False),(False,True),(False,False),(True,True),(True,False),(True,True)):
            p['observe_source_flag']({'source_modified':flag},'test',allowed)
        with self.assertRaises(ValueError):p['observe_source_flag']({'source_modified':False},'reset',True)
        p['last_source_flag']=False
        with self.assertRaises(ValueError):p['observe_source_flag']({'source_modified':True},'compute',False)
        with self.assertRaises(ValueError):p['observe_source_flag']({'source_modified':1},'opaque',True)
        a=dict(source_modified=False,values=[{'value':0}],edge='strict');b=copy.deepcopy(a);b['source_modified']=True
        self.assertEqual(p['source_projection'](a),p['source_projection'](b));self.assertFalse(a['source_modified'])
        b['edge']='changed';self.assertNotEqual(p['source_projection'](a),p['source_projection'](b))
        self.assertNotEqual(pure()['source_projection'](a),pure()['source_projection']({**a,'source_modified':True}))

    def test_actual_eleven_node_checker_reads_only_authored_constants(self):
        p=pure('disorder_repeat');category=types.SimpleNamespace(Input='I',Output='O',Annotation='A')
        def typ(kind):return types.SimpleNamespace(getClassName=lambda:'SDType'+kind,getId=lambda:kind.lower(),getModifier=lambda:types.SimpleNamespace(name='Auto',value=0))
        class Prop:
            def __init__(self,i,k):self.i=i;self.k=k
            def getId(self):return self.i
            def getTypes(self):return [typ(self.k)]
            def getType(self):return typ(self.k)
        class SDValueString:
            text='Disorder'
            def getClassName(self):return 'SDValueString'
            def getType(self):return typ('String')
            def get(self):return self.text
        class Node:
            def __init__(self,role,definition):
                self.role=role;self.definition=definition
                ids=[port for _,dest,port in p['DISORDER_EDGES'] if dest==role]
                if role in ('get','tau','scale'):ids=['__constant__']
                self.inputs={i:Prop(i,'String' if role=='get' else 'Float') for i in ids};self.output=Prop('unique_filter_output','Float2' if role=='vector' else 'Float')
            def getIdentifier(self):return self.role
            def getDefinition(self):return types.SimpleNamespace(getId=lambda:'sbs::function::'+self.definition)
            def getProperties(self,c):return list(self.inputs.values()) if c=='I' else [self.output] if c=='O' else []
            def getPropertyFromId(self,i,c):return self.inputs.get(i) if c=='I' else self.output if i==self.output.i else None
            def getPropertyGraph(self,p):return None
            def getInputPropertyValueFromId(self,i):
                if i!='__constant__' or self.role not in ('get','tau','scale'):raise AssertionError('Evaluated function input forbidden')
                if self.role=='get':return SDValueString()
                v=6.28000021 if self.role=='tau' else .00999999978
                return dict(wrapper='SDValueFloat',bits=[struct.pack('=f',v).hex()])
            def getPropertyValue(self,*_):raise AssertionError('Evaluated output forbidden')
        nodes={r:Node(r,d) for r,d,_ in p['DISORDER_NODES']};links={(d,port):s for s,d,port in p['DISORDER_EDGES']}
        graph=types.SimpleNamespace(getClassName=lambda:'SDSBSFunctionGraph',getNodes=lambda:list(nodes.values()),getOutputNodes=lambda:[nodes['vector']],getNodeFromId=lambda i:nodes[i])
        parent=types.SimpleNamespace(getPropertyFromId=lambda *_:Prop('branchoffset','Float2'),getPropertyGraph=lambda _:graph,getIdentifier=lambda:'lowest-parent')
        p.update(Category=category,disorder_ids={r:r for r in nodes},C={'scalar':lambda v:v},A={'descriptor':lambda v:dict(id=v.i,kind=v.k)},LINKS={'incoming_sources':lambda g,i,port:[] if (i,port) not in links else [(nodes[links[(i,port)]],nodes[links[(i,port)]].output)]})
        result=p['disorder_state'](parent);self.assertEqual((result['node_count'],result['edge_count']),(11,12))
        SDValueString.text='SDisorder'
        with self.assertRaises(ValueError):p['disorder_state'](parent)
        SDValueString.text='Disorder';links[('vector','componentslast')]='x'
        with self.assertRaises(ValueError):p['disorder_state'](parent)
        links[('vector','componentslast')]='y';nodes['amount'].inputs['a'].k='Float2'
        with self.assertRaises(ValueError):p['disorder_state'](parent)

    def test_actual_source_setter_input_bits_and_no_flag_reset(self):
        p=pure('disorder_repeat');typ=dict(class_name='SDTypeFloat',id='float',modifier=dict(name='Auto',value=0))
        def scalar(v):return dict(wrapper='SDValueFloat',type=copy.deepcopy(typ),value=v,bits=[struct.pack('=f',v).hex()])
        absolute=types.SimpleNamespace(name='Absolute',value=2)
        prop=types.SimpleNamespace(getCategory=lambda:'Input',getDefaultValue=lambda:scalar(0.))
        class Node:
            value=0.;modified=False;binding=None;other='fixed'
            def getIdentifier(self):return 'own-noise-instance'
            def getPropertyFromId(self,i,c):return prop if (i,c)==('Disorder','Input') else None
            def getPropertyGraph(self,p):return self.binding
            def getPropertyConnections(self,p):return []
            def getPropertyInheritanceMethod(self,p):return absolute
            def getPropertyValue(self,p):return scalar(self.value)
            def setInputPropertyValueFromId(self,i,v):
                self.assert_id=i
                if self.value!=v:self.modified=True
                self.value=v
        node=Node();graph=types.SimpleNamespace(getNodeFromId=lambda _:node)
        p.update(Category=types.SimpleNamespace(Input='Input'),Inherit=types.SimpleNamespace(Absolute=absolute),mgr=None,ledger={},before=[],role={'ids':{'noise_instance':'own-noise-instance'}},last_source_flag=None,counts={'disorder_set':0},summary={'source_modified_observations':[],'disorder_input_observations':[]},SDValueFloat=types.SimpleNamespace(sNew=lambda v:v),C={'root':lambda *args:graph,'scalar':lambda v:v,'source_view':lambda *args:dict(source_modified=node.modified,other=node.other)},A={'descriptor':lambda _:dict(types=[copy.deepcopy(typ)])})
        for v,previous in ((0.,0.),(50.,0.),(0.,50.)):p['set_disorder'](v,previous)
        self.assertEqual(p['counts']['disorder_set'],3);self.assertEqual(node.assert_id,'Disorder');self.assertTrue(node.modified)
        self.assertEqual([r['actual'] for r in p['summary']['source_modified_observations']],[False,False,False,True,True,True])
        self.assertEqual(p['disorder_input'](0.)['current']['bits'],[struct.pack('=f',0.).hex()])
        node.value=-0.
        with self.assertRaises(ValueError):p['disorder_input'](0.)
        node.value=0.;node.binding=object()
        with self.assertRaises(ValueError):p['disorder_input'](0.)

if __name__=='__main__':unittest.main()
