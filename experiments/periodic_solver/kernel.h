// P1b standalone solver. Existing worker/protocol/UI and geometry module are read-only.
#pragma once
#include "../periodic_backend/geometry.h"
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Core/JobSystemSingleThreaded.h>
#include <Jolt/Physics/Constraints/TwoBodyConstraint.h>
#include <Jolt/Physics/Constraints/ConstraintPart/AxisConstraintPart.h>
#include <nlohmann/json.hpp>
#include <cfloat>
#include <cstring>
#include <set>
#include <queue>

namespace periodic_solver {
using namespace JPH;using json=nlohmann::json;namespace pg=periodic_geometry;
inline json vector(Vec3Arg v){pg::finite(v);return {v.GetX(),v.GetY(),v.GetZ()};}
inline json invariant_bits(const Body &b){
    const auto *m=b.GetMotionProperties();auto q=b.GetRotation(),r=m->GetInertiaRotation();json a=json::array();
    for(float f:{q.GetX(),q.GetY(),q.GetZ(),q.GetW(),b.GetLinearVelocity().GetX(),b.GetLinearVelocity().GetY(),b.GetLinearVelocity().GetZ(),b.GetAngularVelocity().GetX(),b.GetAngularVelocity().GetY(),b.GetAngularVelocity().GetZ(),m->GetInverseMass(),m->GetInverseInertiaDiagonal().GetX(),m->GetInverseInertiaDiagonal().GetY(),m->GetInverseInertiaDiagonal().GetZ(),r.GetX(),r.GetY(),r.GetZ(),r.GetW()}){uint32_t u;std::memcpy(&u,&f,4);a.push_back(u);}return a;
}
struct Controller;
struct Settings final:TwoBodyConstraintSettings{TwoBodyConstraint *Create(Body &,Body &)const override{throw std::runtime_error("No experimental constraint serialization");}};
struct Point {
    Vec3 local1,local2,r1,r2,t1,t2;AxisConstraintPart normal,f1,f2;bool reused=false;
    Point(Vec3Arg a,Vec3Arg b):local1(a),local2(b),r1(Vec3::sZero()),r2(Vec3::sZero()),t1(Vec3::sZero()),t2(Vec3::sZero()){normal.Deactivate();f1.Deactivate();f2.Deactivate();}
};
class Contact final:public TwoBodyConstraint {
    Controller &owner;
public:
    pg::Key key;uint32_t sub1,sub2;Vec3 n=Vec3::sZero(),L=Vec3::sZero();float mu=0,restitution=0;std::vector<Point> points;uint64_t registered=0,iteration=0;
    Contact(Controller &,Body &,Body &,const pg::Manifold &,float,float);
    void update(const pg::Manifold &,float,float);
    void prepare(const std::map<uint32_t,std::pair<Vec3,Vec3>>&);
    EConstraintSubType GetSubType()const override{return EConstraintSubType::User1;}
    void NotifyShapeChanged(const BodyID &,Vec3Arg)override{throw std::runtime_error("Shape revision requires a new experimental world");}
    void ResetWarmStart()override{for(auto &p:points){p.normal.SetTotalLambda(0);p.f1.SetTotalLambda(0);p.f2.SetTotalLambda(0);}}
    void SetupVelocityConstraint(float)override;
    void BuildIslands(uint32 index,IslandBuilder &builder,BodyManager &manager)override;
    void WarmStartVelocityConstraint(float)override;
    bool SolveVelocityConstraint(float)override;
    bool SolvePositionConstraint(float,float)override;
    Mat44 GetConstraintToBody1Matrix()const override{return Mat44::sIdentity();}
    Mat44 GetConstraintToBody2Matrix()const override{return Mat44::sIdentity();}
    Ref<ConstraintSettings> GetConstraintSettings()const override{return new Settings;}
#ifdef JPH_DEBUG_RENDERER
    void DrawConstraint(DebugRenderer *)const override{}
#endif
};
struct CacheKey {pg::Key pair;uint32_t sub1,sub2;bool operator<(const CacheKey& k)const{return std::tie(pair,sub1,sub2)<std::tie(k.pair,k.sub1,k.sub2);}};
struct Controller {
    PhysicsSystem &physics;std::vector<Body*> bodies;float W,D,dt=0;uint64_t generation=0;bool snapshot_ready=false;
    std::map<CacheKey,Ref<Contact>> cache;std::vector<Contact*> active;std::map<uint32_t,std::pair<Vec3,Vec3>> snapshot;
    json ledger;pg::Broadphase broad;pg::Queries geometry;pg::Budget budget;
    Controller(PhysicsSystem &p,std::vector<Body*> b,float w,float d):physics(p),bodies(std::move(b)),W(w),D(d){reset_ledger();}
    ~Controller(){for(auto &entry:cache)physics.RemoveConstraint(entry.second);}
    void reset_ledger(){ledger={{"setup",0},{"island_links",0},{"warmstart",0},{"warmstart_order",json::array()},{"velocity",0},{"position",0},{"position_corrections",0},{"barriers",0},{"cache_reused_points",0},{"cache_cleared",0},{"wrapped",0},{"wrap_invariant_exact",true},{"wake_activated",json::array()},{"wake_seeds",0},{"normal_impulse_max",0.0},{"friction_projection_excess",0.0}};}
    void increment(const char *name){ledger[name]=ledger[name].get<uint64_t>()+1;}
    void register_active(Contact *c){pg::require(c->registered!=generation,"Duplicate active Setup registration");c->registered=generation;active.push_back(c);increment("setup");}
    void prewarm(){
        if(snapshot_ready)return;
        pg::require(!physics.GetPhysicsSettings().mUseLargeIslandSplitter,"Unsupported island splitter");
        // Setup has already registered the actual active constraints. No inactive
        // candidate or unrelated built-in-only island body is read here.
        for(auto *c:active)for(auto *b:{c->GetBody1(),c->GetBody2()}){auto id=b->GetID().GetIndexAndSequenceNumber();if(!snapshot.count(id)){Vec3 v=b->GetLinearVelocity(),w=b->GetAngularVelocity();pg::finite(v);pg::finite(w);snapshot.emplace(id,std::make_pair(v,w));}}
        for(auto *c:active)c->prepare(snapshot);
        ledger["snapshot"]=json::array();for(const auto &entry:snapshot)ledger["snapshot"].push_back({entry.first,vector(entry.second.first),vector(entry.second.second)});
        snapshot_ready=true;increment("barriers");ledger["snapshot_generation"]=generation;ledger["snapshot_bodies"]=snapshot.size();
    }
    std::vector<pg::Input> inputs(){std::vector<pg::Input> data;data.reserve(bodies.size());for(auto *b:bodies)data.push_back({b,b->GetLinearVelocity(),b->GetAngularVelocity(),physics.GetGravity(),b->GetAccumulatedForce(),b->GetAccumulatedTorque()});return data;}
    void begin(float step_dt){
        dt=step_dt;reset_ledger();++generation;snapshot_ready=false;active.clear();snapshot.clear();
        pg::require(!physics.GetPhysicsSettings().mUseLargeIslandSplitter,"Unsupported island splitter");
        auto installed=physics.GetConstraints();pg::require(installed.size()==cache.size(),"Foreign user constraint");std::set<const Constraint*> allowed;for(auto &c:cache)allowed.insert(c.second.GetPtr());for(auto &c:installed)pg::require(allowed.count(c.GetPtr())!=0,"Foreign user constraint");
        budget=pg::Budget();budget.add(bodies.size(),sizeof(pg::Input)+sizeof(Body*)+sizeof(std::vector<uint32_t>)+sizeof(BodyID)+192);auto in=inputs();broad=pg::candidates(in,W,D,dt,budget);
        budget.add(broad.pairs.size(),2*sizeof(uint32_t));budget.add(cache.size(),sizeof(Contact)+160);for(const auto &entry:cache)budget.add(entry.second->points.size(),sizeof(Point));
        // Conservative dynamic-only wake closure; static ground is not in bodies.
        std::vector<std::vector<uint32_t>> neighbors(bodies.size());for(const auto &p:broad.pairs){neighbors[p.i].push_back(p.j);neighbors[p.j].push_back(p.i);}
        std::vector<bool> reached(bodies.size());std::queue<uint32_t> q;for(uint32_t i=0;i<bodies.size();i++)if(bodies[i]->IsActive()){reached[i]=true;q.push(i);ledger["wake_seeds"]=ledger["wake_seeds"].get<uint64_t>()+1;}
        while(!q.empty()){auto i=q.front();q.pop();for(auto j:neighbors[i])if(!reached[j]){reached[j]=true;q.push(j);}}
        std::vector<BodyID> wake;for(uint32_t i=0;i<bodies.size();i++)if(reached[i]&&!bodies[i]->IsActive()){wake.push_back(bodies[i]->GetID());ledger["wake_activated"].push_back(bodies[i]->GetID().GetIndexAndSequenceNumber());}
        if(!wake.empty())physics.GetBodyInterface().ActivateBodies(wake.data(),int(wake.size()));
        geometry=pg::Queries();pg::query(in,broad,W,D,budget,geometry);
        std::set<CacheKey> keep;
        for(const auto &m:geometry.manifolds){if(m.key.x==0&&m.key.y==0)continue;CacheKey k{m.key,m.sub1,m.sub2};pg::require(keep.insert(k).second,"Duplicate image manifold");
            budget.add(1,sizeof(Contact)+256);budget.add(m.points.size(),3*sizeof(Point));
            auto it=cache.find(k);if(it==cache.end()){auto body=[&](uint32_t id){for(auto *b:bodies)if(b->GetID().GetIndexAndSequenceNumber()==id)return b;throw std::runtime_error("Image body not owned");};Ref<Contact> c=new Contact(*this,*body(k.pair.a),*body(k.pair.b),m,W,D);physics.AddConstraint(c);cache.emplace(k,c);}else it->second->update(m,W,D);
        }
        for(auto i=cache.begin();i!=cache.end();)if(!keep.count(i->first)){physics.RemoveConstraint(i->second);i=cache.erase(i);increment("cache_cleared");}else ++i;
        ledger["manifold_features"]=json::array();for(const auto &m:geometry.manifolds){json points=json::array();for(const auto &p:m.points)points.push_back({vector(p.chart1),vector(p.chart2)});ledger["manifold_features"].push_back({{"pair",{m.key.a,m.key.b,m.key.x,m.key.y}},{"normal",vector(m.normal)},{"depth",m.depth},{"points",points}});}
        ledger["wake_candidates"]=broad.pairs.size();ledger["actual_manifolds"]=geometry.manifolds.size();ledger["image_constraints"]=cache.size();ledger["query_calls"]=geometry.calls;ledger["work_bytes"]=budget.used;
    }
    void finish();
};
inline Contact::Contact(Controller &o,Body &a,Body &b,const pg::Manifold &m,float W,float D):TwoBodyConstraint(a,b,Settings()),owner(o),key(m.key),sub1(m.sub1),sub2(m.sub2){update(m,W,D);}
inline void Contact::update(const pg::Manifold &m,float W,float D){
    Vec3 old_n=n;auto previous=std::move(points);n=m.normal;L=Vec3(float(m.key.x*W),float(m.key.y*D),0);key=m.key;sub1=m.sub1;sub2=m.sub2;
    SubShapeID s1,s2;s1.SetValue(sub1);s2.SetValue(sub2);
    mu=owner.physics.GetCombineFriction()(*mBody1,s1,*mBody2,s2);restitution=owner.physics.GetCombineRestitution()(*mBody1,s1,*mBody2,s2);
    std::vector<bool> used(previous.size());points.clear();points.reserve(m.points.size());
    for(const auto &p:m.points){Point next(p.local1,p.local2);int best=-1;float distance=owner.physics.GetPhysicsSettings().mContactPointPreserveLambdaMaxDistSq;
        if(!previous.empty()&&old_n.Dot(n)>=owner.physics.GetPhysicsSettings().mContactNormalCosMaxDeltaRotation)for(int i=0;i<int(previous.size());i++){float d=(p.local1-previous[i].local1).LengthSq()+(p.local2-previous[i].local2).LengthSq();if(!used[i]&&d<=distance){distance=d;best=i;}}
        if(best>=0){auto &old=previous[best];used[best]=true;next.normal.SetTotalLambda(old.normal.GetTotalLambda());Vec3 impulse=old.t1*old.f1.GetTotalLambda()+old.t2*old.f2.GetTotalLambda();next.t1=n.GetNormalizedPerpendicular();next.t2=n.Cross(next.t1);next.f1.SetTotalLambda(impulse.Dot(next.t1));next.f2.SetTotalLambda(impulse.Dot(next.t2));next.reused=true;owner.increment("cache_reused_points");}
        points.push_back(next);
    }
}
inline void Contact::SetupVelocityConstraint(float){iteration=0;owner.register_active(this);}
inline void Contact::BuildIslands(uint32 index,IslandBuilder &builder,BodyManager &manager){TwoBodyConstraint::BuildIslands(index,builder,manager);owner.increment("island_links");}
inline void Contact::prepare(const std::map<uint32_t,std::pair<Vec3,Vec3>> &snapshot){
    auto one=snapshot.at(mBody1->GetID().GetIndexAndSequenceNumber()),two=snapshot.at(mBody2->GetID().GetIndexAndSequenceNumber());Vec3 relative=Vec3(mBody2->GetCenterOfMassPosition())+L-Vec3(mBody1->GetCenterOfMassPosition());
    for(auto &p:points){Vec3 a=mBody1->GetRotation()*p.local1,b=relative+mBody2->GetRotation()*p.local2,mid=.5f*(a+b);p.r1=mid;p.r2=mid-relative;p.t1=n.GetNormalizedPerpendicular();p.t2=n.Cross(p.t1);
        float vn=n.Dot(two.first+two.second.Cross(p.r2)-one.first-one.second.Cross(p.r1));float penetration=(a-b).Dot(n),speculative=std::max(0.0f,-penetration/owner.dt);float bias=speculative;
        if(restitution>0&&vn<-owner.physics.GetPhysicsSettings().mMinVelocityForRestitution&&vn<-speculative)bias=restitution*vn;
        p.normal.CalculateConstraintProperties(*mBody1,p.r1,*mBody2,p.r2,n,bias);p.f1.CalculateConstraintProperties(*mBody1,p.r1,*mBody2,p.r2,p.t1);p.f2.CalculateConstraintProperties(*mBody1,p.r1,*mBody2,p.r2,p.t2);
    }
}
inline void Contact::WarmStartVelocityConstraint(float ratio){pg::require(registered==owner.generation,"Unregistered warmstart");owner.prewarm();pg::require(owner.snapshot_ready,"Snapshot barrier missing");owner.increment("warmstart");owner.ledger["warmstart_order"].push_back({key.a,key.b,key.x,key.y});for(auto &p:points){p.f1.WarmStart(*mBody1,*mBody2,p.t1,ratio);p.f2.WarmStart(*mBody1,*mBody2,p.t2,ratio);p.normal.WarmStart(*mBody1,*mBody2,n,ratio);}}
inline bool Contact::SolveVelocityConstraint(float){
    owner.increment("velocity");bool changed=false;auto *a=mBody1->GetMotionProperties(),*b=mBody2->GetMotionProperties();float ma=a->GetInverseMass(),mb=b->GetInverseMass();size_t point_index=0;
    for(auto &p:points){float x=p.f1.TemplatedSolveVelocityConstraintGetTotalLambda<EMotionType::Dynamic,EMotionType::Dynamic>(a,b,p.t1),y=p.f2.TemplatedSolveVelocityConstraintGetTotalLambda<EMotionType::Dynamic,EMotionType::Dynamic>(a,b,p.t2),limit=mu*p.normal.GetTotalLambda();float square=x*x+y*y;if(square>limit*limit){float scale=limit/std::sqrt(square);x*=scale;y*=scale;}
        double excess=std::max(0.0,std::sqrt(double(x)*x+double(y)*y)-limit);uint64_t samples=owner.ledger.value("friction_projection_samples",uint64_t(0));owner.ledger["friction_projection_samples"]=samples+1;
        if(!owner.ledger.contains("friction_projection_witness")||excess>owner.ledger["friction_projection_excess"].get<double>())owner.ledger["friction_projection_witness"]={{"mu",mu},{"previous_normal_lambda",p.normal.GetTotalLambda()},{"projected_t1",x},{"projected_t2",y},{"pair",{key.a,key.b,key.x,key.y}},{"local1",vector(p.local1)},{"local2",vector(p.local2)},{"point_index",point_index},{"local_iteration",iteration},{"substep_generation",owner.generation},{"excess",excess}};
        owner.ledger["friction_projection_excess"]=std::max(owner.ledger["friction_projection_excess"].get<double>(),excess);++point_index;
        changed|=p.f1.TemplatedSolveVelocityConstraintApplyLambda<EMotionType::Dynamic,EMotionType::Dynamic>(a,ma,b,mb,p.t1,x);changed|=p.f2.TemplatedSolveVelocityConstraintApplyLambda<EMotionType::Dynamic,EMotionType::Dynamic>(a,ma,b,mb,p.t2,y);
    }
    for(auto &p:points)changed|=p.normal.SolveVelocityConstraint(*mBody1,*mBody2,n,0,FLT_MAX);
    ++iteration;return changed;
}
inline bool Contact::SolvePositionConstraint(float,float baumgarte){
    owner.increment("position");bool changed=false;const auto &s=owner.physics.GetPhysicsSettings();
    for(auto &p:points){Vec3 relative=Vec3(mBody2->GetCenterOfMassPosition())+L-Vec3(mBody1->GetCenterOfMassPosition()),a=mBody1->GetRotation()*p.local1,b=relative+mBody2->GetRotation()*p.local2;float C=std::max((b-a).Dot(n)+s.mPenetrationSlop,-s.mMaxPenetrationDistance);
        if(C<0){Vec3 mid=.5f*(a+b);p.normal.CalculateConstraintProperties(*mBody1,mid,*mBody2,mid-relative,n);if(p.normal.SolvePositionConstraint(*mBody1,*mBody2,n,C,baumgarte)){changed=true;owner.increment("position_corrections");}}
    }return changed;
}
inline void Controller::finish(){
    ledger["impulses"]=json::array();for(auto &entry:cache)for(const auto &p:entry.second->points){double normal=p.normal.GetTotalLambda(),t=std::sqrt(double(p.f1.GetTotalLambda())*p.f1.GetTotalLambda()+double(p.f2.GetTotalLambda())*p.f2.GetTotalLambda());pg::require(std::isfinite(normal)&&std::isfinite(t)&&normal>=-1e-6,"Invalid contact impulse");ledger["normal_impulse_max"]=std::max(ledger["normal_impulse_max"].get<double>(),normal);ledger["impulses"].push_back({{"pair",{entry.first.pair.a,entry.first.pair.b,entry.first.pair.x,entry.first.pair.y}},{"local1",vector(p.local1)},{"local2",vector(p.local2)},{"normal",normal},{"tangent",{p.f1.GetTotalLambda(),p.f2.GetTotalLambda()}},{"final_normal_disk_excess_observation",std::max(0.0,t-entry.second->mu*normal)}});}
    // A wrap invalidates the experimental image cache; it never transfers stale
    // lambda to a different image or attempts to inject a builtin contact cache.
    ledger["wraps"]=json::array();bool wrapped=false;for(auto *b:bodies){auto plan=pg::wrap_plan(*b,W,D);if(plan.shift!=Vec3::sZero()){auto before=invariant_bits(*b);auto old_com=vector(Vec3(b->GetCenterOfMassPosition())),old_origin=vector(Vec3(b->GetPosition()));physics.GetBodyInterface().SetPosition(b->GetID(),RVec3(plan.origin),EActivation::DontActivate);physics.GetBodyInterface().InvalidateContactCache(b->GetID());pg::require(before==invariant_bits(*b),"Wrap changed q/v/omega/mass/inertia bytes");ledger["wraps"].push_back({{"body",b->GetID().GetIndexAndSequenceNumber()},{"before_COM",old_com},{"before_render_origin",old_origin},{"shift",vector(plan.shift)},{"after_COM",vector(Vec3(b->GetCenterOfMassPosition()))},{"after_render_origin",vector(Vec3(b->GetPosition()))},{"before_bits",before},{"after_bits",invariant_bits(*b)}});wrapped=true;increment("wrapped");}}
    if(wrapped){for(auto &entry:cache){physics.RemoveConstraint(entry.second);increment("cache_cleared");}cache.clear();}
}
} // namespace periodic_solver
