/* CPU regression harness for the actual patched nr_ordered_commands.h.
 * Vulkan/bridge entry points are mocks: this verifies recording and handoff
 * control flow, NOT GPU execution or memory visibility.
 *
 * v0.3.0 payload SHA-256: 8321cae728d28cb7632d0d58d3d913e91132bf7645c126505698fbe4cd5a0138
 * Independent protocol evidence: Win64 RVAs 0x16b0c..0x16b62 record mode 0;
 * 0x16c36..0x16cf0 record repeated mode 1 Dispatch(1,1,1), capped at 4000;
 * 0x16e71..0x16ec1 always record mode 2, including the single-wait path.
 * The pinned DXBC mode-2 branch checks the HIP completion word and writes
 * success/failure counters. It must execute after the real ordered handoff.
 *
 * Build with -I /path/to/patched-vkd3d/libs/vkd3d (see sources/README.md).
 */
#include <assert.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../native/nr_ordered.h"

typedef uint32_t UINT;
typedef int32_t HRESULT;
typedef int32_t VkResult;
typedef uintptr_t VkBuffer;
typedef uintptr_t VkSemaphore;
typedef struct { int sType; uint64_t srcStageMask, srcAccessMask, dstStageMask, dstAccessMask;
    uint32_t srcQueueFamilyIndex, dstQueueFamilyIndex; VkBuffer buffer; uint64_t offset, size;
} VkBufferMemoryBarrier2;
typedef struct { int sType; uint32_t bufferMemoryBarrierCount; const VkBufferMemoryBarrier2 *pBufferMemoryBarriers;
} VkDependencyInfo;
typedef struct { int sType; uint32_t semaphoreCount; const VkSemaphore *pSemaphores; const uint64_t *pValues;
} VkSemaphoreWaitInfo;
#define VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER_2 1
#define VK_STRUCTURE_TYPE_DEPENDENCY_INFO 2
#define VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO 3
#define VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT 1
#define VK_PIPELINE_STAGE_2_NONE 0
#define VK_ACCESS_2_MEMORY_READ_BIT 1
#define VK_ACCESS_2_MEMORY_WRITE_BIT 2
#define VK_QUEUE_FAMILY_EXTERNAL UINT32_MAX
#define VK_SUCCESS 0
#define VK_ERROR_DEVICE_LOST (-4)
#define S_OK 0
#define DXGI_ERROR_INVALID_CALL ((HRESULT)0x887a0001)
#define VKD3D_MAX_COMMAND_LIST_SEQUENCES 4
#define D3D12_ROOT_PARAMETER_TYPE_UAV 1
#define D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS 2
#define VK_CALL(x) (x)
#define vkd3d_calloc calloc
#define vkd3d_free free
#define INFO(...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define ERR(...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)

struct vkd3d_vk_device_procs { int unused; };
struct d3d12_device { struct vkd3d_vk_device_procs vk_procs; uintptr_t vk_device; HRESULT removed; };
struct vkd3d_shader_root_constant { uint32_t constant_count, constant_index; };
struct root_parameter { uint32_t parameter_type; struct vkd3d_shader_root_constant constant; };
struct d3d12_root_signature { uint32_t parameter_count; struct root_parameter parameters[3]; };
struct pipeline_state { struct { struct { struct { uint64_t hash; } meta; } code; } compute; };
struct nr_ordered_endpoint { uint64_t token; uint32_t frame; };
struct nr_ordered_snapshot { struct nr_ordered_snapshot *next; uint32_t count; struct nr_buffer buffers[NR_ORDERED_MAX_RESOURCES]; };
struct nr_ordered_boundary { struct nr_ordered_endpoint nr_consumer, nr_producer; struct nr_ordered_snapshot *snapshot; };
struct allocator { struct { uint32_t vk_family_index; } primary_pool; struct nr_ordered_snapshot *nr_snapshots; };
struct d3d12_command_list {
    struct d3d12_device *device;
    struct pipeline_state *state;
    struct allocator *allocator;
    struct { struct d3d12_root_signature *root_signature; uint32_t root_constants[4]; } compute_bindings;
    struct {
        uint64_t nr_flag_va, nr_abort_va, nr_armed_token, nr_armed_flag_va, nr_armed_abort_va, nr_wait_token;
        uint32_t nr_armed_frame, nr_wait_spin_cap;
        uintptr_t vk_command_buffer;
        unsigned iteration_count;
        struct { struct nr_ordered_boundary nr_after; } iterations[VKD3D_MAX_COMMAND_LIST_SEQUENCES];
    } cmd;
};
struct queue { VkSemaphore submission_timeline; };
struct d3d12_command_queue { struct d3d12_device *device; struct queue *vkd3d_queue; uint64_t nr_queue_id; };
struct d3d12_command_queue_submission_execute { uint32_t cmd_count; struct nr_ordered_boundary *nr_boundaries; };

