/* Included by hip_bridge.c: CPU rendezvous, no GPU wait/spin and no file counter. */
#include "nr_ordered.h"

/* Bounded, observational tracing. Never changes waits, ownership or errors. */
static void nr_trace(const char *stage, uint64_t token, uint32_t frame, int result) {
    static unsigned count;
    const char *enabled = getenv("DLSSNR_DIAGNOSTICS");
    if (!enabled || strcmp(enabled, "1")) return;
    unsigned n = __atomic_load_n(&count, __ATOMIC_RELAXED);
    do {
        if (n >= 128) return;
    } while (!__atomic_compare_exchange_n(&count, &n, n + 1, 0,
                                         __ATOMIC_RELAXED, __ATOMIC_RELAXED));
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    logmsg("NRDIAG #%u stage=%s token=%llu frame=%u result=%d monotonic=%lld.%09ld",
           n + 1, stage, (unsigned long long)token, frame, result,
           (long long)now.tv_sec, now.tv_nsec);
}

struct nr_pin_bundle {
    struct nr_pin_bundle *next;
    uint32_t count;
    struct nr_buffer buffers[];
};
struct nr_frame_state {
    uint32_t frame;
    int used, input_ready, output_ready, consumed, error, job_owned;
    struct nr_pin_bundle *pins;
};
struct nr_resource_state {
    uint64_t device, handle, va, buffer, size, token;
    uint64_t owner, queue;
    nr_try_retain_fn try_retain;
    nr_release_fn release;
    void *external_memory, *mapped;
    uint64_t mapped_offset, mapped_size;
    int active, probe_busy;
    struct nr_frame_state frames[NR_ORDERED_WINDOW];
};
static struct nr_resource_state nr_resources[NR_ORDERED_MAX_RESOURCES];
static pthread_mutex_t nr_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t nr_condition = PTHREAD_COND_INITIALIZER;
static uint64_t nr_next_token = 1;
/* Process-owned root: thread exit cannot lose quarantined references.
 * No destructor drain: only successful original HIP sync proves completion. */
static struct nr_pin_bundle *nr_pin_bundles;
static _Thread_local struct {
    uint64_t token;
    uint32_t frame;
    void *stream, *flags;
    int active, error, sealed;
    struct nr_frame_state *state;
} nr_job;

/* Detach under mutex; release/free only AFTER unlocking. */
static struct nr_pin_bundle *nr_detach_pins(struct nr_frame_state *s) {
    struct nr_pin_bundle *pins = s->pins;
    if (pins) {
        struct nr_pin_bundle **p = &nr_pin_bundles;
        while (*p != pins) p = &(*p)->next;
        *p = pins->next;
        s->pins = NULL;
    }
    return pins;
}
static void nr_release_pins(struct nr_pin_bundle *pins) {
    if (!pins) return;
    for (uint32_t i = 0; i < pins->count; ++i)
        pins->buffers[i].release(pins->buffers[i].owner);
    free(pins);
}
static int nr_resource_busy(const struct nr_resource_state *r) {
    if (r->probe_busy) return 1;
    for (unsigned i = 0; i < NR_ORDERED_WINDOW; ++i)
        if (r->frames[i].pins || r->frames[i].job_owned) return 1;
    return 0;
}

