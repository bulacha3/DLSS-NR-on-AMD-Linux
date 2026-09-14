/* PE trampoline: Win64 exports → Linux HIP via DlssnrHipBridge (same process).
 * Compiled with clang -target x86_64-pc-windows-msvc (or gnu). */
#include "hip_bridge.h"

#define EXPORT __declspec(dllexport)
#define SYSV __attribute__((sysv_abi))

typedef int BOOL;
typedef unsigned int DWORD;
typedef void *HANDLE;
#define DLL_PROCESS_ATTACH 1
#define GENERIC_WRITE 0x40000000u
#define CREATE_ALWAYS 2
#define FILE_ATTRIBUTE_NORMAL 0x80u
#define INVALID_HANDLE_VALUE ((HANDLE)(long long)-1)

__declspec(dllimport) DWORD __stdcall GetEnvironmentVariableA(const char *name, char *buf, DWORD size);
__declspec(dllimport) int __stdcall __wine_get_unix_env(const char *var, char *buf, unsigned long long size);
__declspec(dllimport) HANDLE __stdcall CreateFileA(const char *name, DWORD acc, DWORD share, void *sa,
                                                   DWORD disp, DWORD attr, HANDLE tmpl);
__declspec(dllimport) BOOL __stdcall WriteFile(HANDLE h, const void *buf, DWORD n, DWORD *w, void *ov);
__declspec(dllimport) BOOL __stdcall CloseHandle(HANDLE h);

static DlssnrHipBridge *g;

static unsigned long long parse_hex_ptr(const char *s) {
    unsigned long long v = 0;
    if (!s)
        return 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        s += 2;
    while (*s) {
        unsigned char c = (unsigned char)*s++;
        v <<= 4;
        if (c >= '0' && c <= '9')
            v |= (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f')
            v |= (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F')
            v |= (unsigned)(c - 'A' + 10);
        else
            break;
    }
    return v;
}

static int bridge_ok(void) {
    return g && g->magic == DLSSNR_HIP_MAGIC;
}

static void pe_log(const char *s, unsigned n) {
    HANDLE h = CreateFileA("Z:\\tmp\\dlssnr-pe.log", GENERIC_WRITE, 0, 0, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE)
        return;
    DWORD w = 0;
    WriteFile(h, s, n, &w, 0);
    CloseHandle(h);
}

static void init_bridge(void) {
    char buf[64];
    char msg[160];
    unsigned i;
    buf[0] = 0;
    /* Live Unix environ (LD_PRELOAD setenv). Wine PE env is a stale snapshot. */
    if (__wine_get_unix_env(DLSSNR_HIP_ENV, buf, sizeof(buf)) != 0 || !buf[0]) {
        DWORD n = GetEnvironmentVariableA(DLSSNR_HIP_ENV, buf, (DWORD)sizeof(buf));
        if (n == 0 || n >= sizeof(buf))
            buf[0] = 0;
    }
    if (buf[0])
        g = (DlssnrHipBridge *)(unsigned long long)parse_hex_ptr(buf);
    /* tiny hex dump into pe log */
    msg[0] = 'e'; msg[1] = 'n'; msg[2] = 'v'; msg[3] = '=';
    for (i = 0; i < 48 && buf[i]; i++)
        msg[4 + i] = buf[i];
    msg[4 + i] = ' ';
    msg[5 + i] = 'o';
    msg[6 + i] = 'k';
    msg[7 + i] = '=';
    msg[8 + i] = (char)('0' + (bridge_ok() ? 1 : 0));
    msg[9 + i] = '\n';
    pe_log(msg, 10 + i);
}

BOOL __stdcall DllMain(void *h, DWORD reason, void *r) {
    (void)h;
    (void)r;
    if (reason == DLL_PROCESS_ATTACH)
        init_bridge();
    return 1;
}

#define HIP_ERROR_NOT_INITIALIZED 3
#define HIP_ERROR_INVALID_VALUE 1
#define HIP_SUCCESS 0

EXPORT void *__hipRegisterFatBinary(void *data) {
    if (!bridge_ok() || !g->p___hipRegisterFatBinary)
        return 0;
    return ((void *SYSV (*)(void *))g->p___hipRegisterFatBinary)(data);
}

EXPORT void __hipUnregisterFatBinary(void **modules) {
    if (!bridge_ok() || !g->p___hipUnregisterFatBinary)
        return;
    ((void SYSV (*)(void **))g->p___hipUnregisterFatBinary)(modules);
}

EXPORT void __hipRegisterFunction(void **modules, const void *hostFunction, char *deviceFunction,
                                  const char *deviceName, unsigned int threadLimit, void *tid,
                                  void *bid, void *blockDim, void *gridDim, int *wSize) {
    if (!bridge_ok() || !g->p___hipRegisterFunction)
        return;
    ((void SYSV (*)(void **, const void *, char *, const char *, unsigned int, void *, void *, void *,
                    void *, int *))g->p___hipRegisterFunction)(
        modules, hostFunction, deviceFunction, deviceName, threadLimit, tid, bid, blockDim, gridDim,
        wSize);
}

EXPORT void __hipRegisterVar(void **modules, void *var, char *hostVar, char *deviceVar, int ext,
                             u64 size, int constant, int global) {
    if (!bridge_ok() || !g->p___hipRegisterVar)
        return;
    ((void SYSV (*)(void **, void *, char *, char *, int, u64, int, int))g->p___hipRegisterVar)(
        modules, var, hostVar, deviceVar, ext, size, constant, global);
}

EXPORT int __hipPushCallConfiguration(dim3_t gridDim, dim3_t blockDim, u64 sharedMem,
                                      void *stream) {
    if (!bridge_ok() || !g->p___hipPushCallConfiguration)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(dim3_t, dim3_t, u64, void *))g->p___hipPushCallConfiguration)(
        gridDim, blockDim, sharedMem, stream);
}

