"""Local worker registrations created explicitly after a successful source build.

The file is local trust configuration, not proof of an independently reviewed build.
Existing registered identities remain valid for verifying older saved results.
"""
from pathlib import Path
import hashlib,json,os,re

ROOT=Path(__file__).resolve().parents[2]
REGISTRY=ROOT/'local_review/workspace/worker-registry.json'
BUILD=ROOT/'build-review-live-ready1'
MODES=('legacy','pbr','periodic')
HEX=re.compile(r'^[0-9a-f]{64}$')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def load():
    if not REGISTRY.exists():return []
    raw=REGISTRY.read_bytes()
    if len(raw)>65536:raise ValueError('Worker registry too large')
    doc=json.loads(raw)
    if type(doc) is not dict or set(doc)!={'version','workers'} or doc['version']!=1 or type(doc['workers']) is not list or len(doc['workers'])>128:raise ValueError('Invalid local worker registry')
    for row in doc['workers']:
        if type(row) is not dict or set(row)!={'mode','fingerprint','sha256'} or row['mode'] not in MODES or any(type(row[k]) is not str or not HEX.fullmatch(row[k]) for k in ('fingerprint','sha256')):raise ValueError('Invalid local worker registry entry')
    return doc['workers']

def register():
    rows=load()
    for mode in MODES:
        fp=(BUILD/(mode+'-build-fingerprint.txt')).read_text(encoding='utf-8').strip()
        material=BUILD/(mode+'-build-inputs.txt')
        binary=BUILD/'Release'/('scatter_worker_'+mode+'_live.exe')
        if not HEX.fullmatch(fp) or digest(material)!=fp:raise ValueError('Build fingerprint material mismatch: '+mode)
        row=dict(mode=mode,fingerprint=fp,sha256=digest(binary))
        if row not in rows:rows.append(row)
    if len(rows)>128:raise ValueError('Worker registry capacity exceeded')
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    temporary=REGISTRY.with_name('worker-registry.json.tmp')
    temporary.write_text(json.dumps(dict(version=1,workers=rows),indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,REGISTRY)
    return rows

def pairs(mode):return {(r['fingerprint'],r['sha256']) for r in load() if r['mode']==mode}
