/* Opt-in C32 weight prepacking for the pinned upstream 0.3.1 gfx1201 kernel.
 * No neural arithmetic is changed. Every new weight/geometry combination is
 * compared byte for byte against the original before the candidate is used.
 * Included by hip_bridge.c; uses the already selected HIP runtime/device.
 */
#define C32_NAME "_Z16k_swin_1h_32_fp810SwinParams"
#define C32_RAW 20672u
#define C32_PACKED 57344u
#define C32_MAX_ALLOCATIONS 4096
#define C32_MAX_WEIGHTS 64
#define C32_MAX_CASES 256
#define C32_MAX_OUTPUT (128u * 1024u * 1024u)
#define C32_GUARD 256u

static const uint16_t c32_offsets[12288] = {
#include "c32_offsets.inc"
};
struct c32_params { void *input, *output, *weights; int32_t h, w, x, y; };
_Static_assert(sizeof(struct c32_params) == 40, "Pinned SwinParams ABI");
struct c32_alloc { void *ptr; size_t bytes; int device; };
struct c32_weight { void *source, *packed; int device, rejected; unsigned generation; };
struct c32_case { unsigned generation; int32_t h,w,x,y; dim3_t grid,block; int use; };
static struct c32_alloc c32_allocs[C32_MAX_ALLOCATIONS];
static struct c32_weight c32_weights[C32_MAX_WEIGHTS];
static struct c32_case c32_cases[C32_MAX_CASES];
static unsigned c32_generation, c32_ncases;
static pthread_mutex_t c32_mutex = PTHREAD_MUTEX_INITIALIZER;
static const void *c32_original;
static void *c32_module, *c32_function;
static int c32_initialized, c32_module_device = -1;
static uint64_t c32_replays, c32_baselines, c32_verified, c32_rejected;
static unsigned c32_seen;
static uint64_t c32_frame_token;
static uint32_t c32_frame_number;
static int c32_has_frame, c32_frame_validated;
static int (*c32_get_device)(int *);
static int (*c32_load_module)(void **, const char *);
static int (*c32_get_function)(void **, void *, const char *);
static int (*c32_launch_module)(void *, unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,void *,void **,void **);
static int (*c32_destroy_event)(void *);

/* Small, pointer-free result survives a normal crash/forced game exit. */
static void c32_log(const char *fmt,...) {
    char line[1024];va_list ap;
    va_start(ap,fmt);vsnprintf(line,sizeof(line),fmt,ap);va_end(ap);
    logmsg("%s",line);
    const char *path=getenv("DLSSNR_C32_REPORT");
    if (!path || path[0]!='/') return;
    int fd=open(path,O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW,0600);
    if (fd>=0) {
        size_t len=strlen(line);line[len++]='\n';
        ssize_t written=write(fd,line,len);(void)written;close(fd);
    }
}

static int c32_requested(void) {
    const char *s=getenv("DLSSNR_C32_PREPACK");
    return s && !strcmp(s,"1");
}
static int c32_device(void) {
    int d=-1;
    int (*fn)(int *)=__atomic_load_n(&c32_get_device,__ATOMIC_ACQUIRE);
    if (!fn) { fn=dlsym(g_hip,"hipGetDevice");__atomic_store_n(&c32_get_device,fn,__ATOMIC_RELEASE); }
    return fn && !fn(&d) ? d : -1;
}
static void c32_track(void *p,size_t n) {
    if (!c32_requested() || !p || !n) return;
    int d=c32_device(); if (d<0) return;
    pthread_mutex_lock(&c32_mutex);
    for (unsigned i=0;i<C32_MAX_ALLOCATIONS;i++) if (!c32_allocs[i].ptr) {
        c32_allocs[i]=(struct c32_alloc){p,n,d}; break;
    }
    pthread_mutex_unlock(&c32_mutex);
}
static size_t c32_available(void *p,int device) {
    uintptr_t address=(uintptr_t)p;
    for (unsigned i=0;i<C32_MAX_ALLOCATIONS;i++) {
        const struct c32_alloc *a=&c32_allocs[i]; uintptr_t begin=(uintptr_t)a->ptr;
        if (a->ptr && a->device==device && address>=begin && address-begin<a->bytes)
            return a->bytes-(address-begin);
    }
    return 0;
}
static int c32_overlap(const void *a,size_t na,const void *b,size_t nb) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=y ? y-x<na : x-y<nb;
}
/* Called before a write/free. hipFree of a cached allocation waits for its
 * uses, so queued candidate kernels never see a prematurely recycled table. */
