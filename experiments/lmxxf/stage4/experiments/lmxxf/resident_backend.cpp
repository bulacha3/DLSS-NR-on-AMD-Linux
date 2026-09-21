#include "resident_backend.h"
#include "stage4_geometry.h"
#include "hip_reference_network.h"
#include <cstdio>
#include <thread>
#include <new>
#include <mutex>
using hip_reference::Options;
#define W 512
#define H 512
#include "optimized_options.h"
#undef W
#undef H
struct lmxxf_context {
 hip_reference::Network*network{};std::thread::id owner=std::this_thread::get_id();
 uint32_t width{},height{};
 bool poisoned=false,pending=false;
 int device=-1;
 bool resident_lease=false,graph_requested=false,profile_requested=false,usage_dirty=true;
 uint64_t resident_id=0,weight_bytes=0,scratch_bytes=0;
 std::string assets,modules,profile_report;
};
static int error(char*out,size_t n,int rc,const char*s){if(out&&n)std::snprintf(out,n,"%s",s);return rc;}
static bool region(const void*p,uint64_t n){uintptr_t a=reinterpret_cast<uintptr_t>(p);return a&&!(a&3)&&n&&n<=UINTPTR_MAX-a;}
static bool overlap(const void*a,uint64_t an,const void*b,uint64_t bn){auto x=reinterpret_cast<uintptr_t>(a),y=reinterpret_cast<uintptr_t>(b);return x<y+bn&&y<x+an;}
extern "C" int lmxxf_validate_frame(const lmxxf_frame*f,char*out,size_t n){
 struct lmxxf_geometry g;
 if(!f||f->abi!=LMXXF_ABI||f->bytes!=sizeof(*f)||f->reserved||!lmxxf_geometry(f->width,f->height,&g)||!lmxxf_features_valid(f->prefix.values))return error(out,n,LMXXF_INVALID,"frame ABI/geometry/prefix parameters");
 uint64_t rgb=uint64_t(f->width)*f->height*12,rgba=uint64_t(f->width)*f->height*16;
 if(!region(f->rgb,rgb)||!region(f->rgba_output,rgba)||f->rgb_bytes<rgb||f->output_bytes<rgba||
 (f->history_rgb&&(!region(f->history_rgb,rgb)||f->history_bytes<rgb))||(!f->history_rgb&&f->history_bytes)||
 overlap(f->rgb,rgb,f->rgba_output,rgba)||(f->history_rgb&&overlap(f->history_rgb,rgb,f->rgba_output,rgba)))
 return error(out,n,LMXXF_INVALID,"frame buffer capacity/alignment/alias");
 return error(out,n,LMXXF_OK,"");
}
static bool owner(lmxxf_context*c){
 int device=-1;
 return c&&c->owner==std::this_thread::get_id()&&c->network&&
        !c->network->Runtime().hipGetDevice(&device)&&device==c->device;
}
static void release(lmxxf_context*c){
 delete c->network;delete c;
}
extern "C" int lmxxf_create(const lmxxf_config*cfg,lmxxf_context**dest,char*out,size_t n){
 struct lmxxf_geometry g;
 if(!cfg||!dest||*dest||cfg->abi!=LMXXF_ABI||cfg->bytes!=sizeof(*cfg)||!lmxxf_geometry(cfg->width,cfg->height,&g)||
 !cfg->assets||cfg->assets[0]!='/'||!cfg->modules||cfg->modules[0]!='/')return error(out,n,LMXXF_INVALID,"configuration ABI/paths/geometry");
 lmxxf_context*c=nullptr;
 try{c=new lmxxf_context;c->width=cfg->width;c->height=cfg->height;
 auto o=optimized_options(0);o.width=c->width;o.height=c->height;o.assets=cfg->assets;o.modules=cfg->modules;o.use_shared_stream=true;o.shared_stream=cfg->stream;o.game_prefix=true;o.borrow_output=true;o.game_rgb_io=true;const char*graph=std::getenv("DLSSNR_LMXXF_GRAPH");o.game_graph=!graph||std::strcmp(graph,"0");
 const char*profile=std::getenv("DLSSNR_LMXXF_GPU_PROFILE");
 const char*profile_report=std::getenv("DLSSNR_LMXXF_GPU_PROFILE_REPORT");
 o.game_profile=profile&&!std::strcmp(profile,"1")&&profile_report&&profile_report[0]=='/';
 if(o.game_profile)o.game_profile_report=profile_report;
 c->assets=cfg->assets;c->modules=cfg->modules;c->graph_requested=o.game_graph;c->profile_requested=o.game_profile;c->profile_report=o.game_profile_report;
 c->network=new hip_reference::Network(std::move(o));auto&a=c->network->Runtime();
 a.Check(a.hipGetDevice(&c->device),"resident current HIP device");
 *dest=c;return error(out,n,LMXXF_OK,"");
 }catch(const std::exception&e){if(c)release(c);return error(out,n,LMXXF_FAILED,e.what());}
 catch(...){if(c)release(c);return error(out,n,LMXXF_FAILED,"backend construction exception");}
}
extern "C" int lmxxf_enqueue(lmxxf_context*c,const lmxxf_frame*f,char*out,size_t n){
 if(!owner(c))return error(out,n,LMXXF_INVALID,"wrong HIP worker thread");
 if(c->poisoned)return error(out,n,LMXXF_FAILED,"poisoned backend; drain required");
 if(c->pending)return error(out,n,LMXXF_INVALID,"previous frame must drain before enqueue");
 int rc=lmxxf_validate_frame(f,out,n);if(rc)return rc;
 if(f->width!=c->width||f->height!=c->height)return error(out,n,LMXXF_INVALID,"context/frame geometry mismatch");
 try{c->network->SetPrefixParameters(f->prefix);c->pending=true;if(!c->weight_bytes)c->usage_dirty=true;
 // The caller pins RGB/history/output until the ORIGINAL stream drains.
 // Only prefix and head see these addresses; the captured core never does.
 c->network->Enqueue(const_cast<void*>(f->rgb),const_cast<void*>(f->history_rgb),f->rgba_output,f->seed);
 return error(out,n,LMXXF_OK,"");
 }catch(const std::exception&e){c->poisoned=true;return error(out,n,LMXXF_FAILED,e.what());}
 catch(...){c->poisoned=true;return error(out,n,LMXXF_FAILED,"backend enqueue exception");}
}
extern "C" int lmxxf_finish(lmxxf_context*c,char*out,size_t n){
 if(!owner(c))return error(out,n,LMXXF_INVALID,"wrong HIP worker thread");
 try{c->network->Synchronize();c->pending=false;return error(out,n,LMXXF_OK,"");}
 catch(const std::exception&e){c->poisoned=true;return error(out,n,LMXXF_PENDING,e.what());}
 catch(...){c->poisoned=true;return error(out,n,LMXXF_PENDING,"backend completion exception");}
}
extern "C" int lmxxf_destroy(lmxxf_context**c,char*out,size_t n){
 if(!c||!*c)return error(out,n,LMXXF_INVALID,"null context");int rc=lmxxf_finish(*c,out,n);if(rc)return rc;
 release(*c);*c=nullptr;return error(out,n,LMXXF_OK,"");
}
extern "C" int lmxxf_get_submission_stats(lmxxf_context*c,lmxxf_submission_stats*s){
 if(!owner(c)||!s||s->bytes!=sizeof(*s))return LMXXF_INVALID;
 c->network->SubmissionStats(s->mode,s->builds,s->replays,s->direct_frames,s->nodes);
 std::snprintf(s->reason,sizeof(s->reason),"%s",c->network->SubmissionReason());
 return LMXXF_OK;
}

