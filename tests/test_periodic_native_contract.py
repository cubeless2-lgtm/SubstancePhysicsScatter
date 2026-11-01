"""Focused source/ABI checks only. These do not run Jolt or claim native physics PASS."""
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import compat

class NativePeriodicBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol=(ROOT/'worker/compatibility.h').read_text(encoding='utf-8')
        cls.main=(ROOT/'worker/main.cpp').read_text(encoding='utf-8')
        cls.solver=(ROOT/'worker/periodic/solver.cpp').read_text(encoding='utf-8')
        cls.cmake=(ROOT/'worker/periodic/CMakeLists.txt').read_text(encoding='utf-8')

    def test_exact_native_policy_matches_accepted_python_values(self):
        body=self.protocol.split('static json periodic_policy(){return ',1)[1].split(';}',1)[0]
        fields=dict(re.findall(r'\{"([^"]+)","([^"]+)"\}',body))
        self.assertEqual(fields,compat.PERIODIC)
        self.assertIn('physical.size()==5',self.protocol)
        self.assertIn('source.size()==result.size()',self.protocol)
        self.assertIn('input3(version)?result["edges"]=="periodic"',self.protocol)

    def test_saved3_raw_key_and_typed_source_binding_are_explicit(self):
        for text in ('protocol_key(request.at("physics_input_hash"),3)==request.at("simulation_key")',
                     'bundle.at("input_format_version").is_number_integer()',
                     'record->at("key_scheme").is_string()',
                     'Consumed Saved3 binding mismatch',
                     'Origin physics/input contract mismatch',
                     'strict?review_n1::strict_json(raw.at(hash)):json::parse(raw.at(hash))'):
            self.assertIn(text,self.protocol)
        self.assertIn('"physics_executed",false',self.protocol)
        self.assertIn('"body_count",0',self.protocol)
        self.assertIn('"steps",0',self.protocol)

    def test_no_release_manual_pose_or_probe_dispatch_for_input3(self):
        guard=self.main.index('Input3 requires a closed N3 operation; probes are forbidden')
        self.assertLess(guard,self.main.index('if(op=="hash_probe")'))
        self.assertIn('source_bundle=load_source(request,out,physical,mask)',self.main)
        self.assertNotIn('TEST_ONLY',self.main)

    def test_one_real_body_and_readonly_kernel_fp_separation(self):
        self.assertIn('real_bodies.push_back(body)',self.main)
        self.assertNotIn('CreateBody',self.solver)
        self.assertNotIn('CreateAndAddBody',self.solver)
        self.assertIn('ps::Controller solver',self.solver)
        self.assertIn('JobSystemSingleThreaded jobs(2048)',self.main)
        self.assertIn('s.mUseLargeIslandSplitter=false',self.solver)
        self.assertIn('/fp:precise',self.cmake)
        self.assertIn('COMPILE_OPTIONS "/fp:fast;/fp:except-"',self.cmake)
        self.assertNotIn('kernel.h',self.main)
        self.assertEqual(hashlib.sha256((ROOT/'experiments/periodic_solver/kernel.h').read_bytes()).hexdigest(),'ecea02b26d4ea738e29f40742a8ff72fce88ac20f705325e49723cf86649b6ff')
        self.assertEqual(hashlib.sha256((ROOT/'experiments/periodic_backend/geometry.h').read_bytes()).hexdigest(),'3f736286bded4cf1107e363e2accb9af5668b52a9fea83b3c81bb3ff4c6f9e88')

    def test_update_order_and_overflow_preconditions(self):
        body=self.main.split('constexpr int substeps=16',1)[1]
        markers=['controller->begin(dt)','physics.Update(dt','controller->finish()', 'displacement_guard(controller->displacement_demand(1.0f/60),sub,false)']
        offsets=[body.index(s) for s in markers]
        self.assertEqual(offsets,sorted(offsets))
        self.assertLess(self.solver.index('std::isfinite(needed)&&needed<=double(INT_MAX)'),self.solver.index('int(needed)'))
        self.assertIn('256*MIB)<=BUDGET',self.main)

    def test_fixed16_preserves_displacement_gate_and_failure_diagnostic(self):
        self.assertIn('displacement_guard(controller->displacement_demand(1.0f/60),-1,true)',self.main)
        self.assertIn('displacement_guard(controller->displacement_demand(1.0f/60),sub,false)',self.main)
        self.assertIn('int required=predicted?demand.predicted_required_n:demand.current_required_n',self.main)
        self.assertIn('if(required>substeps)',self.main)
        for key in ('step','sub','chosen_n','current_required_n','max_linear','max_angular_radius','gravity_speed'):
            self.assertIn('"'+key+'"',self.main)
        self.assertIn('out.current_required_n=required(out.max_speed)',self.solver)
        self.assertIn('out.predicted_required_n=required(out.max_speed+out.gravity_speed)',self.solver)
        # Independent arithmetic for the observed failure mechanism; no Jolt execution.
        dt=1/60;limit=1/64;g=9.81
        required=lambda speed:max(4,math.ceil(speed*dt/limit))
        self.assertEqual(required(3.74),4)
        self.assertEqual(required(3.74+g*dt),5)
        self.assertLessEqual(required(3+2+g*dt),16)
        self.assertEqual(required(15),16)
        self.assertEqual(required(15.01),17) # Still rejected; no displacement relaxation.
        self.assertIn('std::min(s.W,s.D)/64.',self.solver)

if __name__=='__main__':unittest.main()
