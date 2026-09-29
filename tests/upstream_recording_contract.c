/* Replay the actual pinned 0.3.1 command-recording function on CPU COM mocks.
 * The Python driver verifies the complete official payload before extracting
 * RVA 0x17980..0x180a6. No PE entry point, loader, HIP kernel or GPU is run.
 * Feed actual Dispatch/DrawInstanced calls into the patched vkd3d state machine.
 * This tests recording compatibility, not runtime rendering/driver behavior.
 */
#define main prior_contract_main
#include "vkd3d_ordered_contract.c"
#undef main
#include <sys/mman.h>
#include <unistd.h>

#define MS __attribute__((ms_abi))
#define IMAGE_SIZE 0xc0000
/* Both reviewed routines share the same COM contract with PollSpacing=0. */
#ifdef DLSSNR_RECORD_050
#define ENTRY 0x19b90
#define CONST_A 0x834f0
#define CONST_B 0x83508
#define EXEC_PAGE 0x19000
static unsigned global_rva(unsigned old) {
    switch (old) {
    case 0x09aa90: return 0xb6750;
    case 0x09ab28: return 0xb67f8;
    case 0x09aa88: return 0xb6748;
    case 0x09aa89: return 0xb6749;
    case 0x09aa68: return 0xb6728;
    case 0x09aac0: return 0xb6780;
    case 0x09a948: return 0xb65f0;
    case 0x09a950: return 0xb65f8;
    case 0x09a930: return 0xb65d8;
    case 0x09a940: return 0xb65e8;
    case 0x09aae0: return 0xb67a0;
    case 0x09aa8c: return 0xb674c;
    case 0x09ab14: return 0xb67d4;
    case 0x09ab20: return 0xb67f0;
    case 0x09ab18: return 0xb67e8;
    case 0x06cd40: return 0x834f0;
    case 0x06cd58: return 0x83508;
    default: abort();
    }
}
#elif defined(DLSSNR_RECORD_043)
#define ENTRY 0x19cf0
#define CONST_A 0x7f510
#define CONST_B 0x7f528
#define EXEC_PAGE 0x19000
static unsigned global_rva(unsigned old) {
    switch (old) {
    case 0x09aa90: return 0xb1718;
    case 0x09ab28: return 0xb17c0;
    case 0x09aa88: return 0xb1710;
    case 0x09aa89: return 0xb1711;
    case 0x09aa68: return 0xb16f0;
    case 0x09aac0: return 0xb1748;
    case 0x09a948: return 0xb15b8;
    case 0x09a950: return 0xb15c0;
    case 0x09a930: return 0xb15a0;
    case 0x09a940: return 0xb15b0;
    case 0x09aae0: return 0xb1768;
    case 0x09aa8c: return 0xb1714;
    case 0x09ab14: return 0xb179c;
    case 0x09ab20: return 0xb17b8;
    case 0x09ab18: return 0xb17b0;
    case 0x06cd40: return 0x7f510;
    case 0x06cd58: return 0x7f528;
    default: abort();
    }
}
#elif defined(DLSSNR_RECORD_042)
#define ENTRY 0x19540
#define CONST_A 0x7e310
#define CONST_B 0x7e328
#define EXEC_PAGE 0x19000
static unsigned global_rva(unsigned old) {
    switch (old) {
    case 0x09aa90: return 0xaf5a0;
    case 0x09ab28: return 0xaf648;
    case 0x09aa88: return 0xaf598;
    case 0x09aa89: return 0xaf599;
    case 0x09aa68: return 0xaf578;
    case 0x09aac0: return 0xaf5d0;
    case 0x09a948: return 0xaf440;
    case 0x09a950: return 0xaf448;
    case 0x09a930: return 0xaf428;
    case 0x09a940: return 0xaf438;
    case 0x09aae0: return 0xaf5f0;
    case 0x09aa8c: return 0xaf59c;
    case 0x09ab14: return 0xaf624;
    case 0x09ab20: return 0xaf640;
    case 0x09ab18: return 0xaf638;
    case 0x06cd40: return 0x7e310;
    case 0x06cd58: return 0x7e328;
    default: abort();
    }
}
#elif defined(DLSSNR_RECORD_041)
#define ENTRY 0x19120
#define CONST_A 0x791d0
#define CONST_B 0x791e8
#define EXEC_PAGE 0x19000
static unsigned global_rva(unsigned old) {
    switch (old) {
    case 0x09aa90: return 0xaa3d0;
    case 0x09ab28: return 0xaa470;
    case 0x09aa88: return 0xaa3c8;
    case 0x09aa89: return 0xaa3c9;
    case 0x09aa68: return 0xaa3a8;
    case 0x09aac0: return 0xaa400;
    case 0x09a948: return 0xaa270;
    case 0x09a950: return 0xaa278;
    case 0x09a930: return 0xaa258;
    case 0x09a940: return 0xaa268;
    case 0x09aae0: return 0xaa420;
    case 0x09aa8c: return 0xaa3cc;
    case 0x09ab14: return 0xaa454;
    case 0x09ab20: return 0xaa468;
    case 0x09ab18: return 0xaa460;
    case 0x06cd40: return 0x791d0;
    case 0x06cd58: return 0x791e8;
    default: abort();
    }
}
#elif defined(DLSSNR_RECORD_040)
#define ENTRY 0x19130
#define CONST_A 0x781e0
#define CONST_B 0x781f8
#define EXEC_PAGE 0x19000
static unsigned global_rva(unsigned old) {
    switch (old) {
    case 0x09aa90: return 0x0a8398;
    case 0x09ab28: return 0x0a8438;
    case 0x09aa88: return 0x0a8390;
    case 0x09aa89: return 0x0a8391;
    case 0x09aa68: return 0x0a8370;
    case 0x09aac0: return 0x0a83c8;
    case 0x09a948: return 0x0a8238;
    case 0x09a950: return 0x0a8240;
    case 0x09a930: return 0x0a8220;
    case 0x09a940: return 0x0a8230;
    case 0x09aae0: return 0x0a83e8;
    case 0x09aa8c: return 0x0a8394;
    case 0x09ab14: return 0x0a841c;
    case 0x09ab20: return 0x0a8430;
    case 0x09ab18: return 0x0a8428;
    case 0x06cd40: return 0x0781e0;
    case 0x06cd58: return 0x0781f8;
    default: abort();
    }
}
#else
#define ENTRY 0x17980
#define CONST_A 0x6cd40
#define CONST_B 0x6cd58
#define EXEC_PAGE 0x17000
static unsigned global_rva(unsigned old) { return old; }
#endif
#define CODE_SIZE 0x726

