/* Private-prefix loader probe: no rendering, allocations or GPU kernels.
 * Win64 entry point calls the existing bridge table using the SysV ABI.
 * Build with the documented clang/lld recipe; no runtime compiler needed. */
#include "hip_bridge.h"
#define IMPORT __declspec(dllimport)
#define SYSV __attribute__((sysv_abi))
IMPORT int __stdcall __wine_get_unix_env(const char *, char *, unsigned long long);
IMPORT void *__stdcall CreateFileA(const char *, unsigned long, unsigned long, void *, unsigned long, unsigned long, void *);
IMPORT int __stdcall WriteFile(void *, const void *, unsigned long, unsigned long *, void *);
IMPORT int __stdcall CloseHandle(void *);
IMPORT void __stdcall ExitProcess(unsigned int);

static void finish(const char *message, unsigned long length, unsigned int code) {
    void *file = CreateFileA("probe-result.txt", 0x40000000, 0, 0, 2, 0x80, 0);
    unsigned long written = 0;
    if (file == (void *)(long long)-1)
        ExitProcess(20);
    if (!WriteFile(file, message, length, &written, 0) || written != length) {
        CloseHandle(file);
        ExitProcess(20);
    }
    CloseHandle(file);
    ExitProcess(code);
}

void mainCRTStartup(void) {
    char value[64];
    unsigned long long address = 0;
    unsigned i = 0, digit;
    int version = 0, count = 0, rc;
    DlssnrHipBridge *bridge;
    typedef int (SYSV *scalar_fn)(int *);
    if (__wine_get_unix_env(DLSSNR_HIP_ENV, value, sizeof(value)) || !value[0])
        finish("bridge_error", 12, 11);
    if (value[0] == '0' && value[1] == 'x')
        i = 2;
    for (; value[i] && i < sizeof(value) - 1; i++) {
        if (value[i] >= '0' && value[i] <= '9') digit = value[i] - '0';
        else if (value[i] >= 'a' && value[i] <= 'f') digit = value[i] - 'a' + 10;
        else if (value[i] >= 'A' && value[i] <= 'F') digit = value[i] - 'A' + 10;
        else finish("bridge_error", 12, 11);
        address = (address << 4) | digit;
    }
    bridge = (DlssnrHipBridge *)address;
    if (!bridge || bridge->magic != DLSSNR_HIP_MAGIC)
        finish("bridge_error", 12, 11);
    rc = ((scalar_fn)bridge->p_hipRuntimeGetVersion)(&version);
    if (rc) finish("load_error", 10, 10);
    if (version / 10000000 != 7) finish("version_error", 13, 12);
    rc = ((scalar_fn)bridge->p_hipGetDeviceCount)(&count);
    if (rc || count <= 0) finish("no_devices", 10, 13);
    finish("ok", 2, 0);
}