// Idle residents have no owner thread, pending GPU work or borrowed game
// buffers. The process root deliberately has no destructor: HIP driver state
// can already be gone during process teardown. Live leases stay in the bridge.
struct ResidentCache {
 std::mutex mutex;
 // Keep the slot while its resident is leased. Erasing and reinserting the
 // node would free/allocate host memory on every frame. Keys come only from
 // the current HIP device, not game geometry or caller-supplied identifiers.
 std::map<int,lmxxf_context*> idle;
 uint64_t creations=0,reuses=0,resizes=0,evictions=0;
};
static ResidentCache& resident_cache(){static auto*p=new ResidentCache;return *p;}
static int current_device(){
 static auto*a=[](){auto*p=new hip_probe::Api;p->Check(p->hipInit(0),"residency HIP init");return p;}();
 int device=-1;a->Check(a->hipGetDevice(&device),"residency current device");return device;
}
static bool valid_stats(const lmxxf_residency_stats*s){return !s||s->bytes==sizeof(*s);}
static void usage(lmxxf_context*c){
 if(!c->usage_dirty)return;
 c->network->ResidencyUsage(c->weight_bytes,c->scratch_bytes);
 c->usage_dirty=false;
}
static void residency_snapshot(ResidentCache&cache,lmxxf_context*c,
                               lmxxf_residency_stats*s,bool reused,bool resized){
 if(!s)return;
 const auto idle=cache.idle.find(c->device);
 *s={sizeof(*s),uint32_t(reused),uint32_t(resized),uint32_t(c->device),
     c->resident_id,cache.creations,cache.reuses,cache.resizes,cache.evictions,
     uint64_t(idle!=cache.idle.end()&&idle->second),c->weight_bytes,c->scratch_bytes};
}
static void resize_resident(lmxxf_context*c,uint32_t width,uint32_t height){
 // The old frame's original stream already drained before cache insertion.
 // Preserve weights/modules; discard shape-specific graph and scratch.
 c->network->ResizeAfterDrain(width,height);
 c->width=width;c->height=height;c->usage_dirty=true;
}
extern "C" int lmxxf_acquire_resident(const lmxxf_config*cfg,lmxxf_context**dest,
                                      lmxxf_residency_stats*stats,char*out,size_t n){
 struct lmxxf_geometry geometry;
 if(!cfg||!dest||*dest||!valid_stats(stats)||cfg->abi!=LMXXF_ABI||cfg->bytes!=sizeof(*cfg)||
    cfg->stream||!cfg->assets||cfg->assets[0]!='/'||!cfg->modules||cfg->modules[0]!='/'||
    !lmxxf_geometry(cfg->width,cfg->height,&geometry))
  return error(out,n,LMXXF_INVALID,"resident acquisition requires default stream/configuration");
 try{
  const int device=current_device();auto&cache=resident_cache();
  const char*setting=std::getenv("DLSSNR_LMXXF_GRAPH");const bool graph=!setting||std::strcmp(setting,"0");
  const char*profile_flag=std::getenv("DLSSNR_LMXXF_GPU_PROFILE");
  const char*profile_path=std::getenv("DLSSNR_LMXXF_GPU_PROFILE_REPORT");
  const bool profile=profile_flag&&!std::strcmp(profile_flag,"1")&&profile_path&&profile_path[0]=='/';
  const char*profile_report=profile?profile_path:"";
  lmxxf_context*context=nullptr;lmxxf_context*discard=nullptr;bool resized=false;
  {
   std::lock_guard<std::mutex>lock(cache.mutex);
   auto it=cache.idle.find(device);
   if(it!=cache.idle.end()&&it->second){
    context=it->second;it->second=nullptr;context->owner=std::this_thread::get_id();
    if(context->assets!=cfg->assets||context->modules!=cfg->modules||context->graph_requested!=graph||context->profile_requested!=profile||context->profile_report!=profile_report){
     discard=context;context=nullptr;++cache.evictions;
    }
   }
  }
  if(discard)release(discard);
  const bool reused=context!=nullptr;
  if(context){
   *dest=context;
   if(context->width!=cfg->width||context->height!=cfg->height){resize_resident(context,cfg->width,cfg->height);resized=true;}
  }else{
   int rc=lmxxf_create(cfg,dest,out,n);if(rc)return rc;context=*dest;
  }
  context->resident_lease=true;
  {
   std::lock_guard<std::mutex>lock(cache.mutex);
   if(reused)++cache.reuses;else context->resident_id=++cache.creations;
   if(resized)++cache.resizes;
   residency_snapshot(cache,context,stats,reused,resized);
  }
  return error(out,n,LMXXF_OK,"");
 }catch(const std::exception&e){if(*dest)(*dest)->poisoned=true;return error(out,n,LMXXF_FAILED,e.what());}
 catch(...){if(*dest)(*dest)->poisoned=true;return error(out,n,LMXXF_FAILED,"resident acquisition exception");}
}
extern "C" int lmxxf_return_after_sync(lmxxf_context**ptr,void*stream,int sync_result,
                                       lmxxf_residency_stats*stats,char*out,size_t n){
 if(!ptr||!owner(*ptr)||!valid_stats(stats)||!(*ptr)->resident_lease||stream||(*ptr)->network->Stream()!=stream)
  return error(out,n,LMXXF_INVALID,"resident return requires owning thread/default stream");
 auto*c=*ptr;
 if(sync_result){c->poisoned=true;return error(out,n,LMXXF_PENDING,"original GPU drain failed; resident retained");}
 if(c->poisoned)return error(out,n,LMXXF_FAILED,"poisoned resident cannot be reused");
 try{
  if(current_device()!=c->device)return error(out,n,LMXXF_INVALID,"resident return device mismatch");
  c->pending=false;c->network->ConfirmExternalDrain();usage(c);
  auto&cache=resident_cache();lmxxf_context*discard=nullptr;
  {
   std::lock_guard<std::mutex>lock(cache.mutex);
   auto it=cache.idle.find(c->device);
   if(it!=cache.idle.end()){
    discard=it->second;
    if(discard){discard->owner=std::this_thread::get_id();++cache.evictions;}
    it->second=c;
   }else cache.idle.emplace(c->device,c);
   c->owner={};residency_snapshot(cache,c,stats,false,false);*ptr=nullptr;
  }
  if(discard)release(discard);
  return error(out,n,LMXXF_OK,"");
 }catch(const std::exception&e){return error(out,n,LMXXF_FAILED,e.what());}
 catch(...){return error(out,n,LMXXF_FAILED,"resident return exception");}
}
extern "C" int lmxxf_trim_resident(char*out,size_t n){
 try{
  const int device=current_device();auto&cache=resident_cache();lmxxf_context*discard=nullptr;
  {std::lock_guard<std::mutex>lock(cache.mutex);auto it=cache.idle.find(device);
   if(it!=cache.idle.end()){discard=it->second;cache.idle.erase(it);if(discard)++cache.evictions;}}
  if(discard){discard->owner=std::this_thread::get_id();release(discard);}
  return error(out,n,LMXXF_OK,"");
 }catch(const std::exception&e){return error(out,n,LMXXF_FAILED,e.what());}
 catch(...){return error(out,n,LMXXF_FAILED,"resident trim exception");}
}
