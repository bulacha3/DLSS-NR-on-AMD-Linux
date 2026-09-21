#ifndef LMXXF_RESIDENT_BACKEND_H
#define LMXXF_RESIDENT_BACKEND_H
#include <stdint.h>
#include <stddef.h>
#include "prefix_parameters.h"
#ifdef __cplusplus
extern "C" {
#endif
#define LMXXF_ABI 3u
/* Thread/device affine, BORROWS original HIP stream (null is the default).
 * Caller retains all GPU buffers until successful synchronization and publishes
 * Vulkan completion only after its own final marker. No host image transfer. */
struct lmxxf_config {
 uint32_t abi,bytes,width,height;const char *assets,*modules;void *stream;
};
struct lmxxf_frame {
 uint32_t abi,bytes,width,height;const void *rgb,*history_rgb;void *rgba_output;
 uint64_t rgb_bytes,history_bytes,output_bytes;uint32_t seed,reserved;
 struct lmxxf_prefix_parameters prefix;
};
enum {LMXXF_OK,LMXXF_INVALID,LMXXF_FAILED,LMXXF_PENDING};
struct lmxxf_context;
int lmxxf_validate_frame(const struct lmxxf_frame*,char*,size_t);
int lmxxf_create(const struct lmxxf_config*,struct lmxxf_context**,char*,size_t);
int lmxxf_enqueue(struct lmxxf_context*,const struct lmxxf_frame*,char*,size_t);
/* A failed finish/destroy retains the context and allocations. A successful
 * drain permits destruction, but does not make a poisoned context reusable. */
int lmxxf_finish(struct lmxxf_context*,char*,size_t);
int lmxxf_destroy(struct lmxxf_context**,char*,size_t);
/* Optional extension, does not change config/frame ABI 3. No GPU sync. */
struct lmxxf_submission_stats {
 uint32_t bytes,mode; /* 0 direct by request, 1 warmup, 2 graph, 3 fallback */
 uint64_t builds,replays,direct_frames,nodes;
 char reason[192];
};
int lmxxf_get_submission_stats(struct lmxxf_context*,struct lmxxf_submission_stats*);
/* Residency extension. Only the legacy null stream is transferable. The
 * cache owns at most one IDLE context per HIP device; checked-out contexts
 * retain exclusive thread ownership. Modules/weights survive geometry changes.
 * return_after_sync is called by the bridge ONLY after its original final
 * marker and successful original hipStreamSynchronize on the same thread.
 * A nonzero sync result or a poisoned context is never cached or freed. */
struct lmxxf_residency_stats {
 uint32_t bytes,reused,resized,device;
 uint64_t resident_id,creations,reuses,resizes,evictions,cached;
 uint64_t weight_bytes,scratch_bytes;
};
int lmxxf_acquire_resident(const struct lmxxf_config*,struct lmxxf_context**,
                          struct lmxxf_residency_stats*,char*,size_t);
int lmxxf_return_after_sync(struct lmxxf_context**,void *original_stream,
                           int original_sync_result,
                           struct lmxxf_residency_stats*,char*,size_t);
/* Development/shutdown hook: drops only idle residents on the current device.
 * It never touches another thread's active lease or a failed pending context. */
int lmxxf_trim_resident(char*,size_t);
#ifdef __cplusplus
}
#endif
#endif
