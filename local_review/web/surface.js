import * as THREE from 'three';

export function decodeHeight(buffer,meta){
  if(meta.dtype!=='uint16'||meta.byte_order!=='little'||!Number.isInteger(meta.width)||!Number.isInteger(meta.height)||meta.width<2||meta.height<2||meta.width>2048||meta.height>2048||buffer.byteLength!==meta.width*meta.height*2||meta.byte_length!==buffer.byteLength)throw new Error('Height16 shape/LE/길이가 다릅니다.');
  const view=new DataView(buffer),codes=new Uint16Array(meta.width*meta.height);for(let i=0;i<codes.length;i++)codes[i]=view.getUint16(i*2,true);return codes;
}
export function heightGeometry(meta,codes,lod=257){
  if(!(codes instanceof Uint16Array)||![129,257,513].includes(lod)||codes.length!==meta.width*meta.height||!Number.isFinite(meta.height_min)||!Number.isFinite(meta.height_max)||meta.height_max<=meta.height_min||!Number.isFinite(meta.region_width)||meta.region_width<=0||!Number.isFinite(meta.region_depth)||meta.region_depth<=0)throw new Error('Height geometry metadata가 다릅니다.');
  if(meta.periodic)return periodicHeightGeometry(meta,codes,lod);
  const cols=Math.min(meta.width,lod),rows=Math.min(meta.height,lod),positions=new Float32Array(cols*rows*3),uv=new Float32Array(cols*rows*2),indices=new Uint32Array((cols-1)*(rows-1)*6);let at=0;
  for(let row=0;row<rows;row++){const y=Math.round(row*(meta.height-1)/(rows-1));for(let col=0;col<cols;col++){const x=Math.round(col*(meta.width-1)/(cols-1)),i=row*cols+col;positions[i*3]=(x/(meta.width-1)-.5)*meta.region_width;positions[i*3+1]=(.5-y/(meta.height-1))*meta.region_depth;positions[i*3+2]=codes[y*meta.width+x]/65535*(meta.height_max-meta.height_min);uv[i*2]=x/(meta.width-1);uv[i*2+1]=1-y/(meta.height-1);
    if(row+1<rows&&col+1<cols){const a=i,b=i+1,c=i+cols,d=c+1;indices.set([a,c,b,b,c,d],at);at+=6;}
  }}
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));geometry.setIndex(new THREE.BufferAttribute(indices,1));geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.userData.heightOrigin=meta.height_min;geometry.userData.lod={cols,rows,source_width:meta.width,source_height:meta.height,sampling:'nearest source code; no 8bit quantization'};return geometry;
}
export function periodicHeightGeometry(meta,codes,lod=257){
  if(meta.periodic?.domain_axes!=='XY'||meta.periodic?.solver_contract!=='jolt5_2_periodic_coupled_v1')throw new Error('지원하지 않는 periodic 표면 규약입니다.');
  const cols=Math.min(meta.width,lod),rows=Math.min(meta.height,lod),positions=new Float32Array(cols*rows*3),uv=new Float32Array(cols*rows*2),indices=new Uint32Array((cols-1)*(rows-1)*6);let at=0;
  const wrap=(v,n)=>((v%n)+n)%n,sample=(x,y)=>codes[wrap(y,meta.height)*meta.width+wrap(x,meta.width)];
  for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){
    const u=col/(cols-1),v=row/(rows-1),x=u*meta.width-.5,y=v*meta.height-.5,ix=Math.floor(x),iy=Math.floor(y),fx=x-ix,fy=y-iy,i=row*cols+col;
    const code=(sample(ix,iy)*(1-fx)+sample(ix+1,iy)*fx)*(1-fy)+(sample(ix,iy+1)*(1-fx)+sample(ix+1,iy+1)*fx)*fy;
    positions[i*3]=(u-.5)*meta.region_width;positions[i*3+1]=(.5-v)*meta.region_depth;positions[i*3+2]=code/65535*(meta.height_max-meta.height_min);uv[i*2]=u;uv[i*2+1]=1-v;
    if(row+1<rows&&col+1<cols){const a=i,b=i+1,c=i+cols,d=c+1;indices.set([a,c,b,b,c,d],at);at+=6;}
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));geometry.setIndex(new THREE.BufferAttribute(indices,1));geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.userData.heightOrigin=meta.height_min;geometry.userData.lod={cols,rows,source_width:meta.width,source_height:meta.height,sampling:'repeat bilinear from pixel centers; source PNG unchanged'};return geometry;
}
async function digest(buffer){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))].map(v=>v.toString(16).padStart(2,'0')).join('');}
export async function loadSurface(result,lod,getJson){
  if(!result?.height_field)throw new Error('검증된 Height16가 없습니다.');const meta=await getJson(result.height_field.metadata_url),response=await fetch(result.height_field.data_url);if(!response.ok)throw new Error('Height16 data 응답 오류');const buffer=await response.arrayBuffer();if(meta.job_id!==result.job_id||meta.source_png_sha256!==result.map_descriptors.height.byte_sha256||await digest(buffer)!==meta.decoded_sha256)throw new Error('Height16 job/decoded SHA가 다릅니다.');const codes=decodeHeight(buffer,meta),geometry=heightGeometry(meta,codes,lod),textures=[];let material;
  try{
    const loader=new THREE.TextureLoader();async function texture(role,color=false){if(!result.maps[role])return null;const descriptor=result.map_descriptors[role];let url=result.maps[role];if(role==='normal'||role==='normal_material')url+=(url.includes('?')?'&':'?')+'preview=opengl';const t=await loader.loadAsync(url);textures.push(t);t.colorSpace=color?THREE.SRGBColorSpace:THREE.NoColorSpace;t.flipY=true;t.wrapS=t.wrapT=meta.periodic?THREE.RepeatWrapping:THREE.ClampToEdgeWrapping;t.minFilter=THREE.LinearFilter;t.magFilter=THREE.LinearFilter;t.generateMipmaps=false;return t;}
    const bc=await texture('basecolor',true),roughness=await texture('roughness'),metallic=await texture('metallic'),normal=await texture(result.maps.normal_material?'normal_material':'normal'),coverage=await texture('coverage');
    material=new THREE.MeshStandardMaterial({color:0xffffff,map:bc,roughness:roughness?1:.7,roughnessMap:roughness,metalness:metallic?1:0,metalnessMap:metallic,normalMap:normal,normalMapType:THREE.ObjectSpaceNormalMap,alphaMap:coverage,alphaTest:.001,transparent:true,side:THREE.DoubleSide});
    return {geometry,material,meta,lod:geometry.userData.lod,pbr:!!bc,dispose(){geometry.dispose();material.dispose();for(const t of textures)t.dispose();}};
  }catch(error){geometry.dispose();material?.dispose();for(const t of textures)t.dispose();throw error;}
}
