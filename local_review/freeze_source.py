"""Freeze UI2 source and actual runtime inputs; never executes Blender/native/browser."""
from pathlib import Path
import ast,datetime,difflib,hashlib,json,subprocess,sys,uuid,zipfile
BASE=Path(__file__).resolve().parent;ROOT=BASE.parent;EV=ROOT/'output/evidence'
UI2=BASE/'ui2_evidence/6ff7c96e9ac8453eb1060a60ff8f55ee'
BLENDER=Path('C:/Program Files/Blender Foundation/Blender 5.2')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
required={
EV/'local-review-product-contract-85f007f480234513826b5ac5e99e8856.md':'ce831ead76d301b254310ce2564117e2ca79d4bc04bc00cc535d093cc3ae0e6f',
EV/'local-review-first-slice-independent-design-review-178e497d0a8e43b6af4bfc420a59f13c.json':'6f53fddf0a6e1d4c1e6e130169cd712cf26732969ca53f399f841fa85b079239',
EV/'local-review-blender-environment-20261031.json':'30dfa0202be11fda13beccc42c4b90a9745410241ff2c9f1f40fddf76fbdd3c2',
ROOT/'plugin/substance_physics_scatter/core.py':'d4e863e7676dc42c0c2d8cdc1d4e3170e6ec45dccc917a6ce02c55cbae084548',
ROOT/'build/Release/scatter_worker.exe':'1c9f16aa6729bd8a4339116aceeada285311541a94cec4ebd25f4ea7c3a98144',
ROOT/'build-review/Release/scatter_worker_review.exe':'95dd1a2e893872c1f889cea0f2a545f497b3f5a44d79f3fb2f5c9d8e8052a572'}
required.update({EV/'local-review-UI2-first-fbx-hull-independent-postreview-5207059f788f4949a2639d3fb57c716d.json':'2b7ab0b3ef7feb97c388499f5f3814d9d3f84fd53389aeb9fe52b9e7aef25df5',EV/'local-review-UI2-first-fbx-hull-actual-20261031.json':'10ff74eb0af81990855713455cf2756df619f7a5d38a8e954119316629e59f7f'})
for path,h in required.items():
    if sha(path)!=h:raise ValueError('Approved input changed: '+str(path))
baseline=json.loads((UI2/'baseline.json').read_text(encoding='utf-8'))
workspace_now={str(p):sha(p) for p in (BASE/'workspace').rglob('*') if p.is_file()}
if workspace_now!=baseline['workspace_files']:raise ValueError('Existing workspace changed during builder preparation')
write(UI2/'protection.json',dict(workspace_file_count=len(workspace_now),all_original_paths_bytes_and_file_set_unchanged=True,current_sha256=sha(BASE/'workspace/jobs/current.json'),core_sha256=sha(ROOT/'plugin/substance_physics_scatter/core.py'),legacy_worker_sha256=sha(ROOT/'build/Release/scatter_worker.exe'),review_worker_sha256=sha(ROOT/'build-review/Release/scatter_worker_review.exe'),runtime_actual=dict(Blender=0,worker=0,browser=0)))
for p in BASE.glob('*.py'):ast.parse(p.read_text(encoding='utf-8'),str(p))
for name in ('app.js','ui2.js'):
    result=subprocess.run(['node','--check',str(BASE/'web'/name)],capture_output=True,text=True)
    if result.returncode:raise ValueError(result.stderr)
log=(UI2/'tests-final.log').read_text(encoding='utf-8')
if 'Ran 21 tests' not in log or not log.rstrip().endswith('OK'):raise ValueError('Missing final focused evidence')
# Runtime data and reviewer output are deliberately excluded from the frozen files map.
candidate_dir=BASE/'review_candidates'/uuid.uuid4().hex;candidate_dir.mkdir(parents=True)
source=[*BASE.glob('*.py'),*BASE.glob('*.md'),*BASE.glob('*.json'),BASE/'.gitignore',BASE/'requirements.in',BASE/'requirements.lock',*(BASE/'web').rglob('*'),*(BASE/'fixtures').rglob('*'),*(BASE/'licenses').glob('*')]
source=[p for p in source if p.is_file() and p.name!='active_candidate.json']
archive=candidate_dir/'source.zip'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as out:
    for p in source:out.write(p,p.relative_to(BASE).as_posix())
changes=[]
for rel in baseline['source_files']:
    before=(UI2/'before'/rel).read_text(encoding='utf-8');after=(BASE/rel).read_text(encoding='utf-8')
    changes.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='before/'+rel,tofile='after/'+rel))
for rel in ('import_contract.py','canonical_contract.py','review_contract.py','web/ui2.js','test_ui2.py'):
    changes.extend(difflib.unified_diff([], (BASE/rel).read_text(encoding='utf-8').splitlines(True),fromfile='/dev/null',tofile=rel))
