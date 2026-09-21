/* Private dispatch experiment for Daniel 0.3.1's ACTIVE VarParams kernels.
 * The old 40-byte SwinParams kernel is NOT selected. No GPU instructions,
 * weights or model arithmetic are replaced. Only the workgroup size can change.
 * Include from hip_bridge.c with -DDLSSNR_ACTIVE_C32.
 */
#define C32_NAME "_Z10k_swin_varILi32ELb0EEv9VarParams"
#define C32_MAX_ALLOCS 4096
#define C32_MAX_CASES 128
#define C32_MAX_BYTES (128u*1024u*1024u)
#define C32_GUARD 256u
#define C32_FRAME_INTERVAL 8u

struct c32_params {
    void *input, *output, *weights;
    int32_t h,w,x,y;
    uint32_t flags,padding;
    unsigned char optional[112];
    void *scratch;
};
_Static_assert(sizeof(struct c32_params)==168,"Pinned VarParams ABI");
_Static_assert(__builtin_offsetof(struct c32_params,scratch)==160,"VarParams scratch offset");
struct c32_alloc {void *p;size_t n;int device;uint64_t generation;};
struct c32_case {
    void *weights;uint64_t generation;int device;
    int32_t h,w,x,y;uint32_t flags;dim3_t grid;
    size_t input_n,output_n,scratch_n,input_offset,output_offset,scratch_offset;
    unsigned attempts[2],rejected[2],selected,complete;
    float ratio_sum[2];
    uint64_t last_frame;
};
static struct c32_alloc c32_allocs[C32_MAX_ALLOCS];
static struct c32_case c32_cases[C32_MAX_CASES];
static pthread_mutex_t c32_mutex=PTHREAD_MUTEX_INITIALIZER;
static const void *c32_original;
static const char *const c32_names[]={C32_NAME,"_Z10k_swin_varILi32ELb1EEv9VarParams",
    "_Z10k_swin_varILi64ELb0EEv9VarParams","_Z10k_swin_varILi128ELb0EEv9VarParams",
    "_Z10k_swin_varILi256ELb0EEv9VarParams","_Z16k_swin_1h_32_fp810SwinParams"};
static const char *const c32_labels[]={"var32_plain","var32_special","var64","var128","var256","legacy32"};
static const void *c32_functions[6];
static uint64_t c32_seen[6],c32_generation,c32_serial,c32_replays,c32_last_validation;
static uint64_t c32_token;
static uint32_t c32_frame_number;
static unsigned c32_ncases,c32_skips;
static int c32_has_frame,c32_failed;
static int (*c32_get_device)(int *);
static int (*c32_destroy_event)(void *);

