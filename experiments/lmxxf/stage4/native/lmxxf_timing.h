#ifndef DLSSNR_LMXXF_TIMING_H
#define DLSSNR_LMXXF_TIMING_H
#include <stdint.h>

/* Host intervals only. These do not measure GPU execution or displayed FPS.
 * Observe every completion, but bound report writes after the first four events.
 * The idle interval also includes game scheduling and time spent in menus. */
struct lm4_timing {
    uint64_t started, previous_completed, idle_ns, acquire_ns, enqueue_ns;
    uint64_t last_report, anomalies, reports;
};
static void lm4_timing_begin(struct lm4_timing *t, uint64_t now) {
    t->started = now;
    t->idle_ns = t->previous_completed && now >= t->previous_completed
        ? now - t->previous_completed : 0;
    t->acquire_ns = t->enqueue_ns = 0;
}
static unsigned lm4_timing_slow_mask(const struct lm4_timing *t,
                                     uint64_t wall_ns, uint64_t frame) {
    if (frame <= 3) return 0; /* Expected first-frame setup is reported separately. */
    return (wall_ns > UINT64_C(50000000) ? 1u : 0u)
        | (t->idle_ns > UINT64_C(100000000) ? 2u : 0u);
}
static unsigned lm4_timing_complete(struct lm4_timing *t, uint64_t now,
                                    uint64_t frame, uint64_t *wall_ns) {
    *wall_ns = now >= t->started ? now - t->started : 0;
    t->previous_completed = now;
    unsigned reason = lm4_timing_slow_mask(t, *wall_ns, frame);
    if (!reason) return 0;
    ++t->anomalies;
    if (t->reports >= 4 && now >= t->last_report
            && now - t->last_report < UINT64_C(1000000000)) return 0;
    t->last_report = now;
    ++t->reports;
    return reason;
}
#endif