static unsigned char *image;
static struct fixture active;
static struct pipeline_state draw_state;
static unsigned counts[3], predications;
struct object { void **vtable; uint64_t va; };
static void *command_vtable[64], *resource_vtable[12];
static struct object command, flags, abort_word, predicate;

static uint64_t MS gpu_va(struct object *self) { return self->va; }
static void MS ignore(struct object *self) { assert(self == &command); }
static void MS pipeline(struct object *self, struct pipeline_state *state) {
    assert(self == &command && (state == &active.state || state == &draw_state));
    active.list.state=state;
}
static void MS root_uav(struct object *self, unsigned index, uint64_t va) {
    assert(self == &command);
    if (index == 0) active.list.cmd.nr_flag_va = va;
    else { assert(index == 2); active.list.cmd.nr_abort_va = va; }
}
static void MS graphics_uav(struct object *self, unsigned index, uint64_t va) {
    assert(self == &command);
    if (index == 0) active.list.cmd.nr_graphics_flag_va=va;
    else { assert(index == 2); active.list.cmd.nr_graphics_abort_va=va; }
}
static void MS constants(struct object *self, unsigned index, unsigned count,
                         const uint32_t *values, unsigned offset) {
    assert(self == &command && index == 1 && count == 4 && offset == 0);
    memcpy(active.list.compute_bindings.root_constants, values, 16);
}
static void MS graphics_constants(struct object *self, unsigned index, unsigned count,
                                  const uint32_t *values, unsigned offset) {
    assert(self == &command && index == 1 && count == 4 && offset == 0);
    memcpy(active.list.graphics_bindings.root_constants,values,16);
}
static void MS draw(struct object *self, unsigned vertices, unsigned instances,
                    unsigned first_vertex, unsigned first_instance) {
    assert(self == &command && vertices == 3 && instances == 1);
    assert(!first_vertex && !first_instance && counts[0] == 1 && !counts[2]);
    uint32_t *c=active.list.graphics_bindings.root_constants;
    assert(c[0] == 1 && c[1] == 1 && c[2] > 0 && c[3] == 0);
    assert(nr_ordered_draw_boundary(&active.list,vertices,instances,first_vertex,first_instance));
    assert(!active.device.removed && active.list.cmd.nr_wait_graphics);
    counts[1]++;
}
static void MS viewport(struct object *self, unsigned count, const float *v) {
    assert(self == &command && count == 1);
    assert(v[0]==0 && v[1]==0 && v[2]==1 && v[3]==1 && v[4]==0 && v[5]==1);
}
static void MS scissor(struct object *self, unsigned count, const int *r) {
    assert(self == &command && count == 1);
    assert(r[0]==0 && r[1]==0 && r[2]==1 && r[3]==1);
}
static void MS dispatch(struct object *self, unsigned x, unsigned y, unsigned z) {
    assert(self == &command && x == 1 && y == 1 && z == 1);
    uint32_t *c = active.list.compute_bindings.root_constants;
    assert(c[0] <= 2 && c[1] == 1 && c[3] == 0);
    bool replaced = nr_ordered_dispatch_boundary(&active.list, x, y, z);
    assert(!active.device.removed && replaced == (c[0] == 1));
    assert(c[0] == 1 ? c[2] > 0 : c[2] == 0);
    if (c[0] == 0) assert(!counts[0] && !counts[1] && !counts[2]);
    if (c[0] == 1) assert(counts[0] == 1 && !counts[2]);
    if (c[0] == 2) assert(counts[0] == 1 && counts[1] > 0 && !counts[2]);
    counts[c[0]]++;
}
static void MS predication(struct object *self, struct object *buffer,
                           uint64_t offset, unsigned operation) {
    assert(self == &command && offset == 0 && operation <= 1);
    assert(!buffer || buffer == &predicate);
    predications++;
}

