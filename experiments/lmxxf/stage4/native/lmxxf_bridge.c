/* Daniel 0.3.1 ABI, stage 4. Original import/reprojection/export and ordered
 * completion remain. First frame verifies boundaries on the ORIGINAL path;
 * eligible following frames replace the complete neural interval with lmxxf.
 * Unsupported profiles remain original and are explicitly reported. */
#include "../experiments/lmxxf/resident_backend.h"
#include "../experiments/lmxxf/stage4_geometry.h"
#include "lmxxf_timing.h"
struct lm4_import {const void*source;int32_t pitch,format,h,w,ph,pw;void*rgb;uint32_t hdr;float exposure;};
struct lm4_export {const void*rgba;int32_t pw,h,w,pitch,format,pad;void*destination;uint32_t hdr,pad2;const void*rgb;uint32_t difference;float exposure;};
struct lm4_var {
 const void*input;void*output;const void*weights;int32_t h,w,x,y;uint32_t flags,pad;
 void*down_a,*down_b;const void*rgb,*history;float features[6];uint32_t seed,pad2;
 void*rgba;const void*base,*blend_history;float head_scale,blend_strength;
 uint32_t normalize,pad3;const void*decoder;void*scratch;
};
_Static_assert(sizeof(struct lm4_import)==48,"ImportParams ABI");
_Static_assert(sizeof(struct lm4_export)==64,"ExportParams ABI");
_Static_assert(sizeof(struct lm4_var)==168,"VarParams ABI");
_Static_assert(__builtin_offsetof(struct lm4_var,seed)==104,"seed ABI");
_Static_assert(__builtin_offsetof(struct lm4_var,rgba)==112,"RGBA ABI");
_Static_assert(__builtin_offsetof(struct lm4_var,head_scale)==136,"head scale ABI");
struct lm4_alloc {uintptr_t base;uint64_t bytes;};
static struct lm4_alloc lm4_allocations[4096];
static pthread_mutex_t lm4_mutex=PTHREAD_MUTEX_INITIALIZER;
enum {LM4_OTHER,LM4_IMPORT,LM4_SPECIAL,LM4_NEURAL,LM4_REPROJECT,LM4_EXPORT,LM4_MEAN};
enum {LM4_BAD_IMPORT=1u,LM4_BAD_PREFIX=2u,LM4_BAD_POST=4u,LM4_BAD_NEURAL_ORDER=8u,LM4_BAD_REPROJECT=16u,LM4_BAD_EXPORT=32u,LM4_BAD_MEAN=64u,LM4_BAD_UNKNOWN=128u,LM4_BAD_INCOMPLETE=256u};
struct lm4_function {const void*f;int kind;char name[128];};
static struct lm4_function lm4_functions[128];static unsigned lm4_function_count;
static void*lm4_library;
static int (*lm4_create_fn)(const struct lmxxf_config*,struct lmxxf_context**,char*,size_t);
static int (*lm4_enqueue_fn)(struct lmxxf_context*,const struct lmxxf_frame*,char*,size_t);
static int (*lm4_destroy_fn)(struct lmxxf_context**,char*,size_t);
static int (*lm4_stats_fn)(struct lmxxf_context*,struct lmxxf_submission_stats*);
static int (*lm4_acquire_fn)(const struct lmxxf_config*,struct lmxxf_context**,struct lmxxf_residency_stats*,char*,size_t);
static int (*lm4_return_fn)(struct lmxxf_context**,void*,int,struct lmxxf_residency_stats*,char*,size_t);
struct lm4_worker {
 struct lm4_worker*next;struct lmxxf_context*context;unsigned cw,ch;
 uint64_t frames,replaced,skipped;unsigned rejected,mean_preserved;int previous_eligible,phase,eligible,selected,failed;
 void*stream,*context_stream,*final_output;uint64_t token,started;
 struct lm4_import import;struct lm4_var prefix;
 int resident_lease;struct lmxxf_residency_stats residency;
 struct lm4_timing timing;
};
/* Process-owned root retains contexts even after a failed HIP worker exits. */
static struct lm4_worker*lm4_workers;static _Thread_local struct lm4_worker*lm4_worker;
static int lm4_requested(void){const char*v=getenv("DLSSNR_LMXXF");return v&&!strcmp(v,"1");}
static uint64_t lm4_now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;}
static void lm4_log(const char*fmt,...){
 char line[1000];va_list a;va_start(a,fmt);vsnprintf(line,sizeof(line)-2,fmt,a);va_end(a);
 logmsg("%s",line);const char*p=getenv("DLSSNR_LMXXF_REPORT");if(!p||p[0]!='/')return;
 int fd=open(p,O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW,0600);
 if(fd>=0){size_t n=strlen(line);line[n++]='\n';ssize_t result=write(fd,line,n);(void)result;close(fd);}
}
static void lm4_startup(void){if(lm4_requested())lm4_log("[lmxxf-stage4] bridge_loaded=1 build=13 graph_tail=1 output_copy=0 direct_game_io=1 boundary_conversions=0 residency=shared-default-stream prefix_parameters=from-game preserve_mean=1 core=lds-fixed activation=after-boundary-preflight");}
static void lm4_track(void*p,uint64_t n){
 if(!p||!n)return;pthread_mutex_lock(&lm4_mutex);
 for(unsigned i=0;i<4096;i++)if(!lm4_allocations[i].base){lm4_allocations[i]=(struct lm4_alloc){(uintptr_t)p,n};break;}
 pthread_mutex_unlock(&lm4_mutex);
}
static void lm4_untrack(void*p){pthread_mutex_lock(&lm4_mutex);for(unsigned i=0;i<4096;i++)if(lm4_allocations[i].base==(uintptr_t)p)lm4_allocations[i].base=0;pthread_mutex_unlock(&lm4_mutex);}
static uint64_t lm4_room(const void*p){
 uintptr_t x=(uintptr_t)p;uint64_t r=0;pthread_mutex_lock(&lm4_mutex);
 for(unsigned i=0;i<4096;i++){struct lm4_alloc*a=&lm4_allocations[i];if(a->base&&x>=a->base&&x-a->base<a->bytes){r=a->bytes-(x-a->base);break;}}
 pthread_mutex_unlock(&lm4_mutex);return r;
}
static void lm4_register(const void*f,const char*n){
 if(!f||!n)return;int k=LM4_OTHER;
 if(!strcmp(n,"_Z8k_import12ImportParams"))k=LM4_IMPORT;
 else if(!strcmp(n,"_Z8k_export12ExportParams"))k=LM4_EXPORT;
 else if(!strcmp(n,"_Z10k_swin_varILi32ELb1EEv9VarParams"))k=LM4_SPECIAL;
 else if(!strcmp(n,"_Z11k_reproject12ReprojParams"))k=LM4_REPROJECT;
 else if(!strcmp(n,"_Z6k_mean10MeanParams"))k=LM4_MEAN;
 else{
 static const char*const names[]={
 "_Z10k_swin_varILi32ELb0EEv9VarParams","_Z10k_swin_varILi64ELb0EEv9VarParams","_Z10k_swin_varILi128ELb0EEv9VarParams","_Z10k_swin_varILi256ELb0EEv9VarParams",
 "_Z16k_swin_1h_32_fp810SwinParams","_Z21k_pre_block_1h_32_fp89PreParams","_Z22k_post_block_1h_32_fp810PostParams",
 "_Z6k_ffwd10FfwdParams","_Z10k_conv_res10ConvParams","_Z10k_qkv_attn10AttnParams","_Z7k_ffwd211Ffwd2Params","_Z11k_conv_res211Conv2Params","_Z11k_qkv_attn210AttnParams",
 "_Z8k_expand12ExpandParams","_Z13k_conv_splitk12ConvParams1d","_Z5k_qkv9QkvParams","_Z11k_attention12AttnParams1d","_Z9k_expand212ExpandParams","_Z11k_contract212ConvParams1d","_Z6k_qkv29QkvParams","_Z12k_attention212AttnParams1d",
 "_Z14k_ffwd_inpview12FfwdPlParams","_Z16k_conv_res_views12ConvPlParams","_Z12k_final_head10HeadParams","_Z8k_repack12RepackParams","_Z14k_dec_upsample11DecUpParams"};
 for(unsigned i=0;i<sizeof(names)/sizeof(*names);i++)if(!strcmp(n,names[i])){k=LM4_NEURAL;break;}}
 {pthread_mutex_lock(&lm4_mutex);unsigned i;for(i=0;i<lm4_function_count;i++)if(lm4_functions[i].f==f)break;
 if(i<128){lm4_functions[i].f=f;lm4_functions[i].kind=k;snprintf(lm4_functions[i].name,sizeof(lm4_functions[i].name),"%s",n);if(i==lm4_function_count)lm4_function_count++;}pthread_mutex_unlock(&lm4_mutex);}
}
static int lm4_kind(const void*f){int k=0;pthread_mutex_lock(&lm4_mutex);for(unsigned i=0;i<lm4_function_count;i++)if(lm4_functions[i].f==f){k=lm4_functions[i].kind;break;}pthread_mutex_unlock(&lm4_mutex);return k;}
/* Report each rejecting condition on the first three frames; collecting all
 * reasons avoids hiding a later boundary mismatch behind an earlier one. */