static struct nr_resource_state *nr_find_token(uint64_t token) {
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i)
        if (nr_resources[i].active && nr_resources[i].token == token)
            return &nr_resources[i];
    return NULL;
}
static struct nr_frame_state *nr_frame(struct nr_resource_state *r, uint32_t frame, int create) {
    struct nr_frame_state *s = &r->frames[frame % NR_ORDERED_WINDOW];
    if (s->used && s->frame == frame)
        return s;
    if (!create || s->pins || s->job_owned || (s->used && !s->consumed && !s->error))
        return NULL;
    memset(s, 0, sizeof(*s));
    s->used = 1;
    s->frame = frame;
    return s;
}
static int NR_SYSV nr_register_resource(uint64_t device, uint64_t handle, uint64_t va,
        uint64_t buffer, uint64_t size, uint64_t owner,
        nr_try_retain_fn try_retain, nr_release_fn release, uint64_t *token) {
    if (!device || !handle || !va || !buffer || !size || !token || !owner || !try_retain || !release)
        return 1;
    pthread_mutex_lock(&nr_mutex);
    struct nr_resource_state *slot = NULL;
    /* Clear reused handle even when the new owner already has a registry slot.
     * Do not touch the old owner's external_memory/mapping/token. */
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i)
        if (nr_resources[i].active && nr_resources[i].handle == handle)
            nr_resources[i].handle = 0;
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i) {
        struct nr_resource_state *r = &nr_resources[i];
        if (!r->active) { if (!slot && !nr_resource_busy(r)) slot = r; continue; }
        if (r->device == device && r->va == va && r->buffer == buffer && r->size == size &&
                r->owner == owner && r->try_retain == try_retain && r->release == release) {
            r->handle = handle;
            *token = r->token;
            pthread_mutex_unlock(&nr_mutex);
            return 0;
        }
        if (r->device == device && r->va == va) {
            pthread_mutex_unlock(&nr_mutex);
            return 1;
        }
    }
    if (!slot) { pthread_mutex_unlock(&nr_mutex); return 2; }
    memset(slot, 0, sizeof(*slot));
    slot->device = device; slot->handle = handle; slot->va = va;
    slot->buffer = buffer; slot->size = size; slot->active = 1;
    slot->owner = owner; slot->try_retain = try_retain; slot->release = release;
    slot->token = nr_next_token++;
    *token = slot->token;
    pthread_mutex_unlock(&nr_mutex);
    return 0;
}
static int NR_SYSV nr_lookup_va(uint64_t device, uint64_t va, uint64_t *token) {
    int rc = 1;
    if (!token) return rc;
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i) {
        struct nr_resource_state *r = &nr_resources[i];
        if (r->active && r->device == device && va >= r->va && va - r->va < r->size) {
            *token = r->token; rc = 0; break;
        }
    }
    pthread_mutex_unlock(&nr_mutex);
    return rc;
}
static int NR_SYSV nr_snapshot(uint64_t device, struct nr_buffer *out, uint32_t capacity, uint32_t *count) {
    uint32_t n = 0;
    int rc = 0;
    if (!count || (!out && capacity)) return 1;
    *count = 0;
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i) {
        struct nr_resource_state *r = &nr_resources[i];
        if (r->active && r->device == device && r->mapped) {
            if (n == capacity) { rc = 2; break; }
            if (r->try_retain(r->owner)) { rc = 1; break; }
            out[n] = (struct nr_buffer){r->token, r->buffer, r->size, r->owner, r->release};
            ++n;
        }
    }
    pthread_mutex_unlock(&nr_mutex);
    /* A final release may call retire_resource: never run it under nr_mutex. */
    if (rc) {
        while (n--) out[n].release(out[n].owner);
    } else *count = n;
    return rc;
}
static int NR_SYSV nr_claim_queue(const struct nr_buffer *buffers, uint32_t count, uint64_t queue) {
    int rc = 0;
    if (!queue || !buffers || !count || count > NR_ORDERED_MAX_RESOURCES) return 1;
    pthread_mutex_lock(&nr_mutex);
    for (uint32_t i = 0; i < count; ++i) {
        struct nr_resource_state *r = nr_find_token(buffers[i].token);
        if (!r || r->probe_busy || r->buffer != buffers[i].buffer || r->size != buffers[i].size ||
                r->owner != buffers[i].owner || r->release != buffers[i].release ||
                (r->queue && r->queue != queue)) { rc = 1; break; }
    }
    if (!rc)
        for (uint32_t i = 0; i < count; ++i) nr_find_token(buffers[i].token)->queue = queue;
    pthread_mutex_unlock(&nr_mutex);
    return rc;
}
static int NR_SYSV nr_retire_resource(uint64_t device, uint64_t va) {
    struct nr_pin_bundle *drop = NULL;
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i)
        if (nr_resources[i].active && nr_resources[i].device == device && nr_resources[i].va == va) {
            nr_resources[i].active = 0;
            for (unsigned j = 0; j < NR_ORDERED_WINDOW; ++j) {
                struct nr_frame_state *s = &nr_resources[i].frames[j];
                s->error = 1;
                if (s->pins && !s->job_owned) {
                    struct nr_pin_bundle *pins = nr_detach_pins(s);
                    pins->next = drop; drop = pins;
                }
            }
        }
    pthread_cond_broadcast(&nr_condition);
    pthread_mutex_unlock(&nr_mutex);
    while (drop) {
        struct nr_pin_bundle *next = drop->next;
        nr_release_pins(drop); drop = next;
    }
    return 0;
}
static int NR_SYSV nr_publish_input(uint64_t token, uint32_t frame,
        const struct nr_buffer *exact_snapshot, uint32_t count) {
    nr_trace("publish-input-enter", token, frame, 0);
    if (!exact_snapshot || !count || count > NR_ORDERED_MAX_RESOURCES) return 1;
    struct nr_pin_bundle *pins = calloc(1, sizeof(*pins) + count * sizeof(*exact_snapshot));
    if (!pins) return 2;
    memcpy(pins->buffers, exact_snapshot, count * sizeof(*exact_snapshot));
    pthread_mutex_lock(&nr_mutex);
    struct nr_resource_state *r = nr_find_token(token);
    struct nr_frame_state *s = r ? nr_frame(r, frame, 1) : NULL;
    int rc = !s || s->consumed ? 1 : s->error;
    if (!rc && (s->input_ready || s->output_ready || s->job_owned || s->pins)) rc = 1;
    int member = 0;
    for (uint32_t i = 0; !rc && i < count; ++i) {
        const struct nr_buffer *b = &pins->buffers[i];
        struct nr_resource_state *entry = nr_find_token(b->token);
        if (!entry || entry->device != r->device || entry->buffer != b->buffer ||
                entry->size != b->size || entry->owner != b->owner || entry->release != b->release)
            rc = 1;
        for (uint32_t j = 0; j < i; ++j)
            if (pins->buffers[j].token == b->token) rc = 1;
        if (b->token == token) member = 1;
    }
    if (!member) rc = rc ? rc : 1;
    for (uint32_t i = 0; !rc && i < count; ++i) {
        struct nr_resource_state *entry = nr_find_token(pins->buffers[i].token);
        if (entry->try_retain(entry->owner)) rc = 1;
        else ++pins->count;
    }
    if (!rc) {
        pins->next = nr_pin_bundles; nr_pin_bundles = pins;
        s->pins = pins;
        s->input_ready = 1;
        pthread_cond_broadcast(&nr_condition);
    }
    pthread_mutex_unlock(&nr_mutex);
    if (rc) nr_release_pins(pins);
    nr_trace("publish-input-return", token, frame, rc);
    return rc;
}
static int NR_SYSV nr_fail(uint64_t token, uint32_t frame, int error) {
    struct nr_pin_bundle *drop = NULL;
    if (!error) error = 999;
    pthread_mutex_lock(&nr_mutex);
    struct nr_resource_state *r = nr_find_token(token);
    struct nr_frame_state *s = r ? nr_frame(r, frame, 1) : NULL;
    if (s) {
        s->error = error;
        if (!s->job_owned) drop = nr_detach_pins(s);
    }
    pthread_cond_broadcast(&nr_condition);
    pthread_mutex_unlock(&nr_mutex);
    nr_release_pins(drop);
    return error;
}
static int nr_wait_state(uint64_t token, uint32_t frame, uint32_t ms, int output) {
    struct nr_pin_bundle *drop = NULL;
    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    deadline.tv_sec += ms / 1000;
    deadline.tv_nsec += (long)(ms % 1000) * 1000000L;
    if (deadline.tv_nsec >= 1000000000L) { ++deadline.tv_sec; deadline.tv_nsec -= 1000000000L; }
    int rc = 0;
    pthread_mutex_lock(&nr_mutex);
    for (;;) {
        struct nr_resource_state *r = nr_find_token(token);
        struct nr_frame_state *s = r ? nr_frame(r, frame, 1) : NULL;
        if (!s || s->consumed) { rc = 1; break; }
        if (s->error) { rc = s->error; break; }
        if (output ? s->output_ready : s->input_ready) break;
        if (!ms) { rc = 600; break; } /* hipErrorNotReady, non-destructive query */
        int e = pthread_cond_clockwait(&nr_condition, &nr_mutex, CLOCK_MONOTONIC, &deadline);
        if (e) {
            rc = e == ETIMEDOUT ? 600 : 999;
            s = nr_find_token(token) ? nr_frame(nr_find_token(token), frame, 0) : NULL;
            if (s) {
                s->error = rc; /* late signal cannot turn timeout into success */
                if (!s->job_owned) drop = nr_detach_pins(s);
            }
            pthread_cond_broadcast(&nr_condition);
            break;
        }
    }
    pthread_mutex_unlock(&nr_mutex);
    nr_release_pins(drop);
    return rc;
}
static int NR_SYSV nr_wait_output(uint64_t token, uint32_t frame, uint32_t timeout_ms) {
    nr_trace("wait-output-enter", token, frame, 0);
    int result = nr_wait_state(token, frame, timeout_ms, 1);
    nr_trace("wait-output-return", token, frame, result);
    return result;
}
static int NR_SYSV nr_consumer_submitted(uint64_t token, uint32_t frame) {
    pthread_mutex_lock(&nr_mutex);
    struct nr_resource_state *r = nr_find_token(token);
    struct nr_frame_state *s = r ? nr_frame(r, frame, 0) : NULL;
    int rc = !s || !s->output_ready || s->consumed ? 1 : s->error;
    if (!rc) s->consumed = 1;
    pthread_mutex_unlock(&nr_mutex);
    return rc;
}
static struct nr_ordered_api nr_api = {
    NR_ORDERED_MAGIC, NR_ORDERED_VERSION, sizeof(struct nr_ordered_api),
    nr_register_resource, nr_lookup_va, nr_snapshot, nr_claim_queue, nr_retire_resource,
    nr_publish_input, nr_wait_output, nr_consumer_submitted, nr_fail
};
static void nr_associate_import(uint64_t handle, void *external_memory) {
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i)
        if (nr_resources[i].active && nr_resources[i].handle == handle)
            nr_resources[i].external_memory = external_memory;
    pthread_mutex_unlock(&nr_mutex);
}
static void nr_associate_mapping(void *external_memory, void *ptr, uint64_t offset, uint64_t size) {
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i) {
        struct nr_resource_state *r = &nr_resources[i];
        if (r->active && r->external_memory == external_memory && offset <= r->size && size <= r->size - offset) {
            r->mapped = ptr; r->mapped_offset = offset; r->mapped_size = size;
        }
    }
    pthread_mutex_unlock(&nr_mutex);
}

