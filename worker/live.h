// Interactive observation/pacing only. Fixed physics dt and solver are unchanged.
#pragma once
#include <chrono>
#include <thread>
namespace live_v1 {
static std::string environment(const char* key){char buffer[64]{};DWORD n=GetEnvironmentVariableA(key,buffer,DWORD(sizeof(buffer)));require(n<sizeof(buffer),"Live environment value bound");return std::string(buffer,n);}
struct Observer {
    json header;fs::path out;int hz=120,last=-1;std::chrono::steady_clock::time_point started;
    Observer(const json& request,const fs::path& directory):out(directory),started(std::chrono::steady_clock::now()){
        std::string n=environment("SCATTER_LIVE_NONCE");
        require(n.size()==32&&n.find_first_not_of("0123456789abcdef")==std::string::npos,"Live nonce must be32hex");
        hz=request.at("physics_input_format_version")==3?60:120;
        std::vector<wchar_t> exe(32768);DWORD length=GetModuleFileNameW(nullptr,exe.data(),DWORD(exe.size()));require(length>0&&length<exe.size(),"Live executable path");
        fs::path path(std::wstring(exe.data(),length));require(file_bytes(path)<=64*MIB,"Live executable size");std::ifstream f(extended_path(path),std::ios::binary);std::string bytes(std::istreambuf_iterator<char>(f),{});require(bool(f)||f.eof(),"Live executable read");
        header={{"schema_version",1},{"job_id",job},{"nonce",n},{"process_id",GetCurrentProcessId()},{"producer",{{"implementation_version","0.4.0-live.1"},{"build_fingerprint",SCATTER_MOTION_BUILD_FINGERPRINT},{"binary_sha256",sha256(bytes)}}},{"physics_input_hash",request.at("physics_input_hash")},{"coordinate_system","RH_Z_UP"},{"units","meters"},{"ready_status",environment("SCATTER_LIVE_WAIT_READY")=="1"?"waiting":"not_requested"}};
        for(auto cursor=out;!cursor.empty();cursor=cursor.parent_path()){
            DWORD attributes=GetFileAttributesW(extended_path(cursor).c_str());require(attributes!=INVALID_FILE_ATTRIBUTES&&!(attributes&FILE_ATTRIBUTE_REPARSE_POINT),"Live output parent missing/reparse");if(cursor==cursor.parent_path())break;
        }
    }
    void publish(const json& poses,int step,const char* phase="simulate"){
        if(last<0)started=std::chrono::steady_clock::now();
        require(poses.size()<=5000,"Live body budget");json bodies=json::array(),positions=json::array(),rotations=json::array();
        for(const auto& p:poses){bodies.push_back({{"id",p.at("id")},{"asset_id",p.at("asset_id")},{"scale",p.at("scale")}});positions.push_back(p.at("position"));rotations.push_back(p.at("rotation"));}
        json frame=header;frame["sequence"]=step+1;frame["step"]=step;frame["time"]=double(step)/hz;frame["phase"]=phase;frame["bodies"]=bodies;frame["positions"]=positions;frame["rotations"]=rotations;
        auto raw=frame.dump();require(raw.size()<=8*MIB,"Live latest frame exceeds8MiB");
        auto target=out/"live-frame-v1.json",temp=out/"live-frame-v1.json.tmp";
        for(const auto& p:{target,temp}){DWORD attr=GetFileAttributesW(extended_path(p).c_str());require(attr==INVALID_FILE_ATTRIBUTES||!(attr&FILE_ATTRIBUTE_REPARSE_POINT),"Live latest reparse");}
        HANDLE h=CreateFileW(extended_path(temp).c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);require(h!=INVALID_HANDLE_VALUE,"Live exclusive temporary creation");
        DWORD count=0;bool okay=WriteFile(h,raw.data(),DWORD(raw.size()),&count,nullptr)&&count==raw.size()&&FlushFileBuffers(h);CloseHandle(h);require(okay,"Live latest write");
        bool moved=false;DWORD last_error=0;for(int retry=0;retry<25;retry++){
            if(MoveFileExW(extended_path(temp).c_str(),extended_path(target).c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)){moved=true;break;}
            last_error=GetLastError();DWORD attrs=GetFileAttributesW(extended_path(target).c_str());
            if((attrs!=INVALID_FILE_ATTRIBUTES&&(attrs&(FILE_ATTRIBUTE_REPARSE_POINT|FILE_ATTRIBUTE_READONLY)))||(last_error!=ERROR_SHARING_VIOLATION&&last_error!=ERROR_LOCK_VIOLATION&&last_error!=ERROR_ACCESS_DENIED))break;
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        if(!moved)throw std::runtime_error("Live atomic replacement failed; Win32="+std::to_string(last_error)+" (sharing/access retry capped50ms)");last=step;
    }
    void pace(int step){std::this_thread::sleep_until(started+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(double(step)/hz)));}
    void wait_ready(const json& poses){
        if(header.at("ready_status")!="waiting")return;
        auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(8);auto path=out/"live-ready-v1.json";
        while(std::chrono::steady_clock::now()<deadline){
            DWORD attributes=GetFileAttributesW(extended_path(path).c_str());
            if(attributes!=INVALID_FILE_ATTRIBUTES){
                require(!(attributes&FILE_ATTRIBUTE_REPARSE_POINT)&&file_bytes(path)<=512,"Live ready file boundary");
                std::ifstream stream(extended_path(path),std::ios::binary);std::string raw(std::istreambuf_iterator<char>(stream),{});require(bool(stream)||stream.eof(),"Live ready read failed");
                auto ack=review_n1::strict_json(raw);review_n1::fields(ack,{"schema_version","job_id","nonce","sequence"});
                require(ack.at("schema_version").is_number_integer()&&ack.at("schema_version")==1&&ack.at("sequence").is_number_integer()&&ack.at("sequence")==1&&ack.at("job_id")==job&&ack.at("nonce")==header.at("nonce"),"Live ready identity mismatch");
                header["ready_status"]="acknowledged";publish(poses,0);started=std::chrono::steady_clock::now();return;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        header["ready_status"]="timeout";event("progress",{{"stage","live_viewer_ready_timeout"},{"fraction",0}});publish(poses,0);started=std::chrono::steady_clock::now();
    }
};
static std::unique_ptr<Observer> observer;
static bool enabled(){return environment("SCATTER_LIVE_PREVIEW")=="1";}
}
