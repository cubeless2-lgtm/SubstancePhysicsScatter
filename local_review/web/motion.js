// Actual recorded frames only. No interpolation or synthetic trajectory.
export function frameIndex(frames,time){let lo=0,hi=frames.length;while(lo<hi){const mid=(lo+hi)>>1;if(frames[mid].time<=time)lo=mid+1;else hi=mid;}return Math.max(0,lo-1);}
export async function stageMotion(result,fetchJSON){
 const envelope=result.motion;if(!envelope||envelope.status==='absent'||envelope.available===false)return null;
 const url=envelope.data_url||envelope.url;if(typeof url!=='string')throw new Error('Motion URL missing');
 const data=await fetchJSON(url);if(data.schema_version!==1||data.coordinate_system!=='RH_Z_UP'||data.units!=='meters'||!Array.isArray(data.bodies)||!Array.isArray(data.frames)||!data.frames.length||data.frames.length>3601)throw new Error('Motion header invalid');
 if(data.source_job_id!==envelope.source_job_id||data.final_poses_sha256!==envelope.final_poses_sha256||data.frames.length!==envelope.frame_count||data.bodies.length!==envelope.body_count)throw new Error('Motion envelope binding differs');
 const poses=new Map(result.poses.map(p=>[p.id,p]));if(data.bodies.length!==poses.size)throw new Error('Motion body count differs');
 const seen=new Set();for(const b of data.bodies){const p=poses.get(b.id);if(!p||seen.has(b.id)||p.asset_id!==b.asset_id||p.scale!==b.scale)throw new Error('Motion body binding differs');seen.add(b.id);}
 let previous=-1;for(const f of data.frames){if(!Number.isFinite(f.time)||f.time<0||f.time<=previous||f.positions?.length!==data.bodies.length||f.rotations?.length!==data.bodies.length)throw new Error('Motion frame shape/time invalid');previous=f.time;for(let i=0;i<data.bodies.length;i++){if(f.positions[i]?.length!==3||f.rotations[i]?.length!==4||![...f.positions[i],...f.rotations[i]].every(Number.isFinite))throw new Error('Motion pose invalid');}}
 const final=data.frames.at(-1);data.bodies.forEach((b,i)=>{const p=poses.get(b.id);if(!p.position.every((x,j)=>x===final.positions[i][j])||!p.rotation.every((x,j)=>x===final.rotations[i][j]))throw new Error('Motion final pose differs');});
 return {data,key:`${data.source_job_id}:${data.final_poses_sha256}`,duration:final.time};
}
export function motionUI(parent,apply,isResult){
 const bar=document.createElement('div');bar.className='motion-controls';
 const label=document.createElement('span'),slider=document.createElement('input');slider.type='range';slider.min='0';slider.step='any';
 const buttons={};for(const [key,text] of [['play','Play'],['pause','Pause'],['restart','Restart'],['final','최종 배치로 보기']]){const b=document.createElement('button');b.textContent=text;buttons[key]=b;bar.append(b);}bar.append(slider,label);parent.append(bar);
 let current=null,time=0,playing=false,last=null,finalView=true,suspended=false;
 function draw(){const enabled=!!current&&isResult()&&!suspended;slider.disabled=!enabled;for(const b of Object.values(buttons))b.disabled=!enabled;slider.max=String(current?.duration||0);slider.value=String(time);label.textContent=suspended?'LIVE 계산 중 · 이전 완료결과 재생 일시정지':!isResult()?'최종 베이크/원본 · 재생 없음':!current?'기록 없음 · 새 Simulate 필요':`실제 계산 프레임 재생 · ${time.toFixed(2)} / ${current.duration.toFixed(2)} s${!finalView?' · Hull 숨김':''}`;
 if(enabled)apply(finalView?null:current.data.frames[frameIndex(current.data.frames,time)],current.data.bodies);}
 buttons.play.onclick=()=>{if(current){if(time>=current.duration)time=0;finalView=false;playing=true;last=null;draw();}};
 buttons.pause.onclick=()=>{playing=false;last=null;draw();};buttons.restart.onclick=()=>{time=0;finalView=false;playing=true;last=null;draw();};buttons.final.onclick=()=>{time=current?.duration||0;playing=false;finalView=true;last=null;draw();};slider.oninput=()=>{time=Number(slider.value);playing=false;finalView=false;last=null;draw();};
 return {adopt(next){const same=current&&next&&current.key===next.key;current=next;if(!same){time=0;playing=!!next;finalView=!next;last=null;}draw();},tick(now){if(!suspended&&playing&&current&&isResult()){if(last!==null)time=Math.min(current.duration,time+(now-last)/1000);last=now;if(time>=current.duration){playing=false;finalView=true;}}else last=null;draw();},suspend(value){suspended=!!value;last=null;draw();},refresh:draw};
}
