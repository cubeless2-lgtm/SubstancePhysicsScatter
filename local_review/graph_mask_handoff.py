"""Viewer-side Graph mask claims; source files and SDK are never opened here."""
import copy
import hashlib
import json
from pathlib import Path
from substance_physics_scatter.core import _validated_capture
from substance_physics_scatter import maskio

LIMIT = 1024 * 1024
NAME = 'viewer-graph-mask-v1.json'
TRUST = 'client_claimed_capture_not_independently_verified'

def digest(raw): return hashlib.sha256(raw).hexdigest()

def validate(raw, png_path, mask_sha=None):
    if not isinstance(raw, bytes) or len(raw) > LIMIT: raise ValueError('Graph provenance byte limit')
    def pairs(items):
        result = {}
        for k,v in items:
            if k in result: raise ValueError('Duplicate graph provenance field')
            result[k]=v
        return result
    value=json.loads(raw,object_pairs_hook=pairs)
    if type(value) is not dict or set(value)!={'png','capture','operation_authored_payload'}:raise ValueError('Invalid Graph provenance fields')
    png=value['png']
    if type(png) is not dict or set(png)!={'sha256','decoded_u16be_sha256','width','height','bit_depth','format','bytes'}:raise ValueError('Invalid Graph PNG descriptor')
    if mask_sha is not None and png.get('sha256')!=mask_sha:raise ValueError('Graph mask snapshot differs')
    packet=copy.deepcopy(value);packet['png']['path']=str(Path(png_path))
    _validated_capture(packet)
    return value

def make_job(job, request, provenance_raw, png_path, mode):
    sha=request.get('scatter_mask',{}).get('content_hash')
    if not sha or mode not in ('captured','saved_input'):raise ValueError('Graph mask request identity differs')
    value=validate(provenance_raw,png_path,sha)
    return json.dumps(dict(version=1,job_id=job,mode=mode,mask_sha256=sha,trust=TRUST,claim=value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def verify_job(raw, candidate, jobs_root):
    if not isinstance(raw,bytes) or len(raw)>LIMIT+4096:raise ValueError('Graph job provenance byte limit')
    record=json.loads(raw)
    if type(record) is not dict or set(record)!={'version','job_id','mode','mask_sha256','trust','claim'} or record['version']!=1 or record['job_id']!=candidate['job_id'] or record['trust']!=TRUST:raise ValueError('Invalid Graph job provenance')
    request=candidate['request'];sha=request.get('scatter_mask',{}).get('content_hash')
    if sha!=record['mask_sha256'] or record['mode']!=('saved_input' if request['operation']=='bake' else 'captured'):raise ValueError('Graph provenance request differs')
    payload=json.dumps(record['claim'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    validate(payload,maskio.cache_path(jobs_root,sha),sha)
    return record
