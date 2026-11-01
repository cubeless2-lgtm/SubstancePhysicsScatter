"""Affected Node/Three data-only preview checks; no browser/WebGL/native execution."""
from pathlib import Path
import subprocess,unittest

BASE=Path(__file__).resolve().parent
class TilePreview(unittest.TestCase):
    def test_fixed_result_offsets_budget_and_hull_parent_only(self):
        script=r'''
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {previewPlan,regionSpec,previewCosts,drawHulls,disposeHulls,PREVIEW_LIMITS} from './web/ui2.js';
const pose={id:0,asset_id:'a',position:[1,2,3],rotation:[0,0,0,1],scale:1.5};
const result={settings:{snapshot:{simulation:{width:4,depth:6,edges:'walls'}}}};
const before=JSON.stringify({result,pose}),costs=new Map([['a',{triangles:12,drawCalls:4}]]);
const plan=previewPlan('result',result,{width:400,depth:900},'3',[pose],costs);
assert.equal(plan.side,3);assert.equal(plan.totals.instances,9);assert.equal(plan.totals.triangles,108);
assert.equal(new Set(plan.offsets.map(x=>JSON.stringify(x))).size,9);
assert.deepEqual(plan.offsets,[[-4,-6,0],[0,-6,0],[4,-6,0],[-4,0,0],[0,0,0],[4,0,0],[-4,6,0],[0,6,0],[4,6,0]]);
assert.deepEqual(regionSpec('result',result,{width:999,depth:998}),{width:4,depth:6,edges:'walls',valid:true});
assert.equal(previewPlan('source',result,{width:10,depth:20},'3',[pose],costs).side,1);
assert.equal(previewPlan('result',{}, {width:100,depth:100},'3',[pose],costs).region.valid,false);
const many=Array.from({length:1200},()=>pose);const fallback=previewPlan('result',result,{},'3',many,costs);assert.equal(fallback.side,1);assert.match(fallback.notice,/instances/);
for(const [metric,cost,hulls] of [
 ['triangles',{triangles:500000,drawCalls:1},null],
 ['drawCalls',{triangles:1,drawCalls:3000},null],
 ['hullFaces',{triangles:1,drawCalls:1},{hulls:[{asset_id:'a',built_scale:1.5,faces:Array.from({length:30000},()=>[0,1,2])}]}],
 ['hullTriangles',{triangles:1,drawCalls:1},{hulls:[{asset_id:'a',built_scale:1.5,faces:[Array.from({length:60000},()=>0)]}]}]
]){const p=previewPlan('result',result,{},'3',[pose],new Map([['a',cost]]),hulls);assert.equal(p.side,1);assert.match(p.notice,new RegExp(metric));}
const tooBig=previewPlan('result',result,{},'3',[pose],new Map([['a',{triangles:PREVIEW_LIMITS.triangles+1,drawCalls:1}]]));assert.equal(tooBig.side,0);assert.deepEqual(tooBig.offsets,[]);
const hull={hulls:[{asset_id:'a',built_scale:1.5,vertices:[[0,0,0],[1,0,0],[0,1,0]],faces:[[0,1,2]]}]};
const hullBefore=JSON.stringify(hull),group=drawHulls(hull,[pose],plan.offsets);assert.equal(group.children.length,9);
for(let i=0;i<9;i++){const tile=group.children[i],mesh=tile.children[0];assert.deepEqual(tile.position.toArray(),plan.offsets[i]);assert.deepEqual(mesh.position.toArray(),pose.position);assert.deepEqual(mesh.quaternion.toArray(),pose.rotation);assert.deepEqual(tile.scale.toArray(),[1,1,1]);assert.deepEqual(mesh.scale.toArray(),[1,1,1]);}
assert.equal(JSON.stringify(hull),hullBefore);assert.equal(JSON.stringify({result,pose}),before);disposeHulls(group);
const scene=new THREE.Group(),geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,1,0,0,0,1,0],3));scene.add(new THREE.Mesh(geometry,new THREE.MeshBasicMaterial()));assert.deepEqual(previewCosts(scene),{triangles:1,drawCalls:2});
console.log('PASS: frozen dimensions/9offsets/counts/source1x1/5budgetmetrics/Hull parent-only/immutable poses');
'''
        result=subprocess.run(['node','--input-type=module','-'],input=script,text=True,capture_output=True,cwd=BASE,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        source=(BASE/'web/app.js').read_text(encoding='utf-8')
        self.assertLess(source.index('plan=previewPlan('),source.index('.clone(true)'))
        self.assertIn('drawHulls(payload,lastGood.poses,plan.offsets)',source)
        self.assertIn('regionSpec(mode,lastGood',source)

if __name__=='__main__':unittest.main()