static int c32_invalidate(void *p,size_t n,int freeing) {
    if (!c32_requested() || !p || !n) return 0;
    int d=c32_device(); if (d<0) return 3;
    pthread_mutex_lock(&c32_mutex);
    int error=0;
    if (freeing) for (unsigned i=0;i<C32_MAX_ALLOCATIONS;i++)
        if (c32_allocs[i].ptr==p && c32_allocs[i].device==d) {
            n=c32_allocs[i].bytes; break;
        }
    for (unsigned i=0;i<C32_MAX_WEIGHTS;i++) {
        struct c32_weight *w=&c32_weights[i];
        if (w->source && w->device==d && c32_overlap(p,n,w->source,C32_RAW)) {
            if (w->packed && (error=real.p_hipFree(w->packed))) break;
            memset(w,0,sizeof(*w));
        }
    }
    pthread_mutex_unlock(&c32_mutex);
    if (error) c32_log("[c32-prepack] cache release error=%d; propagated to caller",error);
    return error;
}
static void c32_untrack(void *p) {
    if (!c32_requested() || !p) return;
    int d=c32_device();
    pthread_mutex_lock(&c32_mutex);
    for (unsigned i=0;i<C32_MAX_ALLOCATIONS;i++)
        if (c32_allocs[i].ptr==p && c32_allocs[i].device==d) c32_allocs[i].ptr=NULL;
    pthread_mutex_unlock(&c32_mutex);
}
/* Spread first-use comparisons across frames, rather than delaying one frame
 * with all layers' readbacks. The existing rendezvous and waits are untouched. */
static void c32_frame(uint64_t token,uint32_t frame) {
    pthread_mutex_lock(&c32_mutex);
    if (!c32_has_frame || token!=c32_frame_token || frame!=c32_frame_number) {
        c32_has_frame=1;c32_frame_token=token;c32_frame_number=frame;c32_frame_validated=0;
    }
    pthread_mutex_unlock(&c32_mutex);
}
static uint16_t c32_fp8_half(unsigned b) {
    unsigned sign=(b&128u)<<8, exponent=(b>>3)&15, mantissa=b&7;
    if (exponent) return (uint16_t)(sign|((exponent+8)<<10)|(mantissa<<7));
    if (!mantissa) return (uint16_t)sign;
    exponent=9;
    while (!(mantissa&8)) { mantissa<<=1; --exponent; }
    return (uint16_t)(sign|(exponent<<10)|((mantissa&7)<<7));
}
static int c32_pack(unsigned char *out,const unsigned char *raw) {
    memset(out,0,C32_PACKED); memcpy(out,raw,C32_RAW);
    for (unsigned i=0;i<12288;i++) {
        unsigned b=raw[c32_offsets[i]];
        if ((b&127)==127) return 0; /* No assumptions about NaN payloads. */
        uint16_t h=c32_fp8_half(b);
        memcpy(out+32768+i*2,&h,2);
    }
    return 1;
}
static int c32_init(int device,int *error) {
    if (c32_initialized) return c32_function && device==c32_module_device;
    c32_initialized=1;
    const char *path=getenv("DLSSNR_C32_MODULE");
    c32_load_module=dlsym(g_hip,"hipModuleLoad");
    c32_get_function=dlsym(g_hip,"hipModuleGetFunction");
    c32_launch_module=dlsym(g_hip,"hipModuleLaunchKernel");
    c32_destroy_event=dlsym(g_hip,"hipEventDestroy");
    if (!path || !*path || !c32_load_module || !c32_get_function || !c32_launch_module ||
        !c32_destroy_event || !real.p_hipEventRecord || !real.p_hipEventElapsedTime) goto unavailable;
    *error=c32_load_module(&c32_module,path);
    if (*error) goto unavailable;
    *error=c32_get_function(&c32_function,c32_module,C32_NAME);
    if (*error) goto unavailable;
    c32_module_device=device;
    c32_log("[c32-prepack] ready; four weight-load loops replaced; shadow validation and ABBA enabled");
    return 1;
unavailable:
    c32_function=NULL;
    c32_log("[c32-prepack] module unavailable error=%d",*error);
    return 0;
}
static struct c32_weight *c32_weight_get(void *source,int device,void *stream,int *error) {
    struct c32_weight *free_slot=NULL;
    for (unsigned i=0;i<C32_MAX_WEIGHTS;i++) {
        struct c32_weight *w=&c32_weights[i];
        if (w->source==source && w->device==device) return w->rejected?NULL:w;
        if (!w->source && !free_slot) free_slot=w;
    }
    if (!free_slot || c32_available(source,device)<C32_RAW || c32_generation==UINT32_MAX ||
        (c32_has_frame && c32_frame_validated)) return NULL;
    unsigned char *raw=malloc(C32_RAW),*packed=malloc(C32_PACKED);
    void *gpu=NULL; int ok=0;
    if (raw && packed && !(*error=real.p_hipStreamSynchronize(stream)) &&
        !(*error=real.p_hipMemcpy(raw,source,C32_RAW,2)) && c32_pack(packed,raw) &&
        !(*error=real.p_hipMalloc(&gpu,C32_PACKED)) &&
        !(*error=real.p_hipMemcpy(gpu,packed,C32_PACKED,1))) ok=1;
    if (!ok && gpu) { int cleanup=real.p_hipFree(gpu);if (!*error) *error=cleanup;gpu=NULL; }
    free(raw); free(packed);
    *free_slot=(struct c32_weight){source,gpu,device,!ok,++c32_generation};
    if (!ok) c32_log("[c32-prepack] preparation unavailable error=%d",*error);
    return ok?free_slot:NULL;
}
static int c32_same(dim3_t a,dim3_t b) { return a.x==b.x && a.y==b.y && a.z==b.z; }
static int c32_call(const struct c32_params *p,dim3_t nb,dim3_t db,void *st,int candidate) {
    void *a[]={(void *)p};
    if (!candidate) return real.p_hipLaunchKernel(c32_original,nb,db,a,0,st);
    return c32_launch_module(c32_function,nb.x,nb.y,nb.z,db.x,db.y,db.z,0,st,a,NULL);
}
static int c32_timed(const struct c32_params *p,dim3_t nb,dim3_t db,void *st,
                     int candidate,void *start,void *end,float *ms) {
    int e=real.p_hipEventRecord(start,st);
    if (!e) e=c32_call(p,nb,db,st,candidate);
    if (!e) e=real.p_hipEventRecord(end,st);
    if (!e) e=real.p_hipStreamSynchronize(st);
    if (!e) e=real.p_hipEventElapsedTime(ms,start,end);
    return e;
}
/* Return 1 if handled, 0 for ordinary forwarding; error is never hidden after
 * a GPU submission. Validation keeps the original output as the game's frame. */
