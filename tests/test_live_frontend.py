"""Node/Three CPU-only state tests. No browser, WebGL context or actual worker."""
from pathlib import Path
import subprocess,unittest
ROOT=Path(__file__).resolve().parents[1]

class LiveFrontend(unittest.TestCase):
    def test_provisional_cancel_late_build_sequence_replay_and_commit(self):
        script=r"""
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {livePreview} from './web/live.js';
globalThis.document={hidden:false,body:{dataset:{}},getElementById:()=>({}),createElement:()=>({hidden:true}),head:{append(){}}};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async f=>{for(let i=0;i<80&&!f();i++)await delay(5);assert.ok(f(),'bounded mock wait');};
function value(step=0){return {status:'running',job_id:'a'.repeat(32),token:'b'.repeat(32),sequence:step+1,region:{width:2,depth:2,edges:'walls'},assets:[{asset_id:'x',geometry_url:'FIXED'}],frame:{job_id:'a'.repeat(32),nonce:'b'.repeat(32),sequence:step+1,step,time:step/120,coordinate_system:'RH_Z_UP',units:'meters',bodies:[{id:0,asset_id:'x',scale:1}],positions:[[0,0,2-step/120]],rotations:[[0,0,0,1]]}};}
function setup(build){const world=new THREE.Group(),original=new THREE.Group(),hull=new THREE.Group();world.add(original,hull);let current=value(),disposed=0,suspended=[];const renderer={domElement:{parentElement:{append(){}}},getRenderTarget:()=>null,setRenderTarget(){},compile(){},render(){}};const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();const controller=livePreview({endpoint:'FIXED',fetchJSON:async()=>current,world,renderer,camera,scene,build:build||(async()=>({object:new THREE.Mesh(new THREE.BoxGeometry(.2,.2,.2),new THREE.MeshBasicMaterial()),dispose(){disposed++;}})),getHidden:()=>[original,hull],replay:()=>({suspend:x=>suspended.push(x)}),fit(){}});return {controller,world,original,hull,suspended,set(v){current=v;},get disposed(){return disposed;}};}
// Real baseline nodes are hidden only, never cleared/disposed; playback is suspended.
const one=setup();one.controller.start();await wait(()=>one.controller.active);assert.equal(one.original.visible,false);assert.equal(one.hull.visible,false);assert.ok(one.suspended.includes(true));assert.equal(one.world.children.length,3);
one.set(value(4));await wait(()=>document.body.dataset.liveSequence==='5');one.set({...value(4),status:'cancelled',frame:null});await wait(()=>!one.controller.active);assert.equal(one.original.visible,true);assert.equal(one.hull.visible,true);assert.equal(one.world.children.length,2);assert.equal(one.disposed,1);
one.set(value(8));await delay(60);assert.equal(one.controller.active,false,'late active reply after cancellation is ignored');one.controller.dispose();
// Cancel while a source load is pending must release its own object and never show a stale scene.
let resolve,freed=0;const pending=new Promise(r=>resolve=r),two=setup(()=>pending);two.controller.start();await delay(5);two.controller.cancel();resolve({object:new THREE.Mesh(new THREE.BoxGeometry(.2,.2,.2),new THREE.MeshBasicMaterial()),dispose(){freed++;}});await delay(20);assert.equal(two.controller.active,false);assert.equal(freed,1);assert.equal(two.original.visible,true);two.controller.dispose();
// Completed notification alone cannot promote; only an explicitly verified final commit releases live.
const three=setup();three.controller.start();await wait(()=>three.controller.active);three.set({...value(4),status:'completed',frame:null});await delay(50);assert.equal(three.controller.active,true);three.controller.commit('wrong');assert.equal(three.controller.active,true);three.controller.commit('a'.repeat(32));assert.equal(three.controller.active,false);assert.equal(three.original.visible,true);three.controller.dispose();
// Same-run changed id/order/scale is rejected and the last-good group is restored.
const four=setup();four.controller.start();await wait(()=>four.controller.active);const changed=value(4);changed.frame.bodies[0].id=1;four.set(changed);await wait(()=>!four.controller.active);assert.equal(four.original.visible,true);four.controller.dispose();
let resolveDisposed,disposedAssets=0;const pendingDisposed=new Promise(r=>resolveDisposed=r),five=setup(()=>pendingDisposed);five.controller.start();await delay(5);five.controller.dispose();resolveDisposed({object:new THREE.Mesh(new THREE.BoxGeometry(.2,.2,.2),new THREE.MeshBasicMaterial()),dispose(){disposedAssets++;}});await delay(50);assert.equal(five.controller.active,false);assert.equal(disposedAssets,1);assert.equal(five.world.children.length,2);
console.log('provisional/late/cancel/sequence/identity/commit/replay preservation PASS');
"""
        p=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf8',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=ROOT/'local_review',timeout=15)
        self.assertEqual(p.returncode,0,p.stdout)

if __name__=='__main__':unittest.main()
