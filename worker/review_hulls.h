// Optional local-review N1. Legacy protocol/result identity is deliberately untouched.
#pragma once
namespace review_n1 {
constexpr const char* IMPLEMENTATION="0.4.0-review.1";
constexpr uint64_t MANIFEST_LIMIT=MIB,OUTPUT_LIMIT=8*MIB,RESERVE=16*MIB;
static void fields(const json& value,std::initializer_list<const char*> keys){
    require(value.is_object(),"Review object required");std::set<std::string> expected;for(auto key:keys)expected.insert(key);
    std::set<std::string> actual;for(auto it=value.begin();it!=value.end();++it)actual.insert(it.key());require(actual==expected,"Unknown/missing review fields");
}
static fs::path owned(const fs::path& path,const fs::path& root){
    auto r=fs::weakly_canonical(extended_path(root)),p=fs::weakly_canonical(extended_path(path));auto rel=p.lexically_relative(r);
    require(!rel.empty()&&rel!=fs::path(".")&&!rel.is_absolute(),"Review path outside owned root");
    for(const auto& part:rel)require(part!=fs::path(".."),"Review parent path escape");
    auto cursor=r;DWORD attr=GetFileAttributesW(extended_path(cursor).c_str());require(attr!=INVALID_FILE_ATTRIBUTES&&!(attr&FILE_ATTRIBUTE_REPARSE_POINT),"Review root is missing/reparse");
    for(const auto& part:rel){cursor/=part;attr=GetFileAttributesW(extended_path(cursor).c_str());require(attr==INVALID_FILE_ATTRIBUTES||!(attr&FILE_ATTRIBUTE_REPARSE_POINT),"Review reparse path rejected");}
    // Reject aliases even if their target happens to stay within the owned root.
    auto lexical=extended_path(path).lexically_normal(),base=extended_path(root).lexically_normal();auto original=lexical.lexically_relative(base);
    require(!original.empty()&&!original.is_absolute(),"Review lexical root mismatch");for(const auto& part:original)require(part!=fs::path(".."),"Review lexical path escape");
    cursor=base;for(const auto& part:original){cursor/=part;attr=GetFileAttributesW(extended_path(cursor).c_str());require(attr==INVALID_FILE_ATTRIBUTES||!(attr&FILE_ATTRIBUTE_REPARSE_POINT),"Review alias rejected");}
    return p;
}
static std::string bytes(const fs::path& path,uint64_t limit){
    auto size=file_bytes(path);require(size<=limit,"Review file byte budget");std::string raw(size,'\0');std::ifstream in(extended_path(path),std::ios::binary);in.read(raw.data(),std::streamsize(size));
    require(bool(in)&&in.peek()==std::char_traits<char>::eof()&&file_bytes(path)==size,"Review file changed/read failed");return raw;
}
static json strict_json(const std::string& raw){
    std::map<int,std::set<std::string>> keys;
    return json::parse(raw,[&](int depth,json::parse_event_t event,json& parsed){
        require(depth<=32,"Review JSON depth budget");
        if(event==json::parse_event_t::object_start)keys[depth+1].clear();
        if(event==json::parse_event_t::key)require(keys[depth].insert(parsed.get<std::string>()).second,"Duplicate review JSON key");
        return true;
    });
}
struct Context {bool enabled=false;fs::path root,out;std::string manifest_hash;json hulls,producer;};
static std::string executable_hash(){
    std::vector<wchar_t> path(32768);DWORD size=GetModuleFileNameW(nullptr,path.data(),DWORD(path.size()));require(size&&size<path.size(),"Cannot identify review executable");
    return sha256(bytes(fs::path(std::wstring(path.data(),size)),128*MIB));
}
static Context prepare(const json& request,const std::vector<Asset>& assets,const fs::path& out,const std::string& op){
    Context context;if(!request.contains("review_v1"))return context;
#ifndef SCATTER_REVIEW_BUILD
    throw std::runtime_error("Review extension requires the isolated review worker");
#else
    const auto& r=request.at("review_v1");fields(r,{"version","manifest_path","manifest_sha256","export_hulls","bake_pbr"});
    require(r.at("version").is_number_integer()&&!r.at("version").is_boolean()&&r.at("version")==1,"Review version mismatch");
    require(r.at("export_hulls").is_boolean()&&r.at("bake_pbr").is_boolean(),"Review flags must be bool");
    require(r.at("export_hulls").get<bool>()&&!r.at("bake_pbr").get<bool>(),"N1 requires export_hulls=true and bake_pbr=false");
    require(op=="simulate"||op=="simulate_bake","N1 hulls require a new simulation; rebake cannot synthesize used hulls");
    require(out.filename()==fs::path(job)&&out.parent_path().filename()==fs::path("runs"),"Review requires owned runs/job layout");
    context.root=fs::weakly_canonical(extended_path(out.parent_path().parent_path()));context.out=owned(out,context.root);
    for(const char* name:{"hulls-v1.json","review-v1.json","hulls-v1.json.tmp","review-v1.json.tmp"})require(!fs::exists(extended_path(context.out/name)),"Immutable review artifact already exists");
    require(r.at("manifest_path").is_string()&&r.at("manifest_sha256").is_string(),"Review manifest locator types");context.manifest_hash=r.at("manifest_sha256").get<std::string>();require(hexid(context.manifest_hash,64),"Review manifest SHA invalid");
    auto path=owned(fs::u8path(r.at("manifest_path").get<std::string>()),context.root);auto raw=bytes(path,MANIFEST_LIMIT);require(sha256(raw)==context.manifest_hash,"Review manifest raw SHA mismatch");
    auto manifest=strict_json(raw);fields(manifest,{"version","profile","assets","textures"});require(manifest.at("version").is_number_integer()&&manifest.at("version")==1&&manifest.at("profile")=="geometry_only","N1 geometry_only profile required");
    require(manifest.at("textures").is_array()&&manifest.at("textures").empty(),"N1 textures must be empty");const auto& rows=manifest.at("assets");require(rows.is_array()&&rows.size()==assets.size()&&rows.size()>=1&&rows.size()<=6,"N1 asset count/closure");
    std::map<std::string,std::string> expected;for(const auto& a:assets){require(a.mesh.tris.size()>=1&&a.mesh.tris.size()<5000,"N1 assets need1..4999 triangles");expected[a.id]=a.hash;}
    std::set<std::string> seen;for(const auto& row:rows){fields(row,{"asset_id","physics_obj_sha256"});require(row.at("asset_id").is_string()&&row.at("physics_obj_sha256").is_string(),"N1 asset locator types");auto id=row.at("asset_id").get<std::string>(),hash=row.at("physics_obj_sha256").get<std::string>();require(seen.insert(id).second&&expected.count(id)&&expected.at(id)==hash,"N1 asset identity/SHA mismatch");}
    context.enabled=true;context.hulls=json::array();context.producer={{"implementation_version",IMPLEMENTATION},{"build_fingerprint",SCATTER_REVIEW_BUILD_FINGERPRINT},{"binary_sha256",executable_hash()}};return context;
#endif
}
static json vector(Vec3 v){require(std::isfinite(v.GetX())&&std::isfinite(v.GetY())&&std::isfinite(v.GetZ()),"Nonfinite hull point");return {v.GetX(),v.GetY(),v.GetZ()};}
static void collect(Context* context,const Asset& asset,const Shape* shape,double tolerance){
    if(!context)return;require(shape&&shape->GetSubType()==EShapeSubType::ConvexHull,"Actual convex hull shape required");const auto* hull=static_cast<const ConvexHullShape*>(shape);
    require(hull->GetNumPoints()>=3&&hull->GetNumPoints()<=256&&hull->GetNumFaces()>=2&&hull->GetNumFaces()<=512,"Actual hull count budget");Vec3 com=hull->GetCenterOfMass();json vertices=json::array(),faces=json::array();
    for(uint i=0;i<hull->GetNumPoints();i++)vertices.push_back(vector(hull->GetPoint(i)+com));
    size_t total_indices=0;for(uint face=0;face<hull->GetNumFaces();face++){
        uint count=hull->GetNumVerticesInFace(face);require(count>=3&&count<=256,"Hull polygon size");total_indices+=count;require(total_indices<=4096,"Hull aggregate index budget");std::vector<uint> indices(count);require(hull->GetFaceVertices(face,count,indices.data())==count,"Hull face count changed");
        std::set<uint> unique;for(auto index:indices)require(index<hull->GetNumPoints()&&unique.insert(index).second,"Hull face index invalid");
        auto a=hull->GetPoint(indices[0]);Vec3 normal=Vec3::sZero();for(size_t i=1;i+1<indices.size();i++)normal+=(hull->GetPoint(indices[i])-a).Cross(hull->GetPoint(indices[i+1])-a);
        require(normal.LengthSq()>0&&normal.Dot(hull->GetPlanes()[face].GetNormal())>0,"Hull face winding/area invalid");faces.push_back(indices);
    }
    double radius=hull->GetConvexRadius();require(std::isfinite(radius)&&radius>=0,"Invalid convex radius");
    require(std::isfinite(tolerance)&&tolerance>=0,"Invalid construction tolerance");context->hulls.push_back({{"asset_id",asset.id},{"physics_obj_sha256",asset.hash},{"built_scale",asset.scale},{"coordinate_space","scaled_asset_origin_local"},{"center_of_mass_scaled",vector(com)},{"convex_radius",radius},{"vertices",vertices},{"faces",faces},{"Jolt_version","5.2.0"},{"shape_type","ConvexHull"},{"max_hull_points",256},{"construction_tolerance",tolerance}});
}
static void immutable(const fs::path& target,const std::string& raw,const Context& context){
    require(raw.size()<=OUTPUT_LIMIT,"Review output byte budget");auto checked=owned(target,context.out),temp=owned(fs::path(target.wstring()+L".tmp"),context.out);require(!fs::exists(extended_path(checked)),"Review output already exists");
    HANDLE file=CreateFileW(extended_path(temp).c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);require(file!=INVALID_HANDLE_VALUE,"Review exclusive output create failed");
    DWORD done=0;bool ok=WriteFile(file,raw.data(),DWORD(raw.size()),&done,nullptr)&&done==raw.size()&&FlushFileBuffers(file);CloseHandle(file);
    if(!ok){DeleteFileW(extended_path(temp).c_str());throw std::runtime_error("Review output write failed");}
    if(!MoveFileExW(extended_path(temp).c_str(),extended_path(checked).c_str(),MOVEFILE_WRITE_THROUGH)){DeleteFileW(extended_path(temp).c_str());throw std::runtime_error("Immutable review rename failed");}
    require(bytes(checked,OUTPUT_LIMIT)==raw,"Review output changed after close");
}
static json finish(Context& context,const json& result){
    require(context.enabled,"Review context disabled");std::set<std::string> expected;for(const auto& pose:result.at("poses")){auto id=pose.at("asset_id").get<std::string>();expected.insert(id);auto it=std::find_if(context.hulls.begin(),context.hulls.end(),[&](const json& h){return h.at("asset_id")==id;});require(it!=context.hulls.end()&&it->at("built_scale")==pose.at("scale"),"Hull pose asset/scale mismatch");}
    std::set<std::string> present;json counts=json::array();uint64_t vertices=0,faces=0;
    for(const auto& hull:context.hulls){auto id=hull.at("asset_id").get<std::string>();require(present.insert(id).second,"Duplicate actual hull");vertices+=hull.at("vertices").size();faces+=hull.at("faces").size();counts.push_back({{"asset_id",id},{"vertex_count",hull.at("vertices").size()},{"face_count",hull.at("faces").size()}});}
    require(expected==present,"Used hull/pose closure mismatch");
    auto hull_raw=json{{"schema_version",1},{"coordinate_system","RH_Z_UP"},{"units","meters"},{"hulls",context.hulls}}.dump(2);immutable(context.out/"hulls-v1.json",hull_raw,context);
    auto result_raw=bytes(owned(context.out/"result.json",context.out),16*MIB);
    json artifacts={{"hulls",{{"path","hulls-v1.json"},{"byte_sha256",sha256(hull_raw)},{"byte_count",hull_raw.size()},{"format","JSON"},{"schema_version",1},{"hull_count",context.hulls.size()},{"aggregate_vertex_count",vertices},{"aggregate_face_count",faces},{"hulls",counts}}}};
    json sidecar={{"version",1},{"job_id",job},{"result_sha256",sha256(result_raw)},{"manifest_sha256",context.manifest_hash},{"producer",context.producer},{"artifacts",artifacts}};
    auto raw=sidecar.dump(2);immutable(context.out/"review-v1.json",raw,context);return {{"version",1},{"path","review-v1.json"},{"sha256",sha256(raw)},{"bytes",raw.size()}};
}
} // namespace review_n1
