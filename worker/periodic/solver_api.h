#pragma once
#include <Jolt/Jolt.h>
#include <Jolt/Physics/PhysicsSystem.h>
#include <vector>
#include <cstdint>
namespace scatter_periodic {
struct Metrics {uint64_t updates=0,wraps=0,queries=0,manifolds=0;double friction_excess=0;};
struct DisplacementDemand {
    int current_required_n=4,predicted_required_n=4;
    double max_linear=0,max_angular_radius=0,max_speed=0,gravity_speed=0,limit=0;
};
class Controller {
    struct State;State* state;
public:
    Controller(JPH::PhysicsSystem&,const std::vector<JPH::Body*>&,float width,float depth);
    ~Controller();Controller(const Controller&)=delete;Controller& operator=(const Controller&)=delete;
    static void configure(JPH::PhysicsSystem&);
    DisplacementDemand displacement_demand(float macro_dt) const;
    void begin(float dt);void finish();Metrics metrics()const;
};
}
