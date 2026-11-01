"""Read-only startup identity check. Runtime data is deliberately outside the source map."""
from pathlib import Path
import hashlib,json
BASE=Path(__file__).resolve().parent
def verify():
    pointer=json.loads((BASE/'active_candidate.json').read_text(encoding='utf-8'));path=(BASE/pointer['path']).resolve()
    if not path.is_relative_to((BASE/'review_candidates').resolve()):raise ValueError('Candidate pointer outside review archive')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=pointer['manifest_sha256']:raise ValueError('Candidate manifest changed')
    manifest=json.loads(raw)
    if hashlib.sha256(json.dumps(manifest['files'],sort_keys=True).encode()).hexdigest()!=manifest['candidate_sha256']:raise ValueError('Candidate identity changed')
    for name,expected in manifest['files'].items():
        with Path(name).open('rb') as stream:
            h=hashlib.sha256()
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        if h.hexdigest()!=expected:raise ValueError('Frozen input changed: '+name)
    return manifest['candidate_sha256']
if __name__=='__main__':print(verify())