static void lm4_block(struct lm4_worker*w,unsigned bit,const char*reason){
 w->eligible=0;
 if(!(w->rejected&bit)&&w->frames<=3)lm4_log("[lmxxf-stage4] frame=%llu unsupported=%s phase=%d",(unsigned long long)w->frames,reason,w->phase);
 w->rejected|=bit;
}
static void lm4_unknown(const void*f){
 char name[128]="unregistered";pthread_mutex_lock(&lm4_mutex);
 for(unsigned i=0;i<lm4_function_count;i++)if(lm4_functions[i].f==f){snprintf(name,sizeof(name),"%s",lm4_functions[i].name);break;}
 pthread_mutex_unlock(&lm4_mutex);lm4_log("[lmxxf-stage4] unsupported_kernel=%s",name);
}
static int lm4_begin(uint64_t token,void*stream){
 if(!lm4_requested())return 0;
 if(!lm4_worker){struct lm4_worker*w=calloc(1,sizeof(*w));if(!w)return 2;
 pthread_mutex_lock(&lm4_mutex);w->next=lm4_workers;lm4_workers=w;pthread_mutex_unlock(&lm4_mutex);lm4_worker=w;}
 struct lm4_worker*w=lm4_worker;if(w->failed)return 3;
 w->eligible=1;w->selected=0;w->phase=0;w->skipped=0;w->rejected=0;w->mean_preserved=0;w->token=token;w->stream=stream;w->final_output=NULL;w->started=lm4_now();lm4_timing_begin(&w->timing,w->started);++w->frames;return 0;
}
static int lm4_error(const char*reason,int*e){if(lm4_worker){lm4_worker->failed=1;lm4_worker->previous_eligible=0;}lm4_log("[lmxxf-stage4] error=%s completed=0",reason);*e=3;return 1;}
static void lm4_original_error(int code){
 if(!lm4_requested()||!lm4_worker||lm4_worker->failed)return;
 char reason[80];int ignored;snprintf(reason,sizeof(reason),"original-kernel-launch-%d",code);lm4_error(reason,&ignored);
}
static int lm4_load(void){
 pthread_mutex_lock(&lm4_mutex);if(lm4_enqueue_fn){pthread_mutex_unlock(&lm4_mutex);return 0;}
 const char*p=getenv("DLSSNR_LMXXF_LIBRARY");if(p&&p[0]=='/')lm4_library=dlopen(p,RTLD_NOW|RTLD_LOCAL);
 if(lm4_library){lm4_create_fn=dlsym(lm4_library,"lmxxf_create");lm4_enqueue_fn=dlsym(lm4_library,"lmxxf_enqueue");lm4_destroy_fn=dlsym(lm4_library,"lmxxf_destroy");lm4_stats_fn=dlsym(lm4_library,"lmxxf_get_submission_stats");lm4_acquire_fn=dlsym(lm4_library,"lmxxf_acquire_resident");lm4_return_fn=dlsym(lm4_library,"lmxxf_return_after_sync");}
 int good=lm4_create_fn&&lm4_enqueue_fn&&lm4_destroy_fn;if(!good)lm4_enqueue_fn=NULL;pthread_mutex_unlock(&lm4_mutex);return good?0:3;
}
static int lm4_post_valid(const struct lm4_worker*w,const struct lm4_var*p){
 uint64_t n=(uint64_t)w->import.pw*w->import.ph;
 return p->flags==32&&p->w==w->import.pw&&p->h==w->import.ph&&!p->x&&!p->y&&p->base==w->import.rgb&&
 p->head_scale==.03125f&&p->normalize==1&&(!p->blend_history||p->blend_strength==0.f)&&lm4_room(p->rgba)>=n*16;
}
static int lm4_dispatch(const void*f,dim3_t nb,dim3_t db,void**a,u64 sh,void*st,int*e){
 (void)nb;(void)db;(void)sh;
 if(!lm4_requested()||!lm4_worker)return 0;struct lm4_worker*w=lm4_worker;int k=lm4_kind(f);*e=0;
 if(w->failed)return lm4_error("worker-already-failed",e);if(st!=w->stream)return lm4_error("stream-changed",e);
 if(k==LM4_IMPORT){
 if(w->phase||!a||!a[0])return lm4_error("import-order",e);
 struct lm4_import old=w->import;memcpy(&w->import,a[0],sizeof(w->import));w->phase=1;
 struct lmxxf_geometry g;
 int geometry_status=lmxxf_plan_geometry(w->import.pw,w->import.ph,&g);
 int geometry_valid=geometry_status==LMXXF_GEOMETRY_OK;
 w->eligible=geometry_valid&&w->import.w>0&&w->import.h>0&&w->import.w<=w->import.pw&&w->import.h<=w->import.ph&&lm4_room(w->import.rgb)>=(uint64_t)w->import.pw*w->import.ph*12;
 if(!w->eligible){lm4_block(w,LM4_BAD_IMPORT,geometry_valid?"import-contract":"import-geometry");if(w->frames<=3)lm4_log("[lmxxf-stage4] import image=%dx%d padded=%dx%d input_capacity=%llu",w->import.w,w->import.h,w->import.pw,w->import.ph,(unsigned long long)lm4_room(w->import.rgb));}
 if(w->frames<=3){
  if(geometry_valid)lm4_log("[lmxxf-stage4] geometry=automatic processing=%ux%u attention=%ux%u tokens=%u",g.width,g.height,g.token_width,g.token_height,g.token_width*g.token_height);
  else lm4_log("[lmxxf-stage4] geometry=unsupported reason=%s processing=%dx%d",lmxxf_geometry_reason(geometry_status),w->import.pw,w->import.ph);
 }
 if(old.pw!=w->import.pw||old.ph!=w->import.ph)w->previous_eligible=0;return 0;
 }
 if(k==LM4_SPECIAL){
 if(!a||!a[0])return lm4_error("missing-VarParams",e);struct lm4_var p;memcpy(&p,a[0],sizeof(p));
 if(p.flags&16){
 if(w->phase!=1)return lm4_error("prefix-order",e);w->phase=2;w->prefix=p;
 uint64_t n=(uint64_t)w->import.pw*w->import.ph;
 int profile=p.flags==20&&!p.x&&!p.y&&p.rgb==w->import.rgb&&p.w==w->import.pw&&p.h==w->import.ph&&lmxxf_features_valid(p.features)&&(!p.history||lm4_room(p.history)>=n*12);
 if(!profile)lm4_block(w,LM4_BAD_PREFIX,"prefix-contract");w->selected=w->eligible&&w->previous_eligible;
 if(w->frames<=3)lm4_log("[lmxxf-stage4] frame=%llu prefix_valid=%d features=%g,%g,%g,%g,%g,%g seed=%u history=%d shape=%dx%d selected=%d",(unsigned long long)w->frames,profile,p.features[0],p.features[1],p.features[2],p.features[3],p.features[4],p.features[5],p.seed,p.history!=NULL,p.w,p.h,w->selected);
 if(w->selected){++w->skipped;return 1;}return 0;
 }
 if(p.flags&32){
 if(w->phase!=2)return lm4_error("post-order",e);w->phase=3;w->final_output=p.rgba;
 int valid=lm4_post_valid(w,&p);if(!valid)lm4_block(w,LM4_BAD_POST,"post-contract");
 if(!valid&&w->frames<=3)lm4_log("[lmxxf-stage4] post_valid=0 scale=%g normalize=%u blend=%g history=%d output_capacity=%llu",p.head_scale,p.normalize,p.blend_strength,p.blend_history!=NULL,(unsigned long long)lm4_room(p.rgba));
 if(!w->selected)return 0;if(!valid)return lm4_error("post-contract-changed",e);if(lm4_load())return lm4_error("backend-load",e);
 char why[384];
 if(w->context&&(w->cw!=(unsigned)p.w||w->ch!=(unsigned)p.h||w->context_stream!=st))if(lm4_destroy_fn(&w->context,why,sizeof(why)))return lm4_error(why,e);
 if(!w->context){struct lmxxf_config cfg={LMXXF_ABI,sizeof(cfg),p.w,p.h,getenv("DLSSNR_LMXXF_ASSETS"),getenv("DLSSNR_LMXXF_MODULES"),st};
 const char*cache=getenv("DLSSNR_LMXXF_RESIDENCY");
 w->resident_lease=!st&&lm4_acquire_fn&&lm4_return_fn&&(!cache||strcmp(cache,"0"));
 w->residency=(struct lmxxf_residency_stats){.bytes=sizeof(w->residency)};
 uint64_t acquire_started=lm4_now();
 int rc=w->resident_lease?lm4_acquire_fn(&cfg,&w->context,&w->residency,why,sizeof(why)):lm4_create_fn(&cfg,&w->context,why,sizeof(why));
 w->timing.acquire_ns=lm4_now()-acquire_started;
 if(rc)return lm4_error(why,e);w->cw=p.w;w->ch=p.h;w->context_stream=st;}
 struct lmxxf_frame frame={LMXXF_ABI,sizeof(frame),p.w,p.h,w->prefix.rgb,w->prefix.history,p.rgba,lm4_room(w->prefix.rgb),w->prefix.history?lm4_room(w->prefix.history):0,lm4_room(p.rgba),w->prefix.seed,0};
 memcpy(frame.prefix.values,w->prefix.features,sizeof(frame.prefix.values));
 uint64_t enqueue_started=lm4_now();int enqueue_result=lm4_enqueue_fn(w->context,&frame,why,sizeof(why));
 w->timing.enqueue_ns=lm4_now()-enqueue_started;
 if(enqueue_result)return lm4_error(why,e);++w->skipped;return 1;
 }}
 if(k==LM4_SPECIAL||k==LM4_NEURAL){if(w->phase!=2){if(w->selected)return lm4_error("neural-order",e);lm4_block(w,LM4_BAD_NEURAL_ORDER,"neural-order");return 0;}if(w->selected){++w->skipped;return 1;}return 0;}
 if(k==LM4_REPROJECT){if(w->phase!=3){if(w->selected)return lm4_error("reproject-order",e);lm4_block(w,LM4_BAD_REPROJECT,"reproject-order");}return 0;}
 if(k==LM4_EXPORT){
 if(w->phase!=3||!a||!a[0])return lm4_error("export-order",e);struct lm4_export p;memcpy(&p,a[0],sizeof(p));
 int valid=p.rgba==w->final_output&&p.pw==w->import.pw&&p.w>0&&p.h>0&&p.w<=p.pw&&p.h<=w->import.ph;
 if(!valid){lm4_block(w,LM4_BAD_EXPORT,"export-contract");if(w->frames<=3)lm4_log("[lmxxf-stage4] export image=%dx%d pitch_width=%d output_matches=%d",p.w,p.h,p.pw,p.rgba==w->final_output);if(w->selected)return lm4_error("export-contract",e);}w->phase=4;return 0;
 }
 /* Original k_mean reads the imported RGB buffer after export and computes
  * the luminance statistic used by the original host. It is not neural work:
  * forward the same function, arguments, grid and stream before completion. */
 if(k==LM4_MEAN){
  if(w->phase!=4){lm4_block(w,LM4_BAD_MEAN,"mean-order");if(w->selected)return lm4_error("mean-order",e);}
  else ++w->mean_preserved;
  return 0;
 }
 if(w->frames<=3&&!(w->rejected&LM4_BAD_UNKNOWN))lm4_unknown(f);
 lm4_block(w,LM4_BAD_UNKNOWN,"unknown-kernel");
 if(w->selected)return lm4_error("unknown-kernel-inside-frame",e);return 0;
}
static int lm4_seal(void){if(!lm4_requested()||!lm4_worker)return 0;if(lm4_worker->selected&&lm4_worker->phase!=4){int e;lm4_error("incomplete-frame",&e);return e;}return 0;}
static void lm4_complete(int result){
 if(!lm4_requested()||!lm4_worker)return;struct lm4_worker*w=lm4_worker;
 if(result){int e;lm4_error("HIP-completion-failed",&e);return;}
 if(w->phase!=4)lm4_block(w,LM4_BAD_INCOMPLETE,"incomplete-frame");
 w->previous_eligible=w->eligible&&w->phase==4;if(w->selected)++w->replaced;
 uint64_t now=lm4_now(),wall_ns=0;
 unsigned slow=lm4_timing_complete(&w->timing,now,w->frames,&wall_ns);
 int sampled=w->frames<=3||w->frames%120==0||slow;
 if(sampled){
 lm4_log("[lmxxf-stage4] completed=%llu backend=%s replaced_total=%llu skipped_original_neural=%llu shape=%dx%d worker_wall_ms=%.3f next_eligible=%d blocked_mask=0x%x mean_preserved=%u",(unsigned long long)w->frames,w->selected?"lmxxf":"original-preflight-or-unsupported",(unsigned long long)w->replaced,(unsigned long long)w->skipped,w->import.pw,w->import.ph,wall_ns/1000000.,w->previous_eligible,w->rejected,w->mean_preserved);
 lm4_log("[lmxxf-stage4] timing=host frame=%llu mono_ms=%.3f worker_ms=%.3f idle_gap_ms=%.3f acquire_ms=%.3f enqueue_host_ms=%.3f slow_mask=%u slow_events=%llu slow_reports=%llu",(unsigned long long)w->frames,now/1000000.,wall_ns/1000000.,w->timing.idle_ns/1000000.,w->timing.acquire_ns/1000000.,w->timing.enqueue_ns/1000000.,lm4_timing_slow_mask(&w->timing,wall_ns,w->frames),(unsigned long long)w->timing.anomalies,(unsigned long long)w->timing.reports);
 if(w->context&&lm4_stats_fn){struct lmxxf_submission_stats stats={.bytes=sizeof(stats)};
  if(!lm4_stats_fn(w->context,&stats)){const char*mode=stats.mode==2?"graph":stats.mode==1?"warmup":stats.mode==3?"direct-fallback":"direct";
   lm4_log("[lmxxf-stage4] submission=%s graph_builds=%llu graph_replays=%llu direct_frames=%llu graph_nodes=%llu reason=%s",mode,(unsigned long long)stats.builds,(unsigned long long)stats.replays,(unsigned long long)stats.direct_frames,(unsigned long long)stats.nodes,stats.reason[0]?stats.reason:"none");
  }
 }
 }
 /* This point follows the ORIGINAL final marker and successful ORIGINAL
  * stream synchronization. Failed/partial jobs never reach cache insertion.
  * Detach from the per-thread root so a later game worker can reuse the same
  * weights and modules. Non-default streams keep their private ownership. */
 if(w->selected&&w->context&&w->resident_lease){
  char why[384];uint32_t reused=w->residency.reused,resized=w->residency.resized;
  int rc=lm4_return_fn(&w->context,w->stream,0,&w->residency,why,sizeof(why));
  if(rc){int ignored;lm4_error(why,&ignored);return;}
  if(sampled||resized||!reused){
   struct lmxxf_residency_stats*s=&w->residency;
   lm4_log("[lmxxf-stage4] residency=shared resident_id=%llu reused=%u resized=%u creations=%llu reuses=%llu resizes=%llu evictions=%llu idle=%llu weight_bytes=%llu scratch_bytes=%llu",(unsigned long long)s->resident_id,reused,resized,(unsigned long long)s->creations,(unsigned long long)s->reuses,(unsigned long long)s->resizes,(unsigned long long)s->evictions,(unsigned long long)s->cached,(unsigned long long)s->weight_bytes,(unsigned long long)s->scratch_bytes);
  }
 }
}