/* v0.3.0 startup performs two bounded flag-kernel probes, not NR jobs:
 * wait(flags, 0, 1), set(flags, 0, NULL), then wait(flags, 0x40000000,
 * 1500000) after a producer-only D3D12 list and a CPU fence wait. These
 * have no paired consumer/snapshot and must not enter the frame rendezvous.
 * Evidence: unmodified af5027d8 payload, RVAs 0x14e28..0x14ed6 and
 * 0x14f70..0x15079. Forward the exact original bounded kernels, synchronize
 * them, and never manufacture flags or neural frame completion.
 */
static _Thread_local struct {
    uint64_t token;
    void *flags;
    unsigned phase;
} nr_probe;

static int nr_try_startup_probe(const void *f, dim3_t grid, dim3_t block,
        void **args, u64 shared, void *stream, int *result) {
    void *flags, *abort_buffer;
    uint32_t frame, limit;
    unsigned kind = 0;
    if (!f || (f != g_flag_wait && f != g_flag_set)) return 0;
    if (!args || !args[0] || !args[1] || !args[2] || shared || stream ||
            grid.x != 1 || grid.y != 1 || grid.z != 1 ||
            block.x != 32 || block.y != 1 || block.z != 1)
        return 0;
    memcpy(&flags, args[0], sizeof(flags));
    memcpy(&frame, args[1], sizeof(frame));
    if (f == g_flag_wait) {
        memcpy(&limit, args[2], sizeof(limit));
        if (!frame && limit == 1) kind = 1;
        else if (frame == UINT32_C(0x40000000) && limit == 1500000) kind = 3;
    } else if (!frame) {
        memcpy(&abort_buffer, args[2], sizeof(abort_buffer));
        if (!abort_buffer) kind = 2;
    }
    if (!kind) return 0;
    *result = 1;
    if (nr_job.active || nr_job.error || !real.p_hipStreamSynchronize) return 1;
    struct nr_pin_bundle *pins = calloc(1, sizeof(*pins) + sizeof(struct nr_buffer));
    if (!pins) { *result = 2; return 1; }
    struct nr_resource_state *resource = NULL;
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i) {
        struct nr_resource_state *r = &nr_resources[i];
        uintptr_t base = (uintptr_t)r->mapped, ptr = (uintptr_t)flags;
        /* v0.3.0 suballocates its flags inside a larger shared buffer. */
        if (r->active && base && ptr >= base && ptr - base <= r->mapped_size &&
                r->mapped_size - (ptr - base) >= 44 &&
                !nr_resource_busy(r) && (kind == 1 ||
                (nr_probe.phase == kind - 1 && nr_probe.token == r->token && nr_probe.flags == flags))) {
            if (r->try_retain(r->owner)) break;
            resource = r;
            r->probe_busy = 1;
            pins->count = 1;
            pins->buffers[0] = (struct nr_buffer){r->token, r->buffer, r->size, r->owner, r->release};
            pins->next = nr_pin_bundles;
            nr_pin_bundles = pins;
            break;
        }
    }
    pthread_mutex_unlock(&nr_mutex);
    if (!resource) { free(pins); return 1; }
    uint64_t token = pins->buffers[0].token;
    nr_trace("startup-probe-enter", token, frame, 0);
    int launch_result = real.p_hipLaunchKernel(f, grid, block, args, shared, stream);
    int sync_result = real.p_hipStreamSynchronize(stream);
    *result = launch_result ? launch_result : sync_result;
    nr_trace("startup-probe-return", token, frame, *result);
    /* A failed original sync cannot prove that the flag buffer is idle. */
    if (!sync_result) {
        pthread_mutex_lock(&nr_mutex);
        struct nr_pin_bundle **p = &nr_pin_bundles;
        while (*p != pins) p = &(*p)->next;
        *p = pins->next;
        resource->probe_busy = 0;
        pthread_mutex_unlock(&nr_mutex);
        nr_release_pins(pins);
    }
    if (!*result) {
        nr_probe.token = token;
        nr_probe.flags = flags;
        nr_probe.phase = kind == 3 ? 0 : kind;
    } else nr_probe.phase = 0;
    return 1;
}

