// Protocol boundary only. Simulation and triangle bake math remain in main.cpp.
static constexpr uint64_t PROVENANCE_FILE=16*MIB,PROVENANCE_TOTAL=128*MIB;
static const std::vector<std::string> NEW_FIELDS={"pose_format_version","physics_contract_version","bake_contract_version","physics_input_format_version","physics_input_hash","pose_envelope","pose_origin","origin","key_scheme","execution","legacy_proof","scale_semantics","source_steps","rebake_source","physics_inputs_path","pose_source_path","pose_source_hash","scatter_mask","requested_count","spawned_count","attempt_count","max_attempts","spawn_status","spawn_stop_reason"};
static const std::vector<std::string> SPAWN_FIELDS={"requested_count","spawned_count","attempt_count","max_attempts","spawn_status","spawn_stop_reason","initial_positions"};
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static bool input3(int64_t version){
#ifdef SCATTER_REVIEW_PERIODIC_BUILD
    return version==3;
#else
    return false;
#endif
}
static bool masked_input(const json& value){return value==2||(value.is_number_integer()&&input3(value.get<int64_t>()));}
static json periodic_policy(){return {{"domain_axes","XY"},{"representative","com_half_open"},{"render_pose","asset_origin_same_lattice_shift"},{"solver_contract","jolt5_2_periodic_coupled_v1"},{"mask_sampling","initial_center_input2"}};}
static void periodic_binding(const json& value){require(value.contains("periodic")&&value.at("periodic")==periodic_policy(),"Periodic policy must match the closed contract");}
static void semantic_pose(const json& value){require(value.value("coordinate_system","")=="RH_Z_UP"&&value.value("units","")=="meters"&&value.value("scale_semantics","")=="final_uniform_scale_on_original_vertices","Unsupported pose coordinate/units/scale semantics");}
static void contract(const json& value,bool origin=false){
    for(const char* name:{"pose_format_version","physics_input_format_version","physics_contract_version","bake_contract_version"}){
        if(origin&&std::string(name)=="bake_contract_version")continue;
        require(value.contains(name)&&value[name].is_number_integer(),"Missing/invalid contract version");
        require(std::string(name)=="physics_contract_version"?value[name].get<int64_t>()>0:std::string(name)=="pose_format_version"?value[name]==1:(value[name]==1||value[name]==2||input3(value[name].get<int64_t>())),"Unsupported contract version");
    }require(value.contains("worker_version")&&value["worker_version"].is_string()&&!value["worker_version"].get<std::string>().empty(),"Missing worker version");
    if(input3(value.at("physics_input_format_version").get<int64_t>())){require(value.at("physics_contract_version")==3&&(origin||value.at("bake_contract_version")==3),"Input3 requires physics3/bake3");periodic_binding(value);}
    else require(!value.contains("periodic"),"Legacy contracts cannot contain periodic policy");
}
static void nonnegative_integer(const json& value){require(value.is_number_integer()&&(value.is_number_unsigned()||value.get<int64_t>()>=0),"Metric must be a nonnegative integer, not bool/fraction");}
static void origin_metrics(const json& value){nonnegative_integer(value.at("steps"));require(value.at("settling_status").is_string()&&!value.at("settling_status").get<std::string>().empty(),"Invalid settling status");}
static void bundle_metrics(const json& value){nonnegative_integer(value.at("source_steps"));require(value.at("settling_status").is_string()&&!value.at("settling_status").get<std::string>().empty(),"Invalid source settling status");}
static void execution_metrics(const json& value,const json& request){
    origin_metrics(value);nonnegative_integer(value.at("source_steps"));const auto& execution=value.at("execution");
    require(execution.is_object()&&execution.size()==3&&execution.at("physics_executed").is_boolean(),"Invalid execution record/flag");nonnegative_integer(execution.at("steps"));nonnegative_integer(execution.at("body_count"));
    require(value.at("steps")==value.at("source_steps"),"Result steps/source_steps mismatch");
    if(request.at("operation")=="bake")require(execution==json{{"physics_executed",false},{"body_count",0},{"steps",0}},"Rebake execution must be false/0/0");
    else {
        require(request.at("operation")=="simulate"||request.at("operation")=="simulate_bake","Unknown source operation");
        bool executed=masked_input(value.at("physics_input_format_version"))?!value.at("poses").empty():true;
        require(execution==json{{"physics_executed",executed},{"body_count",value.at("poses").size()},{"steps",value.at("source_steps")}},"Simulation execution/body/steps mismatch");
        for(const char* key:{"job_id","worker_version","physics_contract_version"})require(value.at("pose_origin").at(key)==value.at(key),"Initial simulation origin identity mismatch");
    }
}
static json normalized_sim(const json& source,int version=2){
    json result={{"count",40},{"width",4.0},{"depth",4.0},{"seconds",12.0},{"seed",1},{"edges","walls"},{"friction",.6},{"restitution",.05}};
    require(source.is_object(),"Invalid simulation object");if(input3(version))require(source.size()==result.size()||(source.size()==result.size()+1&&source.contains("placement_jitter")),"Input3 requires exact simulation keys");for(auto it=source.begin();it!=source.end();++it){if(it.key()=="placement_jitter"){require(it.value().is_boolean(),"Invalid placement_jitter");if(it.value().get<bool>())result[it.key()]=true;continue;}require(result.contains(it.key()),"Unknown simulation field/global scale");result[it.key()]=it.value();}
    for(auto name:{"count","seed","width","depth","seconds","friction","restitution"}){
        require(result[name].is_number()&&!result[name].is_boolean(),"Invalid simulation number/bool");double value=result[name].get<double>();require(std::isfinite(value),"Non-finite simulation number");
        if(std::string(name)=="count")require(result[name].is_number_integer()&&value>=1&&value<=5000,"Invalid count");
        else if(std::string(name)=="seed")require(result[name].is_number_integer()&&value>=0&&value<=4294967295.0,"Invalid seed");
        else {double low=0,high=1;if(std::string(name)=="width"||std::string(name)=="depth"){low=.1;high=1000;}else if(std::string(name)=="seconds"){low=.1;high=120;}else if(std::string(name)=="friction")high=2;
            require(value>=low&&value<=high,"Simulation number out of range");result[name]=value==0?0.0:value;}
    }require(input3(version)?result["edges"]=="periodic":(result["edges"]=="walls"||result["edges"]=="open"),"Simulation edges differ from input contract");return result;
}
static json mask_identity(const json& descriptor){
    if(descriptor.is_null())return nullptr;require(descriptor.is_object(),"Invalid Mask descriptor");
    for(auto it=descriptor.begin();it!=descriptor.end();++it)require(it.key()=="content_hash"||it.key()=="format"||it.key()=="interpretation"||it.key()=="sampling"||it.key()=="placement"||it.key()=="path"||it.key()=="source_name","Unknown Mask descriptor field");
    require(hexid(descriptor.at("content_hash"),64)&&descriptor.at("format")=="png"&&descriptor.at("interpretation")=="raw_linear_probability"&&descriptor.at("sampling")=="nearest"&&descriptor.at("placement")=="grid_rejection_v1","Unsupported Mask policy");
    return {{"content_hash",descriptor.at("content_hash")},{"format","png"},{"interpretation","raw_linear_probability"},{"sampling","nearest"},{"placement","grid_rejection_v1"}};
}
static json physical_identity(const json& request){require(!request.contains("physics_input_format_version")||(request.at("physics_input_format_version").is_number_integer()&&(request.at("physics_input_format_version")==1||request.at("physics_input_format_version")==2||request.at("physics_input_format_version")==3)),"Input format integer required");int version=request.value("physics_input_format_version",1);require(version==1||version==2||input3(version),"Unsupported physics input format");
    json result={{"physics_input_format_version",version},{"assets",asset_identity(request.at("assets"))},{"simulation",normalized_sim(request.at("simulation"),version)}};
    if(version==2||input3(version))result["scatter_mask"]=mask_identity(request.value("scatter_mask",json(nullptr)));else require(!request.contains("scatter_mask")||request.at("scatter_mask").is_null(),"Input1 cannot contain active Mask");
    if(input3(version)){periodic_binding(request);require(request.contains("scatter_mask"),"Input3 requires scatter_mask key");result["periodic"]=request.at("periodic");}else require(!request.contains("periodic"),"Legacy input cannot contain periodic policy");return result;
}
static void spawn_metrics(const json& record,const json& physical,const Mask& mask,bool initial=false){
    for(const char* key:{"requested_count","spawned_count","attempt_count","max_attempts"})nonnegative_integer(record.at(key));
    uint64_t n=record.at("requested_count"),count=record.at("spawned_count"),attempt=record.at("attempt_count"),maximum=record.at("max_attempts");
    require(n==physical.at("simulation").at("count")&&count==record.at("poses").size()&&count<=n&&maximum==std::min(uint64_t(50000),n*10)&&attempt<=maximum&&record.at("initial_positions").is_array()&&record.at("initial_positions").size()==count,"Spawn counts/initial positions mismatch");
    for(const auto& p:record.at("initial_positions")){require(p.is_array()&&p.size()==3,"Invalid initial position");for(const auto& v:p)require(v.is_number()&&!v.is_boolean()&&std::isfinite(v.get<double>()),"Invalid/non-finite initial position");}
    auto status=record.at("spawn_status"),reason=record.at("spawn_stop_reason");
    bool valid=(status=="complete"&&reason=="requested_count_reached"&&count==n&&attempt>=n);
    valid=valid||(status==(count?"partial":"empty")&&count<n&&reason=="attempts_exhausted"&&attempt==maximum);
    valid=valid||(status==(count?"partial":"empty")&&count<n&&reason=="initial_height_limit"&&attempt>=1);
    valid=valid||(status=="empty"&&reason=="all_black"&&count==0&&attempt==0);
    require(valid,"Invalid spawn status/reason");require(mask.black()==(reason=="all_black"),"all-black reason does not match actual decoded Mask");origin_metrics(record);
    require(count?(record.at("settling_status")!="not_run"):(record.at("steps")==0&&record.at("settling_status")=="not_run"),"Spawn physics steps/settling inconsistent");
    if(initial){const auto& e=record.at("execution");require(e.at("physics_executed").is_boolean(),"Initial execution flag invalid");nonnegative_integer(e.at("body_count"));nonnegative_integer(e.at("steps"));
        require(e==json{{"physics_executed",count>0},{"body_count",count},{"steps",record.at("steps")}},"Initial execution/spawn mismatch");}
}
static std::string protocol_key(const std::string& hash,int64_t version){require(hexid(hash,64)&&version>0,"Invalid physics key material");return sha256("physics_input_v1\n"+hash+"\n"+std::to_string(version)+"\n");}
static bool pure_legacy(const json& value){for(const auto& name:NEW_FIELDS)if(value.contains(name))return false;return true;}
static fs::path extended_path(const fs::path& path){std::wstring value=fs::absolute(path).native();if(value.rfind(L"\\\\?\\",0)==0)return path;
    if(value.rfind(L"\\\\",0)==0)return fs::path(L"\\\\?\\UNC\\"+value.substr(2));return fs::path(L"\\\\?\\"+value);}