static int c32_requested(void) {
    const char *v=getenv("DLSSNR_ACTIVE_C32");return v && !strcmp(v,"1");
}
static void c32_log(const char *fmt,...) {
    char line[768];va_list ap;va_start(ap,fmt);
    vsnprintf(line,sizeof(line)-1,fmt,ap);va_end(ap);
    logmsg("%s",line);
    const char *p=getenv("DLSSNR_C32_REPORT");if (!p || p[0]!='/')return;
    int fd=open(p,O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW,0600);
    if (fd>=0) {size_t n=strlen(line);line[n++]='\n';ssize_t rc=write(fd,line,n);(void)rc;close(fd);}
}
static void c32_startup(void) {
    if (c32_requested())c32_log("[active-c32] bridge_loaded=1 build=2 strategy=dispatch original_model=1");
}
static void c32_register(const void *f,const char *name) {
    if (!name)return;
    for (unsigned i=0;i<6;i++)if (!strcmp(name,c32_names[i])) {
        __atomic_store_n(&c32_functions[i],f,__ATOMIC_RELEASE);
        if (!i)__atomic_store_n(&c32_original,f,__ATOMIC_RELEASE);
        if (c32_requested())c32_log("[active-c32] registered=%s",c32_labels[i]);
        return;
    }
}
static int c32_device(void) {
    int (*fn)(int *)=__atomic_load_n(&c32_get_device,__ATOMIC_ACQUIRE);
    if (!fn) {fn=dlsym(g_hip,"hipGetDevice");__atomic_store_n(&c32_get_device,fn,__ATOMIC_RELEASE);}
    int d=-1;return fn && !fn(&d)?d:-1;
}
static struct c32_alloc *c32_allocation(const void *p,int d) {
    uintptr_t x=(uintptr_t)p;
    for (unsigned i=0;i<C32_MAX_ALLOCS;i++) {
        struct c32_alloc *a=&c32_allocs[i];uintptr_t b=(uintptr_t)a->p;
        if (a->p && a->device==d && x>=b && x-b<a->n)return a;
    }
    return NULL;
}
static void c32_track(void *p,size_t n) {
    if (!c32_requested() || !p || !n)return;
    int d=c32_device();if(d<0)return;
    pthread_mutex_lock(&c32_mutex);
    for (unsigned i=0;i<C32_MAX_ALLOCS;i++)if (!c32_allocs[i].p) {
        c32_allocs[i]=(struct c32_alloc){p,n,d,++c32_generation};break;
    }
    pthread_mutex_unlock(&c32_mutex);
}
static int c32_overlap(const void *p,size_t n,const void *q,size_t m) {
    uintptr_t a=(uintptr_t)p,b=(uintptr_t)q;
    return a<=b?b-a<n:a-b<m;
}
static int c32_invalidate(void *p,size_t n,int freeing) {
    if (!c32_requested() || !p || !n)return 0;
    int d=c32_device();if(d<0)return 0;
    pthread_mutex_lock(&c32_mutex);
    struct c32_alloc *a=c32_allocation(p,d);
    if(a)for(unsigned i=0;i<c32_ncases;i++) {
        struct c32_case *c=&c32_cases[i];
        if (c->device==d && c->generation==a->generation &&
            (freeing || c32_overlap(p,n,c->weights,a->n-((uintptr_t)c->weights-(uintptr_t)a->p)))) {
            c->generation=0;c->selected=256;c->complete=1;
        }
    }
    pthread_mutex_unlock(&c32_mutex);return 0;
}
static void c32_untrack(void *p) {
    if (!c32_requested() || !p)return;
    int d=c32_device();pthread_mutex_lock(&c32_mutex);
    for(unsigned i=0;i<C32_MAX_ALLOCS;i++)if(c32_allocs[i].p==p && c32_allocs[i].device==d)c32_allocs[i].p=NULL;
    pthread_mutex_unlock(&c32_mutex);
}
static void c32_frame(uint64_t token,uint32_t frame) {
    pthread_mutex_lock(&c32_mutex);
    if(!c32_has_frame || token!=c32_token || frame!=c32_frame_number) {
        c32_has_frame=1;c32_token=token;c32_frame_number=frame;++c32_serial;
    }
    pthread_mutex_unlock(&c32_mutex);
}
static int c32_same(dim3_t a,dim3_t b) {return a.x==b.x && a.y==b.y && a.z==b.z;}
static int c32_zero(const void *p,size_t n) {
    const unsigned char *b=p;for(size_t i=0;i<n;i++)if(b[i])return 0;return 1;
}
static int c32_call(const struct c32_params *p,dim3_t grid,unsigned threads,void *stream) {
    void *args[]={(void *)p};return real.p_hipLaunchKernel(c32_original,grid,(dim3_t){threads,1,1},args,0,stream);
}
/* Both writable allocations are private copies. Read-only input and weights
 * must occupy DIFFERENT allocations. No validation dispatch touches game output.
 * The optional operations are deliberately excluded: their ABI includes extra
 * outputs and temporal state. They keep the exact original launch.
 */
