// CPU contract model: deep-copy captured arguments and replay commands in order.
// No neural arithmetic is simulated. Event ticks are synthetic contract data,
// never evidence of GPU time or performance.
#include <cstdint>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include <set>
#include "../experiments/lmxxf/prefix_parameters.h"
#include "lmxxf_kernel_arguments.h"
struct Memory{size_t bytes,id;int device;uint64_t upload_hash=0;};
struct Module{std::string bytes;std::vector<std::string*> functions;};
struct Event {double tick=0;unsigned generation=0;bool ready=false;};
static std::set<Event*>events;
static double event_clock=0;
static int fail_event=0;
static unsigned event_calls=0,stream_syncs=0;
struct Command {
 int kind=0; // kernel, copy, memset
 std::string name;unsigned gx=0,bx=0;std::vector<std::vector<unsigned char>> args;
 void *dst=nullptr;const void*src=nullptr;size_t bytes=0;int value=0;
};
struct Graph{std::vector<Command> commands;};
static std::map<void*,Memory> memory;
static size_t allocations,prefix_calls,launches,host_calls,captures,replays,live_graphs;
static unsigned expected_w,expected_h,expected_seed,expected_history;
static lmxxf_prefix_parameters expected;
static int fail_launch,fail_sync,fail_graph;
static void*borrowed=(void*)0x5550;
static void*aux=nullptr;
static std::set<void*>aux_streams;
static thread_local int selected_device=0;
static size_t uploads=0,upload_bytes=0,module_loads=0,device_syncs=0,peak_bytes=0;
static Graph*capture=nullptr;
static std::string trace;
static std::vector<unsigned> forward_gather;
static unsigned attention_width,attention_height;
static std::pair<size_t,size_t> region(const void*p){
 uintptr_t x=reinterpret_cast<uintptr_t>(p);
 for(const auto&m:memory){uintptr_t start=reinterpret_cast<uintptr_t>(m.first);if(x>=start&&x-start<m.second.bytes)return {m.second.id,x-start};}
 return {0,0};
}
static size_t room(const void*p){auto r=region(p);if(!r.first)return 0;for(auto&m:memory)if(m.second.id==r.first)return m.second.bytes-r.second;return 0;}
static std::string pointer(const void*p){if(!p)return "null";auto r=region(p);assert(r.first);return std::to_string(r.first)+"+"+std::to_string(r.second);}
static int execute(const Command&c){
 std::ostringstream line;
 if(c.kind==3){auto*e=static_cast<Event*>(c.dst);assert(events.count(e));e->tick=event_clock;e->ready=false;++e->generation;return 0;}
 if(c.kind==1){assert(room(c.dst)>=c.bytes&&room(c.src)>=c.bytes);line<<"copy:"<<pointer(c.dst)<<":"<<pointer(c.src)<<":"<<c.bytes;}
 else if(c.kind==2){assert(room(c.dst)>=c.bytes);line<<"zero:"<<pointer(c.dst)<<":"<<c.value<<":"<<c.bytes;}
 else {
  ++launches;line<<c.name<<":"<<c.gx<<":"<<c.bx;
  const auto&desc=kernel_arguments.at(c.name);
  std::vector<void*> args;for(auto&a:c.args)args.push_back(const_cast<unsigned char*>(a.data()));
  for(size_t i=0;i<args.size();++i){line<<":";
   if(desc[i].second){void*p;std::memcpy(&p,args[i],8);line<<pointer(p);}
   else {static const char hex[]="0123456789abcdef";for(auto b:c.args[i])line<<hex[b>>4]<<hex[b&15];}
  }
  const size_t n=size_t(expected_w)*expected_h;
  {
   const unsigned rw=expected_w/64,rh=expected_h/64;
   auto u=[&](unsigned i){unsigned value;std::memcpy(&value,args[i],4);return value;};
   auto p=[&](unsigned i){void*value;std::memcpy(&value,args[i],8);return value;};
   if(c.name=="mh_pool_project_production_h16w"&&u(7)==512){
    attention_width=u(3);attention_height=u(4);
    assert(attention_width>=rw&&attention_height>=rh);
    const unsigned tokens=attention_width*attention_height;
    assert(tokens&&tokens%16==0&&tokens<=640);
    const bool padded=attention_width!=rw||attention_height!=rh;
    assert(u(5)==(padded?rw:0)&&u(6)==(padded?rh:0));
    assert(room(p(0))>=size_t(tokens)*512*4&&room(p(2))>=size_t(tokens)*1024*4);
   }
   const unsigned tokens=attention_width*attention_height;
   if(c.name=="vit_gather"){
    assert(tokens);
    const size_t count=size_t(tokens)*1024;
    // vit_gather uses the reference scalar kernel, 256 threads per block.
    assert(u(3)==count&&c.gx==count/256&&c.bx==256);
    assert(room(p(0))>=count*4&&room(p(1))>=count*4&&room(p(2))>=count*4);
    const auto*map=static_cast<const unsigned*>(p(1));std::vector<bool> seen(count,false);
    for(size_t i=0;i<count;i++){assert(map[i]<count&&!seen[map[i]]);seen[map[i]]=true;}
    if(forward_gather.empty())forward_gather.assign(map,map+count);
    else for(size_t i=0;i<count;i++)assert(map[forward_gather[i]]==i);
   }
   if(c.name.rfind("vit_attention_fused_",0)==0){
    assert(c.name==(tokens<=256?"vit_attention_fused_256_bytein":tokens<=400?"vit_attention_fused_400_bytein":"vit_attention_fused_640_bytein"));
    assert(u(2)==tokens&&tokens%16==0&&tokens<=640&&c.gx==tokens*2&&c.bx==32);
    assert(room(p(0))>=size_t(tokens)*3072&&room(p(1))>=size_t(tokens)*1024*4);
   }
   if(c.name=="decoder_project2x_h16w"&&u(8)==1024){
    assert(u(4)==attention_width&&u(5)==attention_height&&u(6)==rw*2&&u(7)==rh*2&&u(9)==512);
    assert(room(p(0))>=size_t(tokens)*1024*4);
    assert(room(p(2))>=size_t(rw)*rh*4*512*4&&room(p(3))>=size_t(rw)*rh*4*512*4);
   }
  }
  if(c.name=="lmxxf_game_head_rgba"){
   auto ptr=[&](unsigned i){return *static_cast<void**>(args[i]);};
   assert(c.gx==n/64&&c.bx==128);
   assert(room(ptr(5))>=n*12&&room(ptr(7))>=n*16);
   assert(*static_cast<unsigned*>(args[8])==n/64);
   assert(*static_cast<unsigned*>(args[9])==expected_w&&*static_cast<unsigned*>(args[10])==expected_h);
   assert(*static_cast<unsigned*>(args[11])==0&&*static_cast<unsigned*>(args[12])==0);
   assert(*static_cast<float*>(args[13])==.03125f);
   if(fail_launch==2)return 719;
  }
  if(c.name=="lmxxf_rgb_to_rgba"){
   assert(c.gx==(n+255)/256&&c.bx==256&&*static_cast<unsigned*>(args[2])==n);
   assert(room(*static_cast<void**>(args[0]))>=n*12&&room(*static_cast<void**>(args[1]))>=n*16);
  }
  if(c.name=="lmxxf_game_prefix"||c.name=="lmxxf_game_prefix_rgb"){
   assert(c.gx==n/64&&c.bx==128);
   assert(*static_cast<unsigned*>(args[6])==c.gx&&*static_cast<unsigned*>(args[7])==0&&*static_cast<unsigned*>(args[8])==1);
   assert(*static_cast<unsigned*>(args[9])==expected_w&&*static_cast<unsigned*>(args[10])==expected_h);
   assert(*static_cast<unsigned*>(args[11])==expected_seed&&*static_cast<unsigned*>(args[12])==expected_history);
   assert(!std::memcmp(args[13],&expected,24));
   const size_t pixel_bytes=c.name=="lmxxf_game_prefix_rgb"?12:16;
   assert(room(*static_cast<void**>(args[0]))>=n*pixel_bytes&&room(*static_cast<void**>(args[1]))>=n*pixel_bytes);
   assert(room(*static_cast<void**>(args[4]))>=n*8&&room(*static_cast<void**>(args[5]))>=n*32);
   if(!expected_history)assert(*static_cast<void**>(args[0])==*static_cast<void**>(args[1]));
   ++prefix_calls;if(fail_launch==1)return 719;
  }
 }
 event_clock+=0.02;trace+=line.str()+"\n";return 0;
}
extern "C" {
void mock_stream(void*p){assert(aux_streams.empty()&&!capture&&memory.empty());borrowed=p;}
void mock_expect(unsigned w,unsigned h,unsigned seed,unsigned history,const float*p){expected_w=w;expected_h=h;expected_seed=seed;expected_history=history;std::memcpy(expected.values,p,24);trace.clear();forward_gather.clear();attention_width=attention_height=0;}
const char*mock_trace(){return trace.c_str();}
size_t mock_allocations(){return allocations;} size_t mock_live(){return memory.size();}
size_t mock_prefix_calls(){return prefix_calls;} size_t mock_launches(){return launches;}
size_t mock_host_calls(){return host_calls;} size_t mock_replays(){return replays;}
size_t mock_captures(){return captures;} size_t mock_graphs(){return live_graphs;}
size_t mock_uploads(){return uploads;} size_t mock_upload_bytes(){return upload_bytes;}
size_t mock_module_loads(){return module_loads;} size_t mock_device_syncs(){return device_syncs;}
size_t mock_live_bytes(){size_t n=0;for(const auto&m:memory)n+=m.second.bytes;return n;}
size_t mock_peak_bytes(){return peak_bytes;}
const char*mock_uploaded(){static std::string value;std::ostringstream s;for(const auto&m:memory)if(m.second.upload_hash)s<<m.second.id<<":"<<m.second.bytes<<":"<<m.second.upload_hash<<"\n";value=s.str();return value.c_str();}
void mock_failure(int launch,int sync){fail_launch=launch;fail_sync=sync;}
void mock_graph_failure(int stage){fail_graph=stage;}
void mock_event_failure(int stage){fail_event=stage;}
size_t mock_events(){return events.size();}
size_t mock_event_calls(){return event_calls;}
size_t mock_stream_syncs(){return stream_syncs;}
int hipRuntimeGetVersion(int*p){*p=70200000;return 0;} int hipInit(unsigned){return 0;}
int hipGetDevice(int*p){*p=selected_device;return 0;} int hipSetDevice(int d){selected_device=d;return 0;}
int hipMalloc(void**p,size_t n){assert(!capture);*p=std::malloc(n);if(!*p)return 2;memory[*p]={n,++allocations,selected_device};peak_bytes=std::max(peak_bytes,mock_live_bytes());return 0;}
int hipFree(void*p){assert(!capture&&memory.at(p).device==selected_device&&memory.erase(p)==1);std::free(p);return 0;}
int hipMemcpy(void*d,const void*s,size_t n,int kind){assert(!capture&&room(d)>=n&&(kind==1||kind==3));if(kind==3)assert(room(s)>=n);std::memmove(d,s,n);if(kind==1){++uploads;upload_bytes+=n;uint64_t hash=14695981039346656037ull;for(size_t i=0;i<n;i++){hash^=static_cast<const unsigned char*>(s)[i];hash*=1099511628211ull;}memory.at(d).upload_hash=hash;}return 0;}
int hipMemcpyAsync(void*d,const void*s,size_t n,int kind,void*stream){
 assert(kind==3);Command c;c.kind=1;c.dst=d;c.src=s;c.bytes=n;
 if(capture){assert(stream==aux);capture->commands.push_back(c);return 0;}assert(stream==borrowed);return execute(c);
}
int hipMemsetAsync(void*p,int x,size_t n,void*stream){
 Command c;c.kind=2;c.dst=p;c.value=x;c.bytes=n;
 if(capture){assert(stream==aux);capture->commands.push_back(c);return 0;}assert(stream==borrowed);return execute(c);
}
int hipStreamSynchronize(void*stream){assert(!capture&&stream==borrowed);++stream_syncs;
 if(fail_sync)return 719;for(auto*e:events)e->ready=true;return 0;}
int hipDeviceSynchronize(){assert(!capture);++device_syncs;return fail_sync?719:0;}
int hipStreamCreateWithFlags(void**p,unsigned flags){assert(flags==1);if(fail_graph==1)return 719;*p=std::malloc(1);aux_streams.insert(*p);return 0;}
int hipStreamDestroy(void*p){assert(aux_streams.erase(p)==1&&!capture);std::free(p);return 0;}
#ifndef MOCK_NO_GRAPH_API
int hipStreamBeginCapture(void*s,int mode){assert(aux_streams.count(s)&&!capture&&mode==1);aux=s;++captures;if(fail_graph==2)return 719;capture=new Graph;return 0;}
int hipStreamEndCapture(void*s,void**p){assert(aux&&s==aux&&capture);if(fail_graph==4){delete capture;capture=nullptr;*p=nullptr;return 719;}*p=capture;capture=nullptr;++live_graphs;return 0;}
int hipGraphGetNodes(void*p,void**nodes,size_t*n){assert(p&&!nodes);if(fail_graph==8)return 719;*n=fail_graph==7?0:static_cast<Graph*>(p)->commands.size();return 0;}
int hipGraphInstantiate(void**p,void*g,void**error,char*log,size_t bytes){assert(g&&!error&&!log&&!bytes);if(fail_graph==5)return 719;*p=new Graph(*static_cast<Graph*>(g));++live_graphs;return 0;}
int hipGraphDestroy(void*p){assert(p);delete static_cast<Graph*>(p);--live_graphs;return 0;}
int hipGraphExecDestroy(void*p){return hipGraphDestroy(p);}
int hipGraphLaunch(void*p,void*s){assert(!capture&&s==borrowed&&p);auto*g=static_cast<Graph*>(p);++replays;size_t at=0;for(auto&c:g->commands){if(fail_graph==6&&at++==2)return 719;int rc=execute(c);if(rc)return rc;}return 0;}
#endif
int hipModuleLoad(void**p,const char*name){assert(!capture);std::ifstream f(name,std::ios::binary);assert(f);auto m=new Module;m->bytes=std::string(std::istreambuf_iterator<char>(f),{});assert(m->bytes.substr(0,4)==std::string("\177ELF",4));*p=m;++module_loads;return 0;}
int hipModuleGetFunction(void**p,void*module,const char*name){assert(!capture);auto m=static_cast<Module*>(module);assert(m->bytes.find(name)!=std::string::npos&&kernel_arguments.count(name));auto fn=new std::string(name);m->functions.push_back(fn);*p=fn;return 0;}
int hipModuleUnload(void*p){assert(!capture);auto m=static_cast<Module*>(p);for(auto f:m->functions)delete f;delete m;return 0;}
int hipModuleLaunchKernel(void*f,unsigned gx,unsigned gy,unsigned gz,unsigned bx,unsigned by,unsigned bz,unsigned shared,void*stream,void**args,void**extra){
 assert(gy==1&&gz==1&&by==1&&bz==1&&shared==0&&!extra&&args);++host_calls;
 Command c;c.name=*static_cast<std::string*>(f);c.gx=gx;c.bx=bx;
 const auto&desc=kernel_arguments.at(c.name);for(size_t i=0;i<desc.size();++i){auto*p=static_cast<unsigned char*>(args[i]);c.args.emplace_back(p,p+desc[i].first);}
 if(capture){assert(stream==aux&&c.name!="lmxxf_game_prefix"&&c.name!="lmxxf_game_prefix_rgb"&&c.name!="lmxxf_game_head_rgba"&&c.name!="lmxxf_rgb_to_rgba");if(fail_graph==3&&capture->commands.size()==3)return 719;capture->commands.push_back(c);return 0;}
 assert(stream==borrowed);return execute(c);
}
const char*hipGetErrorName(int){return "mock injected error";}
#define UNUSED(name) int name(...){return 71;}
int hipEventCreate(void**p){++event_calls;if(fail_event==1)return 2;auto*e=new Event;events.insert(e);*p=e;return 0;}
int hipEventDestroy(void*p){++event_calls;auto*e=static_cast<Event*>(p);assert(events.erase(e)==1);delete e;return 0;}
int hipEventRecord(void*p,void*s){++event_calls;assert(!capture&&s==borrowed);if(fail_event==2)return 719;
 Command c;c.kind=3;c.dst=p;return execute(c);}
#ifndef MOCK_NO_PROFILE_API
int hipEventRecordWithFlags(void*p,void*s,unsigned flags){++event_calls;assert(capture&&s==aux&&flags==1);
 if(fail_event==3)return 719;Command c;c.kind=3;c.dst=p;capture->commands.push_back(c);return 0;}
#endif
int hipEventElapsedTime(float*ms,void*a,void*b){++event_calls;assert(!capture);
 auto*x=static_cast<Event*>(a);auto*y=static_cast<Event*>(b);
 assert(events.count(x)&&events.count(y)&&x->generation&&y->generation&&x->ready&&y->ready);
 if(fail_event==4)return 719;if(fail_event==5){*ms=-1;return 0;}
 *ms=static_cast<float>(y->tick-x->tick);return 0;}
UNUSED(hipEventSynchronize)
UNUSED(hipHostMalloc) UNUSED(hipGetDeviceCount) UNUSED(hipDeviceGetName) UNUSED(hipMemGetInfo)
UNUSED(hipStreamCreate)
UNUSED(hipImportExternalMemory) UNUSED(hipExternalMemoryGetMappedBuffer) UNUSED(hipDestroyExternalMemory)
UNUSED(hipImportExternalSemaphore) UNUSED(hipSignalExternalSemaphoresAsync) UNUSED(hipWaitExternalSemaphoresAsync) UNUSED(hipDestroyExternalSemaphore)
}
