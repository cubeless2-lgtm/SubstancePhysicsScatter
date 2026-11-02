"""Read-only job-pinned Designer handoff and concurrent-change tests."""
from pathlib import Path
import hashlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local_review'))
from fastapi.testclient import TestClient
import designer_handoff
import server


def fixture(pbr=True):
    job = 'a' * 32
    candidate = {'job_id': job, 'request': {'bake': {'height_min': 0.0, 'height_max': 2.0}}}
    roles = designer_handoff.HNC + (designer_handoff.PBR if pbr else ())
    originals = {role: (role + '-bytes').encode() for role in roles}
    descriptors = {}
    for role, raw in originals.items():
        d = dict(byte_sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw),
                 width=64, height=64, bit_depth=16 if role == 'height' else 8,
                 color_type='RGB' if role in ('normal', 'normal_material', 'basecolor') else 'GREY',
                 color_space='sRGB' if role == 'basecolor' else 'linear', format='PNG')
        if role in ('normal', 'normal_material'):
            d.update(normal_convention='DirectX', normal_space='object/canonical XYZ')
        descriptors[role] = d
    return candidate, dict(original=originals, descriptors=descriptors)


class DesignerHandoff(unittest.TestCase):
    def test_hnc_and_pbr_manifests_reject_partial_and_changed_bytes(self):
        for pbr in (False, True):
            candidate, bundle = fixture(pbr)
            result = designer_handoff.manifest(candidate, bundle)
            self.assertEqual(set(result['maps']), set(bundle['original']))
            self.assertEqual(result['maps']['normal']['normal_convention'], 'DirectX')
            self.assertEqual(result['maps']['height']['bit_depth'], 16)
            if pbr:
                self.assertEqual(result['maps']['normal_material']['normal_space'], 'object/canonical XYZ')
                del bundle['descriptors']['metallic']
                with self.assertRaises(ValueError): designer_handoff.manifest(candidate, bundle)
            bundle['original']['height'] = b'changed'
            with self.assertRaises(ValueError): designer_handoff.manifest(candidate, bundle)

    def test_http_pins_current_and_rejects_busy_or_changed_result(self):
        candidate, bundle = fixture()
        jobs = types.SimpleNamespace(current=candidate)
        with patch.object(server, 'jobs', jobs), patch.object(server, 'process', None), \
             patch.object(server, 'task', None), patch.object(server, 'runtime_latched', False), \
             patch.object(server.result_bundle, 'get', return_value=bundle), \
             TestClient(server.app, base_url=server.ORIGIN, client=('127.0.0.1', 45000)) as client:
            path = '/api/designer-handoff/' + candidate['job_id']
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['job_id'], candidate['job_id'])
            self.assertNotIn('path', str(response.json()))
            self.assertEqual(client.get('/api/designer-handoff/' + 'b'*32).status_code, 404)
            with patch.object(server, 'is_busy', return_value=True):
                self.assertEqual(client.get(path).status_code, 409)
            def change(*args):
                jobs.current = {'job_id': 'b' * 32}
                return bundle
            with patch.object(server.result_bundle, 'get', side_effect=change):
                self.assertEqual(client.get(path).status_code, 409)


if __name__ == '__main__':
    unittest.main()
