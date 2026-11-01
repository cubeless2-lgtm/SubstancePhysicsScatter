// Opt-in material input only. No changes to legacy Tri, loader or N1 exporter.
#pragma once
namespace review_n2 {
using review_n1::fields;using review_n1::owned;using review_n1::bytes;using review_n1::strict_json;
struct UV {double u=0,v=0;};
struct Corner {std::array<UV,3> uv;std::array<V,3> normal,tangent;double handedness=1;size_t material=0;};
struct Texture {std::string id;std::vector<unsigned char> pixels;};
struct Binding {int texture=-1,channel=-1;bool srgb=false,repeat_u=true,repeat_v=true,dx=false;};
struct Material {uint64_t id=0;V color{1,1,1};double roughness=1,metallic=0;Binding bc,r,m,n;};
struct AssetData {std::vector<Corner> corners;std::vector<Material> materials;};
struct Ref {size_t asset=0,tri=0,pose=0;uint64_t pose_id=0;
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
    int64_t kx=0,ky=0;
#endif
};
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
static constexpr const char* IMPLEMENTATION="0.4.0-review.3";
#else
static constexpr const char* IMPLEMENTATION="0.4.0-review.2";
#endif
struct Context:review_n1::Context {
    bool pbr=false,hull_export=false;std::vector<Texture> textures;std::vector<AssetData> assets;
    uint64_t base_work=0,extra=review_n1::RESERVE,held=0;
    void peak(uint64_t n)const{require(mask_add(mask_add(base_work,mask_add(extra,held)),n)<=BUDGET,"PBR input/geometry/work exceeds512MiB before allocation");}
    void hold(uint64_t n){peak(n);held=mask_add(held,n);}
    uint64_t reserve()const{return mask_add(extra,held);}
};
static uint64_t integer(const json& j,uint64_t maximum){require(j.is_number_integer()&&!j.is_boolean()&&j>=0,"PBR nonnegative integer required");auto n=j.get<uint64_t>();require(n<=maximum,"PBR integer bound");return n;}
static double scalar(const json& j,double lo=-std::numeric_limits<double>::max(),double hi=std::numeric_limits<double>::max()){
    require(j.is_number()&&!j.is_boolean(),"PBR number required");double v=j.get<double>();require(std::isfinite(v)&&v>=lo&&v<=hi,"PBR finite/range");return v;
}
static V vector3(const json& j){require(j.is_array()&&j.size()==3,"PBR vector3 shape");return {scalar(j[0]),scalar(j[1]),scalar(j[2])};}
static V unit(V v){double length=dot(v,v);require(std::isfinite(length)&&length>1e-20,"PBR degenerate normal/tangent");return v*(1/std::sqrt(length));}
static void same(V a,V b){require(a.x==b.x&&a.y==b.y&&a.z==b.z,"PBR corner/physics OBJ positions differ exactly");}
static std::vector<unsigned char> decode_texture(const std::string& input,uint64_t work){
    require(input.size()>=8&&input.size()<=8*MIB&&!std::memcmp(input.data(),"\x89PNG\r\n\x1a\n",8),"PBR PNG signature/budget");
    const auto* raw=reinterpret_cast<const unsigned char*>(input.data());size_t at=8;bool header=false,idat=false,done=false,ended=false;uint64_t clean_size=8;
    while(at<input.size()){
        require(input.size()-at>=12,"PBR truncated PNG chunk");uint32_t count=mask_u32(raw+at);uint64_t end=mask_add(at,mask_add(count,12));require(end<=input.size(),"PBR PNG chunk size");
        const auto* type=raw+at+4;std::string name(reinterpret_cast<const char*>(type),4);
        for(char c:name)require((c>='A'&&c<='Z')||(c>='a'&&c<='z'),"PBR PNG chunk type");require(!(type[2]&32),"PBR PNG reserved bit");
        require(lodepng_crc32(type,size_t(count)+4)==mask_u32(raw+at+8+count),"PBR PNG CRC");require(header||name=="IHDR","PBR IHDR first");
        if(name=="IHDR"){require(!header&&count==13,"PBR IHDR singleton");header=true;require(mask_u32(raw+at+8)==512&&mask_u32(raw+at+12)==512&&raw[at+16]==8&&raw[at+17]==6&&raw[at+18]==0&&raw[at+19]==0&&raw[at+20]==0,"PBR requires512x512 noninterlaced RGBA8 PNG");}
        else if(name=="IDAT"){require(!done,"PBR IDAT noncontiguous");idat=true;}
        else {if(idat)done=true;if(name=="IEND"){require(count==0&&idat&&end==input.size(),"PBR IEND/trailing bytes");ended=true;}else require(name!="PLTE"&&name!="tRNS"&&(type[0]&32),"PBR unsupported critical/alpha chunk");}
        if(name=="IHDR"||name=="IDAT"||name=="IEND")clean_size=mask_add(clean_size,uint64_t(count)+12);at=size_t(end);if(ended)break;
    }
    require(ended&&idat,"PBR missing PNG data");constexpr size_t decoded_size=512*512*4,expected=512*(512*4+1);
    uint64_t reserved=mask_add(work,mask_add(mask_mul(input.size(),3),mask_mul(decoded_size,3)));require(reserved<=BUDGET&&expected<=BUDGET-reserved,"PBR PNG decode budget");
    std::vector<unsigned char> clean;clean.reserve(size_t(clean_size));clean.insert(clean.end(),raw,raw+8);
    for(size_t p=8;p<input.size();){auto n=mask_u32(raw+p);std::string name(reinterpret_cast<const char*>(raw+p+4),4);size_t end=p+size_t(n)+12;if(name=="IHDR"||name=="IDAT"||name=="IEND")clean.insert(clean.end(),raw+p,raw+end);p=end;}
    InflateContext context;context.expected=expected;context.reserved=context.live=context.peak=reserved;
    lodepng::State state;state.decoder.color_convert=0;state.decoder.read_text_chunks=0;state.decoder.remember_unknown_chunks=0;state.decoder.ignore_crc=0;state.decoder.ignore_critical=0;state.decoder.zlibsettings.custom_zlib=mask_inflate;state.decoder.zlibsettings.custom_context=&context;
    unsigned char* decoded=nullptr;unsigned w=0,h=0;unsigned error=lodepng_decode(&decoded,&w,&h,&state,clean.data(),clean.size());if(context.reason==0&&context.calls)context.release(context.expected);
    std::unique_ptr<unsigned char,decltype(&std::free)> owner(decoded,&std::free);require(error==0&&decoded&&w==512&&h==512&&state.info_png.color.colortype==LCT_RGBA&&state.info_png.color.bitdepth==8,"PBR bounded RGBA decode failed");
    for(size_t i=3;i<decoded_size;i+=4)require(decoded[i]==255,"PBR requires opaque textures");return std::vector<unsigned char>(decoded,decoded+decoded_size);
}
static Binding binding(const json& j,const char* role,const std::map<std::string,int>& texture_ids,std::set<std::string>& used){
    Binding b;if(j.is_null())return b;bool normal=std::string(role)=="normal",color=std::string(role)=="base_color";
    if(normal)fields(j,{"texture_id","channel","uv_set","wrap_u","wrap_v","filter","color_space","normal_convention"});else fields(j,{"texture_id","channel","uv_set","wrap_u","wrap_v","filter","color_space"});
    require(j.at("texture_id").is_string(),"PBR texture ID type");auto id=j.at("texture_id").get<std::string>();require(texture_ids.count(id),"PBR unknown texture binding");b.texture=texture_ids.at(id);used.insert(id);
    require(integer(j.at("uv_set"),0)==0&&j.at("filter")=="bilinear","PBR UV/filter");auto channel=j.at("channel").get<std::string>();
    if(color||normal)require(channel=="rgb","PBR color/normal require rgb");else{require(channel=="r"||channel=="g"||channel=="b","PBR scalar swizzle");b.channel=channel=="r"?0:channel=="g"?1:2;}
    for(const char* key:{"wrap_u","wrap_v"})require(j.at(key)=="repeat"||j.at(key)=="clamp","PBR wrap");b.repeat_u=j.at("wrap_u")=="repeat";b.repeat_v=j.at("wrap_v")=="repeat";
    require(j.at("color_space")=="linear"||(color&&j.at("color_space")=="sRGB"),"PBR data/color space");b.srgb=j.at("color_space")=="sRGB";
    if(normal){require(j.at("normal_convention")=="OpenGL"||j.at("normal_convention")=="DirectX","PBR normal convention");b.dx=j.at("normal_convention")=="DirectX";}return b;
}
static Context prepare(const json& request,const std::vector<Asset>& values,const fs::path& out,const std::string& op,const json& sim,const json& bake){
    Context c;if(!request.contains("review_v1"))return c;
    const auto& r=request.at("review_v1");fields(r,{"version","manifest_path","manifest_sha256","export_hulls","bake_pbr"});
    require(integer(r.at("version"),1)==1&&r.at("export_hulls").is_boolean()&&r.at("bake_pbr").is_boolean(),"PBR review version/flags");
    if(!r.at("bake_pbr").get<bool>()){
        static_cast<review_n1::Context&>(c)=review_n1::prepare(request,values,out,op);c.hull_export=c.enabled;
#ifdef SCATTER_REVIEW_PBR_BUILD
        c.producer["implementation_version"]=IMPLEMENTATION;
#endif
        return c;
    }
#ifndef SCATTER_REVIEW_PBR_BUILD
    throw std::runtime_error("Material PBR requires the isolated review-pbr worker");
#else
    c.pbr=true;c.hull_export=r.at("export_hulls").get<bool>();require(op=="simulate_bake"||op=="bake","PBR requires bake operation");require(!c.hull_export||op=="simulate_bake","Rebake cannot synthesize used hulls");
    require(out.filename()==fs::path(job)&&out.parent_path().filename()==fs::path("runs"),"PBR owned runs/job layout");c.root=fs::weakly_canonical(extended_path(out.parent_path().parent_path()));c.out=owned(out,c.root);
    for(const char* n:{"hulls-v1.json","review-v1.json","basecolor.png","roughness.png","metallic.png","normal_material.png"}){require(!fs::exists(extended_path(c.out/n))&&!fs::exists(extended_path(c.out/(std::string(n)+".tmp"))),"Immutable PBR output already exists");}
    require(r.at("manifest_path").is_string()&&r.at("manifest_sha256").is_string(),"PBR manifest locator types");c.manifest_hash=r.at("manifest_sha256").get<std::string>();require(hexid(c.manifest_hash,64),"PBR manifest hash");
    require(integer(bake.value("resolution",json(512)),8192)>=16&&integer(bake.value("samples",json(1)),4)>=1,"PBR bake resolution/samples integer range");double low=scalar(bake.value("height_min",json(0)),-1000,1000),high=scalar(bake.value("height_max",json(2)),-1000,1000);require(high>low,"PBR height range");require(bake.value("normal",json("DirectX"))=="OpenGL"||bake.value("normal",json("DirectX"))=="DirectX","PBR output normal convention");
    auto selected=choices(values,sim);c.base_work=mask_geometry_work(values,selected,bake);uint64_t triangles=0;for(auto index:selected)triangles=mask_add(triangles,values[index].mesh.tris.size());
    uint64_t resolution=uint64_t(number(bake,"resolution",512,16,8192));c.extra=mask_add(review_n1::RESERVE,mask_add(mask_mul(triangles,sizeof(Ref)),mask_mul(mask_mul(resolution,resolution),40)));
    auto path=owned(fs::u8path(r.at("manifest_path").get<std::string>()),c.root);c.peak(mask_mul(file_bytes(path),12));auto raw=bytes(path,MIB);require(sha256(raw)==c.manifest_hash,"PBR manifest raw SHA");auto manifest=strict_json(raw);
    fields(manifest,{"version","profile","assets","textures"});require(integer(manifest.at("version"),1)==1&&manifest.at("profile")=="material","PBR material profile required");
    const auto& rows=manifest.at("assets");const auto& textures=manifest.at("textures");require(rows.is_array()&&rows.size()==values.size()&&rows.size()>=1&&rows.size()<=6,"PBR asset closure/count");require(textures.is_array()&&textures.size()<=64,"PBR texture count");
    std::map<std::string,int> texture_ids,texture_hashes;uint64_t texture_bytes=0,corner_bytes=0;
    for(const auto& row:textures){
        fields(row,{"texture_id","path","content_sha256","width","height","channels","bit_depth"});auto id=row.at("texture_id").get<std::string>(),hash=row.at("content_sha256").get<std::string>();require(hexid(id,64)&&hexid(hash,64)&&!texture_ids.count(id),"PBR texture ID/hash/duplicate");
        require(integer(row.at("width"),512)==512&&integer(row.at("height"),512)==512&&integer(row.at("channels"),4)==4&&integer(row.at("bit_depth"),8)==8,"PBR texture descriptor requiresRGBA8/512");
        auto texture_path=owned(fs::u8path(row.at("path").get<std::string>()),c.root);auto size=file_bytes(texture_path);texture_bytes=mask_add(texture_bytes,size);require(size<=8*MIB&&texture_bytes<=64*MIB,"PBR texture byte aggregate");
        c.peak(mask_add(mask_mul(size,3),4*MIB));auto data=bytes(texture_path,8*MIB);require(sha256(data)==hash,"PBR texture raw SHA");if(texture_hashes.count(hash)){texture_ids[id]=texture_hashes.at(hash);continue;}Texture texture;texture.id=id;texture.pixels=decode_texture(data,mask_add(c.base_work,c.reserve()));c.hold(texture.pixels.size());texture_ids[id]=int(c.textures.size());texture_hashes[hash]=int(c.textures.size());c.textures.push_back(std::move(texture));
    }
    c.assets.resize(values.size());std::set<std::string> seen,used;
    for(const auto& row:rows){
        fields(row,{"asset_id","physics_obj_sha256","corner_data_path","corner_data_sha256","materials"});auto id=row.at("asset_id").get<std::string>();require(seen.insert(id).second,"PBR duplicate asset");auto found=std::find_if(values.begin(),values.end(),[&](const Asset& a){return a.id==id;});require(found!=values.end()&&row.at("physics_obj_sha256")==found->hash,"PBR asset hash/identity");
        require(found->mesh.tris.size()>=1&&found->mesh.tris.size()<5000,"PBR triangles1..4999");auto ri=std::find_if(request.at("assets").begin(),request.at("assets").end(),[&](const json& a){return a.at("asset_id")==id;});owned(fs::u8path(ri->at("path").get<std::string>()),c.root);
        auto& data=c.assets[size_t(found-values.begin())];const auto& materials=row.at("materials");require(materials.is_array()&&!materials.empty()&&materials.size()<=64,"PBR material count");std::map<uint64_t,size_t> mids;
        for(const auto& m:materials){fields(m,{"material_id","base_color_factor","roughness_factor","metallic_factor","base_color_texture","roughness_texture","metallic_texture","normal_texture"});Material material;material.id=integer(m.at("material_id"),63);require(!mids.count(material.id),"PBR duplicate material");material.color=vector3(m.at("base_color_factor"));for(double v:{material.color.x,material.color.y,material.color.z})require(v>=0&&v<=1,"PBR BC factor range");material.roughness=scalar(m.at("roughness_factor"),0,1);material.metallic=scalar(m.at("metallic_factor"),0,1);
            material.bc=binding(m.at("base_color_texture"),"base_color",texture_ids,used);material.r=binding(m.at("roughness_texture"),"roughness",texture_ids,used);material.m=binding(m.at("metallic_texture"),"metallic",texture_ids,used);material.n=binding(m.at("normal_texture"),"normal",texture_ids,used);mids[material.id]=data.materials.size();data.materials.push_back(material);}
        auto cp=owned(fs::u8path(row.at("corner_data_path").get<std::string>()),c.root);auto size=file_bytes(cp);corner_bytes=mask_add(corner_bytes,size);require(size<=8*MIB&&corner_bytes<=48*MIB,"PBR corner byte aggregate");c.hold(mask_add(mask_mul(found->mesh.tris.size(),sizeof(Corner)),mask_mul(materials.size(),sizeof(Material))));c.peak(mask_mul(size,12));auto cr=bytes(cp,8*MIB);require(row.at("corner_data_sha256").is_string()&&hexid(row.at("corner_data_sha256"),64)&&sha256(cr)==row.at("corner_data_sha256"),"PBR corner raw SHA");auto corners=strict_json(cr);fields(corners,{"version","triangle_count","triangles"});require(integer(corners.at("version"),1)==1&&integer(corners.at("triangle_count"),4999)==found->mesh.tris.size(),"PBR corner count");const auto& ts=corners.at("triangles");require(ts.is_array()&&ts.size()==found->mesh.tris.size(),"PBR corner triangle closure");data.corners.reserve(ts.size());
        for(size_t i=0;i<ts.size();i++){const auto& t=ts[i];fields(t,{"tri_id","shape_id","material_id","positions","uv0","normals","tangents"});require(integer(t.at("tri_id"),4998)==i&&t.at("shape_id").is_string()&&!t.at("shape_id").get<std::string>().empty(),"PBR stable triangle/shape ID");auto mid=integer(t.at("material_id"),63);require(mids.count(mid),"PBR unknown triangle material");Corner corner;corner.material=mids.at(mid);
            for(const char* key:{"positions","uv0","normals","tangents"})require(t.at(key).is_array()&&t.at(key).size()==3,"PBR three corner attributes required");const auto& tri=found->mesh.tris[i];std::array<V,3> positions{tri.a,tri.b,tri.c};
            for(size_t k=0;k<3;k++){same(vector3(t.at("positions")[k]),positions[k]);const auto& uv=t.at("uv0")[k];require(uv.is_array()&&uv.size()==2,"PBR UV0 shape");corner.uv[k]={scalar(uv[0]),scalar(uv[1])};corner.normal[k]=vector3(t.at("normals")[k]);unit(corner.normal[k]);const auto& tangent=t.at("tangents")[k];require(tangent.is_array()&&tangent.size()==4,"PBR tangent shape");corner.tangent[k]={scalar(tangent[0]),scalar(tangent[1]),scalar(tangent[2])};unit(corner.tangent[k]);double w=scalar(tangent[3]);require((w==1||w==-1)&&(k==0||w==corner.handedness),"PBR triangle handedness mismatch");corner.handedness=w;unit(corner.tangent[k]-unit(corner.normal[k])*dot(corner.tangent[k],unit(corner.normal[k])));}
            double area=(corner.uv[1].u-corner.uv[0].u)*(corner.uv[2].v-corner.uv[0].v)-(corner.uv[1].v-corner.uv[0].v)*(corner.uv[2].u-corner.uv[0].u);if(data.materials[corner.material].n.texture>=0)require(std::isfinite(area)&&std::abs(area)>1e-20,"PBR textured normal requires nondegenerate UV");data.corners.push_back(corner);
        }
    }
    require(used.size()==texture_ids.size(),"PBR unused/extra texture closure");c.enabled=true;c.hulls=json::array();c.producer={{"implementation_version",IMPLEMENTATION},{"build_fingerprint",SCATTER_REVIEW_BUILD_FINGERPRINT},{"binary_sha256",review_n1::executable_hash()}};return c;
#endif
}
} // namespace review_n2
