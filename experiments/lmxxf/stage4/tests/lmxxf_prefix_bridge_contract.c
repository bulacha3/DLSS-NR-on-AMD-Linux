/* Real public HIP bridge + ordered V3; backend enqueue and HIP are simulated.
 * Exercises the user's exact profile through activation and ABI forwarding. */
#define DLSSNR_LMXXF 1
#include "../native/hip_bridge.c"
#include <assert.h>
static int mode,references,enqueues,creates,destroys,original_calls,fail_sync;
static unsigned expected_w,expected_h,expected_seed;static const void*expected_history;
static float expected_features[6];static void*const stream=(void*)0x5550;
static int retain(uint64_t owner){assert(owner==77);++references;return 0;}
static void release(uint64_t owner){assert(owner==77);--references;}
static void registration(void**m,const void*h,char*df,const char*dn,unsigned tl,void*ti,void*bi,void*bd,void*gd,int*ws){
 (void)m;(void)h;(void)df;(void)dn;(void)tl;(void)ti;(void)bi;(void)bd;(void)gd;(void)ws;
}
static int launch(const void*f,dim3_t grid,dim3_t block,void**args,u64 shared,void*st){
 (void)f;(void)grid;(void)block;(void)args;assert(st==stream&&!shared);++original_calls;return 0;
}
static int sync_stream(void*st){assert(st==stream);return fail_sync?719:0;}
static int create(const struct lmxxf_config*c,struct lmxxf_context**out,char*why,size_t n){
 (void)why;(void)n;assert(c->abi==3&&c->bytes==40&&c->width==expected_w&&c->height==expected_h&&c->stream==stream);
 assert(!*out);*out=malloc(1);assert(*out);++creates;return 0;
}
static int enqueue(struct lmxxf_context*c,const struct lmxxf_frame*f,char*why,size_t n){
 (void)why;(void)n;assert(c&&f->abi==3&&f->bytes==96&&f->width==expected_w&&f->height==expected_h);
 assert(f->seed==expected_seed&&f->history_rgb==expected_history&&!f->reserved);
 assert(!memcmp(f->prefix.values,expected_features,24));
 assert(f->rgb_bytes>=(uint64_t)expected_w*expected_h*12&&f->output_bytes>=(uint64_t)expected_w*expected_h*16);
 assert(lm4_worker->selected&&lm4_worker->skipped==2);++enqueues;if(mode==2){snprintf(why,n,"injected partial enqueue");return 2;}return 0;
}
static int destroy(struct lmxxf_context**c,char*why,size_t n){(void)why;(void)n;assert(*c);free(*c);*c=NULL;++destroys;return 0;}
static void reg(const void*f,const char*name){g_bridge.p___hipRegisterFunction(NULL,f,(char*)name,name,0,NULL,NULL,NULL,NULL,NULL);}
static int call(const void*f,void*p){void*args[]={p};return g_bridge.p_hipLaunchKernel(f,(dim3_t){1,1,1},(dim3_t){256,1,1},args,0,stream);}
int main(int argc,char**argv){
 mode=argc>1?atoi(argv[1]):0;assert(mode>=0&&mode<=5);
 _Static_assert(sizeof(struct lmxxf_frame)==96&&offsetof(struct lmxxf_frame,prefix)==72,"resident ABI 3");
 setenv("DLSSNR_LMXXF","1",1);g_hip_ok=1;real.p___hipRegisterFunction=registration;
 real.p_hipLaunchKernel=launch;real.p_hipStreamSynchronize=sync_stream;
 lm4_create_fn=create;lm4_enqueue_fn=enqueue;lm4_destroy_fn=destroy;
 reg((void*)1,"_Z11k_flag_wait");reg((void*)2,"_Z10k_flag_set");
 reg((void*)3,"_Z8k_import12ImportParams");reg((void*)4,"_Z10k_swin_varILi32ELb1EEv9VarParams");
 reg((void*)5,"_Z10k_swin_varILi32ELb0EEv9VarParams");reg((void*)6,"_Z8k_export12ExportParams");
 uint32_t flags[16]={0};uint64_t token;struct nr_buffer snapshot[2];uint32_t count;
 assert(!nr_register_resource(1,2,3,4,sizeof(flags),77,retain,release,&token));
 nr_associate_import(2,(void*)8);nr_associate_mapping((void*)8,flags,0,sizeof(flags));
 assert(!nr_snapshot(1,snapshot,2,&count)&&count==1);assert(!nr_claim_queue(snapshot,1,9));
 void*rgb=(void*)0x100000000ull,*history=(void*)0x200000000ull,*rgba=(void*)0x300000000ull;
 lm4_track(rgb,64*1024*1024);lm4_track(history,64*1024*1024);lm4_track(rgba,64*1024*1024);
 for(uint32_t frame=1;frame<=4;frame++){
  expected_w=frame<=2?2176:2432;expected_h=frame<=2?896:1024;expected_seed=frame-1;
  expected_history=frame%2?NULL:history;
  float values[]={.0625f,0,0,0,1.1f,1.1f};if(frame==4){values[4]=1.2f;values[5]=1.3f;}if(mode==3)values[0]=.125f;
  memcpy(expected_features,values,24);int selected=!(frame%2)&&mode!=3;int before=original_calls;
  assert(!nr_publish_input(token,frame,snapshot,1));void*flagptr=flags,*abortptr=(void*)0x34;void*boundary[]={&flagptr,&frame,&abortptr};
  assert(!g_bridge.p_hipLaunchKernel(g_flag_wait,(dim3_t){1,1,1},(dim3_t){256,1,1},boundary,0,stream));
  struct lm4_import im={.h=expected_h,.w=expected_w,.ph=expected_h,.pw=expected_w,.rgb=rgb};
  struct lm4_var pre={.h=expected_h,.w=expected_w,.flags=20,.rgb=rgb,.history=expected_history,.seed=expected_seed};memcpy(pre.features,values,24);
  struct lm4_var post={.h=expected_h,.w=expected_w,.flags=32,.rgba=rgba,.base=rgb,.head_scale=.03125f,.normalize=1};
  struct lm4_export ex={.rgba=rgba,.pw=expected_w,.h=expected_h,.w=expected_w};
  assert(!call((void*)3,&im));assert(!call((void*)4,&pre));assert(lm4_worker->selected==selected);
  assert(!call((void*)5,&pre));int error=0;
  if(mode==4&&selected)error=call((void*)99,NULL);
  if(mode==5&&selected)post.head_scale=.0625f;
  if(!error)error=call((void*)4,&post);
  if(!error){assert(!call((void*)6,&ex));fail_sync=mode==1&&selected;
   error=g_bridge.p_hipLaunchKernel(g_flag_set,(dim3_t){1,1,1},(dim3_t){256,1,1},boundary,0,stream);}
  if(error){
   assert(mode!=0&&mode!=3&&frame==2&&nr_job.active&&references==2);
   assert(nr_wait_output(token,frame,1)!=0&&lm4_worker->replaced==0);
   fail_sync=1;assert(g_bridge.p_hipStreamSynchronize(stream)!=0&&references==2&&nr_job.active);
   fail_sync=0;assert(g_bridge.p_hipStreamSynchronize(stream)!=0&&!nr_job.active&&references==1);break;
  }
  assert(original_calls-before==(selected?3:6));assert(!nr_job.active&&references==1);
  assert(!nr_wait_output(token,frame,1));assert(!nr_consumer_submitted(token,frame));
 }
 if(mode==0)assert(lm4_worker->replaced==2&&enqueues==2&&creates==2&&destroys==1);
 if(mode==3)assert(!lm4_worker->replaced&&!enqueues&&!creates);
 if(lm4_worker->context)assert(!destroy(&lm4_worker->context,NULL,0));
 snapshot[0].release(snapshot[0].owner);assert(references==0);
 printf("BRIDGE_REAL_LOG_PROFILE_CONTRACT mode=%d passed\n",mode);
 return 0;
}