static int nr_begin_job(void **args, void *stream) {
    void *flags = NULL;
    uint32_t frame = 0;
    uint64_t token = 0;
    if (!args || !args[0] || !args[1]) return 1;
    memcpy(&flags, args[0], sizeof(flags));
    memcpy(&frame, args[1], sizeof(frame));
    pthread_mutex_lock(&nr_mutex);
    for (unsigned i = 0; i < NR_ORDERED_MAX_RESOURCES; ++i) {
        struct nr_resource_state *r = &nr_resources[i];
        uintptr_t base = (uintptr_t)r->mapped, ptr = (uintptr_t)flags;
        if (r->active && base && ptr >= base && ptr - base <= r->mapped_size &&
                r->mapped_size - (ptr - base) >= 20)
            token = r->token;
    }
    pthread_mutex_unlock(&nr_mutex);
    /* Errors do not relinquish ownership. Only successful original sync can. */
    if (nr_job.active) return nr_job.error = nr_fail(nr_job.token, nr_job.frame, 1);
    memset(&nr_job, 0, sizeof(nr_job));
    nr_job.token = token; nr_job.frame = frame; nr_job.stream = stream; nr_job.flags = flags;
    nr_trace("hip-wait-input-enter", token, frame, 0);
    nr_job.error = token ? nr_wait_state(token, frame, 2000, 0) : 3;
    nr_trace("hip-wait-input-return", token, frame, nr_job.error);
    if (!nr_job.error) {
        pthread_mutex_lock(&nr_mutex);
        struct nr_resource_state *r = nr_find_token(token);
        struct nr_frame_state *s = r ? nr_frame(r, frame, 0) : NULL;
        if (!s || !s->input_ready || !s->pins || s->output_ready || s->consumed || s->error || s->job_owned)
            nr_job.error = 1;
        else { s->job_owned = 1; nr_job.state = s; }
        pthread_mutex_unlock(&nr_mutex);
    }
    nr_job.active = nr_job.error == 0;
    if (nr_job.error) logmsg("ordered input refused frame=%u token=%llu err=%d", frame,
            (unsigned long long)token, nr_job.error);
    return nr_job.error;
}