static int c32_try_launch(const void *f,dim3_t nb,dim3_t db,void **a,u64 shared,void *st,int *result) {
    if (!c32_requested() || !c32_original || f!=c32_original || !a || !a[0]) return 0;
    struct c32_params p; memcpy(&p,a[0],sizeof(p));
    unsigned seen=__atomic_add_fetch(&c32_seen,1,__ATOMIC_RELAXED);
    if (seen<=8) c32_log("[c32-prepack] seen=%u shape=%dx%d shift=%d,%d grid=%u,%u,%u block=%u,%u,%u shared=%llu",
        seen,p.w,p.h,p.x,p.y,nb.x,nb.y,nb.z,db.x,db.y,db.z,(unsigned long long)shared);
    if (shared || !db.y || !db.z || (uint64_t)db.x*db.y*db.z>256 ||
        (db.x!=32 && db.x!=64 && db.x!=128 && db.x!=256)) return 0;
    if (p.h<=0 || p.w<=0 || p.h>8192 || p.w>8192 ||
        (p.x!=0 && p.x!=-4 && p.x!=4) || (p.y!=0 && p.y!=-4 && p.y!=4)) return 0;
    int device=c32_device(); if (device<0) return 0;
    pthread_mutex_lock(&c32_mutex);
    int handled=0,e=0;
    size_t required=(size_t)p.h*p.w*32,available=c32_available(p.output,device);
    if (!required || required>C32_MAX_OUTPUT || available<required || available>C32_MAX_OUTPUT ||
        c32_available(p.input,device)<required || c32_overlap(p.input,required,p.output,available) ||
        c32_overlap(p.output,available,p.weights,C32_RAW)) {
        if (seen<=8) c32_log("[c32-prepack] skip=allocation-or-alias input_bytes=%zu output_bytes=%zu required_bytes=%zu",
            c32_available(p.input,device),available,required);
        goto done;
    }
    if (!c32_init(device,&e)) goto done;
    struct c32_weight *weight=c32_weight_get(p.weights,device,st,&e);
    if (!weight) goto done;
    struct c32_case *item=NULL;
    for (unsigned i=0;i<c32_ncases;i++) {
        struct c32_case *c=&c32_cases[i];
        if (c->generation==weight->generation && c->h==p.h && c->w==p.w && c->x==p.x && c->y==p.y &&
            c32_same(c->grid,nb) && c32_same(c->block,db)) { item=c; break; }
    }
    if (item) {
        if (!item->use) { ++c32_baselines; goto done; }
        p.weights=weight->packed;
        e=c32_call(&p,nb,db,st,1); handled=1; ++c32_replays;
        if (c32_replays==1 || c32_replays%4096==0)
            c32_log("[c32-prepack] replay=%llu verified=%llu fallback=%llu",(unsigned long long)c32_replays,
                   (unsigned long long)c32_verified,(unsigned long long)c32_baselines);
        goto done;
    }
    if (c32_ncases==C32_MAX_CASES || (c32_has_frame && c32_frame_validated)) goto done;
    c32_frame_validated=1;
    size_t scratch_size=available+C32_GUARD*2;
    unsigned char *before=malloc(scratch_size),*after=malloc(scratch_size);
    void *shadow=NULL,*start=NULL,*end=NULL;
    if (!before || !after || (e=real.p_hipMalloc(&shadow,scratch_size)) ||
        (e=real.p_hipEventCreate(&start)) || (e=real.p_hipEventCreate(&end))) goto cleanup;
    /* Only the known original writes the actual output during validation. */
    e=c32_call(&p,nb,db,st,0); handled=1;
    if (!e) e=real.p_hipStreamSynchronize(st);
    if (!e) e=real.p_hipMemcpy(before,p.output,available,2);
    if (e) goto cleanup;
    /* Both implementations start from the SAME poisoned scratch image. Do not
     * seed the candidate with the answer: a broken/no-op kernel must fail. The
     * original shadow pass establishes which padding bytes are left untouched. */
    memset(after,0xa5,scratch_size);
    for (size_t i=0;i<available;i++) after[C32_GUARD+i]=(unsigned char)~before[i];
    e=real.p_hipMemcpy(shadow,after,scratch_size,1);
    struct c32_params q=p;q.output=(char *)shadow+C32_GUARD;
    if (!e) e=c32_call(&q,nb,db,st,0);
    if (!e) e=real.p_hipStreamSynchronize(st);
    if (!e) e=real.p_hipMemcpy(before,shadow,scratch_size,2);
    if (!e) e=real.p_hipMemcpy(shadow,after,scratch_size,1);
    q.weights=weight->packed;
    if (!e) e=c32_call(&q,nb,db,st,1);
    if (!e) e=real.p_hipStreamSynchronize(st);
    if (!e) e=real.p_hipMemcpy(after,shadow,scratch_size,2);
    if (e) goto cleanup;
    int identical=!memcmp(before,after,scratch_size);
    for (unsigned i=0;i<C32_GUARD;i++) if (after[i]!=0xa5 || after[C32_GUARD+available+i]!=0xa5) identical=0;
    float old_ms=0,new_ms=0;
    if (identical) {
        /* A B B A, same captured input and scratch output, first dispatch excluded. */
        for (unsigned i=0;i<4 && !e;i++) {
            int candidate=i==1 || i==2;float ms=0;
            q.weights=candidate?weight->packed:p.weights;
            e=c32_timed(&q,nb,db,st,candidate,start,end,&ms);
            if (candidate) new_ms+=ms*.5f; else old_ms+=ms*.5f;
        }
        if (e) goto cleanup;
        ++c32_verified;
    } else ++c32_rejected;
    int use=identical && old_ms>0 && new_ms>0 && new_ms<old_ms*.98f;
    c32_cases[c32_ncases++]=(struct c32_case){weight->generation,p.h,p.w,p.x,p.y,nb,db,use};
    c32_log("[c32-prepack] case=%u shape=%dx%d shift=%d,%d identical=%d original_ms=%.6f candidate_ms=%.6f selected=%s",
           c32_ncases,p.w,p.h,p.x,p.y,identical,old_ms,new_ms,use?"prepacked":"original");
cleanup:
    { int rc;
      if (end) { rc=c32_destroy_event(end);if (!e) e=rc; }
      if (start) { rc=c32_destroy_event(start);if (!e) e=rc; }
      if (shadow) { rc=real.p_hipFree(shadow);if (!e) e=rc; }
    }
    free(before);free(after);
done:
    if (e) { handled=1;c32_log("[c32-prepack] GPU error=%d; propagated to caller",e); }
    pthread_mutex_unlock(&c32_mutex);
    if (handled) *result=e;
    return handled;
}
