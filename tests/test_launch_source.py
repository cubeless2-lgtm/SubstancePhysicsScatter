import sys,unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local_review"))
from unittest.mock import patch
import launch

class LaunchSourceMode(unittest.TestCase):
    def test_source_bypasses_existing_frozen_candidate_only_when_explicit(self):
        with patch.object(sys,'argv',['launch.py','--source']),patch('uvicorn.run') as run,patch('verify_candidate.verify',side_effect=AssertionError('unexpected verification')):
            launch.main();run.assert_called_once()
    def test_default_keeps_existing_frozen_verification(self):
        with patch.object(sys,'argv',['launch.py']),patch('pathlib.Path.exists',return_value=True),patch('verify_candidate.verify',side_effect=ValueError('frozen mismatch')),patch('uvicorn.run') as run:
            with self.assertRaisesRegex(ValueError,'frozen mismatch'):launch.main()
            run.assert_not_called()
if __name__=='__main__':unittest.main()
