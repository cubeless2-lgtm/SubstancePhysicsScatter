"""Root-run isolated official Designer cooker/renderer comparison. No UI edits."""
from pathlib import Path
import hashlib,json,subprocess,uuid
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
APP=Path('C:/Program Files/Adobe/Adobe Substance 3D Designer')
SOURCE=ROOT/'output/designer_bridge/pixel773-private/4984464040cb46e0b0d46b58290c0da6/source'
WORK=ROOT/'output/evidence/pixel773-cpu'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
E={'status':'running','work':str(WORK),'commands':[],'tolerance':0,'originals_modified':False}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def publish():(WORK/'report.json').write_text(json.dumps(E,indent=2)+'\n',encoding='utf8')
def run(args,label):
    E['commands'].append({'label':label,'args':[str(x) for x in args]});publish()
    p=subprocess.run([str(x) for x in args],cwd=str(WORK),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    if len(p.stdout)>2*1024*1024:raise ValueError('Combined2MiB log limit')
    (WORK/(label+'.log')).write_bytes(p.stdout);E['commands'][-1]['exit_code']=p.returncode;publish()
    if p.returncode:raise RuntimeError(label+' failed; see log')
try:
    old={str(p):sha(p) for p in (SOURCE/'Source.sbs',SOURCE/'stock/vertical_noise.sbs',SOURCE/'stock/invert.sbs')}
    for flag in (False,True):
        name='T' if flag else 'F';folder=WORK/name;folder.mkdir();(folder/'stock').mkdir()
        for file in ('vertical_noise.sbs','invert.sbs'):(folder/'stock'/file).write_bytes((SOURCE/'stock'/file).read_bytes())
        raw=(SOURCE/'Source.sbs').read_bytes();needle=b'<constantValueBool v="0"/>'
        assert raw.count(needle)==1
        if flag:raw=raw.replace(needle,b'<constantValueBool v="1"/>')
        path=folder/'Source.sbs';path.write_bytes(raw)
        run([APP/'sbscooker.exe','--inputs',path,'--output-path',folder,'--output-name','Source','--consistent-header','1','--no-optimization'],name+'-cook')
        for engine in ('sse2','d3d11'):
            output=folder/engine;output.mkdir()
            run([APP/'sbsrender.exe','render','--inputs',folder/'Source.sbsar','--engine',engine,'--cpu-count','1','--memory-budget','256','--output-path',output,'--output-format','png'],name+'-'+engine)
    comparisons={}
    for engine in ('sse2','d3d11'):
        files={name:list((WORK/name/engine).glob('*.png')) for name in ('F','T')}
        f=next(p for p in files['F'] if p.name.endswith('_native_mask.png'));t=next(p for p in files['T'] if p.name.endswith('_native_mask.png'))
        n=next(p for p in files['F'] if p.name.endswith('_reference_noise.png'))
        a=list(Image.open(f).getdata());b=list(Image.open(t).getdata());c=list(Image.open(n).getdata())
        if len(a)!=262144 or len(b)!=len(a) or len(c)!=len(a):raise ValueError('Fixed512 shape')
        comparisons[engine]={'F':str(f),'T':str(t),'N':str(n),'F_N_mismatches':sum(x!=y for x,y in zip(a,c)),
            'T_inverseF_mismatches':sum(x+y!=65535 for x,y in zip(a,b)),
            'F_sha':sha(f),'T_sha':sha(t)}
    E.update(status='OBSERVED',comparisons=comparisons,originals_preserved=all(sha(p)==h for p,h in old.items()))
except BaseException as error:
    import traceback
    E.update(status='FAILED',error=str(error),traceback=traceback.format_exc())
publish();print(json.dumps(E,ensure_ascii=False))