struct c32_shadow {void *gpu;unsigned char *initial,*reference,*readback;size_t size;};
static int c32_shadow_create(struct c32_shadow *s,size_t n) {
    s->size=n+2*C32_GUARD;
    s->initial=malloc(s->size);s->reference=malloc(s->size);s->readback=malloc(s->size);
    if (!s->initial || !s->reference || !s->readback)return 2;
    memset(s->initial,0xa5,s->size);
    /* Distinct payload poison is also used for the second independent frame. */
    for(size_t i=C32_GUARD;i<s->size-C32_GUARD;i++)s->initial[i]=(unsigned char)(i*29u+(c32_serial&255u));
    return real.p_hipMalloc(&s->gpu,s->size);
}
static int c32_shadow_reset(struct c32_shadow *s) {return real.p_hipMemcpy(s->gpu,s->initial,s->size,1);}
static int c32_shadow_read(struct c32_shadow *s,unsigned char *out) {return real.p_hipMemcpy(out,s->gpu,s->size,2);}
static int c32_guard_ok(struct c32_shadow *s,const unsigned char *b) {
    for(size_t i=0;i<C32_GUARD;i++)if(b[i]!=0xa5 || b[s->size-1-i]!=0xa5)return 0;
    return 1;
}
static int c32_shadow_free(struct c32_shadow *s) {
    int e=s->gpu?real.p_hipFree(s->gpu):0;
    free(s->initial);free(s->reference);free(s->readback);return e;
}
static int c32_measure(const struct c32_params *p,dim3_t grid,unsigned threads,void *st,
                       void *start,void *end,float *ms) {
    int e=real.p_hipEventRecord(start,st);
    if(!e)e=c32_call(p,grid,threads,st);
    if(!e)e=real.p_hipEventRecord(end,st);
    if(!e)e=real.p_hipStreamSynchronize(st);
    if(!e)e=real.p_hipEventElapsedTime(ms,start,end);
    return e;
}
static int c32_validate(struct c32_case *c,const struct c32_params *p,dim3_t grid,void *st,
                         struct c32_alloc *output,struct c32_alloc *scratch,unsigned candidate) {
    struct c32_shadow s[2]={{0},{0}};void *start=NULL,*end=NULL;int e=0,identical=0;
    float old_ms=0,new_ms=0;
    if(!c32_destroy_event)c32_destroy_event=dlsym(g_hip,"hipEventDestroy");
    if(!c32_destroy_event || !real.p_hipEventRecord || !real.p_hipEventElapsedTime) {
        c->complete=1;c32_log("[active-c32] skip=timing-api-unavailable");return 0;
    }
    e=real.p_hipStreamSynchronize(st);if(e)goto cleanup;
    e=c32_shadow_create(&s[0],output->n);if(e)goto cleanup;
    e=c32_shadow_create(&s[1],scratch->n);if(e)goto cleanup;
    e=real.p_hipEventCreate(&start);if(e)goto cleanup;
    e=real.p_hipEventCreate(&end);if(e)goto cleanup;
    struct c32_params q=*p;
    q.output=(char *)s[0].gpu+C32_GUARD+((uintptr_t)p->output-(uintptr_t)output->p);
    q.scratch=(char *)s[1].gpu+C32_GUARD+((uintptr_t)p->scratch-(uintptr_t)scratch->p);
    for(unsigned pass=0;pass<2;pass++) {
        for(unsigned i=0;i<2 && !e;i++)e=c32_shadow_reset(&s[i]);
        if(!e)e=c32_call(&q,grid,pass?candidate:256,st);
        if(!e)e=real.p_hipStreamSynchronize(st);
        for(unsigned i=0;i<2 && !e;i++)e=c32_shadow_read(&s[i],pass?s[i].readback:s[i].reference);
        if(e)goto cleanup;
    }
    identical=1;
    for(unsigned i=0;i<2;i++)if(memcmp(s[i].reference,s[i].readback,s[i].size) ||
        !c32_guard_ok(&s[i],s[i].reference) || !c32_guard_ok(&s[i],s[i].readback))identical=0;
    if(!memcmp(s[0].reference,s[0].initial,s[0].size))identical=0; /* no-op reference is no evidence */
    if(identical) {
        /* Two ABBA rounds. Reset both scratch allocations OUTSIDE the timer. */
        const unsigned order[]={256,candidate,candidate,256,256,candidate,candidate,256};
        for(unsigned i=0;i<8;i++) {
            for(unsigned j=0;j<2 && !e;j++)e=c32_shadow_reset(&s[j]);
            float ms=0;if(!e)e=c32_measure(&q,grid,order[i],st,start,end,&ms);
            if(e)goto cleanup;
            if(!(ms>0 && ms<10000)) {identical=0;break;}
            if(order[i]==256)old_ms+=ms*.25f;else new_ms+=ms*.25f;
        }
    }
    unsigned k=candidate==128?0:1;
    c->attempts[k]++;
    if(!identical || !(old_ms>0 && new_ms>0) || new_ms>=old_ms*.97f)c->rejected[k]=1;
    else c->ratio_sum[k]+=new_ms/old_ms;
    c32_log("[active-c32] trial=%u shape=%dx%d shift=%d,%d flags=%u threads=%u identical=%d original_ms=%.6f candidate_ms=%.6f accepted=%d",
        c->attempts[k],p->w,p->h,p->x,p->y,p->flags,candidate,identical,old_ms,new_ms,!c->rejected[k]);
cleanup:
    {int rc;
     if(end){rc=c32_destroy_event(end);if(!e)e=rc;}
     if(start){rc=c32_destroy_event(start);if(!e)e=rc;}
     for(unsigned i=0;i<2;i++){rc=c32_shadow_free(&s[i]);if(!e)e=rc;}
    }
    /* Resource exhaustion in a private experiment must not break a working
     * game. No real output has been touched; all other HIP failures propagate. */
    if(e==2){c->complete=1;c32_log("[active-c32] skip=shadow-memory-unavailable");return 0;}
    return e;
}
static int c32_try_launch(const void *f,dim3_t grid,dim3_t block,void **args,u64 shared,void *st,int *result) {
    if(!c32_requested())return 0;
    int which=-1;
    for(unsigned i=0;i<6;i++)if(f && f==__atomic_load_n(&c32_functions[i],__ATOMIC_ACQUIRE)){which=i;break;}
    if(which<0)return 0;
    uint64_t seen=__atomic_add_fetch(&c32_seen[which],1,__ATOMIC_RELAXED);
    if(seen==1)c32_log("[active-c32] dispatch=%s block=%u,%u,%u grid=%u,%u,%u",c32_labels[which],block.x,block.y,block.z,grid.x,grid.y,grid.z);
    if(which || !args || !args[0])return 0;
    struct c32_params p;memcpy(&p,args[0],sizeof(p));
    if(shared || block.x!=256 || block.y!=1 || block.z!=1 || !grid.x || !grid.y || grid.z!=1 ||
       p.h<=0 || p.w<=0 || p.h>8192 || p.w>8192 || (p.flags!=0 && p.flags!=2) ||
       !c32_zero(p.optional,sizeof(p.optional))) {
        if(__atomic_add_fetch(&c32_skips,1,__ATOMIC_RELAXED)<=4)
            c32_log("[active-c32] skip=optional-operation-or-launch flags=%u optional_nonzero=%d",p.flags,!c32_zero(p.optional,sizeof(p.optional)));
        return 0;
    }
    int d=c32_device();if(d<0)return 0;
    pthread_mutex_lock(&c32_mutex);int e=0,handled=0;
    if(c32_failed)goto done;
    if(!c32_has_frame) {
        if(++c32_skips<=8)c32_log("[active-c32] skip=no-ordered-frame-context");
        goto done;
    }
    struct c32_alloc *in=c32_allocation(p.input,d),*out=c32_allocation(p.output,d),
        *weight=c32_allocation(p.weights,d),*scratch=c32_allocation(p.scratch,d);
    if(!in || !out || !weight || !scratch || out==scratch || in==out || in==scratch ||
       weight==out || weight==scratch || out->n>C32_MAX_BYTES || scratch->n>C32_MAX_BYTES) {
        if(++c32_skips<=8)c32_log("[active-c32] skip=allocation-or-alias input=%d output=%d weights=%d scratch=%d",!!in,!!out,!!weight,!!scratch);
        goto done;
    }
    struct c32_case *c=NULL,*slot=NULL;
    for(unsigned i=0;i<c32_ncases;i++) {
        struct c32_case *x=&c32_cases[i];
        if(!x->generation && !slot)slot=x;
        if(x->generation==weight->generation && x->device==d && x->weights==p.weights &&
           x->h==p.h && x->w==p.w && x->x==p.x && x->y==p.y && x->flags==p.flags &&
           c32_same(x->grid,grid) && x->input_n==in->n && x->output_n==out->n && x->scratch_n==scratch->n &&
           x->input_offset==(uintptr_t)p.input-(uintptr_t)in->p &&
           x->output_offset==(uintptr_t)p.output-(uintptr_t)out->p &&
           x->scratch_offset==(uintptr_t)p.scratch-(uintptr_t)scratch->p){c=x;break;}
    }
    if(!c) {
        if(!slot && c32_ncases<C32_MAX_CASES)slot=&c32_cases[c32_ncases++];
        if(!slot)goto done;
        *slot=(struct c32_case){.weights=p.weights,.generation=weight->generation,.device=d,
            .h=p.h,.w=p.w,.x=p.x,.y=p.y,.flags=p.flags,.grid=grid,
            .input_n=in->n,.output_n=out->n,.scratch_n=scratch->n,
            .input_offset=(uintptr_t)p.input-(uintptr_t)in->p,
            .output_offset=(uintptr_t)p.output-(uintptr_t)out->p,
            .scratch_offset=(uintptr_t)p.scratch-(uintptr_t)scratch->p,.selected=256};c=slot;
    }
    if(!c->complete && c32_serial-c32_last_validation>=C32_FRAME_INTERVAL && c->last_frame!=c32_serial) {
        unsigned k=(!c->rejected[0] && c->attempts[0]<2)?0:1;
        c32_last_validation=c32_serial;c->last_frame=c32_serial;
        e=c32_validate(c,&p,grid,st,out,scratch,k?64:128);if(e)goto done;
        if((c->rejected[0] || c->attempts[0]>=2) && (c->rejected[1] || c->attempts[1]>=2)) {
            float best=1;for(unsigned j=0;j<2;j++)if(!c->rejected[j] && c->attempts[j]>=2 && c->ratio_sum[j]*.5f<best) {
                best=c->ratio_sum[j]*.5f;c->selected=j?64:128;
            }
            c->complete=1;
            c32_log("[active-c32] selected=%u shape=%dx%d shift=%d,%d flags=%u ratio=%.4f accepted_frames=%u",
                    c->selected,p.w,p.h,p.x,p.y,p.flags,best,c->selected==256?0:2);
        }
    }
    if(c->complete && c->selected!=256) {
        e=c32_call(&p,grid,c->selected,st);handled=1;++c32_replays;
        if(c32_replays==1 || c32_replays%4096==0)c32_log("[active-c32] replay=%llu threads=%u",(unsigned long long)c32_replays,c->selected);
    }
done:
    if(e){c32_failed=1;handled=1;c32_log("[active-c32] gpu_error=%d propagated=1",e);}
    pthread_mutex_unlock(&c32_mutex);if(handled)*result=e;return handled;
}
