"""Focused periodic host routing and display reconstruction; no native execution."""
import copy,json,subprocess,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import server as s,pbr_contract as pbr
from substance_physics_scatter import compat

class PeriodicHost(unittest.TestCase):
    def test_closed_producer_dispatch_preserves_legacy_and_requires_periodic_pair(self):
        for version in (1,2):self.assertEqual(pbr.implementation_for_request(dict(physics_input_format_version=version)),'0.4.0-review.2')
        request=dict(compat.PERIODIC_VERSIONS,worker_version='0.3.0',periodic=dict(compat.PERIODIC),simulation=dict(edges='periodic'))
        self.assertEqual(pbr.implementation_for_request(request),'0.4.0-review.3')
        for field in ('physics_contract_version','bake_contract_version','pose_format_version','periodic'):
            bad=copy.deepcopy(request);bad[field]=None
            with self.subTest(field=field),self.assertRaises(ValueError):pbr.implementation_for_request(bad)
        bad=copy.deepcopy(request);bad['simulation']['edges']='walls'
        with self.assertRaises(ValueError):pbr.implementation_for_request(bad)

    def test_unavailable_periodic_rejects_before_queue_or_result_mutation(self):
        body=s.Run(assets=[dict(asset_id='a'*32,scale=1.,weight=1.)],simulation=dict(edges='periodic'),bake={})
        before=s.run_state;task=s.task
        with patch.object(s,'is_busy',return_value=False),patch.object(s,'periodic_ready',return_value=False),patch.object(s,'REVIEW_WORKER',SimpleNamespace(is_file=lambda:True)),self.assertRaisesRegex(ValueError,'검증'):
            s.queue_run(body)
        self.assertIs(s.run_state,before);self.assertIs(s.task,task)

    def test_periodic_surface_pixel_centers_and_shared_edges_without_source_pixel_edits(self):
        script=r"""import assert from 'node:assert/strict';import {heightGeometry} from './web/surface.js';import {previewPlan} from './web/ui2.js';
const codes=new Uint16Array(Array.from({length:20},(_,i)=>i*3000)),before=Array.from(codes);
const periodic={domain_axes:'XY',solver_contract:'jolt5_2_periodic_coupled_v1'};
const meta={width:4,height:5,height_min:-1,height_max:3,region_width:2,region_depth:3,periodic};
const g=heightGeometry(meta,codes,129),p=g.attributes.position.array;
for(let y=0;y<5;y++)assert.equal(p[(y*4)*3+2],p[(y*4+3)*3+2]);
for(let x=0;x<4;x++)assert.equal(p[x*3+2],p[(16+x)*3+2]);
assert.equal(p[(2*4)*3+2],Math.fround((codes[8]+codes[11])/2/65535*4));
assert.equal(p[(2*4+1)*3+2],Math.fround((codes[8]/6+codes[9]*5/6)/65535*4));
assert.deepEqual(Array.from(codes),before);assert.equal(p[0],-1);assert.equal(p[9],1);g.dispose();
const poses=[{asset_id:'a',scale:1}],costs=new Map([['a',{triangles:12,drawCalls:1}]]),result={periodic,settings:{snapshot:{simulation:{width:2,depth:3,edges:'periodic'}}}};
let plan=previewPlan('result',result,{},'3',poses,costs);assert.equal(plan.product_seamless_supported,true);assert.equal(plan.offsets.length,9);assert.equal(poses.length,1);assert.equal(plan.totals.instances,9);
assert.equal(previewPlan('result',{...result,periodic:null},{},'3',poses,costs).product_seamless_supported,false);
"""
        run=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf-8',capture_output=True,cwd=Path(__file__).resolve().parent,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
