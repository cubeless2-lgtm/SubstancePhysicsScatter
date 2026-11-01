import * as THREE from 'three';
import {previewCosts,previewPlan} from './ui2.js';

// One latest frame in flight, no history, interpolation or completed-result mutation.
export function livePreview({endpoint,fetchJSON,world,renderer,camera,scene,build,getHidden,replay,fit,repeat=()=>1,onRun=()=>{}}){
 if(!document.getElementById('live-preview-style')){const style=document.createElement('link');style.id='live-preview-style';style.rel='stylesheet';style.href='/web/live.css';document.head.append(style);}
 let epoch=0,key=null,sequence=-1,active=null,timer=null,inFlight=false,stopped=false,closed=new Set(),visible=new Map();
 const note=document.createElement('div');note.className='live-note';note.hidden=true;renderer.domElement.parentElement.append(note);
 function mark(status,value=null){document.body.dataset.live=status;document.body.dataset.liveJob=value?.job_id||'';document.body.dataset.liveToken=value?.token||'';document.body.dataset.liveSequence=String(value?.sequence??'');document.body.dataset.liveTime=String(value?.frame?.time??'');}
 function release(value){if(!value)return;world.remove(value.group);value.group.clear();for(const asset of value.assets)asset.dispose?.();for(const resource of value.owned)resource.dispose();}
 function restore(){for(const [object,shown] of visible)object.visible=shown;visible.clear();replay()?.suspend(false);}
 function close(status='idle',remember=true){epoch++;if(key&&remember){closed.add(key);if(closed.size>8)closed.delete(closed.values().next().value);}release(active);active=null;restore();key=null;sequence=-1;note.hidden=true;mark(status);}
 function hide(){for(const o of getHidden().filter(Boolean))if(!visible.has(o)){visible.set(o,o.visible);o.visible=false;}replay()?.suspend(true);}
 function valid(ticket,id){return !stopped&&ticket===epoch&&key===id&&!closed.has(id);}
 function poses(value){const f=value.frame;if(!f||f.job_id!==value.job_id||f.nonce!==value.token||f.sequence!==value.sequence||!Number.isSafeInteger(f.sequence)||f.sequence<1||!Number.isFinite(f.time)||f.coordinate_system!=='RH_Z_UP'||f.units!=='meters'||f.positions?.length!==f.bodies?.length||f.rotations?.length!==f.bodies?.length)throw new Error('LIVE 프레임 소유권/형식 오류');for(let i=0;i<f.bodies.length;i++)if(f.positions[i]?.length!==3||f.rotations[i]?.length!==4||![...f.positions[i],...f.rotations[i],f.bodies[i].scale].every(Number.isFinite))throw new Error('LIVE pose 형식 오류');return f;}
 function stamp(value){note.hidden=false;const ready=value.frame?.ready_status;note.textContent=`LIVE · ${ready==='waiting'?'뷰어 준비 중 · 물리 시작 대기':ready==='timeout'?'뷰어 준비대기시간 초과 · 현재 실제 계산 관측':value.status==='baking'?'낙하 완료 · 베이크/검증 중':'실제 낙하·쌓임 계산 중'} · ${value.frame?.time.toFixed(2)||'0.00'} s · step ${value.frame?.step??0} · 베이크/지도는 이전 정상 결과`;document.body.dataset.liveReady=ready||'not_requested';mark(value.status,value);}
 async function staging(value,ticket,id){
  const assets=[],owned=[],group=new THREE.Group(),templates=new Map();let valueScene={assets,owned,group,instances:[],bodies:''};
  try{
   for(const asset of value.assets){const prepared=await build(asset);if(!valid(ticket,id)){prepared.dispose?.();release(valueScene);return null;}assets.push(prepared);templates.set(asset.asset_id,prepared.object);}
   // A cancel/new run that arrived while geometry was loading must be observed before display.
   const latest=await fetchJSON(endpoint);if(!valid(ticket,id)){release(valueScene);return null;}
   if(`${latest.job_id}:${latest.token}`!==id||!['running','baking'].includes(latest.status)||!latest.frame){release(valueScene);if(['failed','cancelled','error','idle'].includes(latest.status))close(latest.status);return null;}
   value=latest;const frame=poses(value),costs=new Map([...templates].map(([aid,object])=>[aid,previewCosts(object)]));
   const plan=previewPlan('result',{settings:{snapshot:{simulation:value.region}}},{},repeat(),frame.bodies,costs);
   const identities=JSON.stringify(frame.bodies);valueScene.bodies=identities;
   for(const offset of plan.offsets){const tile=new THREE.Group();tile.position.fromArray(offset);group.add(tile);for(const body of frame.bodies){const template=templates.get(body.asset_id);if(!template)throw new Error('LIVE source geometry 누락');const object=template.clone(true);object.scale.setScalar(body.scale);tile.add(object);valueScene.instances.push({object,id:body.id,scale:body.scale});}}
   const width=value.region.width,depth=value.region.depth;
   const geometry=new THREE.PlaneGeometry(width,depth),material=new THREE.MeshBasicMaterial({color:0x85b5ae,transparent:true,opacity:.13,side:THREE.DoubleSide,depthWrite:false}),floor=new THREE.Mesh(geometry,material);floor.position.z=-.002;group.add(floor);owned.push(geometry,material);
   const borderGeometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-width/2,-depth/2,0),new THREE.Vector3(width/2,-depth/2,0),new THREE.Vector3(width/2,depth/2,0),new THREE.Vector3(-width/2,depth/2,0)]),borderMaterial=new THREE.LineBasicMaterial({color:0x82f5cb});group.add(new THREE.LineLoop(borderGeometry,borderMaterial));owned.push(borderGeometry,borderMaterial);
   apply(valueScene,frame);
   const trial=new THREE.Scene(),w=new THREE.Group();w.rotation.x=-Math.PI/2;w.add(group);trial.add(w);for(const light of scene.children.filter(o=>o.isLight))trial.add(light.clone());const target=new THREE.WebGLRenderTarget(32,32),old=renderer.getRenderTarget();try{renderer.compile(trial,camera);renderer.setRenderTarget(target);renderer.render(trial,camera);}finally{renderer.setRenderTarget(old);target.dispose();w.remove(group);}
   if(!valid(ticket,id)){release(valueScene);return null;}return {value,scene:valueScene};
  }catch(error){release(valueScene);throw error;}
 }
 function apply(s,f){if(JSON.stringify(f.bodies)!==s.bodies)throw new Error('LIVE 실행 중 body identity 변경');const indices=new Map(f.bodies.map((b,i)=>[b.id,i]));for(const item of s.instances){const i=indices.get(item.id);if(i===undefined)throw new Error('LIVE body 누락');item.object.position.fromArray(f.positions[i]);item.object.quaternion.fromArray(f.rotations[i]);item.object.scale.setScalar(item.scale);}}
 async function update(value){
  if(stopped)return;
  const id=`${value.job_id}:${value.token}`;
  if(['idle','failed','cancelled','error'].includes(value.status)){if(active||key)close(value.status);if(value.error){note.hidden=false;note.textContent='LIVE 미리보기 중단 · 이전 정상 결과 유지: '+value.error;}return;}
  if(value.status==='completed'){if(key===id&&active){note.textContent='계산 완료 · 최종 결과 검증/전환 중 · 지도는 이전 정상 결과';mark('validating',value);}return;}
  if(!['starting','running','baking'].includes(value.status)||closed.has(id))return;
  if(id!==key){close('starting',false);key=id;sequence=-1;onRun(value);}
  const ticket=epoch;if(!value.frame){mark('starting',value);return;}poses(value);
  if(!active){const staged=await staging(value,ticket,id);if(!staged)return;if(!valid(ticket,id)){release(staged.scene);return;}value=staged.value;active=staged.scene;world.add(active.group);hide();fit(active.group);stamp(value);
   if(value.frame.ready_status==='waiting'){
    renderer.render(scene,camera);await new Promise((resolve,reject)=>{const deadline=setTimeout(()=>reject(new Error('뷰어 첫 렌더 대기시간 초과')),1000);requestAnimationFrame(()=>requestAnimationFrame(()=>{clearTimeout(deadline);resolve();}));});
    if(!valid(ticket,id))return;
    const response=await fetch(endpoint.replace(/live-state$/,'live-ready'),{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':value.session_token},body:JSON.stringify({job_id:value.job_id,token:value.token,sequence:1})});
    if(!valid(ticket,id))return;const ack=await response.json();if(!response.ok)throw new Error(ack.detail||'LIVE 준비 ACK 실패');
   }
  }
  if(!valid(ticket,id))return;
  if(value.sequence>sequence){apply(active,poses(value));sequence=value.sequence;}
  else if(value.sequence<sequence)return;
  hide();stamp(value);
 }
 async function poll(){if(inFlight||stopped)return;inFlight=true;try{if(!document.hidden)await update(await fetchJSON(endpoint));}catch(error){close('error');note.hidden=false;note.textContent='LIVE 표시 실패 · 이전 정상 결과 유지: '+(error.message||error);}finally{inFlight=false;if(!stopped)timer=setTimeout(poll,document.hidden?500:33);}}
 return {start(){stopped=false;if(timer===null)poll();},commit(job){if(active&&key?.startsWith(job+':'))close('completed');},cancel(){close('cancelled');},get active(){return !!active;},get run(){return key;},dispose(){stopped=true;clearTimeout(timer);timer=null;close();}};
}

export async function liveGeometry(asset,fetchJSON,loadGLB,colors){
 if(asset.render_url){const gltf=await loadGLB(asset.render_url),root=gltf.scene;colors(root);const object=new THREE.Group();const local=new THREE.Group();local.rotation.x=Math.PI/2;local.add(root);object.add(local);return {object,dispose(){const seen=new Set();root.traverse(o=>{if(o.geometry&&!seen.has(o.geometry)){seen.add(o.geometry);o.geometry.dispose();}for(const material of Array.isArray(o.material)?o.material:[o.material])if(material&&!seen.has(material)){seen.add(material);for(const value of Object.values(material))if(value?.isTexture&&!seen.has(value)){seen.add(value);value.dispose();}material.dispose();}});}};}
 const d=await fetchJSON(asset.geometry_url);if(d.coordinate_system!=='RH_Z_UP'||d.units!=='meters'||d.origin_shift?.some(x=>x!==0)||d.scale_applied!==1)throw new Error('LIVE native geometry 원점/축 오류');const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(d.positions.flat(),3));geometry.setIndex(d.indices);geometry.computeVertexNormals();const material=new THREE.MeshStandardMaterial({color:0xbfc6c4,roughness:.78,metalness:0}),object=new THREE.Mesh(geometry,material);return {object,dispose(){geometry.dispose();material.dispose();}};
}
