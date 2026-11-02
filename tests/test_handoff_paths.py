import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter.handoff_paths import owned_external


class HandoffPaths(unittest.TestCase):
    def test_owned_path_and_changed_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            package=Path(tmp)/'Scatter.sbs';graph='scatter_'+'a'*32;job='b'*32
            base=Path(tmp)/'Scatter_PhysicsScatter'/graph
            self.assertEqual(owned_external(package,graph,job,base),base/'external'/job)
            with self.assertRaises(ValueError):owned_external(package,graph,job,Path(tmp)/'other')
            with self.assertRaises(ValueError):owned_external(package,'..',job,base)

    def test_ancestor_reparse_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            package=Path(tmp)/'Scatter.sbs';graph='scatter_'+'a'*32;job='b'*32
            base=Path(tmp)/'Scatter_PhysicsScatter'/graph
            folder=base.parent;folder.mkdir()
            original=Path.lstat
            def junction(path):
                if path==folder:return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
                return original(path)
            with patch.object(Path,'lstat',junction):
                with self.assertRaisesRegex(ValueError,'reparse'):owned_external(package,graph,job,base)

if __name__=='__main__':unittest.main()
