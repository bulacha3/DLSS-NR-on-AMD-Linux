// Offline research probe. Does not load a game or claim numerical validation.
#include "hip_api.h"
#include <cstdio>

int main() {
    try {
        hip_probe::Api api;
        int version = 0, count = 0;
        api.Check(api.hipRuntimeGetVersion(&version), "HIP version");
        api.Check(api.hipInit(0), "HIP initialization");
        api.Check(api.hipGetDeviceCount(&count), "HIP device count");
        if (count < 1) throw std::runtime_error("No HIP device available");
        api.Check(api.hipSetDevice(0), "HIP device selection");
        char name[256] = {};
        api.Check(api.hipDeviceGetName(name, sizeof(name), 0), "HIP device name");
        std::printf("HIP version=%d visible_devices=%d selected_device=0 name=%s\n", version, count, name);
        std::puts("Runtime probe only. Run the gfx1201 FP8 test and network comparison separately.");
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "Research probe: %s\n", error.what());
        return 1;
    }
}
