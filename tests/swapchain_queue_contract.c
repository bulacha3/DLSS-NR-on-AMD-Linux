/* Executes the actual vkd3d GetDevice body with COM/device mocks.
 * This checks queue identity, opt-in behavior and COM references, not a GPU.
 * The Python test extracts the body from the pinned and patched source.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int32_t HRESULT;
typedef const int *REFIID;
typedef struct mock_object { int kind; unsigned refs; HRESULT result; } ID3D12CommandQueue;
typedef struct mock_object ID3D12Device15;
static const int IID_ID3D12CommandQueue = 1, IID_ID3D12Device = 2, IID_IUnknown = 3, IID_UNKNOWN = 4;
#define S_OK ((HRESULT)0)
#define E_NOINTERFACE ((HRESULT)0x80004002)
#define E_POINTER ((HRESULT)0x80004003)
#define E_FAIL ((HRESULT)0x80004005)
#define SUCCEEDED(hr) ((hr) >= 0)
#define STDMETHODCALLTYPE
#define IsEqualGUID(a, b) (*(a) == *(b))
#define TRACE(...) ((void)0)
#define WARN(...) (++warnings)
#define vkd3d_memory_order_relaxed 0
static unsigned warnings;
static const char *compat_env;

struct d3d12_device { ID3D12Device15 ID3D12Device_iface; };
struct d3d12_command_queue {
    ID3D12CommandQueue ID3D12CommandQueue_iface;
    struct d3d12_device *device;
};
struct dxgi_vk_swap_chain { struct d3d12_command_queue *queue; };
typedef struct dxgi_vk_swap_chain IDXGIVkSwapChain2;
#define impl_from_IDXGIVkSwapChain(iface) (iface)

static inline uint32_t vkd3d_atomic_uint32_exchange_explicit(uint32_t *p, uint32_t v, int order)
{ (void)order; uint32_t old = *p; *p = v; return old; }
static inline bool vkd3d_get_env_var(const char *name, char *out, size_t size)
{
    assert(!strcmp(name, "DLSSNR_SWAPCHAIN_QUEUE"));
    if (!compat_env || strlen(compat_env) >= size) return false;
    memcpy(out, compat_env, strlen(compat_env) + 1);
    return true;
}
static HRESULT query(struct mock_object *obj, REFIID iid, void **out)
{
    if (!out) return E_POINTER;
    *out = NULL;
    if (!SUCCEEDED(obj->result)) return obj->result;
    if (*iid != obj->kind && *iid != IID_IUnknown) return E_NOINTERFACE;
    ++obj->refs;
    *out = obj;
    return S_OK;
}
#define ID3D12Device15_QueryInterface query
#define ID3D12CommandQueue_QueryInterface query
static void release(void *p)
{
    struct mock_object *obj = p;
    assert(obj && obj->refs > 1);
    --obj->refs;
}

#include "swapchain_query_body.h"

int main(int argc, char **argv)
{
    bool before = argc > 1 && !strcmp(argv[1], "before");
    struct d3d12_device dev_a = {{2, 1, S_OK}}, dev_b = {{2, 1, S_OK}};
    struct d3d12_command_queue q_a = {{1, 1, S_OK}, &dev_a};
    struct d3d12_command_queue q_b = {{1, 1, S_OK}, &dev_b};
    struct d3d12_command_queue q_same_device = {{1, 1, S_OK}, &dev_a};
    struct dxgi_vk_swap_chain chains[] = {{&q_a}, {&q_b}, {&q_same_device}};
    const char *disabled[] = {NULL, "", "0", "true", "10", "123456789"};
    void *out;

    for (unsigned i = 0; i < sizeof(disabled) / sizeof(*disabled); ++i)
    {
        compat_env = disabled[i]; out = (void *)(uintptr_t)1;
        assert(dxgi_vk_swap_chain_GetDevice(&chains[0], &IID_ID3D12CommandQueue, &out) == E_NOINTERFACE);
        assert(!out && q_a.ID3D12CommandQueue_iface.refs == 1);
    }

    compat_env = "1";
    for (unsigned frame = 0; frame < 120; ++frame)
    {
        for (unsigned i = 0; i < 3; ++i)
        {
            struct d3d12_command_queue *expected = chains[i].queue;
            HRESULT hr = dxgi_vk_swap_chain_GetDevice(&chains[i], &IID_ID3D12CommandQueue, &out);
            if (before)
            {
                assert(hr == E_NOINTERFACE && !out);
                continue;
            }
            assert(hr == S_OK && out == &expected->ID3D12CommandQueue_iface);
            assert(expected->ID3D12CommandQueue_iface.refs == 2);
            release(out);
            assert(expected->ID3D12CommandQueue_iface.refs == 1);
        }
    }

    /* Device and IUnknown queries retain device identity; unknown IIDs fail. */
    assert(dxgi_vk_swap_chain_GetDevice(&chains[0], &IID_ID3D12Device, &out) == S_OK);
    assert(out == &dev_a.ID3D12Device_iface); release(out);
    assert(dxgi_vk_swap_chain_GetDevice(&chains[0], &IID_IUnknown, &out) == S_OK);
    assert(out == &dev_a.ID3D12Device_iface); release(out);
    assert(dxgi_vk_swap_chain_GetDevice(&chains[0], &IID_UNKNOWN, &out) == E_NOINTERFACE && !out);
    assert(dxgi_vk_swap_chain_GetDevice(&chains[0], &IID_ID3D12CommandQueue, NULL) == E_POINTER);
    if (!before)
    {
        q_a.ID3D12CommandQueue_iface.result = E_FAIL;
        assert(dxgi_vk_swap_chain_GetDevice(&chains[0], &IID_ID3D12CommandQueue, &out) == E_FAIL && !out);
        assert(warnings == 1);
    }
    assert(dev_a.ID3D12Device_iface.refs == 1 && dev_b.ID3D12Device_iface.refs == 1);
    puts(before ? "before: missing queue fallback reproduced" : "after: exact queue identity and COM contract passed");
}
