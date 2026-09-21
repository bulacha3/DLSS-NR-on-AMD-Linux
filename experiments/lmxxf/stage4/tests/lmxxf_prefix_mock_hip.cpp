// Test-only HIP runtime: verifies real resident dispatch arguments/lifetimes.
// Does not compute neural arithmetic or simulate GPU timing.
#include <cstdint>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>
#include "../experiments/lmxxf/prefix_parameters.h"
struct Module{std::string bytes;std::vector<std::string*> functions;};
static std::map<void*,size_t> memory;
static size_t allocations,prefix_calls,launches;
static unsigned expected_w,expected_h,expected_seed,expected_history;
static lmxxf_prefix_parameters expected;
static int fail_launch,fail_sync;
static void*const borrowed=(void*)0x5550;
static size_t room(const void*p){
 uintptr_t x=reinterpret_cast<uintptr_t>(p);
 for(const auto&m:memory){uintptr_t start=reinterpret_cast<uintptr_t>(m.first);if(x>=start&&x-start<m.second)return m.second-(x-start);}
 return 0;
}
extern "C" {
int hipGetDevice(int*p){*p=0;return 0;}
void mock_expect(unsigned w,unsigned h,unsigned seed,unsigned history,const float*p){expected_w=w;expected_h=h;expected_seed=seed;expected_history=history;std::memcpy(expected.values,p,24);}
size_t mock_allocations(){return allocations;} size_t mock_live(){return memory.size();}
size_t mock_prefix_calls(){return prefix_calls;} size_t mock_launches(){return launches;}
void mock_failure(int launch,int sync){fail_launch=launch;fail_sync=sync;}
int hipRuntimeGetVersion(int*p){*p=70200000;return 0;} int hipInit(unsigned){return 0;}
int hipMalloc(void**p,size_t n){*p=std::malloc(n);if(!*p)return 2;memory[*p]=n;++allocations;return 0;}
int hipFree(void*p){assert(memory.erase(p)==1);std::free(p);return 0;}
int hipMemcpy(void*d,const void*s,size_t n,int kind){assert(room(d)>=n&&(kind==1||kind==3));if(kind==3)assert(room(s)>=n);std::memmove(d,s,n);return 0;}
int hipMemcpyAsync(void*d,const void*s,size_t n,int kind,void*stream){assert(stream==borrowed&&kind==3);return hipMemcpy(d,s,n,kind);}
int hipMemsetAsync(void*p,int x,size_t n,void*stream){assert(stream==borrowed&&room(p)>=n);std::memset(p,x,n);return 0;}
int hipStreamSynchronize(void*stream){assert(stream==borrowed);return fail_sync?719:0;}
int hipModuleLoad(void**p,const char*name){
 std::ifstream f(name,std::ios::binary);assert(f);auto m=new Module;
 m->bytes=std::string(std::istreambuf_iterator<char>(f),{});assert(m->bytes.substr(0,4)==std::string("\177ELF",4));*p=m;return 0;
}
int hipModuleGetFunction(void**p,void*module,const char*name){auto m=static_cast<Module*>(module);assert(m->bytes.find(name)!=std::string::npos);auto fn=new std::string(name);m->functions.push_back(fn);*p=fn;return 0;}
int hipModuleUnload(void*p){auto m=static_cast<Module*>(p);for(auto f:m->functions)delete f;delete m;return 0;}
int hipModuleLaunchKernel(void*f,unsigned gx,unsigned gy,unsigned gz,unsigned bx,unsigned by,unsigned bz,unsigned shared,void*stream,void**args,void**extra){
 assert(stream==borrowed&&gy==1&&gz==1&&by==1&&bz==1&&shared==0&&!extra&&args);++launches;
 auto name=*static_cast<std::string*>(f);size_t n=size_t(expected_w)*expected_h;
 if(name=="lmxxf_rgb_to_rgba"){
  assert(gx==(n+255)/256&&bx==256&&*static_cast<unsigned*>(args[2])==n);
  assert(room(*static_cast<void**>(args[0]))>=n*12&&room(*static_cast<void**>(args[1]))>=n*16);
 }
 if(name=="lmxxf_game_prefix"){
  assert(gx==n/64&&bx==128);
  for(unsigned i=0;i<6;i++)assert(room(*static_cast<void**>(args[i]))>0);
  assert(*static_cast<unsigned*>(args[6])==gx&&*static_cast<unsigned*>(args[7])==0&&*static_cast<unsigned*>(args[8])==1);
  assert(*static_cast<unsigned*>(args[9])==expected_w&&*static_cast<unsigned*>(args[10])==expected_h);
  assert(*static_cast<unsigned*>(args[11])==expected_seed&&*static_cast<unsigned*>(args[12])==expected_history);
  assert(!std::memcmp(args[13],&expected,24));
  assert(room(*static_cast<void**>(args[0]))>=n*16&&room(*static_cast<void**>(args[1]))>=n*16);
  assert(room(*static_cast<void**>(args[4]))>=n*8&&room(*static_cast<void**>(args[5]))>=n*32);
  ++prefix_calls;if(fail_launch)return 719;
 }
 return 0;
}
const char*hipGetErrorName(int){return "mock injected error";}
#define UNUSED(name) int name(...){return 71;}
UNUSED(hipEventCreate) UNUSED(hipEventRecord) UNUSED(hipEventElapsedTime) UNUSED(hipEventDestroy) UNUSED(hipEventSynchronize)
UNUSED(hipHostMalloc) UNUSED(hipGetDeviceCount) UNUSED(hipDeviceGetName) UNUSED(hipSetDevice) UNUSED(hipMemGetInfo)
UNUSED(hipDeviceSynchronize) UNUSED(hipStreamCreate) UNUSED(hipStreamDestroy)
UNUSED(hipImportExternalMemory) UNUSED(hipExternalMemoryGetMappedBuffer) UNUSED(hipDestroyExternalMemory)
UNUSED(hipImportExternalSemaphore) UNUSED(hipSignalExternalSemaphoresAsync) UNUSED(hipWaitExternalSemaphoresAsync) UNUSED(hipDestroyExternalSemaphore)
}