EXPORT int __hipPopCallConfiguration(dim3_t *gridDim, dim3_t *blockDim, u64 *sharedMem,
                                     void **stream) {
    if (!bridge_ok() || !g->p___hipPopCallConfiguration)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(dim3_t *, dim3_t *, u64 *, void **))g->p___hipPopCallConfiguration)(
        gridDim, blockDim, sharedMem, stream);
}

EXPORT int hipGetDeviceCount(int *count) {
    if (!bridge_ok() || !g->p_hipGetDeviceCount)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(int *))g->p_hipGetDeviceCount)(count);
}

EXPORT int hipSetDevice(int device) {
    if (!bridge_ok() || !g->p_hipSetDevice)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(int))g->p_hipSetDevice)(device);
}

EXPORT int hipGetDevicePropertiesR0600(void *prop, int deviceId) {
    if (!bridge_ok() || !g->p_hipGetDevicePropertiesR0600)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *, int))g->p_hipGetDevicePropertiesR0600)(prop, deviceId);
}

EXPORT int hipDriverGetVersion(int *driverVersion) {
    if (!bridge_ok() || !g->p_hipDriverGetVersion)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(int *))g->p_hipDriverGetVersion)(driverVersion);
}

EXPORT int hipRuntimeGetVersion(int *runtimeVersion) {
    if (!bridge_ok() || !g->p_hipRuntimeGetVersion)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(int *))g->p_hipRuntimeGetVersion)(runtimeVersion);
}

EXPORT int hipMalloc(void **ptr, u64 size) {
    if (!bridge_ok() || !g->p_hipMalloc)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void **, u64))g->p_hipMalloc)(ptr, size);
}

EXPORT int hipFree(void *ptr) {
    if (!bridge_ok() || !g->p_hipFree)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *))g->p_hipFree)(ptr);
}

EXPORT int hipMemcpy(void *dst, const void *src, u64 sizeBytes, int kind) {
    if (!bridge_ok() || !g->p_hipMemcpy)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *, const void *, u64, int))g->p_hipMemcpy)(dst, src, sizeBytes,
                                                                                    kind);
}

EXPORT int hipMemcpyAsync(void *dst, const void *src, u64 sizeBytes, int kind, void *stream) {
    if (!bridge_ok() || !g->p_hipMemcpyAsync)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *, const void *, u64, int, void *))g->p_hipMemcpyAsync)(
        dst, src, sizeBytes, kind, stream);
}

EXPORT int hipMemcpyToSymbol(const void *symbol, const void *src, u64 sizeBytes,
                             u64 offset, int kind) {
    if (!bridge_ok() || !g->p_hipMemcpyToSymbol)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(const void *, const void *, u64, u64, int))
                g->p_hipMemcpyToSymbol)(symbol, src, sizeBytes, offset, kind);
}

EXPORT int hipMemset(void *dst, int value, u64 sizeBytes) {
    if (!bridge_ok() || !g->p_hipMemset)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *, int, u64))g->p_hipMemset)(dst, value, sizeBytes);
}

