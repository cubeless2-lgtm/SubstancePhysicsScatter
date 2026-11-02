import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import compat

class PlacementJitterContract(unittest.TestCase):
    def test_opt_in_preserves_existing_simulation_identity(self):
        for version,edges in ((2,'walls'),(3,'periodic')):
            base={'edges':edges,'seed':18}
            old=compat.simulation(base,version=version)
            self.assertEqual(old,compat.simulation({**base,'placement_jitter':False},version=version))
            changed=compat.simulation({**base,'placement_jitter':True},version=version)
            self.assertEqual(changed['placement_jitter'],True)
            self.assertNotEqual(compat.sha(compat.encoded(old)),compat.sha(compat.encoded(changed)))
            with self.assertRaises(ValueError):compat.simulation({**base,'placement_jitter':1},version=version)
    def test_request_schema_accepts_explicit_boolean(self):
        schema=json.loads((ROOT/'schemas/request.schema.json').read_text(encoding='utf-8'))
        simulation=schema['properties']['simulation']
        self.assertFalse(simulation['additionalProperties'])
        self.assertEqual(simulation['properties']['placement_jitter'],{'type':'boolean'})

if __name__=='__main__':unittest.main()
