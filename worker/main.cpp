#include <Jolt/Jolt.h>
#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Core/JobSystemSingleThreaded.h>
#include <Jolt/Physics/PhysicsSystem.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/ConvexHullShape.h>
#include <nlohmann/json.hpp>
#define TINYOBJLOADER_IMPLEMENTATION
#include <tiny_obj_loader.h>
#include <lodepng.h>
#include <zlib.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#include <cstddef>
#include <cstring>
#include <memory>
#include <cstdlib>
#include <map>
#include <set>
#include <sstream>
#include <iomanip>
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <bcrypt.h>
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
#include "periodic/solver_api.h"
#endif

using json = nlohmann::json;
namespace fs = std::filesystem;
using namespace JPH;
constexpr const char* VERSION = "0.3.0";
constexpr uint64_t MIB=1024ull*1024, BUDGET=512*MIB;
static std::string job;
static fs::path extended_path(const fs::path& path);
static uint64_t file_bytes(const fs::path& path){std::error_code error;auto value=fs::file_size(extended_path(path),error);if(error)throw std::runtime_error("Cannot stat input file");return value;}
static void event(const std::string& type, json data = json::object()) {
    data["event"] = type; data["job_id"] = job; data["schema_version"] = 2;
    std::cout << data.dump() << std::endl;
}
static double number(const json& obj, const char* key, double def, double lo, double hi) {
    double v = obj.value(key, def);
    if (!std::isfinite(v) || v < lo || v > hi) throw std::runtime_error(std::string("Invalid ") + key);
    return v;
}
static bool review_bake_flags(const json& r){
    return r.is_object()&&r.contains("bake_pbr")&&r.at("bake_pbr").is_boolean()&&r.at("bake_pbr").get<bool>()&&r.contains("export_hulls")&&r.at("export_hulls").is_boolean()&&!r.at("export_hulls").get<bool>();
}
static bool review_operation_allowed(const std::string& op,bool material_bake_only){
    return op=="simulate"||op=="simulate_bake"||(op=="bake"&&material_bake_only);
}
struct V {
    double x{}, y{}, z{};
    V operator+(V b) const {return {x+b.x,y+b.y,z+b.z};}
    V operator-(V b) const {return {x-b.x,y-b.y,z-b.z};}
    V operator*(double s) const {return {x*s,y*s,z*s};}
};
static double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static V cross(V a,V b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static V norm(V a){double l=std::sqrt(dot(a,a)); return l>1e-15?a*(1/l):V{0,0,1};}
static V from(Vec3 v){return {v.GetX(),v.GetY(),v.GetZ()};}
struct Tri {V a,b,c,n;};
struct Mesh {std::vector<V> vertices; std::vector<Tri> tris; double radius{};};
static std::string sha256(const std::string& bytes) {
    BCRYPT_ALG_HANDLE algorithm=nullptr; BCRYPT_HASH_HANDLE hash=nullptr;
    std::vector<unsigned char> object;
    auto check=[](NTSTATUS status){if(status<0)throw std::runtime_error("Windows SHA256 failed");};
    try {
        check(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0));
        DWORD length=0,received=0;check(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&length),sizeof(length),&received,0));
        object.resize(length);std::array<unsigned char,32> digest{};
        check(BCryptCreateHash(algorithm,&hash,object.data(),length,nullptr,0,0));
        check(BCryptHashData(hash,reinterpret_cast<PUCHAR>(const_cast<char*>(bytes.data())),ULONG(bytes.size()),0));
        check(BCryptFinishHash(hash,digest.data(),ULONG(digest.size()),0));
        BCryptDestroyHash(hash);hash=nullptr;BCryptCloseAlgorithmProvider(algorithm,0);algorithm=nullptr;
        std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto c:digest)out<<std::setw(2)<<unsigned(c);return out.str();
    } catch(...) {if(hash)BCryptDestroyHash(hash);if(algorithm)BCryptCloseAlgorithmProvider(algorithm,0);throw;}
}
static bool hexid(const std::string& value,size_t count) {return value.size()==count&&value.find_first_not_of("0123456789abcdef")==std::string::npos;}
static Mesh load(const std::string& bytes,uint64_t& parsed) {
    std::istringstream in(bytes);
    tinyobj::attrib_t attrib; std::vector<tinyobj::shape_t> shapes; std::vector<tinyobj::material_t> materials;
    std::string warning,error;
    if(!tinyobj::LoadObj(&attrib,&shapes,&materials,&warning,&error,&in,nullptr,true)) throw std::runtime_error("OBJ: "+error);
    uint64_t indices=0;for(const auto& shape:shapes)indices+=shape.mesh.indices.size();
    uint64_t storage=(attrib.vertices.size()/3)*sizeof(V)+(indices/3)*sizeof(Tri);
    if(storage>BUDGET-parsed)throw std::runtime_error("Parsed mesh storage exceeds 512 MiB budget");parsed+=storage;
    Mesh m;m.vertices.reserve(attrib.vertices.size()/3);m.tris.reserve(size_t(indices/3));
    for(size_t i=0;i+2<attrib.vertices.size();i+=3){
        V p{attrib.vertices[i],attrib.vertices[i+1],attrib.vertices[i+2]};
        if(!std::isfinite(p.x)||!std::isfinite(p.y)||!std::isfinite(p.z)) throw std::runtime_error("Non-finite vertex");
        m.vertices.push_back(p);m.radius=std::max(m.radius,std::sqrt(dot(p,p)));
    }
    if(m.vertices.size()<4 || m.vertices.size()>2000000) throw std::runtime_error("OBJ needs 4..2000000 vertices");
    for(const auto& shape:shapes) for(size_t i=0;i+2<shape.mesh.indices.size();i+=3){
        Tri t;
        V* out[]={&t.a,&t.b,&t.c};
        for(int k=0;k<3;k++){int index=shape.mesh.indices[i+k].vertex_index;if(index<0||size_t(index)>=m.vertices.size()) throw std::runtime_error("Invalid vertex index"); *out[k]=m.vertices[index];}
        V n=cross(t.b-t.a,t.c-t.a); if(dot(n,n)<1e-20) throw std::runtime_error("Degenerate triangle");
        t.n=norm(n); m.tris.push_back(t);
    }
    if(m.tris.empty()) throw std::runtime_error("No triangles");
    return m;
}
struct Asset {std::string id,hash;double weight,scale;Mesh mesh;};
static void validate_asset_weights(const json& rows);
static std::vector<Asset> assets(const json& request) {
    const auto& rows=request.at("assets");if(!rows.is_array()||rows.empty()||rows.size()>1024)throw std::runtime_error("assets needs 1..1024 entries");
    uint64_t total=0,parsed=0;std::set<std::string> ids;std::vector<Asset> result;std::vector<uint64_t> sizes;
    // Check every descriptor and file size before allocating input buffers or parsing any mesh.
    for(const auto& row:rows){auto id=row.at("asset_id").get<std::string>(),hash=row.at("content_hash").get<std::string>();
        if(!hexid(id,32)||!ids.insert(id).second||!hexid(hash,64)||row.at("format")!="obj")throw std::runtime_error("Invalid or duplicate asset identity/format");
        double weight=number(row,"weight",1,0,std::numeric_limits<double>::max());(void)weight;
        if(number(row,"scale",1,0,100)<=0)throw std::runtime_error("Invalid asset scale");
        uint64_t size=file_bytes(fs::u8path(row.at("path").get<std::string>()));
        if(size>256*MIB||size>BUDGET-total)throw std::runtime_error("OBJ input exceeds per-file/aggregate byte budget");total+=size;sizes.push_back(size);
    }
    validate_asset_weights(rows);
    size_t rowindex=0;for(const auto& row:rows){fs::path path=fs::u8path(row.at("path").get<std::string>());uint64_t size=file_bytes(path);
        if(size!=sizes[rowindex++])throw std::runtime_error("OBJ changed size before read");
        std::string bytes(size,'\0');std::ifstream in(extended_path(path),std::ios::binary);in.read(bytes.data(),std::streamsize(size));
        if(!in||in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("OBJ changed while reading");
        std::string actual=sha256(bytes);if(actual!=row.at("content_hash"))throw std::runtime_error("Asset SHA256 mismatch");
        result.push_back({row.at("asset_id"),actual,row.at("weight"),row.at("scale"),load(bytes,parsed)});
    }
    std::sort(result.begin(),result.end(),[](const Asset&a,const Asset&b){return a.id<b.id;});return result;
}
class Selector {
public:
    std::vector<size_t> indices;std::vector<double> cumulative;double total=0;
    explicit Selector(const std::vector<Asset>& values){double maximum=0;for(const auto&a:values)maximum=std::max(maximum,a.weight);
        if(maximum<=0)throw std::runtime_error("At least one positive weight is required");
        double correction=0;
        for(size_t i=0;i<values.size();i++)if(values[i].weight>0){double normalized=values[i].weight/maximum;
            if(normalized==0)throw std::runtime_error("Positive weight underflow");
            double y=normalized-correction,next=total+y;correction=(next-total)-y;
            if(!std::isfinite(next)||next<=total)throw std::runtime_error("Weight cumulative precision loss");total=next;indices.push_back(i);cumulative.push_back(total);
        }
    }
    size_t target(double value)const {if(!std::isfinite(value)||value<0||value>=total)throw std::runtime_error("Selection target outside [0,total)");
        return indices.at(size_t(std::upper_bound(cumulative.begin(),cumulative.end(),value)-cumulative.begin()));}
    size_t next(std::mt19937& rng)const {double value=(double(rng())/4294967296.0)*total;if(value>=total)value=std::nextafter(total,0.0);return target(value);}
};
static void validate_asset_weights(const json& rows){std::vector<Asset> values;for(const auto&row:rows)values.push_back({row.at("asset_id"),"",row.at("weight"),1,{}});
    std::sort(values.begin(),values.end(),[](const Asset&a,const Asset&b){return a.id<b.id;});Selector selector(values);}
static std::vector<size_t> choices(const std::vector<Asset>& values,const json& s){Selector selector(values);std::mt19937 rng(s.value("seed",1u));
    size_t count=size_t(number(s,"count",40,1,5000));std::vector<size_t> selected;selected.reserve(count);for(size_t i=0;i<count;i++)selected.push_back(selector.next(rng));return selected;}
static void budget(const std::vector<Asset>& values,const std::vector<size_t>& selected,const json& b){
    uint64_t triangles=0;for(size_t index:selected){uint64_t n=values.at(index).mesh.tris.size();if(n>2000000-triangles)throw std::runtime_error("Bake exceeds 2 million transformed triangle budget (before allocation)");triangles+=n;}
    uint64_t res=uint64_t(number(b,"resolution",512,16,8192)),buffers=res*res*6;
    if(triangles*256+buffers>BUDGET)throw std::runtime_error("Bake work exceeds 512 MiB budget (before allocation)");
}
static std::vector<size_t> validate_poses(const std::vector<Asset>& values,json& poses,bool allow_empty=false){
    if(!poses.is_array()||(!allow_empty&&poses.empty())||poses.size()>5000)throw std::runtime_error("Invalid poses array");
    std::set<uint64_t> ids;std::vector<size_t> selected;
    for(auto& pose:poses){if(!pose.at("id").is_number_unsigned()&&!(pose.at("id").is_number_integer()&&pose.at("id").get<int64_t>()>=0))throw std::runtime_error("Invalid pose id");
        if(!ids.insert(pose.at("id").get<uint64_t>()).second)throw std::runtime_error("Duplicate pose id");
        auto id=pose.at("asset_id").get<std::string>();auto it=std::find_if(values.begin(),values.end(),[&](const Asset&a){return a.id==id;});if(it==values.end())throw std::runtime_error("Unknown pose asset");
        auto& p=pose.at("position");auto& q=pose.at("rotation");if(!p.is_array()||p.size()!=3||!q.is_array()||q.size()!=4||number(pose,"scale",0,0,100)<=0)throw std::runtime_error("Invalid pose shape or scale");
        double length=0;for(const auto&v:p)if(!std::isfinite(v.get<double>()))throw std::runtime_error("Non-finite pose");for(const auto&v:q){double n=v.get<double>();if(!std::isfinite(n))throw std::runtime_error("Non-finite quaternion");length+=n*n;}
        if(std::abs(length-1)>1e-3)throw std::runtime_error("Rotation quaternion is not normalized");if(std::abs(length-1)>1e-15)for(auto&v:q)v=v.get<double>()/std::sqrt(length);
        selected.push_back(size_t(it-values.begin()));
    }return selected;
}
static json asset_identity(const json& rows){json result=json::array();for(const auto&row:rows)result.push_back({{"asset_id",row.at("asset_id")},{"content_hash",row.at("content_hash")},{"format",row.at("format")},{"weight",row.at("weight")},{"scale",row.at("scale")}});
    std::sort(result.begin(),result.end(),[](const json&a,const json&b){return a.at("asset_id").get<std::string>()<b.at("asset_id").get<std::string>();});return result;}
#include "mask.h"
#include "compatibility.h"
#include "review_hulls.h"
static double requested_radius(const std::vector<Asset>& values,const std::vector<size_t>& selected,const json& s){
    double radius=0;for(size_t index:selected)radius=std::max(radius,values[index].mesh.radius*values[index].scale);
    double width=number(s,"width",4,.1,1000),depth=number(s,"depth",4,.1,1000);
    if(!std::isfinite(radius)||radius<=0||radius*2>=std::min(width,depth))throw std::runtime_error("Mesh too large for region or invalid radius");return radius;
}
static uint64_t mask_geometry_work(const std::vector<Asset>& values,const std::vector<size_t>& selected,const json& b){
    budget(values,selected,b);uint64_t work=0;for(auto index:selected)work=mask_add(work,mask_mul(values[index].mesh.tris.size(),256));
    uint64_t res=uint64_t(number(b,"resolution",512,16,8192));work=mask_add(work,res*res*6);
    for(const auto& a:values)work=mask_add(work,mask_add(mask_mul(a.mesh.vertices.size(),sizeof(V)),mask_mul(a.mesh.tris.size(),sizeof(Tri))));
    work=mask_add(work,mask_mul(selected.size(),sizeof(size_t)*2+sizeof(Quat)*2+sizeof(Vec3)));
    if(work>BUDGET)throw std::runtime_error("Mask geometry work exceeds 512 MiB before allocation");return work;
}
#include "review_pbr_input.h"
struct Placement {std::vector<size_t> selected;std::vector<Quat> rotations;std::vector<Vec3> positions;double radius=0;size_t requested=0,mask_draws=0;json metadata;};
static Placement place(const std::vector<Asset>& values,const std::vector<size_t>& requested,const json& s,const Mask& mask){
    Placement result;result.radius=requested_radius(values,requested,s);result.requested=requested.size();
    std::mt19937 rotation_rng(s.value("seed",1u));std::uniform_real_distribution<float> unit(0,1);std::vector<Quat> rotations;
    for(size_t i=0;i<requested.size();i++){Vec3 axis=Vec3(unit(rotation_rng)*2-1,unit(rotation_rng)*2-1,unit(rotation_rng)*2-1).NormalizedOr(Vec3::sAxisZ());rotations.push_back(Quat::sRotation(axis,unit(rotation_rng)*6.283185307f));}
    size_t maximum=std::min(size_t(50000),requested.size()*10),attempt=0;std::string reason="attempts_exhausted";
    if(mask.black())reason="all_black";
    else {
        double width=number(s,"width",4,.1,1000),depth=number(s,"depth",4,.1,1000),pitch=result.radius*2.2;
        if(!std::isfinite(pitch)||pitch<=0||!std::isfinite(width/pitch)||!std::isfinite(depth/pitch)||width/pitch>std::numeric_limits<int>::max()||depth/pitch>std::numeric_limits<int>::max())throw std::runtime_error("Invalid/non-finite grid calculation");
        uint64_t cols=std::max(uint64_t(1),uint64_t(width/pitch)),rows=std::max(uint64_t(1),uint64_t(depth/pitch)),cells=mask_mul(cols,rows);
        std::mt19937 mask_rng(s.value("seed",1u)^0x4D41534Bu);
        std::mt19937 jitter_rng(s.value("seed",1u)^0x4A495454u);
        for(uint64_t j=0;attempt<maximum;j++){
            uint64_t cell=j%cells,layer=j/cells;
            float x=float((cell%cols+.5)*width/cols-width*.5),y=float((cell/cols+.5)*depth/rows-depth*.5),z=float(1.0+result.radius+layer*pitch);
            if(s.value("placement_jitter",false)){
                auto rand01=[&](){return double(jitter_rng())/4294967296.0;};
                const double x_room=std::max(0.0,width/double(cols)-result.radius*2)*.4;
                const double y_room=std::max(0.0,depth/double(rows)-result.radius*2)*.4;
                x+=float((rand01()*2-1)*x_room);y+=float((rand01()*2-1)*y_room);
                z+=float(rand01()*result.radius*.15);
            }
            ++attempt;double top=double(z)+result.radius;
            if(!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z)||!std::isfinite(top))throw std::runtime_error("Non-finite initial placement");
            if(top>1000){reason="initial_height_limit";break;}
            bool accept=true;if(mask.active()){uint16_t probability=mask_sample(mask,x,y,width,depth);++result.mask_draws;accept=mask_accept(mask_rng(),probability);}
            if(accept){size_t k=result.selected.size();result.selected.push_back(requested[k]);result.rotations.push_back(rotations[k]);result.positions.push_back(Vec3(x,y,z));
                if(result.selected.size()==requested.size()){reason="requested_count_reached";break;}}
        }
    }
    size_t count=result.selected.size();result.metadata={{"requested_count",requested.size()},{"spawned_count",count},{"attempt_count",attempt},{"max_attempts",maximum},{"spawn_status",count==requested.size()?"complete":count?"partial":"empty"},{"spawn_stop_reason",reason}};return result;
}
class Broad final:public BroadPhaseLayerInterface{
public: uint GetNumBroadPhaseLayers()const override{return 2;}
    BroadPhaseLayer GetBroadPhaseLayer(ObjectLayer l)const override{return BroadPhaseLayer(static_cast<BroadPhaseLayer::Type>(l));}
#if defined(JPH_EXTERNAL_PROFILE) || defined(JPH_PROFILE_ENABLED)
    const char* GetBroadPhaseLayerName(BroadPhaseLayer l)const override{return l.GetValue()?"Dynamic":"Static";}
#endif
};
class VsBroad final:public ObjectVsBroadPhaseLayerFilter{public:bool ShouldCollide(ObjectLayer a,BroadPhaseLayer b)const override{return a==1||b.GetValue()==1;}};
class Pair final:public ObjectLayerPairFilter{public:bool ShouldCollide(ObjectLayer a,ObjectLayer b)const override{return a==1||b==1;}};
#include "motion.h"
#ifdef SCATTER_LIVE_BUILD
#include "live.h"
#endif
static json simulate(const std::vector<Asset>& values,const Placement& placement,const json& s,review_n1::Context* review=nullptr,bool periodic=false,json* motion=nullptr) {
    const auto& selected=placement.selected;double radius=placement.radius;
    double width=number(s,"width",4,0.1,1000),depth=number(s,"depth",4,0.1,1000);
    if(radius*2>=std::min(width,depth))throw std::runtime_error("Mesh too large for region");
    RegisterDefaultAllocator(); Factory::sInstance=new Factory(); RegisterTypes();
    event("progress",{{"stage","physics_init"},{"fraction",0}});
    json result;
    {
        Broad broad; VsBroad vb; Pair pair; PhysicsSystem physics;
        physics.Init(10000,0,40000,20000,broad,vb,pair);physics.SetGravity(Vec3(0,0,-9.81f));
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
        if(periodic)scatter_periodic::Controller::configure(physics);
#else
        require(!periodic,"Periodic solver is unavailable in this build");
#endif
        event("progress",{{"stage","physics_world"},{"fraction",0}});
        TempAllocatorImpl allocator(32*1024*1024); JobSystemSingleThreaded jobs(2048);
        auto& bodies=physics.GetBodyInterface();
        int count=int(selected.size());
        double time=number(s,"seconds",12,0.1,120);
        double friction=number(s,"friction",0.6,0,2),bounce=number(s,"restitution",0.05,0,1);
        std::string edges=s.value("edges",std::string("walls"));
        if(periodic?edges!="periodic":(edges!="walls"&&edges!="open")) throw std::runtime_error("Edges/solver dispatch mismatch");
        auto box=[&](Vec3 half,Vec3 pos){RefConst<Shape> sh=new BoxShape(half);BodyCreationSettings bs(sh,RVec3(pos),Quat::sIdentity(),EMotionType::Static,0);bs.mFriction=float(friction);bodies.CreateAndAddBody(bs,EActivation::DontActivate);};
        box(Vec3(float(width*2),float(depth*2),0.5f),Vec3(0,0,-0.5f));
        if(edges=="walls"){
            float h=float(std::max(4.0,placement.requested*radius));
            box(Vec3(.1f,float(depth*.5+.2),h),Vec3(float(width*.5+.1),0,h));
            box(Vec3(.1f,float(depth*.5+.2),h),Vec3(float(-width*.5-.1),0,h));
            box(Vec3(float(width*.5),.1f,h),Vec3(0,float(depth*.5+.1),h));
            box(Vec3(float(width*.5),.1f,h),Vec3(0,float(-depth*.5-.1),h));
        }
        std::map<size_t,RefConst<Shape>> shapes;
        for(size_t index:selected)if(!shapes.count(index)){
            const auto&a=values[index];ConvexHullShapeSettings hull;for(auto p:a.mesh.vertices)hull.mPoints.push_back(Vec3(float(p.x*a.scale),float(p.y*a.scale),float(p.z*a.scale)));
            auto shape=hull.Create();if(shape.HasError())throw std::runtime_error(std::string("Convex hull: ")+shape.GetError().c_str());shapes[index]=shape.Get();
            if(review)review_n1::collect(review,a,shapes[index].GetPtr(),hull.mHullTolerance);
        }
        std::vector<BodyID> ids; json initial=json::array();
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
        std::vector<Body*> real_bodies;
#endif
        for(int i=0;i<count;i++){
            auto initial_position=placement.positions[i];float x=initial_position.GetX(),y=initial_position.GetY(),z=initial_position.GetZ();Quat rotation=placement.rotations[i];
            BodyCreationSettings bs(shapes.at(selected[i]),RVec3(x,y,z),rotation,EMotionType::Dynamic,1);
            bs.mFriction=float(friction);bs.mRestitution=float(bounce);bs.mLinearDamping=.1f;bs.mAngularDamping=.2f;
            #ifdef SCATTER_REVIEW_PERIODIC_BUILD
            if(periodic){auto* body=bodies.CreateBody(bs);require(body!=nullptr,"Periodic body capacity exceeded");bodies.AddBody(body->GetID(),EActivation::Activate);ids.push_back(body->GetID());real_bodies.push_back(body);}
            else
            #endif
            ids.push_back(bodies.CreateAndAddBody(bs,EActivation::Activate)); initial.push_back({x,y,z});
        }
        physics.OptimizeBroadPhase(); int steps=int(time*120),quiet=0; bool settled=false; int executed=0;
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
        std::unique_ptr<scatter_periodic::Controller> controller;if(periodic){controller=std::make_unique<scatter_periodic::Controller>(physics,real_bodies,float(width),float(depth));steps=int(time*60);}
#endif
        auto observed_poses=[&](){json rows=json::array();for(size_t i=0;i<ids.size();i++){RVec3 p=bodies.GetPosition(ids[i]);Quat q=bodies.GetRotation(ids[i]);const auto&a=values[selected[i]];rows.push_back({{"id",i},{"asset_id",a.id},{"position",{p.GetX(),p.GetY(),p.GetZ()}},{"rotation",{q.GetX(),q.GetY(),q.GetZ(),q.GetW()}},{"scale",a.scale}});}return rows;};
        std::unique_ptr<motion_v1::Recorder> recorder;if(motion)recorder=std::make_unique<motion_v1::Recorder>(observed_poses(),steps,periodic);int observed_steps=0;
#ifdef SCATTER_LIVE_BUILD
        if(live_v1::observer){auto initial_live=observed_poses();live_v1::observer->publish(initial_live,0);live_v1::observer->wait_ready(initial_live);}
#endif
        for(int step=0;step<steps;step++){
            #ifdef SCATTER_REVIEW_PERIODIC_BUILD
            if(periodic){
                // Product policy uses the already permitted maximum split. Contact
                // impulses are not predictable from the pre-step velocity alone.
                constexpr int substeps=16;float dt=(1.0f/60)/substeps;
                auto displacement_guard=[&](const scatter_periodic::DisplacementDemand& demand,int sub,bool predicted){
                    int required=predicted?demand.predicted_required_n:demand.current_required_n;
                    if(required>substeps){event("progress",{{"stage","periodic_displacement_failure"},{"fraction",double(step)/steps},{"step",step},{"sub",sub},{"chosen_n",substeps},{"current_required_n",demand.current_required_n},{"predicted_required_n",demand.predicted_required_n},{"max_linear",demand.max_linear},{"max_angular_radius",demand.max_angular_radius},{"max_speed",demand.max_speed},{"gravity_speed",demand.gravity_speed},{"limit",demand.limit},{"macro_dt",1.0f/60},{"checked",predicted?"predicted_before_macro":"current_after_substep"}});throw std::runtime_error(predicted?"Periodic predicted displacement requires more than16 substeps":"Post-solver periodic displacement bound exceeded");}
                };
                displacement_guard(controller->displacement_demand(1.0f/60),-1,true);
                for(int sub=0;sub<substeps;sub++){controller->begin(dt);auto error=physics.Update(dt,1,&allocator,&jobs);if(error!=EPhysicsUpdateError::None)throw std::runtime_error("Periodic physics capacity exceeded");controller->finish();displacement_guard(controller->displacement_demand(1.0f/60),sub,false);++executed;}
            }
            else
            #endif
            {auto error=physics.Update(1.0f/120,1,&allocator,&jobs);if(error!=EPhysicsUpdateError::None) throw std::runtime_error("Physics capacity exceeded");executed=step+1;}
            observed_steps=step+1;if(recorder&&observed_steps%recorder->stride==0)recorder->observe(observed_poses(),observed_steps);
#ifdef SCATTER_LIVE_BUILD
            if(live_v1::observer){if(observed_steps%(periodic?2:4)==0)live_v1::observer->publish(observed_poses(),observed_steps);live_v1::observer->pace(observed_steps);}
#endif
            bool stable=true; for(auto id:ids) if(bodies.IsActive(id)&&(bodies.GetLinearVelocity(id).Length()>.015f || bodies.GetAngularVelocity(id).Length()>.03f)) stable=false;
            quiet=stable?quiet+1:0;
            if(step%120==0)event("progress",{{"stage","simulate"},{"fraction",double(step)/steps}});
            if(quiet>=60){settled=true;break;}
        }
        json poses=observed_poses();if(recorder)*motion=recorder->finish(poses,observed_steps);
#ifdef SCATTER_LIVE_BUILD
        if(live_v1::observer)live_v1::observer->publish(poses,observed_steps,"baking");
#endif
        result={{"poses",poses},{"initial_positions",initial},{"settling_status",settled?"settled":"time_limit"},{"steps",executed},{"engine","Jolt 5.2.0"}};
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
        if(periodic){auto m=controller->metrics();event("progress",{{"stage","periodic_solver"},{"fraction",1},{"logical_bodies",ids.size()},{"image_bodies",0},{"updates",m.updates},{"wraps",m.wraps},{"query_calls",m.queries},{"manifolds",m.manifolds},{"friction_projection_excess",m.friction_excess}});}
#endif
    }
    UnregisterTypes();delete Factory::sInstance;Factory::sInstance=nullptr;return result;
}
// BVH over the precise rendered triangles; collision hulls never enter this path.
struct Node {V lo,hi;int left=-1,right=-1,start=0,end=0;};
class BVH {
public:
    std::vector<Tri> t;std::vector<int> ids;std::vector<Node> nodes;
    explicit BVH(std::vector<Tri> triangles):t(std::move(triangles)){ids.resize(t.size());std::iota(ids.begin(),ids.end(),0);build(0,int(ids.size()));}
    int build(int start,int end){
        Node n;n.start=start;n.end=end;n.lo={1e30,1e30,1e30};n.hi={-1e30,-1e30,-1e30};
        for(int i=start;i<end;i++)for(V p:{t[ids[i]].a,t[ids[i]].b,t[ids[i]].c}){n.lo={std::min(n.lo.x,p.x),std::min(n.lo.y,p.y),std::min(n.lo.z,p.z)};n.hi={std::max(n.hi.x,p.x),std::max(n.hi.y,p.y),std::max(n.hi.z,p.z)};}
        int index=int(nodes.size());nodes.push_back(n);
        if(end-start>8){int axis=(n.hi.x-n.lo.x>n.hi.y-n.lo.y)?0:1;int mid=(start+end)/2;
            std::nth_element(ids.begin()+start,ids.begin()+mid,ids.begin()+end,[&](int a,int b){V ca=t[a].a+t[a].b+t[a].c,cb=t[b].a+t[b].b+t[b].c;return axis?ca.y<cb.y:ca.x<cb.x;});
            int l=build(start,mid),r=build(mid,end);nodes[index].left=l;nodes[index].right=r;
        }return index;
    }
    bool sample(int index,double x,double y,double& z,V& normal)const{
        const Node& n=nodes[index];if(x<n.lo.x||x>n.hi.x||y<n.lo.y||y>n.hi.y||n.hi.z<z)return false;
        bool hit=false;if(n.left>=0){hit=sample(n.left,x,y,z,normal);return sample(n.right,x,y,z,normal)||hit;}
        for(int i=n.start;i<n.end;i++){const Tri& a=t[ids[i]];double den=(a.b.y-a.c.y)*(a.a.x-a.c.x)+(a.c.x-a.b.x)*(a.a.y-a.c.y);if(std::abs(den)<1e-15)continue;
            double u=((a.b.y-a.c.y)*(x-a.c.x)+(a.c.x-a.b.x)*(y-a.c.y))/den;
            double v=((a.c.y-a.a.y)*(x-a.c.x)+(a.a.x-a.c.x)*(y-a.c.y))/den,w=1-u-v;
            if(u>=-1e-10&&v>=-1e-10&&w>=-1e-10){double height=u*a.a.z+v*a.b.z+w*a.c.z;if(height>z){z=height;normal=a.n;if(normal.z<0)normal=normal*-1;hit=true;}}
        }return hit;
    }
};
static void writePNG(const fs::path& path,const std::vector<unsigned char>& data,unsigned w,unsigned h,LodePNGColorType type,unsigned bits){
    lodepng::State state;state.info_raw.colortype=type;state.info_raw.bitdepth=bits;state.info_png.color.colortype=type;state.info_png.color.bitdepth=bits;state.encoder.auto_convert=0;
    std::vector<unsigned char> png;unsigned error=lodepng::encode(png,data,w,h,state);if(error)throw std::runtime_error(lodepng_error_text(error));
    std::ofstream out(extended_path(path),std::ios::binary);out.write(reinterpret_cast<const char*>(png.data()),std::streamsize(png.size()));if(!out)throw std::runtime_error("PNG write failed");
}
#include "review_pbr_bake.h"
static json bake(const std::vector<Asset>& values,json& poses,const json& sim,const json& b,const fs::path& out,bool allow_empty=false){
    unsigned res=unsigned(number(b,"resolution",512,16,8192));double width=number(sim,"width",4,.1,1000),depth=number(sim,"depth",4,.1,1000);
    double minz=number(b,"height_min",0,-1000,1000),maxz=number(b,"height_max",2,-1000,1000);if(maxz<=minz)throw std::runtime_error("height_max must exceed height_min");
    std::string convention=b.value("normal",std::string("DirectX"));if(convention!="DirectX"&&convention!="OpenGL")throw std::runtime_error("Unknown normal convention");
    int aa=int(number(b,"samples",1,1,4));
    json calculation_poses=poses;
    auto selected=validate_poses(values,calculation_poses,allow_empty);budget(values,selected,b);size_t total=0;for(auto index:selected)total+=values[index].mesh.tris.size();
    if(calculation_poses.empty()){
        size_t pixels=size_t(res)*res;std::vector<unsigned char> height(pixels*2,0),normal(pixels*3),coverage(pixels,0);
        for(size_t i=0;i<pixels;i++){normal[i*3]=128;normal[i*3+1]=128;normal[i*3+2]=255;}
        writePNG(out/"height.png",height,res,res,LCT_GREY,16);writePNG(out/"normal.png",normal,res,res,LCT_RGB,8);writePNG(out/"coverage.png",coverage,res,res,LCT_GREY,8);
        return {{"height","height.png"},{"normal","normal.png"},{"coverage","coverage.png"},{"resolution",res},{"height_min",minz},{"height_max",maxz},{"normal_convention",convention},{"clipped_samples",0},{"baker","constant empty scene"}};
    }
    std::vector<Tri> tris;tris.reserve(total);size_t poseindex=0;
    for(const auto& pose:calculation_poses){const auto&m=values[selected[poseindex++]].mesh;auto p=pose.at("position"),q=pose.at("rotation");double scale=pose.at("scale");
        if(p.size()!=3||q.size()!=4||!std::isfinite(scale)||scale<=0)throw std::runtime_error("Invalid pose shape or scale");
        for(const auto& value:p)if(!std::isfinite(value.get<double>()))throw std::runtime_error("Non-finite pose");
        for(const auto& value:q)if(!std::isfinite(value.get<double>()))throw std::runtime_error("Non-finite rotation");
        Quat rot(q[0].get<float>(),q[1].get<float>(),q[2].get<float>(),q[3].get<float>());if(std::abs(rot.LengthSq()-1)>1e-3)throw std::runtime_error("Rotation quaternion is not normalized");V offset{p[0],p[1],p[2]};
        auto transform=[&](V v){return from(rot*Vec3(float(v.x*scale),float(v.y*scale),float(v.z*scale)))+offset;};
        for(auto t:m.tris){t.a=transform(t.a);t.b=transform(t.b);t.c=transform(t.c);t.n=from(rot*Vec3(float(t.n.x),float(t.n.y),float(t.n.z)));tris.push_back(t);}
    }
    if(tris.empty())throw std::runtime_error("No poses to bake");BVH scene(std::move(tris));
    size_t pixels=size_t(res)*res;std::vector<unsigned char> heights(pixels*2),normals(pixels*3),coverage(pixels);uint64_t clipped=0;
    for(unsigned row=0;row<res;row++){
        for(unsigned col=0;col<res;col++){
            double height=0;V normal{};int covered=0;
            for(int sy=0;sy<aa;sy++)for(int sx=0;sx<aa;sx++){
                double x=((col+(sx+.5)/aa)/res-.5)*width,y=(.5-(row+(sy+.5)/aa)/res)*depth,z=-1e30;V n;
                if(scene.sample(0,x,y,z,n)){height+=z;normal=normal+n;covered++;if(z<minz||z>maxz)clipped++;}else{height+=minz;normal=normal+V{0,0,1};}
            }
            size_t pixel=size_t(row)*res+col;double h=(height/(aa*aa)-minz)/(maxz-minz);uint16_t v=uint16_t(std::round(std::clamp(h,0.0,1.0)*65535));heights[pixel*2]=v>>8;heights[pixel*2+1]=v&255;
            V n=norm(normal);if(convention=="DirectX")n.y=-n.y;std::array<double,3> channels{n.x,n.y,n.z};for(int k=0;k<3;k++)normals[pixel*3+k]=uint8_t(std::round(std::clamp(channels[k]*.5+.5,0.0,1.0)*255));
            coverage[pixel]=uint8_t(std::round(covered*255.0/(aa*aa)));
        }if(row%64==0)event("progress",{{"stage","bake"},{"fraction",double(row)/res}});
    }
    writePNG(out/"height.png",heights,res,res,LCT_GREY,16);writePNG(out/"normal.png",normals,res,res,LCT_RGB,8);writePNG(out/"coverage.png",coverage,res,res,LCT_GREY,8);
    return {{"height","height.png"},{"normal","normal.png"},{"coverage","coverage.png"},{"resolution",res},{"height_min",minz},{"height_max",maxz},{"normal_convention",convention},{"clipped_samples",clipped},{"baker","precise-triangle XY BVH"}};
}
#ifdef _WIN32
int wmain(int argc,wchar_t** argv){
#else
int main(int argc,char** argv){
#endif
    try{
        if(argc!=2)throw std::runtime_error("Usage: scatter_worker request.json");
        std::ifstream file{extended_path(fs::path(argv[1]))};json request;file>>request;
        if(request.at("schema_version")!=2)throw std::runtime_error("Unsupported schema_version");job=request.at("job_id").get<std::string>();if(job.empty())throw std::runtime_error("Empty job_id");
        std::string op=request.value("operation",std::string("simulate_bake"));
        if(request.contains("physics_input_format_version"))require(request.at("physics_input_format_version").is_number_integer()&&(request.at("physics_input_format_version")==1||request.at("physics_input_format_version")==2||input3(request.at("physics_input_format_version").get<int64_t>())),"Unsupported request input format/type");
        bool periodic=request.contains("physics_input_format_version")&&request.at("physics_input_format_version").is_number_integer()&&input3(request.at("physics_input_format_version").get<int64_t>());
        require(!request.contains("periodic")||periodic,"Periodic policy is forbidden outside input3");
        if(periodic)require(review_n1::strict_json(review_n1::bytes(fs::path(argv[1]),PROVENANCE_FILE))==request,"Input3 request changed/duplicate fields");
        if(periodic){require(request.contains("review_v1"),"Input3 requires isolated N3 review");const auto& r=request.at("review_v1");require(r.at("bake_pbr").is_boolean()&&r.at("export_hulls").is_boolean(),"Input3 review flags must be bool");require(((op=="simulate_bake"||op=="bake")&&r.at("bake_pbr")==true)||(op=="simulate"&&r.at("bake_pbr")==false&&r.at("export_hulls")==true),"Input3 requires a closed N3 operation; probes are forbidden");}
        if(request.contains("review_v1")){
            require(review_operation_allowed(op,review_bake_flags(request.at("review_v1"))),"Review requires a new simulation or material-only bake without new hulls");
            require(request.contains("assets")&&request.at("assets").is_array()&&request.at("assets").size()>=1&&request.at("assets").size()<=6,"N1 supports1..6 assets");
        }
        // Explicit offline probes exercise the exact production hash/selection implementations, without physics.
        if(op=="hash_probe"){event("completed",{{"sha256",sha256(request.at("text").get<std::string>())}});return 0;}
        if(op=="mask_probe"){
            try{
                if(request.value("fault",std::string())=="precondition"){
                    InflateContext context;context.expected=2;LodePNGDecompressSettings settings;lodepng_decompress_settings_init(&settings);settings.custom_context=&context;
                    unsigned char owned[8]{};unsigned char* pointer=owned;size_t count=1;unsigned status=mask_inflate(&pointer,&count,owned,0,&settings);
                    event("completed",{{"precondition_unchanged",status!=0&&pointer==owned&&count==1},{"diagnostic",mask_stats(context)}});return 0;
                }
                fs::path path=fs::u8path(request.at("path").get<std::string>());uint64_t size=file_bytes(path);if(size>64*MIB)throw std::runtime_error("Mask input exceeds 64 MiB");
                std::ifstream stream(extended_path(path),std::ios::binary);std::string bytes(size,'\0');stream.read(bytes.data(),std::streamsize(size));if(!stream)throw std::runtime_error("Mask read failed");
                auto mask=decode_mask_bytes(bytes,request.value("reserved_work",uint64_t(0)),request.value("fault",std::string()));
                std::string raw;raw.reserve(mask.pixels.size()*2);for(auto p:mask.pixels){raw.push_back(char(p>>8));raw.push_back(char(p&255));}
                json samples=json::array();for(const auto& p:request.value("points",json::array()))samples.push_back(mask_sample(mask,p[0],p[1],request.value("width",2.0),request.value("depth",2.0)));
                json comparisons=json::array();for(const auto& pair:request.value("comparisons",json::array()))comparisons.push_back(mask_accept(pair[0].get<uint32_t>(),pair[1].get<uint16_t>()));
                json random=json::array();unsigned random_count=unsigned(number(request,"random_count",0,0,1000));
                for(uint32_t seed:request.value("random_seeds",std::vector<uint32_t>{})){std::mt19937 rng(seed^0x4D41534Bu);json sequence=json::array();for(unsigned i=0;i<random_count;i++)sequence.push_back(rng());random.push_back(sequence);}
                event("completed",{{"width",mask.width},{"height",mask.height},{"all_black",mask.black()},{"pixels_sha256",sha256(raw)},{"samples",samples},{"comparisons",comparisons},{"random",random},{"diagnostic",mask.diagnostic}});return 0;
            }catch(const MaskFailure& e){event("error",{{"message",e.what()},{"diagnostic",e.diagnostic}});return 1;}
        }
        if(op=="selection_probe"){
            std::vector<Asset> values;std::set<std::string> seen;
            for(const auto&a:request.at("assets")){std::string id=a.at("asset_id");if(!hexid(id,32)||!seen.insert(id).second)throw std::runtime_error("Invalid asset id");values.push_back({id,"",number(a,"weight",1,0,std::numeric_limits<double>::max()),1,{}});}
            std::sort(values.begin(),values.end(),[](const Asset&a,const Asset&b){return a.id<b.id;});Selector selector(values);json ids=json::array();std::mt19937 rng(request.value("seed",1u));
            for(size_t i=0;i<size_t(number(request,"count",1,1,100000));i++)ids.push_back(values[selector.next(rng)].id);
            json targets=json::array();for(double value:request.value("targets",std::vector<double>{}))targets.push_back(values[selector.target(value)].id);
            event("completed",{{"selections",ids},{"targets",targets},{"total",selector.total}});return 0;
        }
        auto values=assets(request);Selector validated_weights(values);
        if(op=="placement_probe"){
            auto s=normalized_sim(request.at("simulation"));auto selected=choices(values,s);requested_radius(values,selected,s);auto mask=load_mask(request,mask_geometry_work(values,selected,request.at("bake")));auto placement=place(values,selected,s,mask);
            json result=placement.metadata;result["mask_draws"]=placement.mask_draws;result["requested_radius"]=placement.radius;result["positions"]=json::array();result["rotations"]=json::array();result["asset_ids"]=json::array();
            for(size_t i=0;i<placement.selected.size();i++){auto p=placement.positions[i];auto q=placement.rotations[i];result["positions"].push_back({p.GetX(),p.GetY(),p.GetZ()});result["rotations"].push_back({q.GetX(),q.GetY(),q.GetZ(),q.GetW()});result["asset_ids"].push_back(values[placement.selected[i]].id);}
            event("completed",result);return 0;
        }
        require(hexid(job,32),"Job ID must be lowercase UUID32hex");
        fs::path out=fs::u8path(request.at("output_directory").get<std::string>());std::error_code filesystem_error;fs::create_directories(extended_path(out),filesystem_error);if(filesystem_error)throw std::runtime_error("Cannot create job directory");
        if(fs::exists(extended_path(out/"result.json"))||fs::exists(extended_path(out/"height.png")))throw std::runtime_error("Job directory already contains a result; use a new job directory");
        auto physical=verify_inputs(request,out);
        json s=normalized_sim(request.at("simulation"),periodic?3:2),b=request.value("bake",json::object()),result;
        auto review=review_n2::prepare(request,values,out,op,s,b);
#ifdef SCATTER_LIVE_BUILD
        if(op!="bake"&&live_v1::enabled())live_v1::observer=std::make_unique<live_v1::Observer>(request,out);
#endif
        json motion_data;json* motion=nullptr;
#ifdef SCATTER_MOTION_BUILD
        if(op!="bake")motion=&motion_data;
#ifdef SCATTER_REVIEW_PBR_BUILD
        review.base_work=mask_add(review.base_work,64*MIB);review.peak(0);
#endif
#endif
        json source_bundle;
        Mask mask;std::vector<size_t> requested;
        if(masked_input(request.at("physics_input_format_version"))){requested=choices(values,s);requested_radius(values,requested,s);mask=load_mask(request,mask_geometry_work(values,requested,b));}
#ifdef SCATTER_MOTION_BUILD
        require(mask_add(mask_add(mask_geometry_work(values,requested,b),mask.bytes()),64*MIB)<=BUDGET,"Motion observation reserve exceeds512MiB before allocation");
#endif
        if(review.enabled)require(mask_add(mask_add(mask_geometry_work(values,requested,b),mask.bytes()),review.reserve())<=BUDGET,"Review input/hull/PBR reserve exceeds512MiB before world allocation");
        if(periodic)require(review.enabled&&(op=="simulate"||review.pbr)&&mask_add(mask_add(mask_add(mask_geometry_work(values,requested,b),mask.bytes()),review.reserve()),256*MIB)<=BUDGET,"Periodic solver/image reserve exceeds512MiB before world allocation");
        if(s.contains("scale"))throw std::runtime_error("Global scale is not supported in schema v2");
        event("started",{{"worker_version",VERSION}});
        if(op=="simulate_bake"||op=="simulate"){
            auto placement=place(values,requested,s,mask);if(mask_add(mask_geometry_work(values,placement.selected,b),mask.bytes())>BUDGET)throw std::runtime_error("Mask actual geometry/work exceeds budget");
            if(placement.selected.empty())result={{"poses",json::array()},{"initial_positions",json::array()},{"steps",0},{"settling_status","not_run"},{"engine","Jolt 5.2.0"}};
            else result=simulate(values,placement,s,review.hull_export?(review.enabled?&review:nullptr):nullptr,periodic,motion);
            if(motion&&placement.selected.empty()){motion_v1::Recorder empty(json::array(),0,periodic);*motion=empty.finish(json::array(),0);}
#ifdef SCATTER_LIVE_BUILD
            if(live_v1::observer&&placement.selected.empty())live_v1::observer->publish(json::array(),0,"baking");
#endif
            for(auto it=placement.metadata.begin();it!=placement.metadata.end();++it)result[it.key()]=it.value();
        }
        else if(op=="bake"){
            source_bundle=load_source(request,out,physical,mask);json checked=source_bundle.at("poses");validate_poses(values,checked,masked_input(request.at("physics_input_format_version")));
            event("progress",{{"stage","pose_validated"},{"fraction",1}});
            result={{"poses",source_bundle.at("poses")},{"steps",source_bundle.at("source_steps")},{"settling_status",source_bundle.at("settling_status")},{"engine","Jolt 5.2.0"}};
        }
        else throw std::runtime_error("Unknown operation");
        result["schema_version"]=2;result["job_id"]=job;result["worker_version"]=VERSION;result["assets"]=request.at("assets");result["simulation_key"]=request.value("simulation_key","");result["status"]="completed";
        result["coordinate_system"]="RH_Z_UP";result["units"]="meters";
        {json calculation_check=result.at("poses");validate_poses(values,calculation_check,masked_input(request.at("physics_input_format_version")));if(request.at("physics_input_format_version")==1)require(calculation_check.size()==size_t(s.at("count")),"Pose count does not match physics input");}
        decorate_result(result,request,out,source_bundle);
        if(masked_input(request.at("physics_input_format_version")))spawn_metrics(result,physical,mask,op!="bake");
        if(op!="simulate"){
            if(review.pbr)result["maps"]=review_n2::bake(review,values,result.at("poses"),s,b,out,masked_input(request.at("physics_input_format_version")));
            else result["maps"]=bake(values,result.at("poses"),s,b,out,masked_input(request.at("physics_input_format_version")));
        }
        std::ofstream saved(extended_path(out/"result.json.tmp"));saved<<result.dump(2);saved.close();require(bool(saved),"Result write failed");fs::rename(extended_path(out/"result.json.tmp"),extended_path(out/"result.json"),filesystem_error);require(!filesystem_error,"Atomic result rename failed");
        if(motion){require(file_bytes(out/"result.json")<=16*MIB,"Motion result byte bound");std::ifstream raw_result(extended_path(out/"result.json"),std::ios::binary);std::string actual_result_bytes(std::istreambuf_iterator<char>(raw_result),{});require(raw_result.eof()||bool(raw_result),"Motion raw result read failed");motion_v1::publish(motion_data,request,result,out,actual_result_bytes);}
        if(review.enabled)event("completed",{{"result_path",(out/"result.json").u8string()},{"review",review_n2::finish(review,result)}});
        else event("completed",{{"result_path",(out/"result.json").u8string()}});return 0;
    }catch(const std::exception& e){event("error",{{"message",e.what()}});std::cerr<<e.what()<<std::endl;return 1;}
}
