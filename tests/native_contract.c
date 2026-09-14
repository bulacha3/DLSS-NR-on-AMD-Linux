/* CPU-only contract checks for forwarding and ordered completion. */
#include "../native/hip_bridge.c"
#include <assert.h>

static int references, sequence, sync_result, probe_mode, probe_launches;
static u64 allocation_size;
static void *test_stream = (void *)0x1234;
static int retain(uint64_t owner) { assert(owner == 77); ++references; return 0; }
static void release(uint64_t owner) { assert(owner == 77); --references; }
static int create_event(void **out, unsigned flags) {
    assert(flags == 2); *out = (void *)0x4567; return 19;
}
static int query_event(void *event) { assert(event == (void *)0x4567); return 600; }
static int create_stream(void **out, unsigned flags) {
    assert(flags == 1); *out = test_stream; return 23;
}
static int allocate(void **out, u64 bytes) { allocation_size = bytes; *out = 0; return 2; }
static int launch(const void *f, dim3_t grid, dim3_t block, void **args, u64 shared, void *stream) {
    if (probe_mode) {
        assert((f == g_flag_wait || f == g_flag_set) && stream == NULL);
        assert(grid.x == 1 && grid.y == 1 && grid.z == 1);
        assert(block.x == 32 && block.y == 1 && block.z == 1 && shared == 0);
        ++probe_launches;
        sequence = 1;
        return 0;
    }
    assert(f == g_flag_set && stream == test_stream);
    assert(args[2] && shared == 0 && grid.x == 1 && block.x == 1);
    sequence = 1;
    return 0;
}
static int synchronize(void *stream) {
    assert(stream == (probe_mode ? NULL : test_stream) && sequence == 1);
    sequence = 2;
    return sync_result;
}

static void startup_probes(uint64_t token, void *flags) {
    uint32_t frame = 0, limit = 1;
    void *abort_buffer = NULL;
    void *args[] = {&flags, &frame, &limit};
    dim3_t grid = {1,1,1}, block = {32,1,1};
    probe_mode = 1;
    int before = references;
    assert(stub_launch(g_flag_wait, grid, block, args, 0, NULL) == 0);
    assert(sequence == 2 && probe_launches == 1 && references == before);
    args[2] = &abort_buffer;
    assert(stub_launch(g_flag_set, grid, block, args, 0, NULL) == 0);
    assert(sequence == 2 && probe_launches == 2 && references == before);
    frame = UINT32_C(0x40000000); limit = 1500000; args[2] = &limit;
    assert(stub_launch(g_flag_wait, grid, block, args, 0, NULL) == 0);
    assert(sequence == 2 && probe_launches == 3 && references == before);
    assert(!nr_job.active && !nr_job.error && !nr_probe.phase);
    assert(!nr_frame(nr_find_token(token), 0, 0));
    assert(!nr_frame(nr_find_token(token), frame, 0));
    /* Genuine jobs and unmatched argument shapes still use rendezvous. */
    int result;
    frame = 1;
    assert(!nr_try_startup_probe(g_flag_wait, grid, block, args, 0, NULL, &result));
    frame = 0; limit = 2;
    assert(!nr_try_startup_probe(g_flag_wait, grid, block, args, 0, NULL, &result));
    /* Unrelated kernels can have fewer arguments; never read args[2]. */
    void *one_arg[] = {&flags};
    assert(!nr_try_startup_probe((void *)0x9999, grid, block, one_arg, 0, NULL, &result));
    probe_mode = 0;
}

static void job(uint32_t frame, uint64_t token, void *flags, struct nr_buffer *snapshot) {
    void *abort_buffer = (void *)0x5678;
    void *arguments[] = {&flags, &frame, &abort_buffer};
    assert(nr_publish_input(token, frame, snapshot, 1) == 0);
    assert(stub_launch(g_flag_wait, (dim3_t){1,1,1}, (dim3_t){1,1,1}, arguments, 0, test_stream) == 0);
    int result = stub_launch(g_flag_set, (dim3_t){1,1,1}, (dim3_t){1,1,1}, arguments, 0, test_stream);
    assert(result == sync_result && sequence == 2);
    if (sync_result == 0) {
        assert(!nr_job.active);
        assert(nr_wait_output(token, frame, 1) == 0);
        assert(nr_consumer_submitted(token, frame) == 0);
    } else {
        assert(nr_job.active); /* Failed GPU sync cannot release memory pins. */
        assert(nr_wait_output(token, frame, 1) != 0);
    }
}

int main(void) {
    _Static_assert(sizeof(u64) == 8, "Win64 and Unix sizes must agree");
    g_hip_ok = 1;
    real.p_hipEventCreateWithFlags = create_event;
    real.p_hipEventQuery = query_event;
    real.p_hipStreamCreateWithFlags = create_stream;
    real.p_hipStreamSynchronize = synchronize;
    real.p_hipMalloc = allocate;
    real.p_hipLaunchKernel = launch;
    void *out = NULL;
    assert(g_bridge.p_hipEventCreateWithFlags(&out, 2) == 19);
    assert(g_bridge.p_hipEventQuery(out) == 600);
    assert(g_bridge.p_hipStreamCreateWithFlags(&out, 1) == 23 && out == test_stream);
    assert(g_bridge.p_hipMalloc(&out, UINT64_C(0x100000007)) == 2);
    assert(allocation_size == UINT64_C(0x100000007));
    g_flag_wait = (void *)1; g_flag_set = (void *)2;
    uint32_t flags[16] = {0};
    uint64_t token;
    assert(nr_register_resource(1, 2, 3, 4, sizeof(flags), 77, retain, release, &token) == 0);
    nr_associate_import(2, (void *)5);
    nr_associate_mapping((void *)5, flags, 0, sizeof(flags));
    struct nr_buffer snapshot[2]; uint32_t count;
    assert(nr_snapshot(1, snapshot, 2, &count) == 0 && count == 1);
    assert(nr_claim_queue(snapshot, 1, 9) == 0);
    /* The real payload places flags at an offset in its shared allocation. */
    startup_probes(token, flags + 4);
    job(1, token, flags, snapshot);
    assert(references == 1);
    sync_result = 719;
    /* A failed startup sync also retains its flag allocation. */
    uint32_t probe_flags[16] = {0}, frame = 0, limit = 1;
    uint64_t probe_token;
    assert(nr_register_resource(1, 12, 13, 14, sizeof(probe_flags), 77, retain, release, &probe_token) == 0);
    nr_associate_import(12, (void *)15);
    nr_associate_mapping((void *)15, probe_flags, 0, sizeof(probe_flags));
    void *probe_ptr = probe_flags;
    void *probe_args[] = {&probe_ptr, &frame, &limit};
    probe_mode = 1;
    int before = references;
    assert(stub_launch(g_flag_wait, (dim3_t){1,1,1}, (dim3_t){32,1,1}, probe_args, 0, NULL) == 719);
    assert(references == before + 1 && nr_find_token(probe_token)->probe_busy);
    assert(!nr_job.active && !nr_job.error);
    probe_mode = 0;
    job(2, token, flags, snapshot);
    assert(references == before + 2);
    puts("HIP forwarding, bounded startup probes, real frame ordering and failed-sync pin retention: passed");
    return 0;
}
