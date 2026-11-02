"""Read-only, job-pinned map manifest for the Designer integration."""
import hashlib
import math
import re

HNC = ('height', 'normal', 'coverage')
PBR = ('basecolor', 'roughness', 'metallic', 'normal_material')
HEX = re.compile(r'^[0-9a-f]{64}$')
JOB = re.compile(r'^[0-9a-f]{32}$')


def manifest(candidate, bundle):
    job = candidate['job_id']
    if not isinstance(job, str) or not JOB.fullmatch(job):
        raise ValueError('Invalid handoff job identity')
    descriptors, original = bundle['descriptors'], bundle['original']
    roles = set(descriptors)
    if roles not in (set(HNC), set(HNC + PBR)) or set(original) != roles:
        raise ValueError('Handoff requires an entire HNC or PBR map set')
    maps = {}
    for role in HNC + PBR:
        if role not in roles:
            continue
        descriptor, raw = descriptors[role], original[role]
        digest = descriptor['byte_sha256']
        if not isinstance(digest, str) or not HEX.fullmatch(digest) or not isinstance(raw, bytes):
            raise ValueError('Invalid handoff map bytes or hash')
        if hashlib.sha256(raw).hexdigest() != digest or len(raw) != descriptor['byte_count']:
            raise ValueError('Handoff map identity changed')
        row = {'sha256': digest, 'bytes': len(raw)}
        for name in ('width', 'height', 'bit_depth', 'color_type', 'color_space', 'format'):
            row[name] = descriptor[name]
        if row['format'] != 'PNG' or type(row['width']) is not int or type(row['height']) is not int or row['width'] <= 0 or row['height'] <= 0:
            raise ValueError('Invalid handoff map format')
        if role in ('normal', 'normal_material'):
            row['normal_convention'] = descriptor['normal_convention']
            row['normal_space'] = descriptor['normal_space']
            if row['normal_convention'] not in ('OpenGL', 'DirectX') or row['normal_space'] != 'object/canonical XYZ':
                raise ValueError('Invalid handoff normal semantics')
        maps[role] = row
    bake = candidate['request']['bake']
    low, high = bake['height_min'], bake['height_max']
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high)) or high <= low:
        raise ValueError('Invalid handoff height range')
    return {'schema_version': 1, 'job_id': job, 'maps': maps, 'height_min': low, 'height_max': high}
