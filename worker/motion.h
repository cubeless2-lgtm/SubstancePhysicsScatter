// Observation only: no Jolt setters, stepping, random draws or pose interpolation.
#pragma once
namespace motion_v1 {
constexpr size_t MAX_BYTES=8*1024*1024,MAX_POSES=40000,MAX_FRAMES=3601;
static void integer(std::string& out,uint32_t value){for(int i=0;i<4;i++)out.push_back(char(value>>(8*i)));}
static void real(std::string& out,double value){uint64_t bits;std::memcpy(&bits,&value,8);for(int i=0;i<8;i++)out.push_back(char(bits>>(8*i)));}
static std::string pose_hash(const json& poses){
    std::string raw("motion-final-poses-v1\0",22);integer(raw,uint32_t(poses.size()));
    for(const auto& p:poses){integer(raw,p.at("id").get<uint32_t>());auto id=p.at("asset_id").get<std::string>();integer(raw,uint32_t(id.size()));raw+=id;real(raw,p.at("scale").get<double>());for(const char* key:{"position","rotation"})for(const auto& v:p.at(key))real(raw,v.get<double>());}
    return sha256(raw);
}
struct Recorder {
    json bodies=json::array(),frames=json::array();int hz=120,substeps=1,stride=4,last=-1;size_t count=0;
    Recorder(const json& first,int maximum_steps,bool periodic):hz(periodic?60:120),substeps(periodic?16:1),count(first.size()){
        if(count>5000)throw std::runtime_error("Motion body budget");
        // 256 bytes/pose plus bounded identity/frame overhead; exact dump cap follows.
        size_t header=count*256+65536,per_frame=count*256+256;
        size_t allowed=std::min(MAX_FRAMES,(MAX_BYTES-header)/per_frame);
        if(count)allowed=std::min(allowed,MAX_POSES/count);
        if(allowed<2)throw std::runtime_error("Motion initial/final sampling budget");
        stride=std::max(periodic?2:4,int((size_t(maximum_steps)+allowed-2)/(allowed-1)));
        for(const auto& p:first)bodies.push_back({{"id",p.at("id")},{"asset_id",p.at("asset_id")},{"scale",p.at("scale")}});
        observe(first,0,true);
    }
    void observe(const json& poses,int step,bool force=false){
        if(step==last||(!force&&step%stride))return;
        if(poses.size()!=count||frames.size()>=MAX_FRAMES||(frames.size()+1)*count>MAX_POSES)throw std::runtime_error("Motion recorded pose/frame budget");
        json positions=json::array(),rotations=json::array();
        for(size_t i=0;i<count;i++){
            const auto& p=poses[i];if(p.at("id")!=bodies[i].at("id")||p.at("asset_id")!=bodies[i].at("asset_id")||p.at("scale")!=bodies[i].at("scale"))throw std::runtime_error("Motion identity changed");
            positions.push_back(p.at("position"));rotations.push_back(p.at("rotation"));
        }
        // Actual completed macro/step count. Periodic observes after all16 updates/wrap.
        frames.push_back({{"step",step},{"time",double(step)/hz},{"positions",positions},{"rotations",rotations}});last=step;
    }
    json finish(const json& poses,int step){
        observe(poses,step,true);
        if(count)for(size_t i=0;i<count;i++)if(frames.back().at("positions")[i]!=poses[i].at("position")||frames.back().at("rotations")[i]!=poses[i].at("rotation"))throw std::runtime_error("Motion final poses differ");
        return {{"schema_version",1},{"coordinate_system","RH_Z_UP"},{"units","meters"},{"bodies",bodies},{"sampling",{{"solver_hz",hz},{"substeps",substeps},{"stride",stride},{"target_hz",30}}},{"frames",frames},{"final_poses_sha256",pose_hash(poses)}};
    }
};
static void publish(json data,const json& request,const json& result,const fs::path& out,const std::string& result_raw){
#ifdef SCATTER_MOTION_BUILD
    auto path=out/"motion-v1.json",temporary=out/"motion-v1.json.tmp";
    if(fs::exists(extended_path(path))||fs::exists(extended_path(temporary)))throw std::runtime_error("Motion immutable output already exists");
    auto executable=[](){std::vector<wchar_t> p(32768);DWORD n=GetModuleFileNameW(nullptr,p.data(),DWORD(p.size()));if(!n||n>=p.size())throw std::runtime_error("Motion executable identity");std::ifstream stream(extended_path(fs::path(std::wstring(p.data(),n))),std::ios::binary);return std::string(std::istreambuf_iterator<char>(stream),{});}();
    data["producer"]={{"implementation_version","0.4.0-motion.1"},{"build_fingerprint",SCATTER_MOTION_BUILD_FINGERPRINT},{"binary_sha256",sha256(executable)}};
    data["source_job_id"]=result.at("job_id");data["result_sha256"]=sha256(result_raw);data["physics_input_hash"]=request.at("physics_input_hash");data["pose_origin"]=result.at("pose_origin");
    auto raw=data.dump();if(raw.size()>MAX_BYTES)throw std::runtime_error("Motion JSON exceeds8MiB; no completed event");
    HANDLE handle=CreateFileW(extended_path(temporary).c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(handle==INVALID_HANDLE_VALUE)throw std::runtime_error("Motion exclusive file creation failed");
    DWORD written=0;bool good=WriteFile(handle,raw.data(),DWORD(raw.size()),&written,nullptr)&&written==raw.size()&&FlushFileBuffers(handle);CloseHandle(handle);
    if(!good)throw std::runtime_error("Motion byte write failed");
    std::error_code error;fs::rename(extended_path(temporary),extended_path(path),error);if(error)throw std::runtime_error("Motion atomic publication failed");
#endif
}
}
