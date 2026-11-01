"""Root-only cook1/info1/render3. No Designer SDK, PNG conversion or float arithmetic.

EXR byte layout: https://openexr.com/en/latest/OpenEXRFileLayout.html
Only flat, uncompressed, scanline FLOAT channels are accepted; no half/lossy fallback.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,runpy,struct,sys,traceback,uuid
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'output/evidence/graph-mask-native-cli-backend-probe/1be67be0b40a407c8e8b50831a7562d4'
INSTALL=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer')
RENDER=INSTALL/'sbsrender.exe';COOK=INSTALL/'sbscooker.exe';ENGINE=INSTALL/'plugins/engines/substance_d3d11_blend.dll'
SOURCE=ROOT/'output/evidence/noise-function-free-preparation-probe/42f42ddc9f404adf8f4607c7ee02e050/runs/35d49c656f554c65999c7c0f3c238fe9/PrivateNoiseFX32.sbs'
SDK=ROOT/'output/evidence/full-stock-reference-probe/e9ef7b8f26c6453e8a3d690754ac9a13'
HELP=ROOT/'output/evidence/native-cli-help-20261031.json'
SDK_WORD_SHA={'N0':'23777bdd22a2978088a70a78237bfb1a90e99b4ba4bae06481fbe0fff8b827a3','N50':'001f9252c43a2ac0934d140289eecaa4d59047612d60792a37340881745bd19a','NR0':'d02677b5482cd69636897dba8a77d5ed3416d3160512402078623956020f071c'}
PINS={RENDER:'9b00406c858b06a8a5e8744f4a5c31b5b16b42d29e425a8ab72944991aee5214',COOK:'1ebdbe113d5016501e13565b11f3d713877576a2cd563a6bd58e49c644c922fe',ENGINE:'2e9d8fca77f45b1a96198074d4b29e0f45dd8eab346c90a3e853769edfb70c08',SOURCE:'433ed9fd6c081be2e21162e766fae406f70040c2f5d48c44cf28b7e9c655656f',HELP:'c4ff5a4760a5c6dabcd29cce33b5c6ffb4b06b586b21b65e0c52cd5cd3517bb7',SDK/'summary.json':'444ccbce1a4ff0693a1a210aedc3ca48b2f65e34105319c1492c87a08e15a298',OLD/'bounded_process.py':'22a95c2a19efbdcbf6e6d8ef3a64489c9cda8a24009033c356cd4bbd76d2a002',OLD/'probe_files.py':'0fc11cfa7f8c30db4131934176a9bd3ce05bd89be6e5a3e0481ffb98ae71a838'}
for _label,_sha in SDK_WORD_SHA.items():
    for _side in ('before','after'):PINS[SDK/(_label+'-'+_side+'.raw')]=_sha
STEPS=(('N0','0'),('N50','50'),('NR0','0'))

def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()

def exr_words(raw):
    if type(raw) is not bytes or not 8<=len(raw)<=4*1024*1024 or raw[:4]!=b'\x76\x2f\x31\x01':raise ValueError('Bounded OpenEXR file required')
    version=struct.unpack_from('<I',raw,4)[0]
    if version not in (2,2|0x400):raise ValueError('Only flat single-part scanline EXR2 accepted')
    limit=255 if version&0x400 else 31
    def string(data,pos):
        end=data.find(b'\0',pos,pos+limit+1)
        if end<0:raise ValueError('Unterminated/oversized EXR name')
        return data[pos:end].decode('ascii'),end+1
    pos=8;attributes={}
    while True:
        name,pos=string(raw,pos)
        if not name:break
        kind,pos=string(raw,pos)
        if name in attributes or not kind or pos+4>len(raw):raise ValueError('Duplicate/invalid EXR attribute')
        size=struct.unpack_from('<i',raw,pos)[0];pos+=4
        if not 0<=size<=65536 or pos+size>len(raw) or pos+size>65536:raise ValueError('EXR header bound exceeded')
        attributes[name]=(kind,raw[pos:pos+size]);pos+=size
    required={'channels':'chlist','compression':'compression','dataWindow':'box2i','displayWindow':'box2i','lineOrder':'lineOrder','pixelAspectRatio':'float','screenWindowCenter':'v2f','screenWindowWidth':'float'}
    if any(k not in attributes or attributes[k][0]!=v for k,v in required.items()):raise ValueError('Missing/incorrect EXR header type')
    if attributes['compression'][1]!=b'\0':raise ValueError('Only EXR compression none is lossless-contract supported here')
    window=struct.pack('<4i',0,0,511,255)
    if attributes['dataWindow'][1]!=window or attributes['displayWindow'][1]!=window:raise ValueError('Measured EXR window is not512x256; no resize/size retry')
    if attributes['lineOrder'][1]!=b'\0':raise ValueError('Only increasing-Y EXR scanlines accepted; no row-flip adaptation')
    channels=[];data=attributes['channels'][1];cursor=0
    while True:
        name,cursor=string(data,cursor)
        if not name:break
        if cursor+16>len(data):raise ValueError('Truncated EXR channel')
        pixel,linear,reserved,xs,ys=struct.unpack_from('<iB3sii',data,cursor);cursor+=16
        if pixel!=2 or linear not in (0,1) or reserved!=b'\0'*3 or (xs,ys)!=(1,1):raise ValueError('Exact full-resolution FLOAT32 channel required; half/UINT forbidden')
        channels.append(name)
    if cursor!=len(data) or channels!=sorted(set(channels)) or tuple(channels) not in (('Y',),('R',),('B','G','R'),('A','B','G','R')):raise ValueError('Unsupported EXR channel layout')
    header_end=pos;table_end=pos+256*8
    if table_end>len(raw):raise ValueError('Truncated EXR offset table')
    offsets=struct.unpack_from('<256Q',raw,pos);rows=[];ranges=[];expected=512*4*len(channels)
    for y,offset in enumerate(offsets):
        if not table_end<=offset<=len(raw)-8:raise ValueError('EXR scanline offset outside file')
        actual_y,size=struct.unpack_from('<ii',raw,offset)
        if actual_y!=y or size!=expected or offset+8+size>len(raw):raise ValueError('EXR row index/packed byte size differs')
        block=raw[offset+8:offset+8+size];planes={name:block[i*2048:(i+1)*2048] for i,name in enumerate(channels)};words=planes['Y'] if 'Y' in planes else planes['R']
        if any(planes[c]!=words for c in ('G','B') if c in planes):raise ValueError('EXR RGB is not bit-exact grayscale; no luminance conversion')
        if 'A' in planes and planes['A']!=struct.pack('<I',0x3f800000)*512:raise ValueError('Unexpected EXR alpha; no conversion')
        rows.append(words);ranges.append((offset,offset+8+size))
    ranges.sort();end=table_end
    for first,last in ranges:
        if first!=end:raise ValueError('Overlapping/gapped/unreferenced EXR chunks')
        end=last
    if end!=len(raw):raise ValueError('Unexpected EXR trailer')
    words=b''.join(rows)
    return words,dict(size=[512,256],channels=channels,pixel_type='FLOAT32',compression='none',row_order='EXR y0..255, no vertical flip',dtype='opaque little-endian4bytewords; no numeric conversion',word_sha256=hashlib.sha256(words).hexdigest(),file_sha256=hashlib.sha256(raw).hexdigest(),header_sha256=hashlib.sha256(raw[8:header_end]).hexdigest())

def info_mapping(text):
    graphs={};current=None
    for line in text.splitlines():
        line=line.strip()
        if not line:continue
        if line.startswith('GRAPH-URL '):
            current=line.split()[1]
            if current in graphs:raise ValueError('Duplicate cooked graph URL')
            graphs[current]=dict(inputs={},outputs=[])
        elif current and re.fullmatch(r'INPUT \S+ \S+',line):
            _,name,kind=line.split()
            if name in graphs[current]['inputs']:raise ValueError('Duplicate cooked input')
            graphs[current]['inputs'][name]=kind
        elif current and re.fullmatch(r'OUTPUT \S+',line):graphs[current]['outputs'].append(line.split()[1])
        else:raise ValueError('Unknown cooked info line')
    expected=dict(inputs={'$outputsize':'INTEGER2','$randomseed':'INTEGER1','Disorder':'FLOAT1'},outputs=['Vertical_Noise'])
    if graphs!={'pkg://vertical_noise':expected}:raise ValueError('Cooked graph/Disorder/type/size/seed/output mapping differs; render0')
    return dict(graph_url='pkg://vertical_noise',output='Vertical_Noise',inputs=expected['inputs'])

def render_argv(archive,mapping,output,label,value,cache):
    if (label,value) not in STEPS:raise ValueError('Only fixed0/50/0 render cases allowed')
    return [str(RENDER),'render','--input',str(archive),'--input-graph',mapping['graph_url'],'--input-graph-output',mapping['output'],'--set-value','Disorder@'+value,'--set-value','$outputsize@9,9','--set-value','$randomseed@0','--output-path',str(output),'--output-name',label+'.exr','--output-format','exr','--output-bit-depth','32f','--exr-format-use-float','--exr-format-compression','none','--engine',str(ENGINE),'--memory-budget','256','--cpu-count','1','--cache-dir',str(cache)]

def compare(a,b):
    if type(a) is not bytes or type(b) is not bytes or len(a)!=524288 or len(b)!=524288:raise ValueError('Exact512x256x4 raw word arrays required')
    mismatches=0;first=[]
    for pos in range(0,len(a),4):
        if a[pos:pos+4]!=b[pos:pos+4]:
            mismatches+=1
            if len(first)<8:first.append(dict(x=(pos//4)%512,y=(pos//4)//512,reference=a[pos:pos+4].hex(),candidate=b[pos:pos+4].hex()))
    return dict(exact=mismatches==0,word_mismatch_count=mismatches,first=first,reference_sha256=hashlib.sha256(a).hexdigest(),candidate_sha256=hashlib.sha256(b).hexdigest())

def preflight():
    for path,expected in PINS.items():
        if sha(path)!=expected:raise ValueError('Frozen input SHA differs: '+str(path))
    if sys.byteorder!='little':raise ValueError('SDK native raw comparison is pinned to little-endian Windows')
    text=next(x['combined_output'] for x in json.loads(HELP.read_bytes())['observations'] if x['name']=='render')
    for option in ('--exr-format-compression','--exr-format-use-float','--output-bit-depth','"32f"','--set-value'):
        if option not in text:raise ValueError('Installed CLI help capability pin differs')
    tree=ET.fromstring(SOURCE.read_bytes());graphs=tree.findall('content/graph')
    if len(graphs)!=1 or graphs[0].find('identifier').get('v')!='vertical_noise' or list(tree.find('dependencies')):raise ValueError('Fixed private Noise graph/dependencies differ')
    inputs=graphs[0].findall('paraminputs/paraminput')
    if len(inputs)!=1 or inputs[0].find('identifier').get('v')!='Disorder' or inputs[0].find('type').get('v')!='256':raise ValueError('Source exposed Disorder Float differs')
    for label in SDK_WORD_SHA:
        if (SDK/(label+'-before.raw')).stat().st_size!=524288:raise ValueError('SDK raw size differs')

def main(execute=False):
    preflight();work=ROOT/'output/evidence/cli-d3d-float-reference'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=False)
    helper=runpy.run_path(str(OLD/'bounded_process.py'));F=helper['F'];original_mkdir=F['mkdir']
    def write(path,value):
        path=F['scoped'](path,work,True)
        with F['io'](path).open('x',encoding='utf8') as stream:json.dump(value,stream,indent=2,allow_nan=False)
    helper['run'].__globals__['F']=dict(F,mkdir=lambda p:original_mkdir(p,root=work),write_json=write)
    result=dict(status='prepared_not_executed',work=str(work),process_count=0,maximum_processes=5,cook=0,info=0,render=0,timeout_each_seconds=120,log_each_bytes=4194304,shell=False,retry=0,PNG=0,SDK=0,tolerance=0,original_SDK_failure_resolved=False,product_acceptance=False,pins={str(p):s for p,s in PINS.items()},commands=[],scope='Direct private Noise kernel cook, not the SDK single-reference wrapper. Size request9,9 is not a measured shape guarantee. Actual EXR512x256 FLOAT32 words only; no resize, row flip, float normalization or tolerance. Engine/default color/export/context differences are not isolated causes; original SDK math FAIL is preserved. Fresh CLI cache directories do not establish absence of OS/GPU-driver global caches.')
    report=work/'summary.json'
    def checkpoint():
        temp=report.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2),encoding='utf8');temp.replace(report)
    def child(argv,name):
        if result['process_count']>=5:raise ValueError('Fixed5 CLI child budget exhausted')
        result['process_count']+=1;checkpoint();record=helper['run'](argv,work/'commands'/name,120);result['commands'].append(record);checkpoint()
        if record['status']!='completed' or record.get('owned_child_active') or record.get('reader_threads_alive'):raise ValueError('CLI child failed; no retry/fallback')
        return record
    checkpoint()
    try:
        inputs=work/'inputs';inputs.mkdir();source=inputs/'PrivateNoiseFX32.sbs'
        with source.open('xb') as stream:stream.write(SOURCE.read_bytes())
        if sha(source)!=PINS[SOURCE]:raise ValueError('Copied source bytes differ')
        if execute:
            cooked=work/'cooked';cooked.mkdir();result['cook']=1
            child([str(COOK),'--inputs',str(source),'--output-path',str(cooked),'--output-name','archive.sbsar','--size-limit','10','--consistent-header','1'],'cook')
            archive=F['scoped'](cooked/'archive.sbsar',work)
            if not archive.is_file() or not 0<archive.stat().st_size<=16*1024*1024:raise ValueError('Missing/oversized cooked archive')
            archive_sha=sha(archive);result['archive']=dict(path=str(archive),sha256=archive_sha);result['info']=1
            info=child([str(RENDER),'info','--input',str(archive)],'info');stdout=Path(info['logs']['stdout']['path'])
            if stdout.stat().st_size>65536:raise ValueError('Cooked info exceeds64KiB')
            mapping=info_mapping(stdout.read_text(encoding='utf8'));result['mapping']=mapping;images={};result['outputs']=[]
            for label,value in STEPS:
                if sha(archive)!=archive_sha:raise ValueError('Same archive changed before render')
                output=work/'rendered'/label;cache=work/'cache'/label;output.mkdir(parents=True);cache.mkdir(parents=True)
                result['render']+=1;child(render_argv(archive,mapping,output,label,value,cache),'render-'+label)
                path=F['scoped'](output/(label+'.exr'),work)
                if path.stat().st_size>4*1024*1024:raise ValueError('EXR artifact exceeds4MiB')
                words,metadata=exr_words(path.read_bytes());images[label]=words
                with (output/(label+'.raw')).open('xb') as stream:stream.write(words)
                result['outputs'].append(dict(label=label,exr=str(path),metadata=metadata,SDK_comparison=compare((SDK/(label+'-before.raw')).read_bytes(),words)));checkpoint()
                if sha(archive)!=archive_sha:raise ValueError('Same archive changed after render')
            result['CLI_return_comparison']=compare(images['N0'],images['NR0']);result['CLI_input_effect']=compare(images['N0'],images['N50'])
            result['math_pass']=result['CLI_return_comparison']['exact'];result['status']='CLI_float_observation_complete'
        result['source_copy_unchanged']=sha(source)==PINS[SOURCE]
    except Exception as error:result.update(status='failed',error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
    finally:
        result['frozen_inputs_unchanged']=all(sha(p)==s for p,s in PINS.items())
        if 'source' in locals() and source.exists():result['source_copy_unchanged']=sha(source)==PINS[SOURCE]
        if 'archive_sha' in locals():result['archive_unchanged']=sha(archive)==archive_sha
        if not result['frozen_inputs_unchanged'] or result.get('source_copy_unchanged') is False or result.get('archive_unchanged') is False:result['status']='failed_preservation'
        checkpoint()
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true',help='Root owner only: cook1/info1 then conditionally3 independent renders');args=parser.parse_args();REPORT=main(args.execute);print(str(REPORT))
