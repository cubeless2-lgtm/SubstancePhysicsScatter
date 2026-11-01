// Compiled /fp:fast separately. The accepted P1 kernel/geometry remain read-only.
#include "solver_api.h"
#include "../../experiments/periodic_solver/kernel.h"
#include <memory>
#include <climits>
namespace scatter_periodic {
namespace ps=periodic_solver;namespace pg=periodic_geometry;using namespace JPH;
struct Controller::State {ps::Controller solver;Metrics metrics;State(PhysicsSystem&p,const std::vector<Body*>&b,float w,float d):solver(p,b,w,d){solver.finish();}};
void Controller::configure(PhysicsSystem&p){auto s=p.GetPhysicsSettings();s.mUseLargeIslandSplitter=false;s.mNumVelocitySteps=16;s.mNumPositionSteps=2;s.mPenetrationSlop=1.0f/1024;s.mMaxPenetrationDistance=1.0f/16;s.mMinVelocityForRestitution=0;s.mSpeculativeContactDistance=0;s.mAllowSleeping=true;p.SetPhysicsSettings(s);}
Controller::Controller(PhysicsSystem&p,const std::vector<Body*>&b,float w,float d):state(new State(p,b,w,d)){}
Controller::~Controller(){delete state;}
DisplacementDemand Controller::displacement_demand(float macro_dt)const{
    pg::require(std::isfinite(macro_dt)&&macro_dt>0&&macro_dt<=1.0f/60,"Periodic macro dt");
    auto&s=state->solver;DisplacementDemand out;out.limit=std::min(s.W,s.D)/64.;out.gravity_speed=double(s.physics.GetGravity().Length())*macro_dt;
    for(auto*b:s.bodies){pg::Input in{b,b->GetLinearVelocity(),b->GetAngularVelocity(),s.physics.GetGravity(),b->GetAccumulatedForce(),b->GetAccumulatedTorque()};double radius=pg::bounds(in,1.0f/240,s.W,s.D).radius,linear=double(in.linear.Length()),angular_radius=double(in.angular.Length())*radius;out.max_linear=std::max(out.max_linear,linear);out.max_angular_radius=std::max(out.max_angular_radius,angular_radius);out.max_speed=std::max(out.max_speed,linear+angular_radius);}
    auto required=[&](double speed){double needed=std::ceil(speed*macro_dt/out.limit);pg::require(std::isfinite(needed)&&needed<=double(INT_MAX),"Periodic displacement demand is not representable");return std::max(4,int(needed));};
    out.current_required_n=required(out.max_speed);out.predicted_required_n=required(out.max_speed+out.gravity_speed);return out;
}
void Controller::begin(float dt){pg::require(dt>0&&dt<=1.0f/240,"Periodic substep dt");state->solver.begin(dt);}
void Controller::finish(){auto&s=state->solver;s.finish();auto&m=state->metrics;++m.updates;m.wraps+=s.ledger["wrapped"].get<uint64_t>();m.queries+=s.ledger["query_calls"].get<uint64_t>();m.manifolds+=s.ledger["actual_manifolds"].get<uint64_t>();m.friction_excess=std::max(m.friction_excess,s.ledger["friction_projection_excess"].get<double>());pg::require(m.friction_excess<=1e-6,"Periodic Coulomb projection bound");}
Metrics Controller::metrics()const{return state->metrics;}
}
