// Linux research: load/unload production modules and resolve one entry each.
// Does not dispatch their kernels or validate the complete network.
#include "hip_api.h"
#include <cstdio>

int main(int argc, char **argv) {
    try {
        if (argc < 3 || argc % 2 != 1)
            throw std::runtime_error("usage: module_probe MODULE ENTRY [MODULE ENTRY ...]");
        hip_probe::Api api;
        api.Check(api.hipInit(0), "HIP initialization");
        api.Check(api.hipSetDevice(0), "HIP device selection");
        unsigned count = 0;
        for (int i = 1; i < argc; i += 2) {
            std::printf("Loading %s entry=%s\n", argv[i], argv[i + 1]);
            std::fflush(stdout);
            hip_probe::Handle module{}, function{};
            api.Check(api.hipModuleLoad(&module, argv[i]), "module load");
            const int resolved = api.hipModuleGetFunction(&function, module, argv[i + 1]);
            const int unloaded = api.hipModuleUnload(module);
            api.Check(resolved, "kernel entry lookup");
            api.Check(unloaded, "module unload");
            ++count;
        }
        std::printf("RESULT modules=%u entries=%u (load/unload only; no inference)\n", count, count);
        return 0;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "Module probe: %s\n", error.what());
        return 1;
    }
}
