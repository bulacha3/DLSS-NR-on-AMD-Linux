// Additional assertions on the real host dispatch, before graph capture.
// Includes the existing CPU HIP model; it does not execute neural arithmetic.
#define hipModuleLaunchKernel base_hipModuleLaunchKernel
#include "lmxxf_graph_mock_hip.cpp"
#undef hipModuleLaunchKernel
static std::map<void*,std::pair<size_t,unsigned>> byte_features;
static size_t feature_producers=0,feature_consumers=0;
extern "C" size_t mock_feature_producers(){return feature_producers;}
extern "C" size_t mock_feature_consumers(){return feature_consumers;}
extern "C" int hipModuleLaunchKernel(void*f,unsigned gx,unsigned gy,unsigned gz,unsigned bx,unsigned by,unsigned bz,unsigned shared,void*stream,void**args,void**extra){
 const std::string&name=*static_cast<std::string*>(f);
 auto u=[&](unsigned i){unsigned value;std::memcpy(&value,args[i],4);return value;};
 auto p=[&](unsigned i){void*value;std::memcpy(&value,args[i],8);return value;};
 if(name.rfind("mh_ffn_fused_c",0)==0){
  const unsigned channels=unsigned(std::stoul(name.substr(14)));
  assert(channels==64||channels==128||channels==256);
  assert(name.find("_g128_qkv_fb")!=std::string::npos);
  assert(name.find("bytein")==std::string::npos);
  const unsigned tokens=u(5),width=u(6),height=u(7),workw=u(8),sx=u(9),sy=u(10);
  assert(tokens&&tokens%16==0&&gx==tokens/16&&bx==2*channels);
  const bool mapped=name.find("_mapped")!=std::string::npos;
  assert(!mapped||(tokens%workw==0&&workw>=width+sx&&tokens/workw>=height+sy));
  assert(room(p(0))>=size_t(mapped?width*height:tokens)*channels*4);
  assert(room(p(3))>=size_t(tokens)*channels);
  assert(room(p(4))>=size_t(tokens)*channels*3);
  byte_features[p(3)]={tokens,channels};++feature_producers;
 }
 if(name.rfind("c64_attention_project",0)==0||name.rfind("c128_attention_project",0)==0||name.rfind("c256_attention_project",0)==0){
  const unsigned channels=unsigned(std::stoul(name.substr(1)));
  assert(name=="c"+std::to_string(channels)+"_attention_project_fb_diag");
  const unsigned width=u(4),height=u(5),post=u(6),cropw=u(7),croph=u(8),sx=u(9),sy=u(10);
  assert(width%8==0&&height%8==0&&gx==width*height/64);
  assert(post==0||post==3||post==4); // F16/F8 epilogues remain selected by the host.
  assert(byte_features.count(p(2)));
  assert(byte_features[p(2)]==std::make_pair(size_t(width)*height,channels));
  assert(room(p(0))>=size_t(width)*height*channels*3);
  assert(room(p(2))>=size_t(width)*height*channels);
  assert(!cropw||(cropw+sx<=width&&croph+sy<=height));
  assert(room(p(3))>=size_t(cropw?cropw*croph:width*height)*channels*4);
  ++feature_consumers;
 }
 return base_hipModuleLaunchKernel(f,gx,gy,gz,bx,by,bz,shared,stream,args,extra);
}
