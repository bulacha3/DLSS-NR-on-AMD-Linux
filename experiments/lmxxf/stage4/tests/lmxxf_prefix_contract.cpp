// Independent raw VarParams/LDS -> converted-weight feature mapping.
// CPU only: shares the GPU conditioning helper, not its expected layout.
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <initializer_list>
#include <limits>
#include "../experiments/lmxxf/resident_backend.h"
static float Hrtz(float x){
 uint32_t u;std::memcpy(&u,&x,4);unsigned sign=u>>31,e=(u>>23)&255,m=u&0x7fffff;
 if(e==255)return x;
 if(e<103)return std::copysign(0.f,x);
 if(e<113){unsigned v=(m|0x800000)>>(126-e);return std::copysign(std::ldexp(float(v),-24),x);}
 if(e>142)return std::copysign(65504.f,x);
 u=(sign<<31)|(e<<23)|(m&0x7fe000);std::memcpy(&x,&u,4);return x;
}
#define DEV static inline
#include "../experiments/lmxxf/prefix_features.inc"
int main(){
 static_assert(sizeof(lmxxf_prefix_parameters)==24 && sizeof(lmxxf_config)==40 && sizeof(lmxxf_frame)==96);
 static_assert(offsetof(lmxxf_frame,prefix)==72);
 const lmxxf_prefix_parameters profiles[]={{{.0625f,1,1,.0078125f,1,1}},{{.0625f,0,0,0,1.1f,1.1f}},{{.0625f,.25f,.5f,.75f,1.25f,1.5f}}};
 for(auto p:profiles){
  assert(lmxxf_features_valid(p.values));
  // Raw sequence established from the original kernel's two 128-bit LDS stores.
  float raw[]={.25f,.5f,.75f,1,.03125f,.0625f,.09375f,.125f,.15625f,.1875f,Hrtz(p.values[3]),Hrtz(p.values[1]),Hrtz(p.values[2]),Hrtz(p.values[4]),Hrtz(p.values[5]),0};
  float expected[16]={},features[]={.25f,.5f,.15625f,.1875f,.75f,1,.0078125f,1,.03125f,.0625f,1,1,.09375f,.125f,1,0};
  for(unsigned group=0;group<4;group++)for(unsigned j=0;j<4;j++){
   unsigned s14=group*4,s13=group*2;
   unsigned byte_offset=(s13&4)+((s14%8+(j>=2?2:0))*8&~15u)+(j%2?2:0);
   unsigned half_index=byte_offset/2,feature=(half_index/8%4)*4+half_index%4;
   expected[feature]=raw[group*4+j];
  }
  lmxxf_condition_features(features,p);assert(!std::memcmp(expected,features,sizeof(expected)));
  for(float x:{-.125f,0.f,.25f,.5f,1.f,2.f})assert(lmxxf_condition_color(x,p)==Hrtz(Hrtz(Hrtz(x)-.5f)*.125f));
 }
 float observed[16]={};lmxxf_condition_features(observed,profiles[1]);
 assert(observed[6]==0&&observed[7]==0&&observed[10]==0&&observed[11]==1.099609375f&&observed[14]==1.099609375f);
 for(unsigned i=0;i<6;i++)for(float x:{std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()}){
  auto p=profiles[1];p.values[i]=x;assert(!lmxxf_features_valid(p.values));
 }
 auto bad=profiles[1];bad.values[0]=.125f;assert(!lmxxf_features_valid(bad.values));
 std::puts("PREFIX_RAW_ABI_WEIGHT_MAPPING_AND_REAL_LOG_PROFILE passed");
}
