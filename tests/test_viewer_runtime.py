import os,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import viewer_runtime,viewer_identity

class ViewerRuntime(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows TCP listener table')
    def test_kernel_listener_table_detects_own_listener_and_release(self):
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
            self.assertFalse(viewer_runtime.port_is_unbound(port))
        self.assertTrue(viewer_runtime.port_is_unbound(port))
    def test_health_rejects_other_checkout_or_unidentified_listener(self):
        with tempfile.TemporaryDirectory() as d:
            value=dict(application=viewer_runtime.APP,protocol_version=1,project_root_sha256=viewer_identity.root_sha256(d),authentication='none_local_identity_only',process_id=42)
            self.assertEqual(viewer_runtime.validate_health(value,d),42)
            for key,bad in (('application','other'),('project_root_sha256','0'*64),('authentication','authenticated'),('process_id',True)):
                altered=dict(value);altered[key]=bad
                with self.assertRaises(ValueError):viewer_runtime.validate_health(altered,d)
    def test_only_exact_checkout_runtime_can_launch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);paths=['local_review/.venv/Scripts/python.exe','local_review/launch.py','local_review/server.py','plugin/substance_physics_scatter/ui.py']
            for name in paths:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
            with patch.object(viewer_runtime.subprocess,'Popen') as spawn:
                viewer_runtime.launch(root,8879)
                args,kwargs=spawn.call_args;self.assertEqual(args[0],[str(root/paths[0]),str(root/paths[1]),'--source','--port','8879'])
                self.assertFalse(kwargs['shell']);self.assertEqual(kwargs['cwd'],str(root));self.assertEqual(kwargs['stdout'],viewer_runtime.subprocess.DEVNULL)
                (root/paths[2]).unlink()
                with self.assertRaisesRegex(ValueError,'not installed'):viewer_runtime.launch(root,8879)
                self.assertEqual(spawn.call_count,1)

if __name__=='__main__':unittest.main()
