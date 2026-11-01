// TEST ONLY: exercise the production shared baker without a physics/protocol bypass.
#define main scatter_protocol_main_unused
#define wmain scatter_protocol_wmain_unused
#include "../worker/main.cpp"
#undef main
#undef wmain

int wmain(int argc,wchar_t** argv){
    try{
        require(argc==3&&std::wstring(argv[1])==L"--test-only-fixtures","TEST_ONLY fixed fixture argument required");
        const auto path=fs::weakly_canonical(fs::path(argv[2]));auto spec=review_n1::strict_json(review_n1::bytes(path,MIB));review_n1::fields(spec,{"TEST_ONLY","cases"});require(spec.at("TEST_ONLY")==true&&spec.at("cases").is_array()&&spec.at("cases").size()==5,"Exactly five fixed bake fixtures required");
        json observations=json::array();unsigned calls=0,guards=0;bool tie_checked=false;
        for(const auto& item:spec.at("cases")){
            review_n1::fields(item,{"id","poses","expanded_poses","periodic_request","expanded_request"});json observed={{"id",item.at("id")}};
            for(bool periodic:{true,false}){
                auto rp=review_n1::owned(fs::u8path(item.at(periodic?"periodic_request":"expanded_request").get<std::string>()),path.parent_path());auto request=review_n1::strict_json(review_n1::bytes(rp,MIB));
                job=request.at("job_id").get<std::string>();require(hexid(job,32),"TEST_ONLY job identity");auto out=review_n1::owned(fs::u8path(request.at("output_directory").get<std::string>()),path.parent_path());fs::create_directories(extended_path(out));
                auto values=assets(request);auto poses=item.at(periodic?"poses":"expanded_poses");const auto& sim=request.at("simulation");const auto& bake=request.at("bake");auto context=review_n2::prepare(request,values,out,"bake",sim,bake);
                if(!tie_checked){
                    for(double invalid:{std::numeric_limits<double>::infinity(),9007199254740992.}){bool rejected=false;try{(void)review_n2::lattice_bound(invalid,true);}catch(const std::exception&){rejected=true;}require(rejected,"Periodic lattice overflow guard failed");++guards;}
                    Tri triangle{{-1,-1,.5},{1,-1,.5},{0,1,.5},{0,0,1}};BVH scene({triangle,triangle});std::vector<review_n2::Ref> refs{{0,0,0,7,0,0},{0,0,0,7,-1,1}};review_n2::Hit top;review_n2::hit(scene,refs,0,0,0,top);require(top.covered&&top.index==1,"Periodic exact-height image tie order failed");tie_checked=true;
                }
                auto maps=review_n2::bake(context,values,poses,sim,bake,out,true);++calls;observed[periodic?"periodic_out":"expanded_out"]=out.u8string();observed[periodic?"periodic_maps":"expanded_maps"]=maps;
            }
            observations.push_back(observed);
        }
        std::cout<<json{{"status","TEST_ONLY_BAKE_PROBE_COMPLETE"},{"physics_calls",0},{"bake_calls",calls},{"lattice_guard_rejections",guards},{"tie_order_checked",tie_checked},{"cases",observations}}.dump()<<std::endl;return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<std::endl;return 1;}
}
