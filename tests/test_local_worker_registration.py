import hashlib,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from unittest.mock import patch
from substance_physics_scatter import local_workers

class LocalWorkerRegistration(unittest.TestCase):
    def test_registration_requires_fingerprint_material_and_preserves_old_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);build=root/'build';release=build/'Release';release.mkdir(parents=True)
            registry=root/'workspace/worker-registry.json'
            for mode in local_workers.MODES:
                material=('input '+mode).encode();(build/(mode+'-build-inputs.txt')).write_bytes(material)
                (build/(mode+'-build-fingerprint.txt')).write_text(hashlib.sha256(material).hexdigest(),encoding='utf-8')
                (release/('scatter_worker_'+mode+'_live.exe')).write_bytes(('binary '+mode).encode())
            with patch.object(local_workers,'BUILD',build),patch.object(local_workers,'REGISTRY',registry):
                rows=local_workers.register();self.assertEqual(len(rows),3)
                old=registry.read_bytes()
                (build/'pbr-build-inputs.txt').write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'fingerprint material mismatch'):local_workers.register()
                self.assertEqual(registry.read_bytes(),old)
                self.assertIn((rows[1]['fingerprint'],rows[1]['sha256']),local_workers.pairs('pbr'))
                self.assertNotIn((rows[1]['fingerprint'],rows[1]['sha256']),local_workers.pairs('periodic'))

if __name__=='__main__':unittest.main()
