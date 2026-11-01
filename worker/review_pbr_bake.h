// Material path shares a single highest-Z Hit with all seven map channels.
#pragma once
namespace review_n2 {
struct Hit {bool covered=false;size_t index=0;double z=-1e30;V bary,geometric;bool backface=false;};
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
struct ImageRange {V lo,hi;int64_t x0=0,x1=0,y0=0,y1=0;};
static int64_t lattice_bound(double value,bool lower){
    require(std::isfinite(value),"Periodic render image bound is nonfinite");
    value=lower?std::ceil(std::nextafter(value,-std::numeric_limits<double>::infinity())):std::floor(std::nextafter(value,std::numeric_limits<double>::infinity()));
    require(std::isfinite(value)&&std::abs(value)<=4503599627370496.,"Periodic render lattice offset exceeds exact integer range");return int64_t(value);
}
static bool intersects(const ImageRange& r,double dx,double dy,double width,double depth){
    return r.lo.x+dx<=width*.5&&r.hi.x+dx>=-width*.5&&r.lo.y+dy<=depth*.5&&r.hi.y+dy>=-depth*.5;
}
static void periodic_scene(Context& context,const std::vector<Asset>& values,const json& poses,const std::vector<size_t>& selected,double width,double depth,std::vector<Tri>& triangles,std::vector<Ref>& refs,std::vector<Quat>& rotations){
    const uint64_t plan_bytes=mask_mul(poses.size(),sizeof(ImageRange));context.peak(plan_bytes);
    std::vector<ImageRange> ranges;ranges.reserve(poses.size());uint64_t base=0,total=0;
    for(size_t pi=0;pi<poses.size();pi++){
        const auto& pose=poses[pi];const auto& p=pose.at("position");const auto& q=pose.at("rotation");double scale=pose.at("scale");Quat rotation(q[0].get<float>(),q[1].get<float>(),q[2].get<float>(),q[3].get<float>());V offset{p[0],p[1],p[2]};
        ImageRange range;range.lo={INFINITY,INFINITY,INFINITY};range.hi={-INFINITY,-INFINITY,-INFINITY};const auto& mesh=values[selected[pi]].mesh;
        for(const auto& tri:mesh.tris)for(V v:{tri.a,tri.b,tri.c}){v=from(rotation*Vec3(float(v.x*scale),float(v.y*scale),float(v.z*scale)))+offset;require(std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z),"Periodic render AABB is nonfinite");range.lo={std::min(range.lo.x,v.x),std::min(range.lo.y,v.y),std::min(range.lo.z,v.z)};range.hi={std::max(range.hi.x,v.x),std::max(range.hi.y,v.y),std::max(range.hi.z,v.z)};}
        range.x0=lattice_bound((-width*.5-range.hi.x)/width,true);range.x1=lattice_bound((width*.5-range.lo.x)/width,false);range.y0=lattice_bound((-depth*.5-range.hi.y)/depth,true);range.y1=lattice_bound((depth*.5-range.lo.y)/depth,false);
        require(range.x1>=range.x0&&range.y1>=range.y0,"Periodic render image range is empty");
        uint64_t images=mask_mul(uint64_t(range.x1-range.x0+1),uint64_t(range.y1-range.y0+1));base=mask_add(base,mesh.tris.size());total=mask_add(total,mask_mul(images,mesh.tris.size()));require(total<=2000000,"Periodic bake exceeds 2 million transformed triangle image budget");ranges.push_back(range);
    }
    const uint64_t extra=mask_add(plan_bytes,mask_mul(total-base,256+sizeof(Ref)));context.peak(extra);context.extra=mask_add(context.extra,extra);
    triangles.reserve(size_t(total));refs.reserve(size_t(total));rotations.reserve(poses.size());
    for(size_t pi=0;pi<poses.size();pi++){
        const auto& pose=poses[pi];const auto& p=pose.at("position");const auto& q=pose.at("rotation");double scale=pose.at("scale");Quat rotation(q[0].get<float>(),q[1].get<float>(),q[2].get<float>(),q[3].get<float>());rotations.push_back(rotation);V offset{p[0],p[1],p[2]};const auto& mesh=values[selected[pi]].mesh;const auto& range=ranges[pi];
        for(int64_t kx=range.x0;kx<=range.x1;kx++)for(int64_t ky=range.y0;ky<=range.y1;ky++){
            double dx=double(kx)*width,dy=double(ky)*depth;require(std::isfinite(dx)&&std::isfinite(dy),"Periodic render image translation is nonfinite");if(!intersects(range,dx,dy,width,depth))continue;
            auto transform=[&](V v){V basepoint=from(rotation*Vec3(float(v.x*scale),float(v.y*scale),float(v.z*scale)))+offset;return V{basepoint.x+dx,basepoint.y+dy,basepoint.z};};
            for(size_t ti=0;ti<mesh.tris.size();ti++){auto tri=mesh.tris[ti];tri.a=transform(tri.a);tri.b=transform(tri.b);tri.c=transform(tri.c);tri.n=from(rotation*Vec3(float(tri.n.x),float(tri.n.y),float(tri.n.z)));triangles.push_back(tri);refs.push_back({selected[pi],ti,pi,pose.at("id").get<uint64_t>(),kx,ky});}
        }
    }
}
#endif
static void hit(const BVH& scene,const std::vector<Ref>& refs,int index,double x,double y,Hit& h){
    const auto& n=scene.nodes[size_t(index)];if(x<n.lo.x||x>n.hi.x||y<n.lo.y||y>n.hi.y||n.hi.z<h.z)return;
    if(n.left>=0){hit(scene,refs,n.left,x,y,h);hit(scene,refs,n.right,x,y,h);return;}
    for(int i=n.start;i<n.end;i++){size_t ti=size_t(scene.ids[size_t(i)]);const auto& a=scene.t[ti];double den=(a.b.y-a.c.y)*(a.a.x-a.c.x)+(a.c.x-a.b.x)*(a.a.y-a.c.y);if(std::abs(den)<1e-15)continue;
        double u=((a.b.y-a.c.y)*(x-a.c.x)+(a.c.x-a.b.x)*(y-a.c.y))/den,v=((a.c.y-a.a.y)*(x-a.c.x)+(a.a.x-a.c.x)*(y-a.c.y))/den,w=1-u-v;
        if(u>=-1e-10&&v>=-1e-10&&w>=-1e-10){double z=u*a.a.z+v*a.b.z+w*a.c.z;const auto& ref=refs[ti];bool earlier=!h.covered||ref.pose_id<refs[h.index].pose_id||(ref.pose_id==refs[h.index].pose_id&&ref.tri<refs[h.index].tri);
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
            if(h.covered&&ref.pose_id==refs[h.index].pose_id&&ref.tri==refs[h.index].tri)earlier=ref.kx<refs[h.index].kx||(ref.kx==refs[h.index].kx&&ref.ky<refs[h.index].ky);
#endif
            if(z>h.z||(z==h.z&&earlier)){h.covered=true;h.index=ti;h.z=z;h.bary={u,v,w};h.geometric=a.n;h.backface=a.n.z<0;if(h.backface)h.geometric=h.geometric*-1;}
        }
    }
}
static double linear(double value){return value<=.04045?value/12.92:std::pow((value+.055)/1.055,2.4);}
static double srgb(double value){return value<=.0031308?value*12.92:1.055*std::pow(value,1/2.4)-.055;}
static int tap(int n,bool repeat){return repeat?(n%512+512)%512:std::clamp(n,0,511);}
static V texel(const Texture& t,int x,int y,const Binding& b){size_t i=(size_t(tap(y,b.repeat_v))*512+size_t(tap(x,b.repeat_u)))*4;V color{t.pixels[i]/255.,t.pixels[i+1]/255.,t.pixels[i+2]/255.};if(b.srgb)color={linear(color.x),linear(color.y),linear(color.z)};return color;}
static V sample(const Context& context,const Binding& b,UV uv){
    if(b.texture<0)return {1,1,1};double u=b.repeat_u?uv.u-std::floor(uv.u):std::clamp(uv.u,0.,1.),v=b.repeat_v?uv.v-std::floor(uv.v):std::clamp(uv.v,0.,1.);double x=u*512-.5,y=(1-v)*512-.5;int x0=int(std::floor(x)),y0=int(std::floor(y));double tx=x-x0,ty=y-y0;const auto& t=context.textures.at(size_t(b.texture));
    return (texel(t,x0,y0,b)*(1-tx)+texel(t,x0+1,y0,b)*tx)*(1-ty)+(texel(t,x0,y0+1,b)*(1-tx)+texel(t,x0+1,y0+1,b)*tx)*ty;
}
static double channel(V v,int c){require(c>=0&&c<=2,"PBR scalar channel missing");return c==0?v.x:c==1?v.y:v.z;}
struct Surface {V color,normal;double roughness=1,metallic=0;};
static Surface surface(const Context& context,const Ref& ref,const Hit& h,const Quat& rotation){
    const auto& data=context.assets.at(ref.asset);const auto& corner=data.corners.at(ref.tri);const auto& material=data.materials.at(corner.material);
    V weights{std::max(0.,h.bary.x),std::max(0.,h.bary.y),std::max(0.,h.bary.z)};weights=weights*(1/(weights.x+weights.y+weights.z));std::array<double,3> w{weights.x,weights.y,weights.z};UV uv;V normal{},tangent{};
    for(size_t k=0;k<3;k++){uv.u+=w[k]*corner.uv[k].u;uv.v+=w[k]*corner.uv[k].v;normal=normal+corner.normal[k]*w[k];tangent=tangent+corner.tangent[k]*w[k];}
    require(std::isfinite(uv.u)&&std::isfinite(uv.v),"PBR interpolated UV not finite");Surface value;auto color=sample(context,material.bc,uv);value.color={color.x*material.color.x,color.y*material.color.y,color.z*material.color.z};
    value.roughness=material.roughness*(material.r.texture<0?1:channel(sample(context,material.r,uv),material.r.channel));value.metallic=material.metallic*(material.m.texture<0?1:channel(sample(context,material.m,uv),material.m.channel));value.normal=h.geometric;
    if(material.n.texture>=0){normal=unit(normal);tangent=unit(tangent-normal*dot(tangent,normal));normal=unit(from(rotation*Vec3(float(normal.x),float(normal.y),float(normal.z))));tangent=unit(from(rotation*Vec3(float(tangent.x),float(tangent.y),float(tangent.z))));tangent=unit(tangent-normal*dot(tangent,normal));
        // Backface: keep T; flip N and therefore B. Geometry and material frame face the same ray.
        if(h.backface)normal=normal*-1;V bitangent=cross(normal,tangent)*corner.handedness;auto sampled=sample(context,material.n,uv);V n{sampled.x*2-1,sampled.y*2-1,sampled.z*2-1};if(material.n.dx)n.y=-n.y;n=unit(n);value.normal=unit(tangent*n.x+bitangent*n.y+normal*n.z);
    }return value;
}
static unsigned char quantize(double value){return static_cast<unsigned char>(std::round(std::clamp(value,0.,1.)*255));}
static void material_png(Context& context,const char* name,const std::vector<unsigned char>& data,unsigned res,LodePNGColorType type){
    lodepng::State state;state.info_raw.colortype=type;state.info_raw.bitdepth=8;state.info_png.color.colortype=type;state.info_png.color.bitdepth=8;state.encoder.auto_convert=0;std::vector<unsigned char> png;unsigned error=lodepng::encode(png,data,res,res,state);require(!error,"PBR PNG encode failed");review_n1::immutable(context.out/name,std::string(reinterpret_cast<const char*>(png.data()),png.size()),context);
}
static json bake(Context& context,const std::vector<Asset>& values,json& poses,const json& sim,const json& b,const fs::path& out,bool allow_empty){
    unsigned res=unsigned(number(b,"resolution",512,16,8192));double width=number(sim,"width",4,.1,1000),depth=number(sim,"depth",4,.1,1000),minz=number(b,"height_min",0,-1000,1000),maxz=number(b,"height_max",2,-1000,1000);require(maxz>minz,"height_max must exceed height_min");int aa=int(number(b,"samples",1,1,4));auto convention=b.value("normal",std::string("DirectX"));require(convention=="DirectX"||convention=="OpenGL","PBR output normal convention");
    json calculation=poses;auto selected=validate_poses(values,calculation,allow_empty);require(mask_add(mask_geometry_work(values,selected,b),context.reserve())<=BUDGET,"PBR actual pose/work budget before BVH");
    size_t total=0;for(auto a:selected)total+=values[a].mesh.tris.size();std::vector<Tri> triangles;std::vector<Ref> refs;std::vector<Quat> rotations;
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
    if(sim.value("edges",std::string("walls"))=="periodic")periodic_scene(context,values,calculation,selected,width,depth,triangles,refs,rotations);
    else
#endif
    {triangles.reserve(total);refs.reserve(total);rotations.reserve(calculation.size());
    for(size_t pi=0;pi<calculation.size();pi++){const auto& pose=calculation[pi];const auto& p=pose.at("position");const auto& q=pose.at("rotation");double scale=pose.at("scale");Quat rotation(q[0].get<float>(),q[1].get<float>(),q[2].get<float>(),q[3].get<float>());rotations.push_back(rotation);V offset{p[0],p[1],p[2]};auto transform=[&](V v){return from(rotation*Vec3(float(v.x*scale),float(v.y*scale),float(v.z*scale)))+offset;};const auto& mesh=values[selected[pi]].mesh;
        for(size_t ti=0;ti<mesh.tris.size();ti++){auto tri=mesh.tris[ti];tri.a=transform(tri.a);tri.b=transform(tri.b);tri.c=transform(tri.c);tri.n=from(rotation*Vec3(float(tri.n.x),float(tri.n.y),float(tri.n.z)));triangles.push_back(tri);refs.push_back({selected[pi],ti,pi,pose.at("id").get<uint64_t>()});}
    }}
    std::unique_ptr<BVH> scene;if(!triangles.empty())scene=std::make_unique<BVH>(std::move(triangles));size_t pixels=size_t(res)*res;std::vector<unsigned char> heights(pixels*2),normals(pixels*3),coverage(pixels),bc(pixels*3),roughness(pixels),metallic(pixels),normal_material(pixels*3);uint64_t clipped=0,queries=0,covered_samples=0;json diagnostic=json::array();
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
    std::set<std::tuple<uint64_t,size_t,int64_t,int64_t>> reported;
#else
    std::set<std::pair<uint64_t,size_t>> reported;
#endif
    for(unsigned row=0;row<res;row++){
        for(unsigned col=0;col<res;col++){double height=0,r=0,m=0;V geometric{},color{},matnormal{};int covered=0;
            for(int sy=0;sy<aa;sy++)for(int sx=0;sx<aa;sx++){double x=((col+(sx+.5)/aa)/res-.5)*width,y=(.5-(row+(sy+.5)/aa)/res)*depth;Hit top;++queries;if(scene)hit(*scene,refs,0,x,y,top);
                if(top.covered){const auto& ref=refs[top.index];auto value=surface(context,ref,top,rotations[ref.pose]);height+=top.z;geometric=geometric+top.geometric;color=color+value.color;r+=value.roughness;m+=value.metallic;matnormal=matnormal+value.normal;++covered;++covered_samples;if(top.z<minz||top.z>maxz)++clipped;
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
                    if(diagnostic.size()<64&&reported.insert({ref.pose_id,ref.tri,ref.kx,ref.ky}).second){diagnostic.push_back({{"row",row},{"col",col},{"sx",sx},{"sy",sy},{"pose_id",ref.pose_id},{"tri_id",ref.tri},{"asset_id",values[ref.asset].id},{"material_id",context.assets[ref.asset].materials[context.assets[ref.asset].corners[ref.tri].material].id},{"lattice_offset",{ref.kx,ref.ky}}});}
#else
                    if(diagnostic.size()<64&&reported.insert({ref.pose_id,ref.tri}).second)diagnostic.push_back({{"row",row},{"col",col},{"sx",sx},{"sy",sy},{"pose_id",ref.pose_id},{"tri_id",ref.tri},{"asset_id",values[ref.asset].id},{"material_id",context.assets[ref.asset].materials[context.assets[ref.asset].corners[ref.tri].material].id}});
#endif
                }else{height+=minz;geometric=geometric+V{0,0,1};}
            }
            size_t pixel=size_t(row)*res+col;uint16_t h=uint16_t(std::round(std::clamp((height/(aa*aa)-minz)/(maxz-minz),0.,1.)*65535));heights[pixel*2]=static_cast<unsigned char>(h>>8);heights[pixel*2+1]=static_cast<unsigned char>(h&255);coverage[pixel]=quantize(double(covered)/(aa*aa));
            if(covered){color=color*(1./covered);r/=covered;m/=covered;matnormal=unit(matnormal);}else{color={0,0,0};r=1;m=0;matnormal={0,0,1};}
            V n=norm(geometric);if(convention=="DirectX"){n.y=-n.y;matnormal.y=-matnormal.y;}std::array<double,3> gn{n.x,n.y,n.z},mn{matnormal.x,matnormal.y,matnormal.z};for(size_t k=0;k<3;k++){normals[pixel*3+k]=quantize(gn[k]*.5+.5);normal_material[pixel*3+k]=quantize(mn[k]*.5+.5);}bc[pixel*3]=quantize(srgb(color.x));bc[pixel*3+1]=quantize(srgb(color.y));bc[pixel*3+2]=quantize(srgb(color.z));roughness[pixel]=quantize(r);metallic[pixel]=quantize(m);
        }if(row%64==0)event("progress",{{"stage","bake"},{"fraction",double(row)/res}});
    }
    writePNG(out/"height.png",heights,res,res,LCT_GREY,16);writePNG(out/"normal.png",normals,res,res,LCT_RGB,8);writePNG(out/"coverage.png",coverage,res,res,LCT_GREY,8);material_png(context,"basecolor.png",bc,res,LCT_RGB);material_png(context,"roughness.png",roughness,res,LCT_GREY);material_png(context,"metallic.png",metallic,res,LCT_GREY);material_png(context,"normal_material.png",normal_material,res,LCT_RGB);
    const char* tie_policy="exactZ then pose_id,tri_id";
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
    tie_policy="exactZ then pose_id,tri_id,kx,ky";
#endif
    event("progress",{{"stage","review_pbr_shared_hit"},{"fraction",1},{"queries",queries},{"covered_samples",covered_samples},{"first_unique_top_hits",diagnostic},{"tie_policy",tie_policy},{"barycentric_policy","visibility>=-1e-10; attributes clamp0 then normalize"},{"PBR_average","covered samples only; straight coverage"},{"backface_frame","T unchanged; N and B flipped"}});
    return {{"height","height.png"},{"normal","normal.png"},{"coverage","coverage.png"},{"resolution",res},{"height_min",minz},{"height_max",maxz},{"normal_convention",convention},{"clipped_samples",clipped},{"baker",scene?"precise-triangle XY BVH":"constant empty scene"}};
}
static json finish(Context& context,const json& result){
    if(!context.pbr)return review_n1::finish(context,result);json artifacts=json::object();
    if(context.hull_export){
        std::set<std::string> expected,present;for(const auto& pose:result.at("poses")){auto id=pose.at("asset_id").get<std::string>();expected.insert(id);auto found=std::find_if(context.hulls.begin(),context.hulls.end(),[&](const json& h){return h.at("asset_id")==id;});require(found!=context.hulls.end()&&found->at("built_scale")==pose.at("scale"),"PBR used hull scale/identity");}
        json counts=json::array();uint64_t vertices=0,faces=0;for(const auto& hull:context.hulls){auto id=hull.at("asset_id").get<std::string>();require(present.insert(id).second,"PBR duplicate hull");vertices+=hull.at("vertices").size();faces+=hull.at("faces").size();counts.push_back({{"asset_id",id},{"vertex_count",hull.at("vertices").size()},{"face_count",hull.at("faces").size()}});}require(expected==present,"PBR used hull closure");auto raw=json{{"schema_version",1},{"coordinate_system","RH_Z_UP"},{"units","meters"},{"hulls",context.hulls}}.dump(2);review_n1::immutable(context.out/"hulls-v1.json",raw,context);artifacts["hulls"]={{"path","hulls-v1.json"},{"byte_sha256",sha256(raw)},{"byte_count",raw.size()},{"format","JSON"},{"schema_version",1},{"hull_count",context.hulls.size()},{"aggregate_vertex_count",vertices},{"aggregate_face_count",faces},{"hulls",counts}};
    }else require(context.hulls.empty(),"PBR rebake must not collect actual hulls");
    unsigned res=result.at("maps").at("resolution");
    for(const char* role:{"basecolor","roughness","metallic","normal_material"}){bool rgb=std::string(role)=="basecolor"||std::string(role)=="normal_material";std::string name=std::string(role)+".png";auto raw=bytes(owned(context.out/name,context.out),review_n1::OUTPUT_LIMIT);const auto* p=reinterpret_cast<const unsigned char*>(raw.data());require(raw.size()>=33&&!std::memcmp(p,"\x89PNG\r\n\x1a\n",8)&&mask_u32(p+8)==13&&!std::memcmp(p+12,"IHDR",4)&&mask_u32(p+16)==res&&mask_u32(p+20)==res&&p[24]==8&&p[25]==(rgb?2:0),"PBR actual output PNG descriptor mismatch");json descriptor={{"path",name},{"byte_sha256",sha256(raw)},{"byte_count",raw.size()},{"format","PNG"},{"width",res},{"height",res},{"bit_depth",8},{"color_type",rgb?"RGB":"GREY"},{"color_space",std::string(role)=="basecolor"?"sRGB":"linear"}};if(std::string(role)=="normal_material")descriptor["normal_convention"]=result.at("maps").at("normal_convention");artifacts[role]=descriptor;}
    auto result_raw=bytes(owned(context.out/"result.json",context.out),16*MIB);auto raw=json{{"version",1},{"job_id",job},{"result_sha256",sha256(result_raw)},{"manifest_sha256",context.manifest_hash},{"producer",context.producer},{"artifacts",artifacts}}.dump(2);review_n1::immutable(context.out/"review-v1.json",raw,context);return {{"version",1},{"path","review-v1.json"},{"sha256",sha256(raw)},{"bytes",raw.size()}};
}
} // namespace review_n2