EXPORT int hipMemsetAsync(void *dst, int value, u64 sizeBytes, void *stream) {
    if (!bridge_ok() || !g->p_hipMemsetAsync)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *, int, u64, void *))g->p_hipMemsetAsync)(dst, value, sizeBytes,
                                                                                   stream);
}

EXPORT int hipLaunchKernel(const void *function_address, dim3_t numBlocks, dim3_t dimBlocks, void **args,
                           u64 sharedMemBytes, void *stream) {
    if (!bridge_ok() || !g->p_hipLaunchKernel)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(const void *, dim3_t, dim3_t, void **, u64, void *))
                g->p_hipLaunchKernel)(function_address, numBlocks, dimBlocks, args, sharedMemBytes,
                                      stream);
}

EXPORT int hipDeviceSynchronize(void) {
    if (!bridge_ok() || !g->p_hipDeviceSynchronize)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void))g->p_hipDeviceSynchronize)();
}

EXPORT int hipGetLastError(void) {
    if (!bridge_ok() || !g->p_hipGetLastError)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void))g->p_hipGetLastError)();
}

EXPORT const char *hipGetErrorString(int error) {
    if (!bridge_ok() || !g->p_hipGetErrorString)
        return "hip bridge not initialized";
    return ((const char *SYSV (*)(int))g->p_hipGetErrorString)(error);
}

EXPORT int hipEventCreate(void **event) {
    if (!bridge_ok() || !g->p_hipEventCreate)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void **))g->p_hipEventCreate)(event);
}

EXPORT int hipEventCreateWithFlags(void **event, unsigned int flags) {
    if (!bridge_ok() || !g->p_hipEventCreateWithFlags) return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void **, unsigned int))g->p_hipEventCreateWithFlags)(event, flags);
}

EXPORT int hipEventQuery(void *event) {
    if (!bridge_ok() || !g->p_hipEventQuery) return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *))g->p_hipEventQuery)(event);
}

EXPORT int hipStreamCreateWithFlags(void **stream, unsigned int flags) {
    if (!bridge_ok() || !g->p_hipStreamCreateWithFlags) return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void **, unsigned int))g->p_hipStreamCreateWithFlags)(stream, flags);
}

EXPORT int hipStreamSynchronize(void *stream) {
    if (!bridge_ok() || !g->p_hipStreamSynchronize) return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *))g->p_hipStreamSynchronize)(stream);
}

EXPORT int hipEventRecord(void *event, void *stream) {
    if (!bridge_ok() || !g->p_hipEventRecord)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *, void *))g->p_hipEventRecord)(event, stream);
}

EXPORT int hipEventSynchronize(void *event) {
    if (!bridge_ok() || !g->p_hipEventSynchronize)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(void *))g->p_hipEventSynchronize)(event);
}

EXPORT int hipEventElapsedTime(float *ms, void *start, void *stop) {
    if (!bridge_ok() || !g->p_hipEventElapsedTime)
        return HIP_ERROR_NOT_INITIALIZED;
    return ((int SYSV (*)(float *, void *, void *))g->p_hipEventElapsedTime)(ms, start, stop);
}

EXPORT int hipImportExternalMemory(void **extMem_out, const void *memHandleDesc) {
    /* Windows D3D12/NT handles cannot be imported by Linux HIP. Let the mod fall back to readback. */
    if (!bridge_ok() || !g->p_hipImportExternalMemory)
        return HIP_ERROR_INVALID_VALUE;
    return ((int SYSV (*)(void **, const void *))g->p_hipImportExternalMemory)(extMem_out, memHandleDesc);
}

EXPORT int hipExternalMemoryGetMappedBuffer(void **devPtr, void *extMem, const void *bufferDesc) {
    if (!bridge_ok() || !g->p_hipExternalMemoryGetMappedBuffer)
        return HIP_ERROR_INVALID_VALUE;
    return ((int SYSV (*)(void **, void *, const void *))g->p_hipExternalMemoryGetMappedBuffer)(
        devPtr, extMem, bufferDesc);
}

EXPORT int hipDestroyExternalMemory(void *extMem) {
    if (!bridge_ok() || !g->p_hipDestroyExternalMemory)
        return HIP_ERROR_INVALID_VALUE;
    return ((int SYSV (*)(void *))g->p_hipDestroyExternalMemory)(extMem);
}
