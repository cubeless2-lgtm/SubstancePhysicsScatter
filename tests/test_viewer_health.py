"""Loopback viewer identity is read-only and explicitly not authentication."""
import os
from pathlib import Path
import sys
import unittest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'local_review'))
import server
from substance_physics_scatter import viewer_identity

class ViewerHealth(unittest.TestCase):
    def test_fixed_identity_and_loopback_boundary(self):
        with TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            response=client.get('/api/viewer-health');self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),dict(application='substance-physics-scatter-local-viewer',protocol_version=1,project_root_sha256=viewer_identity.root_sha256(ROOT),authentication='none_local_identity_only',process_id=os.getpid()))
            self.assertNotIn('session_token',response.json())
            self.assertEqual(client.get('/api/viewer-health',headers={'Host':'evil.example'}).status_code,403)
            self.assertEqual(client.get('/api/viewer-health',headers={'Origin':'https://evil.example'}).status_code,403)

if __name__=='__main__':unittest.main()