static void u32(unsigned rva, uint32_t value) { memcpy(image+global_rva(rva), &value, 4); }
static void ptr(unsigned rva, void *value) { memcpy(image+global_rva(rva), &value, 8); }
static void scenario(unsigned use_predication, unsigned target_slices,
                     unsigned spin_budget, unsigned expected_slices,
                     unsigned graphics, unsigned have_pipeline) {
    init(&active);
    draw_state=active.state; draw_state.graphics_mode=true;
    memset(counts, 0, sizeof(counts)); predications = 0;
    memset(image+0x9a000, 0, IMAGE_SIZE-0x9a000);
    image[global_rva(0x9aa88)] = use_predication;
    u32(0x9aa90, 8192);
    u32(0x9ab28, target_slices);
    u32(0x9aa8c, 1); /* PredWait=1 */
    u32(0x9ab14, graphics);
    ptr(0x9ab18, &active.rs);
    ptr(0x9ab20, have_pipeline ? &draw_state : NULL);
    ptr(0x9a948, &active.rs); ptr(0x9a950, &active.state);
    ptr(0x9a930, &flags); ptr(0x9aae0, &abort_word);
    u32(0x9a940, 0x100);
    ptr(0x9aa68, &predicate); ptr(0x9aac0, &predicate);
    typedef void (MS *record_fn)(struct object *, uint32_t, uint32_t);
    ((record_fn)(image+ENTRY))(&command, 1, spin_budget);
    assert(counts[0] == 1 && counts[1] == expected_slices && counts[2] == 1);
    assert(predications == (use_predication ? 2u : 0u));
    assert(snapshots == 1 && barriers == 2 && active.list.cmd.iteration_count == 2);
    assert(!active.list.cmd.nr_wait_token && !active.list.cmd.nr_armed_token);
    assert(active.list.cmd.iterations[0].nr_after.nr_producer.token == 14);
    assert(active.list.cmd.iterations[1].nr_after.nr_consumer.token == 14);
    destroy(&active);
}

