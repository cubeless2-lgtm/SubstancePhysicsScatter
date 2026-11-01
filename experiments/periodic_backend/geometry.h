// Query-only periodic geometry. No impulses, integration, sleep or solver policy.
#pragma once
#include <Jolt/Physics/Body/Body.h>
#include <Jolt/Physics/Collision/CollisionDispatch.h>
#include <Jolt/Physics/Collision/CollisionCollectorImpl.h>
#include <Jolt/Physics/Collision/CollideShape.h>
#include <Jolt/Physics/Collision/ManifoldBetweenTwoFaces.h>
#include <Jolt/Physics/Collision/Shape/RotatedTranslatedShape.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <algorithm>
#include <map>
#include <tuple>
#include <vector>
#include <stdexcept>
#include <cmath>

namespace periodic_geometry {
using namespace JPH;
constexpr uint64_t MIB=1024*1024;
struct Limits {size_t bodies=5000,candidates=200000,manifolds=50000,points=200000,cell_entries=2000000,queries=200000;uint64_t bytes=256*MIB;};
struct Budget {
    uint64_t used=0;Limits limits;
    void add(uint64_t count,uint64_t size){if(size&&count>(limits.bytes-used)/size)throw std::runtime_error("periodic additional work budget");used+=count*size;}
};
inline void require(bool ok,const char *what){if(!ok)throw std::runtime_error(what);}
inline void finite(Vec3Arg v){require(std::isfinite(v.GetX())&&std::isfinite(v.GetY())&&std::isfinite(v.GetZ()),"nonfinite geometry");}
struct Input {const Body *body;Vec3 linear,angular,known_acceleration,external_force,external_torque;}; // Bounds only, not integration.
struct Wrap {Vec3 COM,origin,shift;};
inline Wrap wrap_plan(const Body &body,float W,float D){
    require(W>0&&D>0&&std::isfinite(W)&&std::isfinite(D),"wrap domain");
    Vec3 com(body.GetCenterOfMassPosition()),origin(body.GetPosition());finite(com);finite(origin);
    Vec3 shift(-W*std::floor((com.GetX()+W*.5f)/W),-D*std::floor((com.GetY()+D*.5f)/D),0);
    return {com+shift,origin+shift,shift};
}
struct ShapeBounds {AABox current,swept;float radius;};
inline ShapeBounds bounds(const Input &in,float dt,float W,float D){
    require(in.body&&dt>0&&std::isfinite(dt)&&W>0&&D>0&&std::isfinite(W)&&std::isfinite(D),"geometry domain/dt");finite(in.linear);finite(in.angular);finite(in.known_acceleration);finite(in.external_force);finite(in.external_torque);
    require(in.external_force==Vec3::sZero()&&in.external_torque==Vec3::sZero(),"unsupported external force/torque bound");
    const Shape *shape=in.body->GetShape(),*leaf=shape;if(shape->GetSubType()==EShapeSubType::RotatedTranslated)leaf=static_cast<const RotatedTranslatedShape*>(shape)->GetInnerShape();
    require(leaf->GetSubType()==EShapeSubType::Sphere||leaf->GetSubType()==EShapeSubType::Box||leaf->GetSubType()==EShapeSubType::ConvexHull,"unsupported geometry shape");
    AABox local=shape->GetLocalBounds();Vec3 ext=Vec3::sMax(local.mMin.Abs(),local.mMax.Abs());float radius=leaf->GetSubType()==EShapeSubType::Sphere?static_cast<const SphereShape*>(leaf)->GetRadius():ext.Length();
    radius=std::nextafter(radius,INFINITY);
    require(std::isfinite(radius)&&radius>0,"shape radius");require(2*radius<std::min(W,D)*.5f,"oversized or self-image-unsafe bounding sphere");
    AABox current=shape->GetWorldSpaceBounds(in.body->GetCenterOfMassTransform().ToMat44(),Vec3::sReplicate(1));AABox swept=current;
    Vec3 move=dt*in.linear;swept.Encapsulate(AABox(current.mMin+move,current.mMax+move));
    float rotation=radius*std::min(2.0f,in.angular.Length()*dt);swept.ExpandBy(in.known_acceleration.Abs()*(dt*dt)+Vec3::sReplicate(rotation+1.0f/(1<<19)));finite(swept.mMin);finite(swept.mMax);
    return {current,swept,radius};
}
struct Image {uint32_t body;int64_t x,y;AABox box;};
struct Cell {int64_t x,y,z;uint32_t image;bool operator<(const Cell &b)const{return std::tie(x,y,z,image)<std::tie(b.x,b.y,b.z,b.image);}};
struct Key {uint32_t a,b;int64_t x,y;bool operator<(const Key &k)const{return std::tie(a,b,x,y)<std::tie(k.a,k.b,k.x,k.y);}bool operator==(const Key&k)const{return a==k.a&&b==k.b&&x==k.x&&y==k.y;}};
struct Candidate {Key key;uint32_t i,j;};
struct Broadphase {std::vector<Image> images;std::vector<Candidate> pairs;std::vector<ShapeBounds> shapes;uint64_t cell_entries=0,pair_visits=0,duplicates=0;};
inline int64_t integer(double n){require(std::isfinite(n)&&n>=-1073741824.&&n<=1073741824.,"geometry cell/image integer range");return static_cast<int64_t>(n);}
inline Key key(uint32_t a,uint32_t b,int64_t x,int64_t y){require(a!=b,"self-image pair is unsupported");return a<b?Key{a,b,x,y}:Key{b,a,-x,-y};}
inline Broadphase candidates(const std::vector<Input>& bodies,float W,float D,float dt,Budget &budget){
    require(!bodies.empty()&&bodies.size()<=budget.limits.bodies,"body budget");Broadphase out;budget.add(bodies.size(),sizeof(ShapeBounds));out.shapes.reserve(bodies.size());float max_radius=0;
    budget.add(bodies.size(),96);std::map<uint32_t,uint32_t> real;
    for(uint32_t i=0;i<bodies.size();i++){auto *b=bodies[i].body;require(b!=nullptr,"missing body");auto id=b->GetID().GetIndexAndSequenceNumber();require(real.emplace(id,i).second,"duplicate real body");out.shapes.push_back(bounds(bodies[i],dt,W,D));max_radius=std::max(max_radius,out.shapes.back().radius);}
    float cell_size=2*max_radius;require(cell_size>0&&std::isfinite(cell_size),"cell size");
    for(uint32_t i=0;i<bodies.size();i++){
        const AABox &b=out.shapes[i].swept;
        int64_t x0=integer(std::ceil((-W*.5-double(b.mMax.GetX()))/W)),x1=integer(std::floor((W*.5-double(b.mMin.GetX()))/W));
        int64_t y0=integer(std::ceil((-D*.5-double(b.mMax.GetY()))/D)),y1=integer(std::floor((D*.5-double(b.mMin.GetY()))/D));
        require(x1>=x0&&y1>=y0,"image range");require(uint64_t(x1-x0+1)*uint64_t(y1-y0+1)<=budget.limits.cell_entries,"image budget");
        for(int64_t y=y0;y<=y1;y++)for(int64_t x=x0;x<=x1;x++){
            budget.add(3,sizeof(Image));Vec3 L(float(x*W),float(y*D),0);out.images.push_back({i,x,y,AABox(b.mMin+L,b.mMax+L)});
        }
    }
    struct Range {int64_t lo[3],hi[3];};std::vector<Range> ranges;budget.add(out.images.size(),sizeof(Range));ranges.reserve(out.images.size());uint64_t total=0;
    for(const auto &im:out.images){Range r;uint64_t count=1;for(int a=0;a<3;a++){r.lo[a]=integer(std::floor(im.box.mMin[a]/cell_size));r.hi[a]=integer(std::floor(im.box.mMax[a]/cell_size));uint64_t n=uint64_t(r.hi[a]-r.lo[a]+1);require(n&&n<=budget.limits.cell_entries&&count<=budget.limits.cell_entries/n,"grid range budget");count*=n;}require(count<=budget.limits.cell_entries-total,"grid entry budget");total+=count;ranges.push_back(r);}
    budget.add(total,sizeof(Cell));std::vector<Cell> cells;cells.reserve(size_t(total));out.cell_entries=total;
    for(uint32_t i=0;i<ranges.size();i++){auto r=ranges[i];for(int64_t z=r.lo[2];z<=r.hi[2];z++)for(int64_t y=r.lo[1];y<=r.hi[1];y++)for(int64_t x=r.lo[0];x<=r.hi[0];x++)cells.push_back({x,y,z,i});}
    std::sort(cells.begin(),cells.end());std::map<Key,Candidate> unique;
    for(size_t start=0;start<cells.size();){size_t end=start+1;while(end<cells.size()&&cells[end].x==cells[start].x&&cells[end].y==cells[start].y&&cells[end].z==cells[start].z)++end;
        for(size_t a=start;a<end;a++)for(size_t b=a+1;b<end;b++){
            require(++out.pair_visits<=uint64_t(budget.limits.cell_entries)*64,"grid pair-visit budget");const Image &ia=out.images[cells[a].image],&ib=out.images[cells[b].image];if(ia.body==ib.body)continue;if(!ia.box.Overlaps(ib.box))continue;
            uint32_t aid=bodies[ia.body].body->GetID().GetIndexAndSequenceNumber(),bid=bodies[ib.body].body->GetID().GetIndexAndSequenceNumber();Key k=key(aid,bid,ib.x-ia.x,ib.y-ia.y);auto it=unique.find(k);if(it!=unique.end()){++out.duplicates;continue;}
            require(unique.size()<budget.limits.candidates,"image candidate pair budget");budget.add(1,sizeof(Candidate)+96);unique.emplace(k,Candidate{k,aid<bid?ia.body:ib.body,aid<bid?ib.body:ia.body});
        }start=end;
    }
    budget.add(unique.size(),sizeof(Candidate));out.pairs.reserve(unique.size());for(auto p:unique)out.pairs.push_back(p.second);return out;
}
struct Point {Vec3 local1,local2,chart1,chart2;};
struct Manifold {Key key;uint32_t sub1,sub2;Vec3 normal;float depth;std::vector<Point> points;CollideShapeResult::Face face1,face2;};
struct Queries {std::vector<Manifold> manifolds;size_t calls=0,raw_hits=0,total_points=0;};
using Trace=void (*)(const char*,size_t,bool,void*);
inline bool needs_prune(size_t count1,size_t count2){
    require(count1==count2&&count1>0,"nonempty equal manifold points required");
    return count1>4;
}
inline bool reduce_contacts(ContactPoints &one,ContactPoints &two,Vec3Arg n,RVec3Arg base,Trace trace=nullptr,void *context=nullptr){
    if(trace)trace("manifold_point_count",one.size(),one.size()>4,context);bool prune=needs_prune(one.size(),two.size());finite(n);
    if(prune){if(trace)trace("prune_begin",one.size(),true,context);PruneContactPoints(n,one,two JPH_IF_DEBUG_RENDERER(,base));if(trace)trace("prune_end",one.size(),true,context);}
    require(one.size()==two.size()&&!one.empty()&&one.size()<=4,"manifold points");if(trace)trace("manifold_ready",one.size(),prune,context);return prune;
}
inline void query(const std::vector<Input>& bodies,const Broadphase &broad,float W,float D,Budget &budget,Queries &out,Trace trace=nullptr,void *trace_context=nullptr){
    budget.add(1,sizeof(CollideShapeResult));
    class SingleHit final:public CollideShapeCollector{public:bool found=false;CollideShapeResult hit;void AddHit(const CollideShapeResult &h)override{require(!found,"nonconvex or multiple dispatch results unsupported");hit=h;found=true;}};
    for(const auto &p:broad.pairs){const Body &a=*bodies[p.i].body,&b=*bodies[p.j].body;Vec3 base(a.GetCenterOfMassPosition()),L(float(p.key.x*W),float(p.key.y*D),0),relative=Vec3(b.GetCenterOfMassPosition())+L-base;
        Mat44 t1=Mat44::sRotation(a.GetRotation()),t2=Mat44::sRotationTranslation(b.GetRotation(),relative);CollideShapeSettings settings;settings.mCollisionTolerance=1.0f/(1<<20);settings.mPenetrationTolerance=1.0f/(1<<20);settings.mCollectFacesMode=ECollectFacesMode::CollectFaces;settings.mMaxSeparationDistance=0;
        require(out.calls<budget.limits.queries,"dispatch query budget");SingleHit collector;++out.calls;if(trace)trace("query_begin",out.calls,false,trace_context);CollisionDispatch::sCollideShapeVsShape(a.GetShape(),b.GetShape(),Vec3::sReplicate(1),Vec3::sReplicate(1),t1,t2,SubShapeIDCreator(),SubShapeIDCreator(),settings,collector);if(trace)trace("query_end",collector.found?1:0,false,trace_context);
        if(collector.found){const auto &h=collector.hit;++out.raw_hits;require(out.manifolds.size()<budget.limits.manifolds,"manifold budget");finite(h.mPenetrationAxis);require(std::isfinite(h.mPenetrationDepth),"nonfinite depth");
            ContactPoints one,two;if(trace)trace("manifold_begin",0,false,trace_context);ManifoldBetweenTwoFaces(h.mContactPointOn1,h.mContactPointOn2,h.mPenetrationAxis,1e-6f,h.mShape1Face,h.mShape2Face,one,two JPH_IF_DEBUG_RENDERER(,a.GetCenterOfMassPosition()));
            Vec3 n=h.mPenetrationAxis.Normalized();finite(n);reduce_contacts(one,two,n,a.GetCenterOfMassPosition(),trace,trace_context);require(one.size()<=budget.limits.points-out.total_points,"contact point budget");
            budget.add(3,sizeof(Manifold));budget.add(one.size(),sizeof(Point));Manifold m{p.key,h.mSubShapeID1.GetValue(),h.mSubShapeID2.GetValue(),n,h.mPenetrationDepth,{},h.mShape1Face,h.mShape2Face};m.points.reserve(one.size());
            for(uint k=0;k<one.size();k++){finite(one[k]);finite(two[k]);m.points.push_back({a.GetRotation().Conjugated()*one[k],b.GetRotation().Conjugated()*(two[k]-relative),one[k]+base,two[k]+base});}
            out.total_points+=one.size();out.manifolds.push_back(std::move(m));
        }
    }
}
} // namespace periodic_geometry