(candidate_dir/'implementation.diff').write_text(''.join(changes),encoding='utf-8')
files={str(p.resolve()):sha(p) for p in source}
def pin(path):
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('Missing input '+str(path))
    files[str(path)]=sha(path)
for path in required:pin(path)
# Same installed deployment as the accepted first slice; no install or dependency changes.
for directory in (BASE/'node_modules/three',BASE/'.venv/Lib/site-packages'):
    for p in directory.rglob('*'):
        if p.is_file():pin(p)
for p in (BASE/'.venv/Scripts/python.exe',Path(sys._base_executable),Path(sys.base_prefix)/'python311.dll',BLENDER/'blender.exe',ROOT/'build-review/review-build-fingerprint.txt',ROOT/'tests/test_review_native.py'):
    pin(p)
for rel in ('io_scene_fbx/import_fbx.py','io_scene_fbx/parse_fbx.py','io_scene_fbx/fbx_utils.py','io_scene_gltf2/__init__.py'):
    pin(BLENDER/'5.2/scripts/addons_core'/rel)
pin(BLENDER/'5.2/scripts/addons_core/io_scene_gltf2/blender/exp/material/encode_image.py')
for rel in ('bpy_extras/image_utils.py','bpy_extras/node_shader_utils.py'):
    pin(BLENDER/'5.2/scripts/modules'/rel)
for name in ('__init__.py','core.py','compat.py','maskio.py','mask_source.py','graph_companion.py','fileio.py'):
    pin(ROOT/'plugin/substance_physics_scatter'/name)
for name in ('local-review-native-pbr-hull-contract-304ff64bf0e84f27bfb524c8032017e5.md','local-review-native-pbr-hull-independent-design-review-104892507c2b4322951d58180ac45cfe.json','local-review-native-artifact-revision-34859143c9c143ccb532eb4190d7358f.md','local-review-native-artifact-independent-rereview-b3292ea998da49d285e510dd16a812ac.json'):
    pin(EV/name)
for p in (EV/'local-review-native-N1/09fc40f043f540de968e6daba52196ee/candidate.json',EV/'local-review-N1-actual/a10b2292a2c74bd5848568341e538b93/independent-N1-actual-postreview-3bff6b2113ec42ffaa9660f386c73715.json',EV/'local-review-N1-actual/a10b2292a2c74bd5848568341e538b93/actual-summary.json',EV/'fbx-risk-fixtures/33ba774a09f64186a29a94268cfdaee9/A/owned-locators-only.fbx',EV/'fbx-risk-fixtures/00fd1319990547d383950c1c133c15d5/B/TEST_ONLY_hierarchy.fbx'):
    pin(p)
for p in UI2.rglob('*'):
    if p.is_file():pin(p)
validation=dict(status='PASS_PREPARATION_ONLY',focused_tests=21,command='.venv/Scripts/python.exe -B -m unittest test_local test_ui2 -q',log=str(UI2/'tests-final.log'),JS_syntax=['app.js PASS','ui2.js PASS'],Python_AST='all local .py parsed',test_scope='pure/ASGI plus fake owned subprocess only; real FBX metadata bytes read without Blender',N1_verifier_function_AST='identical to accepted test_review_native.py',warning='Starlette TestClient httpx deprecation; production does not use httpx',Blender_actual=0,worker_actual=0,browser_actual=0,active_builder_sessions=0,workspace_original_files_unchanged=len(workspace_now),limits=['UI2 Blender5.2 FBX hierarchy, embedded textures, material clones and GLB geometry require root actual','Actual UI Hull overlay, cancel/failure and before/current display require root actual','N2 PBR bake and rebake are unsupported; material manifests are preparation inputs','Single convex collider; no exact visual mesh claim','Native RSS/write hard cap and workspace relocation are unproven','All settings currently create new geometry derivative IDs; material-only same-ID render revisions remain a later step'],source_archive_sha256=sha(archive),environment=dict(python=sys.version,platform=sys.platform))
write(candidate_dir/'validation.json',validation)
for p in (archive,candidate_dir/'implementation.diff',candidate_dir/'validation.json'):pin(p)
identity=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
manifest=dict(candidate_sha256=identity,files=files,scope='UI2 OBJ/FBX canonical import, role-bound source materials and verified actual N1 hull viewer',entry=str(BASE/'launch.py'),entry_sha256=sha(BASE/'launch.py'),created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),actual_owner='root',actual_executions=dict(Blender=0,worker=0,browser=0),product_full_acceptance=False)
write(candidate_dir/'candidate.json',manifest)
for name,h in files.items():
    if sha(name)!=h:raise ValueError('Input changed during freeze: '+name)
write(BASE/'active_candidate.json',dict(path=(candidate_dir/'candidate.json').relative_to(BASE).as_posix(),manifest_sha256=sha(candidate_dir/'candidate.json')))
print(json.dumps(dict(path=str(candidate_dir),candidate_sha256=identity,manifest_sha256=sha(candidate_dir/'candidate.json'),entry_sha256=manifest['entry_sha256'],files=len(files),actual=0)))