static uint32_t barriers, snapshots, claims, handoff_stage, publications;
static VkResult prefix_result;
static int output_result;
static struct nr_ordered_api api;
static struct nr_ordered_api *nr_ordered_get_api(void) { return &api; }
static bool d3d12_pipeline_state_is_compute(struct pipeline_state *p) { return p != NULL; }
static bool d3d12_command_list_allows_new_sequence(struct d3d12_command_list *p) { (void)p; return true; }
static void d3d12_command_list_end_transfer_batch(struct d3d12_command_list *p, bool b) { (void)p; (void)b; }
static void d3d12_command_list_end_current_render_pass(struct d3d12_command_list *p, bool b) { (void)p; (void)b; }
static void d3d12_command_list_begin_new_sequence(struct d3d12_command_list *p, bool b) { (void)b; ++p->cmd.iteration_count; ++p->cmd.vk_command_buffer; }
static void d3d12_device_mark_as_removed(struct d3d12_device *p, HRESULT r, const char *fmt, ...) { (void)fmt; p->removed = r; }
static HRESULT d3d12_device_removed_reason(struct d3d12_device *p) { return p->removed; }
static bool nr_ordered_trace_allowed(void) { return false; }
static void nr_ordered_trace_list(const char *s, struct d3d12_command_list *p) { (void)s; (void)p; }
static void nr_ordered_trace_execute(const char *s, struct d3d12_command_queue *q, const struct d3d12_command_queue_submission_execute *e) { (void)s; (void)q; (void)e; }
static void nr_ordered_queue_phase(struct d3d12_command_queue *q, const char *s, void *f, uint64_t v) { (void)q; (void)s; (void)f; (void)v; }
static void vkCmdPipelineBarrier2(uintptr_t cmd, const VkDependencyInfo *d) {
    assert(cmd && d->bufferMemoryBarrierCount == 1);
    assert(d->pBufferMemoryBarriers[0].size == 8 * 1024 * 1024);
    ++barriers;
}
static VkResult vkWaitSemaphores(uintptr_t d, const VkSemaphoreWaitInfo *w, uint64_t timeout) {
    (void)d; assert(w->semaphoreCount == 1 && *w->pValues == 100);
    assert(timeout == UINT64_C(2000000000)); assert(handoff_stage == 0);
    handoff_stage = 1; return prefix_result;
}
static int NR_SYSV lookup(uint64_t d, uint64_t va, uint64_t *token) {
    (void)d; if (va < 0x100000 || va >= 0x900000) return 1;
    *token = 14; return 0; /* interior addresses deliberately share a token */
}
static int NR_SYSV snapshot(uint64_t d, struct nr_buffer *out, uint32_t cap, uint32_t *count) {
    (void)d; assert(cap); *count = 1;
    out[0] = (struct nr_buffer){.token=14, .buffer=100, .size=8*1024*1024};
    ++snapshots; return 0;
}
static int NR_SYSV claim(const struct nr_buffer *b, uint32_t n, uint64_t q) { assert(n==1 && b->token==14 && q==1); ++claims; return 0; }
static int NR_SYSV publish(uint64_t t, uint32_t f, const struct nr_buffer *b, uint32_t n) {
    assert(t==14 && f==1 && b->token==14 && n==1 && handoff_stage==1);
    handoff_stage=2; ++publications; return 0;
}
static int NR_SYSV wait_output(uint64_t t, uint32_t f, uint32_t ms) {
    assert(t==14 && f==1 && ms==2000 && handoff_stage==2);
    handoff_stage=3; return output_result;
}
static int NR_SYSV fail(uint64_t t, uint32_t f, int e) { assert(t==14 && f==1 && e==600); return 0; }

/* Compile the implementation under test, never a copied state machine. */
#include "nr_ordered_commands.h"

