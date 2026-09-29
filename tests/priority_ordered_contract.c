/* Production bridge exercised with two deferred CPU queues, not GPU arithmetic. */
#include "../native/hip_bridge.c"
#include <assert.h>

static int refs, pending_work, marker_pending, marker_done;
static int fail_kind, marker_syncs, work_syncs, launches, failed_once;
static void *marker_stream, *work_stream;
static uint64_t token;
static char trace[256];
static unsigned trace_n;
static void record(char ch) { assert(trace_n+1<sizeof(trace)); trace[trace_n++]=ch; }
static int retain(uint64_t owner) { assert(owner==77); ++refs; return 0; }
static void release(uint64_t owner) { assert(owner==77); --refs; }
static int native_sync(void *stream) {
    if (stream==marker_stream) {
        record('m'); ++marker_syncs;
        if (!failed_once && (fail_kind==1 || (fail_kind==4 && marker_pending) ||
                (fail_kind==5 && nr_job.error))) { failed_once=1; return 719; }
    } else if (stream==work_stream) {
        record('w'); ++work_syncs;
        if (!failed_once && fail_kind==2) { failed_once=1; return 719; }
    } else { record('u'); return 0; }
    if (stream==work_stream) pending_work=0;
    if (stream==marker_stream && marker_pending) {
        assert(!pending_work); marker_pending=0; marker_done=1;
    }
    /* Completion must not already have been published before sync returns. */
    assert(nr_wait_output(token,1,0)!=0);
    return 0;
}
static int device_sync(void) {
    record('d'); pending_work=0;
    if (marker_pending) {marker_pending=0;marker_done=1;}
    return 0;
}
static int native_launch(const void *f,dim3_t grid,dim3_t block,void **args,u64 shared,void *stream) {
    (void)grid;(void)block;(void)args;(void)shared;
    ++launches;
    if(f==g_flag_set) {
        assert(stream==marker_stream);
        if(work_stream!=marker_stream) assert(!pending_work);
        record('F');
        if(!failed_once && fail_kind==3){failed_once=1;return 700;}
        marker_pending=1;
    } else {
        assert(stream==work_stream);
        record(f==g_k_import?'I':f==g_k_export?'X':'K');
        ++pending_work;
    }
    return 0;
}
static int send(const void *fn,void **args,void *stream) {
    return stub_launch(fn,(dim3_t){1,1,1},(dim3_t){32,1,1},args,0,stream);
}
int main(int argc,char **argv) {
    assert(argc==2);int scenario=atoi(argv[1]);
    marker_stream=scenario==1 || scenario==11 ? (void *)0x1000:NULL;
    work_stream=scenario==0 || scenario==1 ? marker_stream:(void *)0x2000;
    g_hip_ok=1;real.p_hipLaunchKernel=native_launch;
    real.p_hipStreamSynchronize=native_sync;real.p_hipDeviceSynchronize=device_sync;
    g_flag_wait=(void *)1;g_flag_set=(void *)2;g_k_import=(void *)3;g_k_export=(void *)4;
    uint32_t flags[16]={0},frame=1,limit=20000000;
    void *flag_ptr=flags,*abort_ptr=(void *)0x3000;
    void *wait_args[]={&flag_ptr,&frame,&limit};
    void *set_args[]={&flag_ptr,&frame,&abort_ptr};
    void *ordinary_args[]={&flag_ptr};
    struct nr_buffer snapshot[2];uint32_t count;
    assert(!nr_register_resource(1,2,3,4,sizeof(flags),77,retain,release,&token));
    nr_associate_import(2,(void *)5);nr_associate_mapping((void *)5,flags,0,sizeof(flags));
    assert(!nr_snapshot(1,snapshot,2,&count) && count==1);
    assert(!nr_claim_queue(snapshot,1,9));
    assert(!nr_publish_input(token,frame,snapshot,count) && refs==2);
    assert(!send(g_flag_wait,wait_args,marker_stream));
    assert(nr_job.active && nr_wait_output(token,1,0)==600);
    if(scenario==10) {
        assert(send((void *)0x9999,ordinary_args,work_stream)==1 && !launches);
        goto recover;
    }
    if(scenario==11) {
        assert(send(g_k_import,ordinary_args,work_stream)==1 && !launches);
        goto recover;
    }
    if(scenario==5)fail_kind=1;
    int rc=send(g_k_import,ordinary_args,work_stream);
    if(scenario==5){assert(rc==719 && !launches);goto recover;}
    if(rc){fprintf(stderr,"initial import refused: %d (scenario %d)\n",rc,scenario);return 42;}
    assert(!send((void *)0x9999,ordinary_args,work_stream));
    assert(nr_wait_output(token,1,0)==600 && refs==2);
    if(scenario==3 || scenario==12 || scenario==13) {
        assert(send((void *)0x9999,ordinary_args,(void *)0x4000)==1 && launches==2);
        if(scenario==12 || scenario==13) {
            if(scenario==13)fail_kind=5;
            rc=stub_streamsync(work_stream);
            if(scenario==12){assert(rc==1 && !nr_job.active && refs==1);goto finish;}
            assert(rc==719 && nr_job.active && refs==2);goto recover;
        }
        goto recover;
    }
    if(scenario==4) {
        assert(send(g_flag_set,set_args,work_stream)==1 && launches==2);goto recover;
    }
    if(scenario==9) {
        assert(!stub_streamsync((void *)0x4000) && nr_job.active && refs==2);
        assert(!stub_streamsync(work_stream) && nr_job.active && refs==2);
        assert(nr_wait_output(token,1,0)==600 && !marker_done);
        assert(!stub_sync() && nr_job.active && refs==2);
    }
    assert(!send(g_k_export,ordinary_args,work_stream));
    if(scenario==6)fail_kind=2;
    if(scenario==7)fail_kind=3;
    if(scenario==8)fail_kind=4;
    if(scenario==14)frame=2;
    if(scenario==15)flag_ptr=flags+1;
    rc=send(g_flag_set,set_args,marker_stream);
    if(scenario==6 || scenario==7 || scenario==8 || scenario==14 || scenario==15) {
        assert(rc!=0 && nr_job.active && refs==2);goto recover;
    }
    assert(!rc && !nr_job.active && !pending_work && marker_done && refs==1);
    assert(!nr_wait_output(token,1,0));assert(!nr_consumer_submitted(token,1));
    if(scenario==2)assert(!strcmp(trace,"mIKXwFm"));
    goto finish;
recover:
    assert(nr_job.active && nr_job.error && refs==2);
    assert(nr_wait_output(token,1,0)!=0 && nr_consumer_submitted(token,1)!=0);
    assert(stub_sync()!=0 && !nr_job.active && refs==1);
    assert(nr_wait_output(token,1,0)!=0 && nr_consumer_submitted(token,1)!=0);
finish:
    snapshot[0].release(snapshot[0].owner);assert(refs==0);
    printf("scenario %d passed: %s\n",scenario,trace);return 0;
}
