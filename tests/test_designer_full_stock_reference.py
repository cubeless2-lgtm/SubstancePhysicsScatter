"""Pure fixed-fixture/metadata-reader tests. No Designer imports or raw reads."""
import ast,copy,runpy,types,unittest,tempfile,hashlib,traceback,re,json,struct
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/designer_full_stock_reference.py'

class FullStock(unittest.TestCase):
    def setUp(self):self.p=runpy.run_path(str(SOURCE))
    def test_accepted_raw_preparation_and_full_shared_shape(self):
        p=self.p;shape=p['xml_shape'](p['ORIGINAL'].read_bytes())
        self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['root']),(8,28,6,'1028056080'))
        self.assertEqual(sum(r['data']=='1028058599' for r in shape['nodes']),3)
        prep=p['json'].loads(p['PREPARATION'].read_bytes())
        self.assertEqual((prep['uid'],prep['prepared_sha256']),(p['KERNEL_UID'],p['ORIGINAL_SHA']))
        with self.assertRaisesRegex(ValueError,'SHA differs'):p['xml_shape'](p['ORIGINAL'].read_bytes()+b' ')
    def test_actual_metadata_reader_never_reads_kernel_values_and_rejects_foreign(self):
        p=self.p;shape=p['xml_shape'](p['ORIGINAL'].read_bytes());identity=dict(uid=p['KERNEL_UID'],path='own/path.sbs')
        class OwnerError(ValueError):pass
        class Node:
            def __init__(self,i):self.i=i
            def getIdentifier(self):return self.i
            def getDefinition(self):return types.SimpleNamespace(getId=lambda:'sbs::fxmap::paramset')
            def getProperties(self,c):return []
            def getPropertyValue(self,*_):raise AssertionError('Private evaluated property getter forbidden')
            def getPropertyGraph(self,*_):raise AssertionError('Private function traversal forbidden')
        nodes={r['node_id']:Node(r['node_id']) for r in shape['nodes']};owner=dict(identity)
        child=types.SimpleNamespace(getClassName=lambda:'SDSBSFxMapGraph',getPackage=lambda:owner,getNodes=lambda:list(nodes.values()),getOutputNodes=lambda:[nodes[shape['root']]])
        fx=types.SimpleNamespace(getReferencedResource=lambda:child,getDefinition=lambda:types.SimpleNamespace(getId=lambda:'sbs::compositing::fxmaps'))
        graph=types.SimpleNamespace(getNodeFromId=lambda _:fx,getClassName=lambda:'SDSBSCompGraph',getIdentifier=lambda:'vertical_noise',getNodes=lambda:[Node(i) for i in ('1041349787','1094664715','1094664716')])
        package=types.SimpleNamespace(getChildrenResources=lambda _: [graph],isModified=lambda:False)
        C={'item':lambda *args:dict(identity=identity)};P={'canonical':lambda *args:package,'package_id':lambda o:o};A={'OwnerError':OwnerError,'descriptor':lambda _:(_ for _ in ()).throw(AssertionError('No fake properties'))}
        category=types.SimpleNamespace(Input='I',Output='O',Annotation='A')
        def incoming(g,target,port):return [(nodes[e['source']],types.SimpleNamespace(getId=lambda:'unique_filter_output')) for e in shape['edges'] if e['target']==target and e['input']==port]
        args=(C,P,A,None,{},[],shape,category,{'incoming_sources':incoming})
        result=p['kernel_metadata'](*args);self.assertEqual(len(result['edges']),28);self.assertFalse(result['kernel_modified'])
        owner['uid']='foreign'
        with self.assertRaises(OwnerError):p['kernel_metadata'](*args)
        owner.update(identity)
        class SDKError(BaseException):pass
        def owner_error():raise SDKError('SDK owner getter poison')
        child.getPackage=owner_error
        with self.assertRaises(OwnerError):p['kernel_metadata'](*args,errors=(Exception,SDKError))
        child.getPackage=lambda:owner
        original=shape['edges'][0]['source'];shape['edges'][0]['source']='unknown'
        with self.assertRaises((ValueError,KeyError)):p['kernel_metadata'](*args)
        shape['edges'][0]['source']=original
    def test_modified_scope_schedule_and_forbidden_calls(self):
        p=self.p;state=dict(rows=[])
        for value,setter in ((False,False),(False,True),(True,True),(True,False),(True,True)):p['source_flag'](state,{'source_modified':value},'stage',setter)
        with self.assertRaises(ValueError):p['source_flag'](state,{'source_modified':False},'reset',True)
        state['last']=False
        with self.assertRaises(ValueError):p['source_flag'](state,{'source_modified':True},'compute')
        raw=dict(source_modified=False,edge={'fixed':1});changed=copy.deepcopy(raw);changed['source_modified']=True
        self.assertEqual(p['source_projection'](raw),p['source_projection'](changed));self.assertFalse(raw['source_modified'])
        self.assertEqual(p['SCHEDULE'],(('N0',0.),('N50',50.),('NR0',0.)))
        tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr in ('newPropertyGraph','newNode','setOutputNode','compute') for n in calls))
        saves=[n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='save']
        self.assertEqual([ast.unparse(n.func.value) for n in saves],['files']) # RAW.Artifacts ordinary byte storage only.
        self.assertFalse(any(isinstance(n.func,ast.Subscript) and isinstance(n.func.slice,ast.Constant) and n.func.slice.value in ('kernel_view','snapshot','scope','run','set_pattern') for n in calls))
        self.assertEqual(sum(isinstance(n.func,ast.Subscript) and isinstance(n.func.slice,ast.Constant) and n.func.slice.value=='protected_snapshot' for n in calls),2)
        self.assertEqual(sum(isinstance(n.func,ast.Subscript) and isinstance(n.func.slice,ast.Constant) and n.func.slice.value=='read_terminal' for n in calls),1)
        self.assertIn("if step:set_input(value,SCHEDULE[step-1][1])",SOURCE.read_text(encoding='utf8'))
        self.assertIn("set_input(0.,0.);source_baseline=",SOURCE.read_text(encoding='utf8'))

    def test_raw_artifacts_adapter_is_only_this_work_and_keeps_base_helper(self):
        p=self.p;F=runpy.run_path(str(p['BASE']/'probe_files.py'));RAW=runpy.run_path(str(p['BASE']/'raw_texture.py'));original_own=F['own']
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)/'own';work.mkdir();raw=b'\0'*524288;layout=RAW['K_LAYOUT']
            with self.assertRaises(ValueError):F['own'](work/'K.raw')
            adapted=dict(F,own=lambda path:p['own_raw'](path,work,F));files=RAW['Artifacts'](work,adapted)
            metadata=dict(size=[512,512],shape=[512,512],bpp=2,format=layout[3],sha256=hashlib.sha256(raw).hexdigest())
            result=files.save('K',raw,metadata,expected_layout=layout)
            self.assertEqual(Path(result['path']).read_bytes(),raw)
            for path in (work,work/'..'/'escaped.raw'):
                with self.assertRaises(ValueError):adapted['own'](path)
            self.assertIs(F['own'],original_own);self.assertEqual(list(Path(directory).glob('*.raw')),[])

    def test_baseexception_main_handler_and_cleanup_stop(self):
        p=self.p
        class SDKError(BaseException):pass
        class OwnerError(ValueError):pass
        tree=ast.parse(SOURCE.read_text(encoding='utf8'));main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        handler=next(n for n in ast.walk(main) if isinstance(n,ast.ExceptHandler) and isinstance(n.type,ast.Name) and n.type.id=='ERRORS')
        def poison():raise SDKError('SDK main poison')
        try:poison()
        except SDKError as caught:error=caught
        self.assertIsNotNone(error.__traceback__);summary={}
        exec(compile(ast.Module(body=handler.body,type_ignores=[]),str(SOURCE),'exec'),dict(error=error,A={'OwnerError':OwnerError},summary=summary,traceback=traceback))
        self.assertEqual(summary['error']['type'],'SDKError');self.assertIsNone(error.__traceback__);self.assertIsNone(error.__context__)
        P=runpy.run_path(str(p['BASE']/'ownership.py'));ledger=dict(ambiguous=False);attempts=[]
        def remove(*args):
            attempts.append(args[1]);ledger['ambiguous']=True;raise SDKError('SDK cleanup poison')
        P['cleanup'].__globals__.update(active=lambda _:[{'name':'first'},{'name':'second'}],remove=remove)
        result=P['cleanup'](None,ledger,[],(Exception,SDKError))
        self.assertEqual(len(attempts),1);self.assertEqual(result['status'],'ambiguous')
        self.assertIn("P['cleanup'](manager,ledger,before,ERRORS)",SOURCE.read_text(encoding='utf8'))

    def test_unique_scope_ids_are_27_global_numbers_and_inverse_all_bytes(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();derived,proof,scopes=p['unique_function_ids'](raw)
        self.assertEqual(p['FX_FIXTURE_MODE'],'original')
        ids=[int(n['uid']) for s in scopes for n in s['nodes']]
        self.assertEqual(sorted(ids),list(range(1146345844,1146345871)))
        restored=derived
        for scope in proof['mapping']:
            self.assertEqual(list(scope['nodes']),sorted(scope['nodes'],key=int))
            for old,new in scope['nodes'].items():restored=restored.replace(('v="'+new+'"').encode(),('v="'+old+'"').encode())
        self.assertEqual(restored,raw);self.assertTrue(proof['inverse_raw_exact'])
        self.assertEqual([(s['owner_data'],s['property'],s['owners']) for s in scopes],[(s['owner_data'],s['property'],s['owners']) for s in p['function_scopes'](raw)])
        self.assertEqual(next(s for s in scopes if s['owner_data']=='1028058599')['owners'],['1028058598','1028376909','1028376922'])
        bad=p['ET'].fromstring(raw);dynamic=next(bad.iter('dynamicValue'));next(dynamic.iter('connRef')).set('v','1')
        with self.assertRaisesRegex(ValueError,'external'):p['function_scopes'](p['ET'].tostring(bad))
        for invalid in (True,'arbitrary'):
            with self.assertRaises(ValueError):runpy.run_path(str(SOURCE),init_globals={'FX_FIXTURE_MODE':invalid})
        forward=ROOT/'tests/designer_full_stock_unique_fn_ids.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'unique_function_ids'}))])

    def test_actual_post_metadata_reads_only_ids_definitions_after_raw_loop(self):
        p=self.p;_,_,scopes=p['unique_function_ids'](p['ORIGINAL'].read_bytes());identity={'uid':p['KERNEL_UID'],'path':'own.sbs'}
        class OwnerError(ValueError):pass
        class FnNode:
            def __init__(self,n):self.n=n
            def getIdentifier(self):return self.n['uid']
            def getDefinition(self):return types.SimpleNamespace(getId=lambda:'sbs::function::'+self.n['definition'])
            def getPropertyValue(self,*_):raise AssertionError('Function output evaluation forbidden')
        def function(scope):
            nodes=[FnNode(n) for n in scope['nodes']]
            return types.SimpleNamespace(getClassName=lambda:'SDSBSFunctionGraph',getNodes=lambda:nodes,getOutputNodes=lambda:[n for n in nodes if n.getIdentifier()==scope['root']])
        bindings={(o,s['property']):function(s) for s in scopes for o in s['owners']}
        class Owner:
            def __init__(self,i):self.i=i
            def getPropertyFromId(self,i,c):return i
            def getPropertyGraph(self,prop):return bindings[(self.i,prop)]
            def getPropertyValue(self,*_):raise AssertionError('Bound current forbidden')
        child=types.SimpleNamespace(getClassName=lambda:'SDSBSFxMapGraph',getPackage=lambda:identity,getNodeFromId=lambda i:Owner(i))
        package=types.SimpleNamespace(getChildrenResources=lambda _:[types.SimpleNamespace(getNodeFromId=lambda _:types.SimpleNamespace(getReferencedResource=lambda:child))])
        args=({'item':lambda *args:dict(identity=identity)},{'canonical':lambda *args:package,'package_id':lambda o:o},{'OwnerError':OwnerError},None,{},[],scopes,types.SimpleNamespace(Input='Input'),(Exception,))
        result=p['post_function_metadata'](*args);self.assertEqual((len(result['bindings']),result['evaluated_function_getters']),(9,0))
        first=bindings[next(iter(bindings))];first.getOutputNodes=lambda:[]
        with self.assertRaises(ValueError):p['post_function_metadata'](*args)
        split_scopes=p['split_shared_data'](p['ORIGINAL'].read_bytes())[2]
        bindings.clear();bindings.update({(o,s['property']):function(s) for s in split_scopes for o in s['owners']})
        split_result=p['post_function_metadata'](*args[:6],split_scopes,*args[7:])
        self.assertEqual(len(split_result['bindings']),9)
        self.assertEqual({r['owner_data_XML'] for r in split_result['bindings']},{s['owner_data'] for s in split_scopes})
        cut_scopes=p['cut_after_first_gaussian'](p['ORIGINAL'].read_bytes())[2]
        bindings.clear();bindings.update({(o,s['property']):function(s) for s in cut_scopes for o in s['owners']})
        self.assertEqual(len(p['post_function_metadata'](*args[:6],cut_scopes,*args[7:])['bindings']),9)
        tree=ast.parse(SOURCE.read_text(encoding='utf8'));main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        post=next(n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='post_function_metadata')
        reads=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Subscript) and isinstance(n.func.slice,ast.Constant) and n.func.slice.value=='read_terminal']
        self.assertGreater(post.lineno,max(n.lineno for n in reads))
        for name in ('kernel_metadata','post_function_metadata'):
            fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('getPropertyValue','getInputPropertyValueFromId') for n in ast.walk(fn)))

    def test_split_data_exact_clones_inverse_bytes_and_closed_mode_shape(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();derived,proof,scopes=p['split_shared_data'](raw)
        shape=p['xml_shape'](derived,'split_shared_data')
        self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,28,8,9))
        self.assertEqual(proof['insertion_order'],['1028058599','1146345844','1146345845'])
        before=p['ET'].fromstring(raw);after=p['ET'].fromstring(derived)
        old=list(before.iter('paramsGraphData'));new=list(after.iter('paramsGraphData'));by_id={d.find('uid').get('v'):d for d in new}
        for data in old:self.assertEqual(p['ET'].tostring(data),p['ET'].tostring(by_id[data.find('uid').get('v')]))
        blocks=re.findall(rb'<paramsGraphData>.*?</paramsGraphData>',derived,re.S);restored=derived
        for uid in ('1146345844','1146345845'):
            clone=next(b for b in blocks if re.search(rb'^<paramsGraphData><identifier[^>]*><uid v="'+uid.encode()+rb'"',b))
            original=next(b for b in blocks if re.search(rb'^<paramsGraphData><identifier[^>]*><uid v="1028058599"',b))
            self.assertEqual(clone.replace(('v="'+uid+'"').encode(),b'v="1028058599"',1),original)
            restored=restored.replace(clone,b'',1)
            restored,count=re.subn(rb'(<data\b[^>]*\bv=")'+uid.encode()+rb'(")',rb'\g<1>1028058599\g<2>',restored)
            self.assertEqual(count,1)
        self.assertEqual(restored,raw)
        self.assertEqual([(s['owner_data'],s['owners']) for s in scopes if s['property']=='opacity' and s['owner_data'] in ('1028058599','1146345844','1146345845')],[('1028058599',['1028058598']),('1146345844',['1028376909']),('1146345845',['1028376922'])])
        old_functions=[s for s in p['function_scopes'](raw) if s['owner_data']=='1028058599']
        for scope in scopes:
            if scope['owner_data'] in ('1146345844','1146345845'):
                original=next(s for s in old_functions if s['property']==scope['property'])
                for field in ('nodes','edges','root'):self.assertEqual(scope[field],original[field])
        ids=[n['uid'] for s in scopes for n in s['nodes']];self.assertEqual(len(ids),43);self.assertLess(len(set(ids)),43)
        with self.assertRaises(ValueError):p['xml_shape'](derived)
        with self.assertRaises(ValueError):p['xml_shape'](derived+b' ','split_shared_data')
        with self.assertRaises(ValueError):p['split_shared_data'](p['unique_function_ids'](raw)[0])
        forward=ROOT/'tests/designer_full_stock_split_data.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'split_shared_data'}))])

    def test_cut_only_four_edges_preserves_unused_nodes_and_inverse_bytes(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();derived,proof,scopes=p['cut_after_first_gaussian'](raw)
        shape=p['xml_shape'](derived,'cut_after_first_gaussian');original=p['xml_shape'](raw)
        self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,24,6,5))
        restored=derived
        for row in proof['removed_connections']:
            offset=row['original_byte_offset'];restored=restored[:offset]+row['xml'].encode('utf8')+restored[offset:]
        self.assertEqual(restored,raw)
        self.assertEqual(shape['nodes'],original['nodes']);self.assertEqual(shape['function_uids'],original['function_uids'])
        old=p['ET'].fromstring(raw);new=p['ET'].fromstring(derived)
        self.assertEqual([p['ET'].tostring(n) for n in old.iter('paramsGraphData')],[p['ET'].tostring(n) for n in new.iter('paramsGraphData')])
        self.assertEqual([n.find('uid').get('v') for n in old.iter('paramsGraphNode')],[n.find('uid').get('v') for n in new.iter('paramsGraphNode')])
        removed=[e for e in original['edges'] if e not in shape['edges']]
        self.assertEqual(len(removed),4);self.assertEqual({(e['source'],e['target']) for e in removed},{('1028058598','1028055564')})
        self.assertEqual(proof['root_reachable_XML'],['1028055564','1028056080','1028056090','1028376473','1028376477'])
        self.assertEqual(proof['not_root_reachable_XML'],['1028058598','1028376909','1028376922']);self.assertFalse(proof['internal_execution_count_measured'])
        self.assertEqual(scopes,p['function_scopes'](raw))
        with self.assertRaises(ValueError):p['xml_shape'](derived)
        for transform in ('unique_function_ids','split_shared_data'):
            with self.assertRaises(ValueError):p['cut_after_first_gaussian'](p[transform](raw)[0])
        forward=ROOT/'tests/designer_full_stock_cut_first.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'cut_after_first_gaussian'}))])

    def test_second_cut_only_four_edges_inverse_bytes_and_fixed_forwarder(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();derived,proof,scopes=p['cut_after_second_gaussian'](raw)
        shape=p['xml_shape'](derived,'cut_after_second_gaussian');original=p['xml_shape'](raw)
        self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,24,6,5))
        restored=derived
        for row in proof['removed_connections']:
            offset=row['original_byte_offset'];restored=restored[:offset]+row['xml'].encode('utf8')+restored[offset:]
        self.assertEqual(restored,raw);self.assertEqual(shape['nodes'],original['nodes']);self.assertEqual(shape['function_uids'],original['function_uids']);self.assertEqual(scopes,p['function_scopes'](raw))
        before=p['ET'].fromstring(raw);after=p['ET'].fromstring(derived)
        self.assertEqual([p['ET'].tostring(n) for n in before.iter('paramsGraphData')],[p['ET'].tostring(n) for n in after.iter('paramsGraphData')])
        self.assertEqual([n.find('uid').get('v') for n in before.iter('paramsGraphNode')],[n.find('uid').get('v') for n in after.iter('paramsGraphNode')])
        removed=[e for e in original['edges'] if e not in shape['edges']]
        self.assertEqual(len(removed),4);self.assertEqual({(e['source'],e['target']) for e in removed},{('1028376909','1028058598')})
        self.assertEqual(proof['root_reachable_XML'],['1028055564','1028056080','1028056090','1028058598','1028376473','1028376477']);self.assertEqual(proof['not_root_reachable_XML'],['1028376909','1028376922']);self.assertFalse(proof['internal_execution_count_measured'])
        with self.assertRaises(ValueError):p['xml_shape'](derived)
        with self.assertRaises(ValueError):p['cut_after_second_gaussian'](derived)
        forward=ROOT/'tests/designer_full_stock_cut_second.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'cut_after_second_gaussian'}))])

    def test_third_cut_only_four_edges_inverse_bytes_and_fixed_forwarder(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();derived,proof,scopes=p['cut_after_third_gaussian'](raw)
        shape=p['xml_shape'](derived,'cut_after_third_gaussian');original=p['xml_shape'](raw)
        self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,24,6,5))
        restored=derived
        for row in proof['removed_connections']:
            offset=row['original_byte_offset'];restored=restored[:offset]+row['xml'].encode('utf8')+restored[offset:]
        self.assertEqual(restored,raw);self.assertEqual(shape['nodes'],original['nodes']);self.assertEqual(shape['function_uids'],original['function_uids']);self.assertEqual(scopes,p['function_scopes'](raw))
        before=p['ET'].fromstring(raw);after=p['ET'].fromstring(derived)
        self.assertEqual([p['ET'].tostring(n) for n in before.iter('paramsGraphData')],[p['ET'].tostring(n) for n in after.iter('paramsGraphData')])
        self.assertEqual([n.find('uid').get('v') for n in before.iter('paramsGraphNode')],[n.find('uid').get('v') for n in after.iter('paramsGraphNode')])
        removed=[e for e in original['edges'] if e not in shape['edges']]
        self.assertEqual(len(removed),4);self.assertEqual({(e['source'],e['target']) for e in removed},{('1028376922','1028376909')})
        self.assertEqual(proof['root_reachable_XML'],['1028055564','1028056080','1028056090','1028058598','1028376473','1028376477','1028376909']);self.assertEqual(proof['not_root_reachable_XML'],['1028376922']);self.assertFalse(proof['internal_execution_count_measured'])
        with self.assertRaises(ValueError):p['xml_shape'](derived)
        with self.assertRaises(ValueError):p['cut_after_third_gaussian'](derived)
        forward=ROOT/'tests/designer_full_stock_cut_third.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'cut_after_third_gaussian'}))])

    def test_last_gaussian_one_branch_keeps_output0_and_all_nodes_reachable(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();derived,proof,scopes=p['last_gaussian_one_branch'](raw)
        shape=p['xml_shape'](derived,'last_gaussian_one_branch');original=p['xml_shape'](raw)
        self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,25,6,5))
        restored=derived
        for row in proof['removed_connections']:
            offset=row['original_byte_offset'];restored=restored[:offset]+row['xml'].encode('utf8')+restored[offset:]
        self.assertEqual(restored,raw);self.assertTrue(proof['only_three_connections_removed']);self.assertEqual(shape['nodes'],original['nodes']);self.assertEqual(shape['function_uids'],original['function_uids']);self.assertEqual(scopes,p['function_scopes'](raw))
        before=p['ET'].fromstring(raw);after=p['ET'].fromstring(derived)
        self.assertEqual([p['ET'].tostring(n) for n in before.iter('paramsGraphData')],[p['ET'].tostring(n) for n in after.iter('paramsGraphData')])
        self.assertEqual([n.find('uid').get('v') for n in before.iter('paramsGraphNode')],[n.find('uid').get('v') for n in after.iter('paramsGraphNode')])
        removed=[e for e in original['edges'] if e not in shape['edges']]
        self.assertEqual({(e['source'],e['target'],e['input']) for e in removed},{('1028376922','1028376909',port) for port in ('output1','output2','output3')})
        self.assertIn(dict(source='1028376922',target='1028376909',input='output0',output='unique_filter_output'),shape['edges'])
        self.assertEqual(len(proof['root_reachable_XML']),8);self.assertEqual(proof['not_root_reachable_XML'],[]);self.assertFalse(proof['internal_execution_count_measured'])
        with self.assertRaises(ValueError):p['xml_shape'](derived)
        with self.assertRaises(ValueError):p['last_gaussian_one_branch'](derived)
        forward=ROOT/'tests/designer_full_stock_last_one_branch.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'last_gaussian_one_branch'}))])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['last_gaussian_one_branch'],forward.name)

    def test_repeat_cycles_original_bytes_5steps_11raw_and_first_failure_preserved(self):
        p=runpy.run_path(str(SOURCE),init_globals={'FX_FIXTURE_MODE':'full_stock_repeat_cycles'})
        self.assertEqual(p['SCHEDULE'],(('N0',0.),('N50',50.),('NR0',0.),('N50_2',50.),('NR0_2',0.)))
        original=p['ORIGINAL'].read_bytes();self.assertEqual(p['xml_shape'](original,'full_stock_repeat_cycles'),p['xml_shape'](original))
        RAW=runpy.run_path(str(p['BASE']/'raw_texture.py'));limits=runpy.run_path(str(p['BASE']/'observation_limits.py'));layouts=(limits['K_LAYOUT'],)+(limits['FX_LAYOUT'],)*10
        p['repeat_before_read'](0,0,layouts,limits);raws=[]
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory);F={'logical':lambda v:Path(v).resolve(),'io':lambda v:Path(v),'sha':lambda v:hashlib.sha256(Path(v).read_bytes()).hexdigest()};F['own']=lambda v:p['own_raw'](v,work,F)
            collectors=[RAW['Artifacts'](work,F),RAW['Artifacts'](work,F)]
            for index,layout in enumerate(layouts):
                used=sum(c.used for c in collectors)
                if index%2:p['repeat_before_read'](index,used,(limits['FX_LAYOUT'],)*2,limits)
                p['repeat_before_read'](index,used,(layout,),limits);data=bytes([index])*524288;raws.append(data)
                metadata=dict(size=list(layout[:2]),shape=[layout[1],layout[0]],bpp=layout[2],format=layout[3],sha256=hashlib.sha256(data).hexdigest())
                collectors[0 if index<7 else 1].save('raw'+str(index),data,metadata,expected_layout=layout)
            self.assertEqual([len(c.rows) for c in collectors],[7,4]);self.assertEqual(sum(c.used for c in collectors),5767168)
            with self.assertRaises(ValueError):p['repeat_before_read'](11,5767168,(limits['FX_LAYOUT'],),limits)
            with self.assertRaises(ValueError):p['repeat_before_read'](10,10*524288,(limits['FX_LAYOUT'],)*2,limits)
            with self.assertRaises(ValueError):p['repeat_before_read'](1,0,(limits['FX_LAYOUT'],),limits)
            with self.assertRaises(ValueError):p['repeat_before_read'](True,524288,(limits['FX_LAYOUT'],),limits)
        images=dict(N0=raws[1],N50=raws[3],NR0=raws[5],N50_2=raws[3],NR0_2=raws[5]);result=p['repeat_comparisons'](images,lambda a,b:dict(exact=a==b))
        self.assertFalse(result['comparisons']['first_return']['exact']);self.assertTrue(result['comparisons']['second_return_from_first']['exact']);self.assertTrue(result['comparisons']['same_50']['exact']);self.assertFalse(result['math_pass']);self.assertTrue(result['first_return_failed']);self.assertFalse(result['prior_failures_reclassified'])
        forward=ROOT/'tests/designer_full_stock_repeat_cycles.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'full_stock_repeat_cycles'}))])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['full_stock_repeat_cycles'],forward.name)

    def test_last_owner_baseline_none_bytes_and_actual_conditional_group_path(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();baseline,proof,functions=p['last_owner_split'](raw);control,none_proof,none_functions=p['last_owner_split'](raw,True)
        self.assertEqual(len(baseline),len(control));self.assertEqual(sum(a!=b for a,b in zip(baseline,control)),1)
        self.assertEqual([(a,b) for a,b in zip(baseline,control) if a!=b],[(ord('6'),ord('0'))])
        for data,mode in ((baseline,'last_owner_split_baseline'),(control,'last_owner_split_none')):
            shape=p['xml_shape'](data,mode);self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,28,7,7))
            blocks=re.findall(rb'<paramsGraphData>.*?</paramsGraphData>',data,re.S);clone=next(b for b in blocks if re.search(rb'^<paramsGraphData><identifier[^>]*><uid v="1146345844"',b))
            restored=data.replace(clone,b'',1);restored,count=re.subn(rb'(<data\b[^>]*\bv=")1146345844(")',rb'\g<1>1028058599\g<2>',restored)
            self.assertEqual(count,1);self.assertEqual(restored,raw)
            old=p['ET'].fromstring(raw);new=p['ET'].fromstring(data);by_id={n.find('uid').get('v'):n for n in new.iter('paramsGraphData')}
            for node in old.iter('paramsGraphData'):self.assertEqual(p['ET'].tostring(node),p['ET'].tostring(by_id[node.find('uid').get('v')]))
            self.assertEqual(next(n for n in new.iter('paramsGraphNode') if n.find('uid').get('v')=='1028376922').find('data').get('v'),'1146345844')
        self.assertTrue(proof['inverse_raw_exact']);self.assertTrue(none_proof['inverse_raw_exact']);self.assertFalse(proof['pattern_token_changed']);self.assertTrue(none_proof['pattern_token_changed'])
        self.assertEqual([(s['property'],s['nodes'],s['edges'],s['root']) for s in functions if s['owner_data']=='1146345844'],[(s['property'],s['nodes'],s['edges'],s['root']) for s in p['function_scopes'](raw) if s['owner_data']=='1028058599'])
        with self.assertRaises(ValueError):p['last_owner_split'](baseline,True)
        with self.assertRaises(ValueError):p['last_owner_split'](raw,0)
        path=ROOT/'tests/designer_full_stock_fourth_contribution.py';spec=__import__('importlib.util',fromlist=['util']).spec_from_file_location('pure_fourth_group',path);group=__import__('importlib.util',fromlist=['util']).module_from_spec(spec);spec.loader.exec_module(group)
        with tempfile.TemporaryDirectory() as directory:
            group.ROOT=Path(directory);driver_sha=hashlib.sha256(group.DRIVER.read_bytes()).hexdigest()
            good=dict(status='full_stock_reference_observation_complete',inventory_unchanged=True,user_unchanged=True,original_disks_unchanged=True,raw_count=7,raw_bytes=3670016,driver_source=dict(unchanged=True,before_sha256=driver_sha),counts=dict(compute=3,disorder_set=3,new_package=1,save=1),ledger=dict(ambiguous=False,load_calls=1,final_unload_calls=2,owned=[{'state':'removed'},{'state':'removed'}]),loaded_function_metadata={'path':'owned-metadata'},return_comparison={'exact':False})
            bad=copy.deepcopy(good);bad['user_unchanged']=False;self.assertFalse(group.next_arm(bad)['run_control'])
            for baseline_exact,expected_count in ((True,1),(False,2)):
                calls=[]
                def run_driver(filename,**kwargs):
                    mode=kwargs['init_globals']['FX_FIXTURE_MODE'];calls.append(mode);value=copy.deepcopy(good);value['return_comparison']['exact']=baseline_exact if mode=='last_owner_split_baseline' else True
                    report=Path(directory)/(str(baseline_exact)+'-'+mode+'.json');report.write_text(json.dumps(value),encoding='utf8');return {'REPORT':report}
                with patch.object(group.runpy,'run_path',side_effect=run_driver):report=group.main()
                value=json.loads(report.read_bytes());self.assertEqual(len(calls),expected_count);self.assertFalse(value['product_acceptance']);self.assertFalse(value['original_stock_failure_resolved'])
                if baseline_exact:self.assertEqual(value['status'],'baseline_exact_control_skipped')
                else:self.assertEqual(calls,['last_owner_split_baseline','last_owner_split_none']);self.assertTrue(value['baseline_math_failure_preserved']);self.assertFalse(value['arms'][0]['return_exact']);self.assertTrue(value['arms'][1]['return_exact'])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['fourth_gaussian_contribution'],path.name)

    def test_last_none_zero_offset_only_target_subtree_and_inverse(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();base,_,base_scopes=p['last_owner_split'](raw,True);derived,proof,scopes=p['last_owner_none_zero_offset'](raw)
        shape=p['xml_shape'](derived,'last_owner_none_zero_offset');self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,28,7,6))
        offset=proof['original_param_value_offset'];literal=proof['replacement_xml'].encode('utf8');original=proof['original_param_value_xml'].encode('utf8')
        self.assertEqual(derived[offset:offset+len(literal)],literal);self.assertEqual(derived[:offset]+original+derived[offset+len(literal):],base)
        self.assertEqual(proof['base_none_fixture_sha256'],p['FIXTURE_SHAS']['last_owner_split_none']);self.assertTrue(proof['target_function_definition_removed']);self.assertEqual(len(proof['removed_function_node_uids']),4);self.assertEqual(proof['literal_bits'],['00000000']*2)
        old=p['ET'].fromstring(base);new=p['ET'].fromstring(derived);old_data={d.find('uid').get('v'):d for d in old.iter('paramsGraphData')};new_data={d.find('uid').get('v'):d for d in new.iter('paramsGraphData')}
        for uid in old_data:
            if uid!='1146345844':self.assertEqual(p['ET'].tostring(old_data[uid]),p['ET'].tostring(new_data[uid]))
        param=next(q for q in new_data['1146345844'].findall('parameters/parameter') if q.find('name').get('v')=='branchoffset')
        self.assertEqual(param.find('paramValue/constantValueFloat2').get('v'),'0 0');self.assertIsNone(param.find('paramValue/dynamicValue'))
        expected=[s for s in base_scopes if not (s['owner_data']=='1146345844' and s['property']=='branchoffset')]
        self.assertEqual(scopes,expected);self.assertEqual(sum(len(s['nodes']) for s in scopes),31)
        with self.assertRaises(ValueError):p['last_owner_none_zero_offset'](base)
        forward=ROOT/'tests/designer_full_stock_last_none_zero_offset.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'last_owner_none_zero_offset'}))])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['last_owner_none_zero_offset'],forward.name)

    def test_last_none_half_opacity_only_target_subtree_and_inverse_chain(self):
        p=self.p;raw=p['ORIGINAL'].read_bytes();base,_,base_scopes=p['last_owner_none_zero_offset'](raw);derived,proof,scopes=p['last_owner_none_half_opacity'](raw)
        shape=p['xml_shape'](derived,'last_owner_none_half_opacity');self.assertEqual((len(shape['nodes']),len(shape['edges']),shape['physical_data_count'],shape['function_count']),(8,28,7,5))
        offset=proof['original_param_value_offset'];literal=proof['replacement_xml'].encode('utf8');original=proof['original_param_value_xml'].encode('utf8')
        self.assertEqual(derived[offset:offset+len(literal)],literal);restored=derived[:offset]+original+derived[offset+len(literal):];self.assertEqual(restored,base)
        prior=proof['source_zero_offset_proof'];offset=prior['original_param_value_offset'];none_base=restored[:offset]+prior['original_param_value_xml'].encode('utf8')+restored[offset+len(prior['replacement_xml'].encode('utf8')):]
        self.assertEqual(hashlib.sha256(none_base).hexdigest(),p['FIXTURE_SHAS']['last_owner_split_none']);self.assertTrue(prior['source_clone_proof']['inverse_raw_exact'])
        blocks=re.findall(rb'<paramsGraphData>.*?</paramsGraphData>',none_base,re.S);clone=next(b for b in blocks if re.search(rb'^<paramsGraphData><identifier[^>]*><uid v="1146345844"',b));restored=none_base.replace(clone,b'',1);restored,count=re.subn(rb'(<data\b[^>]*\bv=")1146345844(")',rb'\g<1>1028058599\g<2>',restored)
        self.assertEqual(count,1);self.assertEqual(restored,raw)
        old=p['ET'].fromstring(base);new=p['ET'].fromstring(derived);old_data={d.find('uid').get('v'):d for d in old.iter('paramsGraphData')};new_data={d.find('uid').get('v'):d for d in new.iter('paramsGraphData')}
        for uid in old_data:
            if uid!='1146345844':self.assertEqual(p['ET'].tostring(old_data[uid]),p['ET'].tostring(new_data[uid]))
        parameters={q.find('name').get('v'):q for q in new_data['1146345844'].findall('parameters/parameter')};self.assertEqual(parameters['opacity'].find('paramValue/constantValueFloat4').get('v'),'0.5 0.5 0.5 0.5');self.assertIsNone(parameters['opacity'].find('paramValue/dynamicValue'));self.assertEqual(parameters['branchoffset'].find('paramValue/constantValueFloat2').get('v'),'0 0')
        descriptor=next(d for d in json.loads((p['BASE']/'expected_metadata.json').read_bytes())['keeper_descriptors'] if d['id']=='opacity');self.assertEqual(descriptor['types'][0]['class_name'],'SDTypeFloat4')
        self.assertEqual(proof['literal_bits'],[struct.pack('=f',.5).hex()]*4);self.assertTrue(proof['target_function_definition_removed']);self.assertEqual(scopes,[s for s in base_scopes if s['owner_data']!='1146345844']);self.assertEqual(sum(len(s['nodes']) for s in scopes),27)
        with self.assertRaises(ValueError):p['last_owner_none_half_opacity'](base)
        forward=ROOT/'tests/designer_full_stock_last_none_half_opacity.py';calls=[]
        with patch.object(runpy,'run_path',side_effect=lambda path,**kw:calls.append((path,kw)) or {'REPORT':'not-executed'}):exec(compile(forward.read_text(encoding='utf8'),str(forward),'exec'),{'__file__':str(forward)})
        self.assertEqual(calls,[(str(SOURCE),dict(run_name='__main__',init_globals={'FX_FIXTURE_MODE':'last_owner_none_half_opacity'}))])
        router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));self.assertEqual(router['ROUTES']['last_owner_none_half_opacity'],forward.name)

if __name__=='__main__':unittest.main()
