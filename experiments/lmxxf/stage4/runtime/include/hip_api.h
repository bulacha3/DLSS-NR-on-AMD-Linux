#pragma once
// Minimal Windows dynamic HIP ABI used by probes, from ROCm/HIP rocm-7.1.1 hip_runtime_api.h.
// Copyright (c) 2015-2023 Advanced Micro Devices, Inc. MIT license:
// Permission is hereby granted, free of charge, to any person obtaining a copy of this software
// and associated documentation files (the "Software"), to deal in the Software without restriction,
// including without limitation the rights to use, copy, modify, merge, publish, distribute,
// sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions: The above copyright notice and this
// permission notice shall be included in all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
// BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
// DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#include <cstdlib>
#endif
#include <algorithm>
#include <cstddef>
#include <cstdio>
#include <stdexcept>
#include <string>
namespace hip_probe {
using Handle=void*;
struct MemoryDesc {int type;union {int fd;struct {void*handle;const void*name;} win32;const void*nvSciBufObject;} handle;unsigned long long size;unsigned flags;unsigned reserved[16];};
struct BufferDesc {unsigned long long offset,size;unsigned flags;unsigned reserved[16];};
struct SemaphoreDesc {int type;union {int fd;struct {void*handle;const void*name;} win32;const void*nvSciSyncObj;} handle;unsigned flags;unsigned reserved[16];};
struct SignalParams {struct {struct {unsigned long long value;} fence;union {void*fence;unsigned long long reserved;} nvSciSync;struct {unsigned long long key;} keyedMutex;unsigned reserved[12];} params;unsigned flags;unsigned reserved[16];};
struct WaitParams {struct {struct {unsigned long long value;} fence;union {void*fence;unsigned long long reserved;} nvSciSync;struct {unsigned long long key;unsigned timeoutMs;} keyedMutex;unsigned reserved[10];} params;unsigned flags;unsigned reserved[16];};
// Virtual memory management (sparse weight mappings): hipMemAllocationProp / hipMemAccessDesc of rocm-7.x.
struct MemAllocationProp {unsigned type;unsigned requestedHandleType;struct {unsigned type;int id;} location;void*win32HandleMetaData;struct {unsigned char compressionType,gpuDirectRDMACapable;unsigned short usage;unsigned char reserved[4];} allocFlags;};
struct MemAccessDesc {struct {unsigned type;int id;} location;unsigned flags;};
static_assert(sizeof(MemoryDesc)==104&&sizeof(BufferDesc)==88&&sizeof(SemaphoreDesc)==96&&sizeof(SignalParams)==144&&sizeof(WaitParams)==144,"HIP external resource ABI");
struct Api {
#ifdef _WIN32
 HMODULE dll{};
#else
 void* dll{};
#endif
 #define HIP_FN(name,args) using name##Fn=int(*)args;name##Fn name{}
 HIP_FN(hipInit,(unsigned));HIP_FN(hipRuntimeGetVersion,(int*));HIP_FN(hipGetDeviceCount,(int*));HIP_FN(hipGetDevice,(int*));HIP_FN(hipDeviceGetName,(char*,int,int));HIP_FN(hipSetDevice,(int));
 HIP_FN(hipMemGetInfo,(size_t*,size_t*));HIP_FN(hipMalloc,(void**,size_t));HIP_FN(hipHostMalloc,(void**,size_t,unsigned));HIP_FN(hipFree,(void*));HIP_FN(hipMemcpy,(void*,const void*,size_t,int));HIP_FN(hipMemcpyAsync,(void*,const void*,size_t,int,Handle));HIP_FN(hipMemsetAsync,(void*,int,size_t,Handle));
 HIP_FN(hipEventRecordWithFlags,(Handle,Handle,unsigned));
 HIP_FN(hipEventCreate,(Handle*));HIP_FN(hipEventRecord,(Handle,Handle));HIP_FN(hipEventElapsedTime,(float*,Handle,Handle));HIP_FN(hipEventDestroy,(Handle));HIP_FN(hipEventSynchronize,(Handle));
 HIP_FN(hipDeviceSynchronize,());HIP_FN(hipStreamCreate,(Handle*));HIP_FN(hipStreamSynchronize,(Handle));HIP_FN(hipStreamDestroy,(Handle));
 HIP_FN(hipImportExternalMemory,(Handle*,const MemoryDesc*));HIP_FN(hipExternalMemoryGetMappedBuffer,(void**,Handle,const BufferDesc*));HIP_FN(hipDestroyExternalMemory,(Handle));
 HIP_FN(hipImportExternalSemaphore,(Handle*,const SemaphoreDesc*));HIP_FN(hipSignalExternalSemaphoresAsync,(const Handle*,const SignalParams*,unsigned,Handle));HIP_FN(hipWaitExternalSemaphoresAsync,(const Handle*,const WaitParams*,unsigned,Handle));HIP_FN(hipDestroyExternalSemaphore,(Handle));
 // Optional graph API, loaded only when requested.
 HIP_FN(hipStreamBeginCapture,(Handle,int));HIP_FN(hipStreamEndCapture,(Handle,Handle*));
 HIP_FN(hipGraphInstantiate,(Handle*,Handle,Handle*,char*,size_t));HIP_FN(hipGraphLaunch,(Handle,Handle));
 HIP_FN(hipGraphDestroy,(Handle));HIP_FN(hipGraphExecDestroy,(Handle));
 HIP_FN(hipStreamCreateWithFlags,(Handle*,unsigned));HIP_FN(hipGraphGetNodes,(Handle,Handle*,size_t*));
 // Optional VMM API (EnableVmm): address reservation + physical chunks mapped at chosen offsets.
 HIP_FN(hipMemAddressReserve,(void**,size_t,size_t,void*,unsigned long long));HIP_FN(hipMemAddressFree,(void*,size_t));HIP_FN(hipMemCreate,(void**,size_t,const MemAllocationProp*,unsigned long long));HIP_FN(hipMemRelease,(void*));HIP_FN(hipMemMap,(void*,size_t,size_t,void*,unsigned long long));HIP_FN(hipMemUnmap,(void*,size_t));HIP_FN(hipMemSetAccess,(void*,size_t,const MemAccessDesc*,size_t));HIP_FN(hipMemGetAllocationGranularity,(size_t*,const MemAllocationProp*,unsigned));
 HIP_FN(hipModuleLoad,(Handle*,const char*));HIP_FN(hipModuleGetFunction,(Handle*,Handle,const char*));HIP_FN(hipModuleLaunchKernel,(Handle,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,Handle,void**,void**));HIP_FN(hipModuleUnload,(Handle));
 #undef HIP_FN
 using ErrorNameFn=const char*(*)(int);ErrorNameFn hipGetErrorName{};
 template<class T>void Load(T&f,const char*n){
#ifdef _WIN32
 f=reinterpret_cast<T>(GetProcAddress(dll,n));
#else
 f=reinterpret_cast<T>(dlsym(dll,n));
#endif
 if(!f)throw std::runtime_error(std::string("missing HIP export ")+n);}
  explicit Api(unsigned version=7){
#ifdef _WIN32
const wchar_t*name=version==6?L"amdhip64_6.dll":L"amdhip64_7.dll";dll=LoadLibraryExW(name,nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!dll)throw std::runtime_error("HIP runtime not found in System32");
#else
  if(version!=7)throw std::runtime_error("Linux research backend requires HIP 7");
  const char*library=std::getenv("DLSSNR_RESEARCH_HIP_LIBRARY");
  if(library&&library[0]!='/')throw std::runtime_error("DLSSNR_RESEARCH_HIP_LIBRARY must be an absolute path");
  dll=dlopen(library?library:"libamdhip64.so.7",RTLD_NOW|RTLD_LOCAL);
  if(!dll)throw std::runtime_error(std::string("Cannot load native HIP 7: ")+dlerror());
  Load(hipRuntimeGetVersion,"hipRuntimeGetVersion");
  int actual=0;
  if(hipRuntimeGetVersion(&actual)||actual/10000000!=7)
   throw std::runtime_error("Loaded library is not HIP 7 (runtime="+std::to_string(actual)+")");
#endif
 #define LOAD(name) Load(name,#name)
 LOAD(hipEventCreate);LOAD(hipEventRecord);LOAD(hipEventElapsedTime);LOAD(hipEventDestroy);LOAD(hipEventSynchronize);LOAD(hipHostMalloc);LOAD(hipInit);LOAD(hipRuntimeGetVersion);LOAD(hipGetDeviceCount);LOAD(hipGetDevice);LOAD(hipDeviceGetName);LOAD(hipSetDevice);LOAD(hipMemGetInfo);LOAD(hipMalloc);LOAD(hipFree);LOAD(hipMemcpy);LOAD(hipMemcpyAsync);LOAD(hipMemsetAsync);LOAD(hipDeviceSynchronize);LOAD(hipStreamCreate);LOAD(hipStreamSynchronize);LOAD(hipStreamDestroy);LOAD(hipImportExternalMemory);LOAD(hipExternalMemoryGetMappedBuffer);LOAD(hipDestroyExternalMemory);LOAD(hipImportExternalSemaphore);LOAD(hipSignalExternalSemaphoresAsync);LOAD(hipWaitExternalSemaphoresAsync);LOAD(hipDestroyExternalSemaphore);LOAD(hipModuleLoad);LOAD(hipModuleGetFunction);LOAD(hipModuleLaunchKernel);LOAD(hipModuleUnload);LOAD(hipGetErrorName);
 #undef LOAD
 }
 void EnableVmm(){Load(hipMemAddressReserve,"hipMemAddressReserve");Load(hipMemAddressFree,"hipMemAddressFree");Load(hipMemCreate,"hipMemCreate");Load(hipMemRelease,"hipMemRelease");Load(hipMemMap,"hipMemMap");Load(hipMemUnmap,"hipMemUnmap");Load(hipMemSetAccess,"hipMemSetAccess");Load(hipMemGetAllocationGranularity,"hipMemGetAllocationGranularity");}
 void EnableGraphs(){Load(hipStreamBeginCapture,"hipStreamBeginCapture");Load(hipStreamEndCapture,"hipStreamEndCapture");Load(hipGraphInstantiate,"hipGraphInstantiate");Load(hipGraphLaunch,"hipGraphLaunch");Load(hipGraphDestroy,"hipGraphDestroy");Load(hipGraphExecDestroy,"hipGraphExecDestroy");}
 void EnableGameGraphs(){EnableGraphs();Load(hipStreamCreateWithFlags,"hipStreamCreateWithFlags");Load(hipGraphGetNodes,"hipGraphGetNodes");}
 void Check(int result,const char*what){if(result)throw std::runtime_error(std::string(what)+": "+hipGetErrorName(result)+" ("+std::to_string(result)+")");}
 // Keep runtime loaded until process teardown: driver-owned workers may outlive probe objects.
};
}