int main(int argc, char **argv) {
    assert(argc == 2 && sizeof(void *) == 8 && sysconf(_SC_PAGESIZE) == 4096);
    FILE *file = fopen(argv[1], "rb"); assert(file);
    image = mmap(NULL, IMAGE_SIZE, PROT_READ|PROT_WRITE,
                 MAP_ANONYMOUS|MAP_PRIVATE, -1, 0);
    assert(image != MAP_FAILED);
    assert(fread(image+ENTRY, 1, CODE_SIZE, file) == CODE_SIZE);
    assert(fread(image+CONST_A, 1, 16, file) == 16);
    assert(fread(image+CONST_B, 1, 16, file) == 16);
    assert(fgetc(file) == EOF); fclose(file);
    /* Only the reviewed recording routine pages are executable. */
    assert(!mprotect(image+EXEC_PAGE, 0x2000, PROT_READ|PROT_EXEC));
    resource_vtable[0x58/8] = gpu_va;
    flags = (struct object){resource_vtable, 0x100000};
    abort_word = (struct object){resource_vtable, 0x900000};
    predicate = (struct object){resource_vtable, 0xa00000};
    command = (struct object){command_vtable, 0};
    command_vtable[0x70/8] = dispatch;
    command_vtable[0x60/8] = draw;
    command_vtable[0x78/8] = ignore; /* CopyBufferRegion */
    command_vtable[0xc8/8] = pipeline;
    command_vtable[0xd0/8] = ignore; /* ResourceBarrier */
    command_vtable[0xe8/8] = ignore; /* SetComputeRootSignature */
    command_vtable[0xf0/8] = ignore; /* SetGraphicsRootSignature */
    command_vtable[0xa0/8] = ignore; /* IASetPrimitiveTopology */
    command_vtable[0xa8/8] = viewport;
    command_vtable[0xb0/8] = scissor;
    command_vtable[0x170/8] = ignore; /* OMSetRenderTargets */
    command_vtable[0x118/8] = constants;
    command_vtable[0x148/8] = root_uav;
    command_vtable[0x120/8] = graphics_constants;
    command_vtable[0x150/8] = graphics_uav;
    command_vtable[0x1b8/8] = predication;
    setenv("VKD3D_NR_FLAG_HASH", "135ea1f88cbc832d", 1);
    api.lookup_va=lookup; api.snapshot=snapshot; api.claim_queue=claim;
    api.publish_input=publish; api.wait_output=wait_output; api.fail=fail;
    scenario(0, 64, 20000000, 1, 0, 0);
    scenario(1, 1, 20000000, 1, 0, 0);
    scenario(1, 64, 20000000, 64, 0, 0);
    scenario(1, 4000, 32768000, 4000, 0, 0);
    scenario(0, 64, 20000000, 1, 1, 1); /* no predicate: upstream compute fallback */
    scenario(1, 64, 20000000, 64, 1, 0); /* no graphics PSO: compute fallback */
    scenario(1, 1, 20000000, 1, 1, 1);
    scenario(1, 64, 20000000, 64, 1, 1);
    scenario(1, 4000, 32768000, 4000, 1, 1);
    assert(!munmap(image, IMAGE_SIZE));
    puts("Pinned upstream compute and graphics recorder accepted by Linux bridge: 1/64/4000 waits, producer/finalizer retained, compute fallbacks checked (CPU mocks only)");
    return 0;
}