static int nr_job_error(int error) {
    if (!error) error = 999;
    nr_job.error = error;
    if (nr_job.token) nr_fail(nr_job.token, nr_job.frame, error);
    return error;
}
static int nr_seal_job(void **args, void *stream) {
    void *flags = NULL;
    uint32_t frame = 0;
    if (!nr_job.active || nr_job.sealed || nr_job.error || stream != nr_job.stream ||
            !args || !args[0] || !args[1]) return nr_job_error(1);
    memcpy(&flags, args[0], sizeof(flags));
    memcpy(&frame, args[1], sizeof(frame));
    pthread_mutex_lock(&nr_mutex);
    struct nr_resource_state *r = nr_find_token(nr_job.token);
    int valid = r && flags == nr_job.flags && frame == nr_job.frame;
    pthread_mutex_unlock(&nr_mutex);
    if (!valid) return nr_job_error(1);
    nr_job.sealed = 1;
    return 0;
}
static int nr_complete_job(int hip_error) {
    if (!nr_job.active) return hip_error;
    /* Failed sync proves nothing about outstanding accesses: quarantine. */
    if (hip_error) return nr_job_error(hip_error);
    pthread_mutex_lock(&nr_mutex);
    struct nr_resource_state *r = nr_find_token(nr_job.token);
    /* state cannot be recycled while job_owned, even on explicit retirement. */
    struct nr_frame_state *s = nr_job.state;
    int rc = nr_job.error ? nr_job.error : s->error;
    if (!rc && (!r || !s->input_ready || s->output_ready || s->consumed)) rc = 1;
    if (!rc && !nr_job.sealed) {
        pthread_mutex_unlock(&nr_mutex);
        return 0; /* healthy intermediate sync: more kernels may follow */
    }
    if (rc) s->error = rc;
    else s->output_ready = 1;
    struct nr_pin_bundle *drop = nr_detach_pins(s);
    s->job_owned = 0;
    nr_job.active = 0;
    nr_job.state = NULL;
    nr_job.error = rc;
    pthread_cond_broadcast(&nr_condition);
    pthread_mutex_unlock(&nr_mutex);
    nr_release_pins(drop);
    nr_trace("hip-complete", nr_job.token, nr_job.frame, rc);
    if (!rc) logmsg("ordered complete token=%llu frame=%u", (unsigned long long)nr_job.token, nr_job.frame);
    return rc;
}