static std::string legacy_previous(const json& request){
    std::string path=request.at("poses_path");std::replace(path.begin(),path.end(),'\\','/');auto marker=path.rfind("/runs/");
    require(marker!=std::string::npos&&fs::u8path(path).is_absolute()&&path.find("/../")==std::string::npos,"Legacy poses_path escapes expected run layout");
    std::string tail=path.substr(marker+6);require(tail.size()==44&&tail.substr(32)=="/result.json"&&hexid(tail.substr(0,32),32),"Legacy poses_path invalid run identity");
    std::string output=request.at("output_directory");std::replace(output.begin(),output.end(),'\\','/');auto own=output.rfind("/runs/");
    require(own!=std::string::npos&&output.substr(own+6)==request.at("job_id").get<std::string>()&&output.substr(0,own)==path.substr(0,marker),"Legacy poses_path root mismatch");return tail.substr(0,32);
}
namespace review_n1 {static json strict_json(const std::string& raw);}
class ProtocolFiles {
public:
    fs::path root;uint64_t total=0;std::map<std::string,std::string> raw;bool strict=false;
    explicit ProtocolFiles(fs::path directory,bool strict3=false):root(fs::weakly_canonical(extended_path(directory))),strict(strict3){}
    json read(const fs::path& path,const std::string& expected=""){
        event("progress",{{"stage","provenance_read"},{"fraction",0},{"path",path.u8string()}});
        fs::path canonical=fs::weakly_canonical(extended_path(path)),relative=fs::relative(canonical,root);
        require(!relative.empty()&&!relative.is_absolute()&&*relative.begin()!="..","Provenance path escapes job");
        fs::path io_path=extended_path(canonical);std::error_code error;uint64_t size=fs::file_size(io_path,error);require(!error,"Cannot stat provenance file");require(size<=PROVENANCE_FILE,"Provenance file exceeds 16 MiB");
        require((!expected.empty()&&raw.count(expected))||total+size<=PROVENANCE_TOTAL,"Provenance exceeds 128 MiB before read");
        std::string bytes(size,'\0');std::ifstream stream(io_path,std::ios::binary);stream.read(bytes.data(),std::streamsize(size));
        require(bool(stream)&&stream.peek()==std::char_traits<char>::eof()&&fs::file_size(io_path,error)==size&&!error,"Provenance file changed during read");
        std::string hash=sha256(bytes);require(expected.empty()||hash==expected,"Provenance raw SHA mismatch");
        if(!raw.count(hash)){require(total+size<=PROVENANCE_TOTAL,"Provenance exceeds 128 MiB unique bytes");total+=size;raw[hash]=std::move(bytes);}
        json decoded=strict?review_n1::strict_json(raw.at(hash)):json::parse(raw.at(hash));event("progress",{{"stage","provenance_read"},{"fraction",1},{"path",path.u8string()}});return decoded;
    }
    json blob(const std::string& hash){require(hexid(hash,64),"Invalid provenance hash");return read(root/"provenance"/(hash+".json"),hash);}
};
static void check_legacy_chain(const json& bundle,const json& physical,ProtocolFiles& files){
    bundle_metrics(bundle);
    require(bundle.at("origin").at("worker_version")=="0.2.0"&&bundle.at("origin").at("physics_contract_version").is_number_integer()&&bundle.at("origin").at("physics_contract_version")==1,"Legacy origin producer mismatch");
    const auto& chain=bundle.at("legacy_chain");require(chain.is_array()&&!chain.empty()&&chain.size()<=64,"Legacy chain limit");std::set<std::string> visited;
    for(size_t i=0;i<chain.size();i++){
        const auto& step=chain[i];std::string id=step.at("job_id");require(hexid(id,32)&&visited.insert(id).second,"Legacy chain cycle/identity");
        json request=files.blob(step.at("request_sha256")),result=files.blob(step.at("result_sha256")),material=files.blob(step.at("key_material_sha256"));
        origin_metrics(result);require(result.at("steps")==bundle.at("source_steps")&&result.at("settling_status")==bundle.at("settling_status"),"Legacy source steps/settling mismatch");
        require(pure_legacy(request)&&!request.contains("worker_version")&&pure_legacy(result)&&request.at("schema_version")==2&&result.at("schema_version")==2&&result.at("worker_version")=="0.2.0","Unsupported/partial legacy source");
        require(request.at("job_id")==id&&result.at("job_id")==id&&request.at("simulation_key")==bundle.at("simulation_key")&&result.at("simulation_key")==bundle.at("simulation_key"),"Legacy job/key identity mismatch");
        require(physical_identity(request)==physical&&asset_identity(result.at("assets"))==physical.at("assets")&&result.at("poses")==bundle.at("poses"),"Legacy physics/assets/pose mismatch");
        require(result.at("coordinate_system")=="RH_Z_UP"&&result.at("units")=="meters","Legacy coordinate/units mismatch");
        require(step.at("key_material_sha256")==bundle.at("simulation_key")&&material.at("worker")=="0.2.0"&&material.at("assets")==asset_identity(request.at("assets"))&&material.at("simulation")==request.at("simulation"),"Old Python key-material raw SHA/semantics mismatch");
        if(i+1<chain.size())require(request.at("operation")=="bake"&&legacy_previous(request)==chain[i+1].at("job_id"),"Legacy chain path/order mismatch");
        else {
            require((request.at("operation")=="simulate"||request.at("operation")=="simulate_bake")&&id==bundle.at("origin").at("job_id")&&step.at("result_sha256")==bundle.at("origin").at("record_sha256"),"Legacy initial origin unresolved");
            require(bundle.at("source_steps")==result.at("steps")&&bundle.at("settling_status")==result.at("settling_status"),"Legacy source steps mismatch");
        }
    }
}
static json verify_inputs(const json& request,const fs::path& out){
    contract(request);semantic_pose(request);require(request.at("worker_version")==VERSION,"Current worker version mismatch");
    bool p3=input3(request.at("physics_input_format_version").get<int64_t>());
    require(request.at("pose_format_version")==1&&(p3?(request.at("physics_contract_version")==3&&request.at("bake_contract_version")==3):(request.at("physics_contract_version")==2&&request.at("bake_contract_version")==2&&(request.at("physics_input_format_version")==1||request.at("physics_input_format_version")==2))),"Current worker contract mismatch");
    ProtocolFiles files(out,p3);json physical=files.read(out/"physics_inputs.json",request.at("physics_input_hash"));
    require(physical==physical_identity(request),"physics_inputs raw bytes do not match request semantics");
    if(p3)require(physical.is_object()&&physical.size()==5&&request.at("key_scheme").is_string()&&request.at("key_scheme")=="physics_input_v1"&&hexid(request.at("simulation_key"),64)&&protocol_key(request.at("physics_input_hash"),3)==request.at("simulation_key"),"Input3 exact physical keys/raw key binding");
    if(request.at("operation")!="bake")require(masked_input(request.at("physics_input_format_version"))&&request.at("key_scheme")=="physics_input_v1"&&protocol_key(request.at("physics_input_hash"),p3?3:2)==request.at("simulation_key"),"New simulation key mismatch before physics");return physical;
}
static json load_source(const json& request,const fs::path& out,const json& physical,const Mask& mask){
    ProtocolFiles files(out,input3(physical.at("physics_input_format_version").get<int64_t>()));files.read(out/"physics_inputs.json",request.at("physics_input_hash"));
    json bundle=files.read(out/"pose_source.json",request.at("pose_source_hash"));
    require(bundle.at("input_format_version")==physical.at("physics_input_format_version"),"Pose source input format mismatch");
    bundle_metrics(bundle);
    require(bundle.at("key_scheme")==request.at("key_scheme")&&bundle.at("simulation_key")==request.at("simulation_key"),"Pose source key mismatch");
    bool p3=input3(physical.at("physics_input_format_version").get<int64_t>());
    if(p3)require(bundle.at("input_format_version").is_number_integer()&&bundle.at("input_format_version")==3&&bundle.at("key_scheme").is_string()&&bundle.at("key_scheme")=="physics_input_v1"&&hexid(bundle.at("simulation_key"),64)&&protocol_key(request.at("physics_input_hash"),3)==bundle.at("simulation_key"),"Saved3 format/scheme/raw key binding");
    const auto& source=bundle.at("source");require(hexid(source.at("job_id"),32),"Invalid source job");
    json previous=files.blob(source.at("record_sha256")),previous_request=files.blob(bundle.at("source_request_sha256"));
    origin_metrics(previous);require(previous.at("steps")==bundle.at("source_steps")&&previous.at("settling_status")==bundle.at("settling_status"),"Immediate source steps/settling mismatch");
    require(previous.at("job_id")==source.at("job_id")&&previous_request.at("job_id")==source.at("job_id")&&previous.at("worker_version")==source.at("worker_version")&&previous.at("poses")==bundle.at("poses"),"Immediate source identity/pose mismatch");
    require(physical_identity(previous_request)==physical&&asset_identity(previous.at("assets"))==physical.at("assets"),"Source physics input changed");
    if(bundle.at("kind")=="legacy"){
        event("progress",{{"stage","legacy_provenance"},{"fraction",0}});
        require(previous.at("worker_version")=="0.2.0"&&bundle.at("origin_kind")=="legacy_result"&&bundle.at("key_scheme")=="legacy_0_2_0"&&bundle.at("legacy_chain")[0].at("result_sha256")==source.at("record_sha256"),"Legacy immediate source mismatch");
        check_legacy_chain(bundle,physical,files);
        event("progress",{{"stage","legacy_provenance"},{"fraction",1}});
    }else {
        require(bundle.at("kind")=="new","Unknown source kind");contract(previous);contract(previous_request);semantic_pose(previous);semantic_pose(previous_request);semantic_pose(previous.at("pose_envelope"));
        require(previous_request.at("schema_version")==2&&previous.at("schema_version")==2&&previous.at("status")=="completed"&&previous.at("operation")==previous_request.at("operation"),"Source execution identity");
        for(auto name:{"pose_format_version","physics_contract_version","bake_contract_version","physics_input_format_version"})require(previous.at(name)==previous_request.at(name),"Source request/result contract mismatch");
        execution_metrics(previous,previous_request);
        if(masked_input(physical.at("physics_input_format_version")))spawn_metrics(previous,physical,mask);
        if(p3){for(const auto* record:{&previous_request,&previous}){require(record->at("key_scheme").is_string()&&record->at("key_scheme")=="physics_input_v1"&&hexid(record->at("simulation_key"),64)&&record->at("simulation_key")==request.at("simulation_key"),"Input3 source request/result scheme/key binding");periodic_binding(*record);}require(bundle.at("kind")=="new"&&bundle.at("origin_kind")=="origin_result","Input3 cannot adopt legacy origin");}
        if(previous.at("operation")=="bake"){
            require(bundle.at("source_pose_source_sha256")==previous_request.at("pose_source_hash"),"Source pose-source raw hash mismatch");json consumed=files.blob(bundle.at("source_pose_source_sha256"));
            bundle_metrics(consumed);require(consumed.at("source")==previous.at("rebake_source")&&consumed.at("origin")==bundle.at("origin")&&consumed.at("poses")==bundle.at("poses")&&consumed.at("source_steps")==bundle.at("source_steps")&&consumed.at("settling_status")==bundle.at("settling_status"),"Source immediate provenance tuple mismatch");
            if(p3)require(consumed.at("input_format_version").is_number_integer()&&consumed.at("input_format_version")==3&&consumed.at("key_scheme")==request.at("key_scheme")&&consumed.at("simulation_key")==request.at("simulation_key"),"Consumed Saved3 binding mismatch");
        }
        require(previous_request.at("worker_version")==previous.at("worker_version")&&previous_request.at("simulation_key")==previous.at("simulation_key")&&previous.at("simulation_key")==bundle.at("simulation_key")&&previous.at("key_scheme")==bundle.at("key_scheme"),"New source request/result key mismatch");
        require(previous.at("physics_input_hash")==request.at("physics_input_hash")&&previous_request.at("physics_input_hash")==request.at("physics_input_hash")&&files.read(out/"physics_inputs.json",bundle.at("source_input_sha256"))==physical,"Source exact physical input identity mismatch");
        const auto& envelope=previous.at("pose_envelope");require(envelope.at("pose_format_version")==1&&envelope.at("poses")==bundle.at("poses")&&envelope.at("origin")==bundle.at("origin")&&previous.at("pose_origin")==bundle.at("origin")&&envelope.at("physics_input_hash")==request.at("physics_input_hash")&&envelope.at("simulation_key")==bundle.at("simulation_key")&&envelope.at("key_scheme")==bundle.at("key_scheme"),"Pose envelope mismatch");
        json origin=files.blob(bundle.at("origin").at("record_sha256"));
        origin_metrics(origin);
        require(previous.at("origin").at("record_sha256")==bundle.at("origin").at("record_sha256")&&previous.at("origin").at("kind")==bundle.at("origin_kind"),"Source origin reference mismatch");
        if(bundle.at("origin_kind")=="legacy_result"){require(bundle.at("key_scheme")=="legacy_0_2_0","Legacy origin key scheme");check_legacy_chain(bundle,physical,files);}
        else {
            require(bundle.at("origin_kind")=="origin_result","Unknown origin record kind");contract(origin,true);semantic_pose(origin);
            require(origin.at("job_id")==bundle.at("origin").at("job_id")&&origin.at("worker_version")==bundle.at("origin").at("worker_version")&&origin.at("physics_contract_version")==bundle.at("origin").at("physics_contract_version")&&origin.at("poses")==bundle.at("poses")&&origin.at("physics_input_hash")==request.at("physics_input_hash"),"Initial origin record identity mismatch");
            require(origin.at("simulation_key")==bundle.at("simulation_key")&&origin.at("key_scheme")=="physics_input_v1"&&protocol_key(request.at("physics_input_hash"),origin.at("physics_contract_version"))==bundle.at("simulation_key"),"Initial origin key mismatch");
            require(origin.at("steps")==bundle.at("source_steps")&&origin.at("settling_status")==bundle.at("settling_status"),"Initial origin steps mismatch");
            if(masked_input(physical.at("physics_input_format_version"))){
                require(origin.at("physics_contract_version")== (p3?3:2)&&origin.at("physics_input_format_version")== (p3?3:2),"Origin physics/input contract mismatch");spawn_metrics(origin,physical,mask,true);
                for(const auto& key:SPAWN_FIELDS)require(previous.at(key)==origin.at(key)&&bundle.at("spawn").at(key)==origin.at(key),"Result/source spawn differs from origin");
                if(previous.at("operation")=="bake"){auto consumed=files.blob(bundle.at("source_pose_source_sha256"));require(consumed.at("spawn")==bundle.at("spawn"),"Consumed spawn differs from origin");}
            }
        }
    }return bundle;
}
static void decorate_result(json& result,const json& request,const fs::path& out,const json& bundle){
    bool first=request.at("operation")!="bake",physics=first&&!result.at("poses").empty();json origin;std::string kind,record_hash,record_path;
    int version=input3(request.at("physics_input_format_version").get<int64_t>())?3:2;
    if(first){
        require(request.at("key_scheme")=="physics_input_v1"&&protocol_key(request.at("physics_input_hash"),version)==request.at("simulation_key"),"New simulation key mismatch");
        json record={{"job_id",job},{"worker_version",VERSION},{"pose_format_version",1},{"physics_contract_version",2},{"physics_input_format_version",2},{"key_scheme","physics_input_v1"},{"simulation_key",request.at("simulation_key")},{"physics_input_hash",request.at("physics_input_hash")},{"coordinate_system","RH_Z_UP"},{"units","meters"},{"scale_semantics","final_uniform_scale_on_original_vertices"},{"poses",result.at("poses")},{"steps",result.at("steps")},{"settling_status",result.at("settling_status")}};
        for(const auto& key:SPAWN_FIELDS)record[key]=result.at(key);
        if(version==3){record["physics_contract_version"]=3;record["physics_input_format_version"]=3;record["periodic"]=request.at("periodic");}
        record["execution"]={{"physics_executed",physics},{"body_count",result.at("poses").size()},{"steps",result.at("steps")}};
        require(!fs::exists(extended_path(out/"origin_result.json")),"Origin record already exists");std::string bytes=record.dump(2);require(bytes.size()<=PROVENANCE_FILE,"Origin exceeds 16 MiB before write");{std::ofstream stream(extended_path(out/"origin_result.json"),std::ios::binary);stream.write(bytes.data(),std::streamsize(bytes.size()));stream.close();require(bool(stream),"Origin write failed");}
        record_hash=sha256(bytes);ProtocolFiles verify_origin(out,version==3);require(verify_origin.read(out/"origin_result.json",record_hash)==record,"Origin after-close raw verification failed");record_path="origin_result.json";kind="origin_result";origin={{"job_id",job},{"worker_version",VERSION},{"physics_contract_version",version},{"record_sha256",record_hash}};
    }else {
        origin=bundle.at("origin");record_hash=origin.at("record_sha256");record_path="provenance/"+record_hash+".json";kind=bundle.at("origin_kind");
        result["rebake_source"]=bundle.at("source");if(bundle.contains("legacy_chain"))result["legacy_proof"]=bundle.at("legacy_chain");
        if(masked_input(request.at("physics_input_format_version")))for(const auto& key:SPAWN_FIELDS)result[key]=bundle.at("spawn").at(key);
    }
    result["source_steps"]=first?result.at("steps"):bundle.at("source_steps");result["pose_origin"]=origin;
    result["origin"]={{"record_sha256",record_hash},{"record_path",record_path},{"kind",kind}};
    for(auto name:{"pose_format_version","physics_contract_version","bake_contract_version","physics_input_format_version"})result[name]=request.at(name);
    result["physics_input_hash"]=request.at("physics_input_hash");result["key_scheme"]=request.at("key_scheme");result["operation"]=request.at("operation");result["scale_semantics"]="final_uniform_scale_on_original_vertices";
    result["execution"]={{"physics_executed",physics},{"body_count",physics?result.at("poses").size():0},{"steps",physics?result.at("steps"):json(0)}};
    result["pose_envelope"]={{"pose_format_version",1},{"coordinate_system","RH_Z_UP"},{"units","meters"},{"scale_semantics","final_uniform_scale_on_original_vertices"},{"physics_input_hash",request.at("physics_input_hash")},{"simulation_key",request.at("simulation_key")},{"key_scheme",request.at("key_scheme")},{"poses",result.at("poses")},{"origin",origin}};
    if(version==3)result["periodic"]=request.at("periodic");
    execution_metrics(result,request);
}
