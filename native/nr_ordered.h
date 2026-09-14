/* Versioned ABI shared by the native HIP bridge and the vkd3d PE/native client.
 * Fixed-width fields only. Every function pointer uses the Unix x86_64 ABI.
 * No GPU waits are issued by this table; the producer must first finish its
 * already-submitted Vulkan command buffer before publishing input readiness.
 */
#ifndef DLSSNR_ORDERED_H
#define DLSSNR_ORDERED_H
#include <stdint.h>
#define NR_ORDERED_ENV "DLSSNR_ORDERED_ABI_V3"
#define NR_ORDERED_MAGIC UINT64_C(0x3144524f524e4c44)
#define NR_ORDERED_VERSION 3u
#define NR_ORDERED_MAX_RESOURCES 128u
#define NR_ORDERED_WINDOW 8u
#if defined(__x86_64__) || defined(_M_X64)
#define NR_SYSV __attribute__((sysv_abi))
#else
#define NR_SYSV
#endif
/* try_retain runs under registry mutex: CAS nonzero only, no reentry.
 * release runs outside it. Registry holds no owning reference. */
typedef int (NR_SYSV *nr_try_retain_fn)(uint64_t owner);
typedef void (NR_SYSV *nr_release_fn)(uint64_t owner);
struct nr_buffer {
    uint64_t token, buffer, size;
    uint64_t owner;
    nr_release_fn release;
};
struct nr_ordered_api {
    uint64_t magic;
    uint32_t version, bytes;
    int (NR_SYSV *register_resource)(uint64_t device, uint64_t handle, uint64_t va,
            uint64_t buffer, uint64_t size, uint64_t owner,
            nr_try_retain_fn try_retain, nr_release_fn release, uint64_t *token);
    int (NR_SYSV *lookup_va)(uint64_t device, uint64_t va, uint64_t *token);
    /* Success transfers one pin per entry; failure returns count=0 and rolls back. */
    int (NR_SYSV *snapshot)(uint64_t device, struct nr_buffer *out, uint32_t capacity, uint32_t *count);
    /* All-or-none permanent logical queue affinity until resource retirement.
     * Queue IDs must be nonzero, unique, never reused; call BEFORE any prefix. */
    int (NR_SYSV *claim_queue)(const struct nr_buffer *buffers, uint32_t count, uint64_t queue);
    int (NR_SYSV *retire_resource)(uint64_t device, uint64_t va);
    /* Independent HIP pins for EXACT producer barriers; caller keeps its pins. */
    int (NR_SYSV *publish_input)(uint64_t token, uint32_t frame,
            const struct nr_buffer *exact_snapshot, uint32_t count);
    int (NR_SYSV *wait_output)(uint64_t token, uint32_t frame, uint32_t timeout_ms);
    int (NR_SYSV *consumer_submitted)(uint64_t token, uint32_t frame);
    int (NR_SYSV *fail)(uint64_t token, uint32_t frame, int error);
};
#endif
