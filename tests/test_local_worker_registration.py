import hashlib,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from unittest.mock import patch
from substance_physics_scatter import local_workers

class LocalWorkerRegistration(unittest.TestCase):
    def test_only_fixed_build_choices_are_allowed(self):
        self.assertEqual(local_workers.build_directory('standard'),local_workers.ROOT/'build-review-live-ready1')
        self.assertEqual(local_workers.build_directory('jitter'),local_workers.ROOT/'build-review-live-jitter1')
        for bad in ('../outside','', 'JITTER'):
            with self.assertRaises(ValueError):local_workers.build_directory(bad)

    def test_auto_chooses_only_registered_capable_jitter_build(self):
        with patch.dict('os.environ',{},clear=True),patch.object(local_workers,'supports_jitter',return_value=True):
            self.assertEqual(local_workers.build_directory().name,'build-review-live-jitter1')
        with patch.dict('os.environ',{},clear=True),patch.object(local_workers,'supports_jitter',return_value=False):
            self.assertEqual(local_workers.build_directory().name,'build-review-live-ready1')

    def test_jitter_capability_requires_registered_binary_and_matching_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            build=Path(tmp);(build/'Release').mkdir()
            material=('worker/main.cpp='+local_workers.digest(local_workers.ROOT/'worker/main.cpp')+'\nworker/compatibility.h='+local_workers.digest(local_workers.ROOT/'worker/compatibility.h')+'\n').encode()
            (build/'pbr-build-inputs.txt').write_bytes(material)
            fp=hashlib.sha256(material).hexdigest();(build/'pbr-build-fingerprint.txt').write_text(fp)
            binary=build/'Release/scatter_worker_pbr_live.exe';binary.write_bytes(b'known')
            with patch.object(local_workers,'pairs',return_value={(fp,hashlib.sha256(b'known').hexdigest())}):
                self.assertTrue(local_workers.supports_jitter(build,'pbr'))
                binary.write_bytes(b'tampered')
                self.assertFalse(local_workers.supports_jitter(build,'pbr'))

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
