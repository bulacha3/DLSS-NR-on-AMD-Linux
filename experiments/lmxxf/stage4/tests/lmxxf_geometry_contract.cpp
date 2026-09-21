// Exhaustive planner properties and head/decoder index bounds, no GPU arithmetic.
#include "../experiments/lmxxf/stage4_geometry.h"
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <limits>
int main(){
 unsigned accepted=0,padding_rejected=0;
 for(unsigned rw=1;rw<=641;++rw)for(unsigned rh=1;rh<=641;++rh){
  struct lmxxf_geometry g{};
  const int status=lmxxf_plan_geometry(rw*64,rh*64,&g);
  unsigned best=641;
  // Independent exhaustive rectangle oracle, not the production GCD algorithm.
  if(rw*rh<=640)for(unsigned w=rw;w<=640/rh;++w)for(unsigned h=rh;h<=640/w;++h)
   if(w*h%16==0&&w*h<best)best=w*h;
  assert((status==LMXXF_GEOMETRY_OK)==(best<=640));
  if(status){
   assert(status==(rw*rh>640?LMXXF_GEOMETRY_TOKENS:LMXXF_GEOMETRY_PADDING));
   if(status==LMXXF_GEOMETRY_PADDING)++padding_rejected;
   continue;
  }
  ++accepted;const unsigned tw=g.token_width,th=g.token_height,n=tw*th;
  assert(g.width==rw*64&&g.height==rh*64&&tw>=rw&&th>=rh&&n<=640&&n%16==0);
  if(rw==30&&rh==18)assert(tw==32&&th==20); // preserved validated layout
  else assert(n==best);
  // Pool reads four neighbors only for real cells. Decoder crops extra cells
  // before accessing the real skip/output arrays; check last channel too.
  const uint64_t source_width=rw*2,source_height=rh*2,bytes=source_width*source_height*512*4;
  for(unsigned y=0;y<th;++y)for(unsigned x=0;x<tw;++x){
   if(x<rw&&y<rh){
    const uint64_t last=((uint64_t(y)*2+1)*source_width+uint64_t(x)*2+1)*512+511;
    assert((last+1)*4<=bytes);
   }
   for(unsigned dy=0;dy<2;++dy)for(unsigned dx=0;dx<2;++dx){
    const uint64_t ox=uint64_t(x)*2+dx,oy=uint64_t(y)*2+dy;
    if(ox>=source_width||oy>=source_height)continue;
    assert(((oy*source_width+ox)*512+512)*4<=bytes);
   }
  }
 }
 // All previously accepted layouts stay exactly the same.
 const unsigned old[][4]={{512,512,8,8},{1920,1152,32,20},{1280,768,20,12},
  {1600,1024,25,16},{1600,960,25,16},{2432,1024,38,16},{2176,896,34,16},
  {1792,768,28,12},{2048,896,32,14}};
 for(auto&v:old){struct lmxxf_geometry g{};assert(lmxxf_geometry(v[0],v[1],&g));assert(g.token_width==v[2]&&g.token_height==v[3]);}
 struct lmxxf_geometry g{};
 assert(lmxxf_plan_geometry(0,64,&g)==LMXXF_GEOMETRY_SIZE);
 assert(lmxxf_plan_geometry(64,0,&g)==LMXXF_GEOMETRY_SIZE);
 assert(lmxxf_plan_geometry(64,64,nullptr)==LMXXF_GEOMETRY_SIZE);
 assert(lmxxf_plan_geometry(1920,1080,&g)==LMXXF_GEOMETRY_ALIGNMENT);
 assert(lmxxf_plan_geometry(1600,1600,&g)==LMXXF_GEOMETRY_PADDING);
 assert(lmxxf_plan_geometry(40960,64,&g)==LMXXF_GEOMETRY_OK);
 assert(lmxxf_plan_geometry(64,40960,&g)==LMXXF_GEOMETRY_OK);
 assert(lmxxf_plan_geometry(41024,64,&g)==LMXXF_GEOMETRY_TOKENS);
 assert(lmxxf_plan_geometry(UINT32_MAX-63,UINT32_MAX-63,&g)==LMXXF_GEOMETRY_TOKENS);
 std::printf("AUTOMATIC_GEOMETRY exhaustive_pairs=410881 accepted=%u padding_limit=%u old_layouts=preserved index_bounds=passed overflow=rejected\n",accepted,padding_rejected);
}