struct fixture {
    struct d3d12_device device;
    struct pipeline_state state;
    struct d3d12_root_signature rs;
    struct allocator alloc;
    struct d3d12_command_list list;
};
static void init(struct fixture *f) {
    memset(f, 0, sizeof(*f)); barriers=snapshots=claims=handoff_stage=publications=0;
    prefix_result=VK_SUCCESS; output_result=0;
    f->state.compute.code.meta.hash=UINT64_C(0x135ea1f88cbc832d);
    f->rs.parameter_count=3;
    f->rs.parameters[0].parameter_type=f->rs.parameters[2].parameter_type=D3D12_ROOT_PARAMETER_TYPE_UAV;
    f->rs.parameters[1].parameter_type=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    f->rs.parameters[1].constant.constant_count=4;
    f->list.device=&f->device; f->list.state=&f->state; f->list.allocator=&f->alloc;
    f->list.compute_bindings.root_signature=&f->rs;
    f->list.cmd.iteration_count=1; f->list.cmd.vk_command_buffer=1;
    f->list.cmd.nr_flag_va=0x100100; f->list.cmd.nr_abort_va=0x900000;
}
static void destroy(struct fixture *f) {
    while(f->alloc.nr_snapshots) {
        struct nr_ordered_snapshot *p=f->alloc.nr_snapshots;
        f->alloc.nr_snapshots=p->next; free(p);
    }
}
static bool record(struct fixture *f, uint32_t mode, uint32_t frame, uint32_t cap) {
    uint32_t *c=f->list.compute_bindings.root_constants;
    c[0]=mode; c[1]=frame; c[2]=cap; c[3]=0;
    return nr_ordered_dispatch_boundary(&f->list, 1, 1, 1);
}
static int golden_sequence(unsigned slices) {
    struct fixture f; init(&f);
    assert(!record(&f,0,1,0)); /* original producer must run */
    for (unsigned i=0; i<slices; ++i) {
        bool replaced=record(&f,1,1,slices==1 ? 20000000 : 256);
        if (!replaced || f.device.removed) {
            fprintf(stderr,"FAIL: v0.3.0 wait slice %u/%u rejected (device %#x)\n",i+1,slices,(uint32_t)f.device.removed);
            destroy(&f); return 1;
        }
    }
    bool replaced=record(&f,2,1,0);
    if (replaced || f.device.removed) {
        fprintf(stderr,"FAIL: v0.3.0 finalizer rejected after %u wait slice(s) (device %#x)\n",slices,(uint32_t)f.device.removed);
        destroy(&f); return 1;
    }
    assert(snapshots==1 && barriers==2 && f.list.cmd.iteration_count==2);
    assert(f.list.cmd.iterations[0].nr_after.nr_producer.token==14);
    assert(f.list.cmd.iterations[1].nr_after.nr_consumer.token==14);
    assert(!f.list.cmd.nr_armed_token && !f.list.cmd.nr_wait_token);
    struct nr_ordered_boundary b[2]={f.list.cmd.iterations[0].nr_after,f.list.cmd.iterations[1].nr_after};
    struct queue vq={.submission_timeline=1};
    struct d3d12_command_queue q={.device=&f.device,.vkd3d_queue=&vq,.nr_queue_id=1};
    struct d3d12_command_queue_submission_execute e={.cmd_count=2,.nr_boundaries=b};
    assert(nr_ordered_claim_submission(&q,&e) && claims==1);
    assert(nr_ordered_after_producer(&q,&b[0],100)==VK_SUCCESS);
    assert(handoff_stage==3 && publications==1);
    handoff_stage=publications=0; prefix_result=2; /* timeout cannot publish */
    assert(nr_ordered_after_producer(&q,&b[0],100)!=VK_SUCCESS && publications==0);
    handoff_stage=0; prefix_result=VK_SUCCESS; output_result=600;
    assert(nr_ordered_after_producer(&q,&b[0],100)==VK_ERROR_DEVICE_LOST);
    destroy(&f); return 0;
}
static void invalid_sequences(void) {
    struct fixture f;
    for (unsigned kind=0;kind<9;++kind) {
        init(&f);
        if (kind>=2) { assert(!record(&f,0,1,0)); assert(record(&f,1,1,256)); }
        switch(kind) {
        case 0: record(&f,1,1,256); break; /* wait without producer */
        case 1: record(&f,2,1,0); break; /* finalize without handoff */
        case 2: record(&f,1,2,256); break; /* another frame */
        case 3: f.list.cmd.nr_flag_va+=4; record(&f,1,1,256); break; /* same allocation, wrong flag */
        case 4: f.list.cmd.nr_abort_va+=8; record(&f,1,1,256); break;
        case 5: record(&f,1,1,512); break; /* changed slice constants */
        case 6: record(&f,3,1,0); break; /* unknown mode */
        case 7: record(&f,0,2,0); break; /* missing previous finalizer */
        case 8: record(&f,2,2,0); break; /* wrong finalizer frame */
        }
        assert(f.device.removed==DXGI_ERROR_INVALID_CALL);
        destroy(&f);
    }
    init(&f); assert(!record(&f,0,1,0)); assert(record(&f,1,1,256)); assert(!record(&f,2,1,0));
    /* Closed/completed sequences cannot license an unpaired later wait. */
    record(&f,1,1,256); assert(f.device.removed); destroy(&f);
}
int main(int argc, char **argv) {
    setenv("VKD3D_NR_FLAG_HASH","135ea1f88cbc832d",1);
    api.lookup_va=lookup; api.snapshot=snapshot; api.claim_queue=claim;
    api.publish_input=publish; api.wait_output=wait_output; api.fail=fail;
    if (argc==2) return golden_sequence((unsigned)strtoul(argv[1],NULL,10));
    if (golden_sequence(1) || golden_sequence(4000)) return 1;
    invalid_sequences();
    puts("vkd3d ordered protocol contracts passed (CPU mocks; no GPU validation)");
    return 0;
}
