// Host allocator contract for the real resident API and modeled HIP runtime.
// No kernels or GPU timing: warm lease transfers must not allocate/free C++
// objects, and trimming an empty device slot must preserve its active lease.
// Build with -std=c++17 -O2 -rdynamic -pthread -ldl so the loaded resident's
// operator new/delete resolve to these counters. Arguments: absolute paths to
// the existing graph mock DSO, the resident DSO and the runtime modules folder.
#include "../experiments/lmxxf/resident_backend.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <new>

static bool counting;
static bool no_allocations = true;
static size_t allocations, deallocations;
static const char* modules;
static decltype(lmxxf_acquire_resident)* acquire_resident;
static decltype(lmxxf_return_after_sync)* return_after_sync;
static decltype(lmxxf_trim_resident)* trim_resident;

void* operator new(size_t bytes) {
    if (void* p = std::malloc(bytes ? bytes : 1)) {
        if (counting) ++allocations;
        return p;
    }
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept {
    if (p && counting) ++deallocations;
    std::free(p);
}
void* operator new[](size_t bytes) { return ::operator new(bytes); }
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete(void* p, size_t) noexcept { ::operator delete(p); }
void operator delete[](void* p, size_t) noexcept { ::operator delete(p); }

static void check_transfers(bool profile) {
    assert(!setenv("DLSSNR_LMXXF_GPU_PROFILE", profile ? "1" : "0", 1));
    assert(!setenv("DLSSNR_LMXXF_GPU_PROFILE_REPORT",
                   "/unused/long-profile-path-for-host-allocation-contract.txt", 1));
    lmxxf_config cfg{LMXXF_ABI, sizeof(cfg), 512, 512,
                     "/unused/assets", modules, nullptr};
    lmxxf_context* ctx = nullptr;
    lmxxf_residency_stats stats{};
    stats.bytes = sizeof(stats);
    char error[384];
    auto acquire = [&] {
        assert(!acquire_resident(&cfg, &ctx, &stats, error, sizeof(error)));
        assert(ctx && !stats.cached);
    };
    auto give_back = [&] {
        assert(!return_after_sync(&ctx, nullptr, 0, &stats, error, sizeof(error)));
        assert(!ctx && stats.cached == 1);
    };
    acquire();
    give_back();
    const uint64_t identity = stats.resident_id;
    const uint64_t evictions = stats.evictions;
    allocations = deallocations = 0;
    counting = true;
    for (unsigned i = 0; i != 4096; ++i) {
        acquire();
        assert(stats.reused && stats.resident_id == identity);
        give_back();
        assert(stats.evictions == evictions);
    }
    counting = false;
    std::printf("RESIDENT_HOST_TRANSFERS profile=%u iterations=4096 new=%zu delete=%zu\n",
                unsigned(profile), allocations, deallocations);
    std::fflush(stdout);
    no_allocations = no_allocations && !allocations && !deallocations;

    // The map may contain an empty slot for this checked-out resident. Trim
    // must not count a nonexistent eviction or invalidate the active lease.
    acquire();
    assert(!trim_resident(error, sizeof(error)));
    give_back();
    assert(stats.resident_id == identity && stats.evictions == evictions);
    assert(!trim_resident(error, sizeof(error)));
}

int main(int argc, char** argv) {
    assert(argc == 4);
    modules = argv[3];
    assert(!setenv("DLSSNR_RESEARCH_HIP_LIBRARY", argv[1], 1));
    assert(!setenv("DLSSNR_LMXXF_GRAPH", "1", 1));
    void* resident = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
    assert(resident);
    acquire_resident = reinterpret_cast<decltype(acquire_resident)>(dlsym(resident, "lmxxf_acquire_resident"));
    return_after_sync = reinterpret_cast<decltype(return_after_sync)>(dlsym(resident, "lmxxf_return_after_sync"));
    trim_resident = reinterpret_cast<decltype(trim_resident)>(dlsym(resident, "lmxxf_trim_resident"));
    assert(acquire_resident && return_after_sync && trim_resident);
    check_transfers(false);
    check_transfers(true);
    std::puts("RESIDENT_EMPTY_SLOT_TRIM active_lease=preserved eviction_count=unchanged");
    assert(no_allocations);
}
