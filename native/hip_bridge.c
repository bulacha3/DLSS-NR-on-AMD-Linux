#define _GNU_SOURCE
#include "hip_bridge.h"

#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>

/* Keep stubs in g_bridge forever. Real HIP lives in `real`. */
static DlssnrHipBridge g_bridge;
static DlssnrHipBridge real;
static void *g_hip;
static int g_hip_ok;
static FILE *g_log;
static int g_nr_fds[16];
static int g_nr_nfds;
static unsigned g_wait_n;
static void *g_flag_wait;
static void *g_flag_set;
static void *g_k_export;
static void *g_k_import;
static void *g_done_event;
static int (*p_hipStreamSynchronize)(void *stream);
static int (*p_hipImportExternalSemaphore)(void **out, const void *desc);
static int (*p_hipSignalExternalSemaphoresAsync)(const void *sems, const void *params, unsigned n, void *stream);
static void *g_hip_sem;
static unsigned long long g_nr_seq;
static int g_sem_ok;
static int g_job_open;
static int g_drm_fd = -1;
static unsigned int g_syncobj;
static unsigned g_pending;
static unsigned g_nlaunch_log;
static void *g_map_ptr[16];
static u64 g_map_sz[16];
static int g_nmap;
static unsigned char g_flushbuf[1 << 20];
static pthread_mutex_t g_job_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_job_cv = PTHREAD_COND_INITIALIZER;
static pthread_t g_job_tid;
static int g_job_tid_set;
static int g_job_busy;

void hip_log(const char *fmt, ...);
#define logmsg hip_log
typedef int (*wine_h2fd_t)(void *handle, unsigned int access, int *unix_fd, unsigned int *options);

void hip_log(const char *fmt, ...) {
    va_list ap;
    if (!g_log) {
        const char *path = getenv("DLSSNR_HIP_LOG");
        g_log = fopen(path && path[0] ? path : "/tmp/dlssnr-hip.log", "a");
        if (g_log)
            setvbuf(g_log, NULL, _IOLBF, 0);
    }
    if (!g_log)
        return;
    flockfile(g_log);
    fprintf(g_log, "[pid %d] ", (int)getpid());
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    funlockfile(g_log);
}

static void *must_dlsym(const char *name) {
    void *p = dlsym(g_hip, name);
    if (!p)
        logmsg("missing %s: %s", name, dlerror());
    return p;
}

/* Distro HIP often has no DT_RUNPATH. Proton then misses NEEDED libs that
 * live beside HIP or under llvm/lib and rocm_sysdeps/lib. Preload those by
 * full path at the first HIP open (Wine/Vulkan already loaded). Do not put
 * the whole ROCm lib dir on LD_LIBRARY_PATH (would shadow libstdc++). */
static int hip_system_soname(const char *name) {
    static const char *const names[] = {
        "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",
        "libgcc_s.so.1", "libstdc++.so.6", "ld-linux-x86-64.so.2", NULL,
    };
    int i;
    if (!name || !name[0])
        return 1;
    for (i = 0; names[i]; i++)
        if (!strcmp(name, names[i]))
            return 1;
    return 0;
}

static const char *elf_vma(const unsigned char *map, size_t size, uint64_t vma, size_t need) {
    const Elf64_Ehdr *eh;
    const Elf64_Phdr *ph;
    uint16_t i;
    if (size < sizeof(*eh))
        return NULL;
    eh = (const Elf64_Ehdr *)map;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) || eh->e_ident[EI_CLASS] != ELFCLASS64 ||
        eh->e_ident[EI_DATA] != ELFDATA2LSB || eh->e_machine != EM_X86_64)
        return NULL;
    if (!eh->e_phnum || eh->e_phentsize != sizeof(*ph) || eh->e_phoff > size ||
        eh->e_phoff + (size_t)eh->e_phnum * sizeof(*ph) > size)
        return NULL;
    ph = (const Elf64_Phdr *)(map + eh->e_phoff);
    for (i = 0; i < eh->e_phnum; i++) {
        uint64_t start, end, off;
        if (ph[i].p_type != PT_LOAD || ph[i].p_filesz < need)
            continue;
        start = ph[i].p_vaddr;
        end = start + ph[i].p_filesz;
        if (vma < start || vma + need > end)
            continue;
        off = ph[i].p_offset + (vma - start);
        if (off > size || off + need > size)
            return NULL;
        return (const char *)map + off;
    }
    return NULL;
}

static int elf_needed(const char *path, char out[][128], int maxn) {
    struct stat st;
    const unsigned char *map;
    const Elf64_Ehdr *eh;
    const Elf64_Phdr *ph;
    const Elf64_Dyn *dyn = NULL;
    const char *strtab = NULL;
    size_t dyn_bytes = 0, strsz = 0;
    uint64_t str_vma = 0;
    int fd, n = 0, i, seen_str = 0;
    if (!path || path[0] != '/' || maxn <= 0)
        return 0;
    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return 0;
    if (fstat(fd, &st) || st.st_size < (off_t)sizeof(Elf64_Ehdr) || st.st_size > 128 * 1024 * 1024) {
        close(fd);
        return 0;
    }
    map = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (map == MAP_FAILED)
        return 0;
    eh = (const Elf64_Ehdr *)map;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) || eh->e_ident[EI_CLASS] != ELFCLASS64 ||
        eh->e_ident[EI_DATA] != ELFDATA2LSB || eh->e_phentsize != sizeof(*ph) ||
        eh->e_phoff > (size_t)st.st_size ||
        eh->e_phoff + (size_t)eh->e_phnum * sizeof(*ph) > (size_t)st.st_size) {
        munmap((void *)map, (size_t)st.st_size);
        return 0;
    }
    ph = (const Elf64_Phdr *)(map + eh->e_phoff);
    for (i = 0; i < eh->e_phnum; i++) {
        if (ph[i].p_type != PT_DYNAMIC)
            continue;
        if (ph[i].p_offset > (size_t)st.st_size || ph[i].p_filesz < sizeof(*dyn) ||
            ph[i].p_offset + ph[i].p_filesz > (size_t)st.st_size)
            break;
        dyn = (const Elf64_Dyn *)(map + ph[i].p_offset);
        dyn_bytes = ph[i].p_filesz;
        break;
    }
    if (dyn) {
        size_t ndyn = dyn_bytes / sizeof(*dyn), k;
        for (k = 0; k < ndyn && dyn[k].d_tag != DT_NULL; k++) {
            if (dyn[k].d_tag == DT_STRTAB)
                str_vma = dyn[k].d_un.d_ptr;
            else if (dyn[k].d_tag == DT_STRSZ) {
                strsz = dyn[k].d_un.d_val;
                seen_str = 1;
            }
        }
        if (seen_str && strsz && strsz < 1024 * 1024)
            strtab = elf_vma(map, (size_t)st.st_size, str_vma, strsz);
        if (strtab) {
            for (k = 0; k < ndyn && dyn[k].d_tag != DT_NULL && n < maxn; k++) {
                size_t off;
                const char *name;
                if (dyn[k].d_tag != DT_NEEDED)
                    continue;
                off = dyn[k].d_un.d_val;
                if (off >= strsz)
                    continue;
                name = strtab + off;
                if (!name[0] || strlen(name) >= 128)
                    continue;
                memcpy(out[n], name, strlen(name) + 1);
                n++;
            }
        }
    }
    munmap((void *)map, (size_t)st.st_size);
    return n;
}

static int hip_find_soname(const char *hip_path, const char *soname, char *out, size_t outsz) {
    const char *slash;
    char origin[512];
    size_t olen;
    const char *suffix[] = {"", "/llvm/lib", "/rocm_sysdeps/lib", NULL};
    int i;
    if (!hip_path || hip_path[0] != '/' || !soname || soname[0] == '/' || strchr(soname, '/'))
        return -1;
    slash = strrchr(hip_path, '/');
    if (!slash || slash == hip_path)
        return -1;
    olen = (size_t)(slash - hip_path);
    if (olen >= sizeof(origin))
        return -1;
    memcpy(origin, hip_path, olen);
    origin[olen] = '\0';
    for (i = 0; suffix[i]; i++) {
        char path[768];
        struct stat st;
        if (snprintf(path, sizeof(path), "%s%s/%s", origin, suffix[i], soname) >= (int)sizeof(path))
            continue;
        if (!stat(path, &st) && S_ISREG(st.st_mode)) {
            if (strlen(path) >= outsz)
                return -1;
            memcpy(out, path, strlen(path) + 1);
            return 0;
        }
    }
    return -1;
}

static void hip_preload_deps(const char *hip_path, const char *path,
        char seen[][128], int *ns) {
    char needed[24][128];
    int nn = elf_needed(path, needed, 24), i;
    for (i = 0; i < nn; i++) {
        char found[768];
        int s;
        void *h;
        if (hip_system_soname(needed[i]))
            continue;
        for (s = 0; s < *ns; s++)
            if (!strcmp(seen[s], needed[i]))
                break;
        if (s < *ns)
            continue;
        if (*ns >= 48) {
            logmsg("HIP dependency limit reached at %s", needed[i]);
            return;
        }
        /* Mark before descending to bound cycles and shared subgraphs. */
        memcpy(seen[*ns], needed[i], strlen(needed[i]) + 1);
        (*ns)++;
        h = dlopen(needed[i], RTLD_NOW | RTLD_GLOBAL | RTLD_NOLOAD);
        if (h) {
            dlclose(h); /* Balance the NOLOAD reference, not its original owner. */
            continue;
        }
        if (hip_find_soname(hip_path, needed[i], found, sizeof(found))) {
            logmsg("HIP NEEDED %s not in HIP origin/llvm/rocm_sysdeps", needed[i]);
            continue;
        }
        /* Inspect even an unloadable parent: e.g. rocprofiler needs fmt first. */
        hip_preload_deps(hip_path, found, seen, ns);
        h = dlopen(found, RTLD_NOW | RTLD_GLOBAL);
        if (!h) {
            logmsg("dlopen HIP dep %s failed: %s", found, dlerror());
            continue;
        }
        logmsg("preloaded HIP dep %s", found);
    }
}

static void hip_preload_needed(const char *hip_path) {
    char seen[48][128];
    int ns = 0;
    if (!hip_path || hip_path[0] != '/' || strlen(hip_path) >= 768)
        return;
    hip_preload_deps(hip_path, hip_path, seen, &ns);
}

static int ensure_hip(void) {
    if (g_hip_ok)
        return 0;
    if (g_hip)
        return -1;
    const char *candidates[] = {
        "/opt/rocm/lib/libamdhip64.so.7",
        "libamdhip64.so.7",
        "libamdhip64.so",
        NULL,
    };
    const char *selected = getenv("DLSSNR_HIP_LIBRARY");
    if (selected && selected[0]) {
        /* A validated installer selection is authoritative. Never fall back
         * to an unrelated system runtime when an explicit wheel moved. */
        hip_preload_needed(selected);
        g_hip = dlopen(selected, RTLD_NOW | RTLD_GLOBAL);
        if (!g_hip) {
            logmsg("dlopen selected HIP %s failed: %s", selected, dlerror());
            return -1;
        }
        logmsg("dlopen selected HIP %s", selected);
    } else {
        for (int i = 0; candidates[i]; i++) {
            hip_preload_needed(candidates[i]);
            g_hip = dlopen(candidates[i], RTLD_NOW | RTLD_GLOBAL);
            if (g_hip) {
                logmsg("dlopen %s", candidates[i]);
                break;
            }
        }
    }
    if (!g_hip) {
        logmsg("dlopen libamdhip64 failed: %s", dlerror());
        return -1;
    }
    real.p___hipRegisterFatBinary = must_dlsym("__hipRegisterFatBinary");
    real.p___hipUnregisterFatBinary = must_dlsym("__hipUnregisterFatBinary");
    real.p___hipRegisterFunction = must_dlsym("__hipRegisterFunction");
    real.p___hipRegisterVar = must_dlsym("__hipRegisterVar");
    real.p___hipPushCallConfiguration = must_dlsym("__hipPushCallConfiguration");
    real.p___hipPopCallConfiguration = must_dlsym("__hipPopCallConfiguration");
    real.p_hipGetDeviceCount = must_dlsym("hipGetDeviceCount");
    real.p_hipSetDevice = must_dlsym("hipSetDevice");
    real.p_hipGetDevicePropertiesR0600 = must_dlsym("hipGetDevicePropertiesR0600");
    real.p_hipDriverGetVersion = must_dlsym("hipDriverGetVersion");
    real.p_hipRuntimeGetVersion = must_dlsym("hipRuntimeGetVersion");
    real.p_hipMalloc = must_dlsym("hipMalloc");
    real.p_hipFree = must_dlsym("hipFree");
    real.p_hipMemcpy = must_dlsym("hipMemcpy");
    real.p_hipMemcpyAsync = must_dlsym("hipMemcpyAsync");
    real.p_hipMemcpyToSymbol = must_dlsym("hipMemcpyToSymbol");
    real.p_hipMemset = must_dlsym("hipMemset");
    real.p_hipMemsetAsync = must_dlsym("hipMemsetAsync");
    real.p_hipLaunchKernel = must_dlsym("hipLaunchKernel");
    real.p_hipDeviceSynchronize = must_dlsym("hipDeviceSynchronize");
    real.p_hipGetLastError = must_dlsym("hipGetLastError");
    real.p_hipGetErrorString = must_dlsym("hipGetErrorString");
    real.p_hipEventCreate = must_dlsym("hipEventCreate");
    real.p_hipEventCreateWithFlags = must_dlsym("hipEventCreateWithFlags");
    real.p_hipEventQuery = must_dlsym("hipEventQuery");
    real.p_hipStreamCreateWithFlags = must_dlsym("hipStreamCreateWithFlags");
    real.p_hipStreamSynchronize = must_dlsym("hipStreamSynchronize");
    real.p_hipEventRecord = must_dlsym("hipEventRecord");
    real.p_hipEventSynchronize = must_dlsym("hipEventSynchronize");
    real.p_hipEventElapsedTime = must_dlsym("hipEventElapsedTime");
    real.p_hipImportExternalMemory = must_dlsym("hipImportExternalMemory");
    real.p_hipExternalMemoryGetMappedBuffer = must_dlsym("hipExternalMemoryGetMappedBuffer");
    real.p_hipDestroyExternalMemory = must_dlsym("hipDestroyExternalMemory");
    p_hipStreamSynchronize = (int (*)(void *))must_dlsym("hipStreamSynchronize");
    p_hipImportExternalSemaphore = (int (*)(void **, const void *))must_dlsym("hipImportExternalSemaphore");
    p_hipSignalExternalSemaphoresAsync =
        (int (*)(const void *, const void *, unsigned, void *))must_dlsym("hipSignalExternalSemaphoresAsync");
    g_hip_ok = 1;
    if (real.p_hipEventCreate)
        real.p_hipEventCreate(&g_done_event);
    return 0;
}

/* MSVC/GCC layout of hipExternalMemoryHandleDesc (104 bytes). */
struct pe_extmem_desc {
    unsigned int type;
    unsigned int pad;
    union {
        int fd;
        struct {
            void *handle;
            const void *name;
        } win32;
    } handle;
    unsigned long long size;
    unsigned int flags;
    unsigned int reserved[16];
};

enum {
    HIP_MEM_OPAQUE_FD = 1,
    HIP_MEM_OPAQUE_WIN32 = 2,
    HIP_MEM_OPAQUE_WIN32_KMT = 3,
    HIP_MEM_D3D12_HEAP = 4,
    HIP_MEM_D3D12_RESOURCE = 5,
};

#define GENERIC_READ 0x80000000u
#define GENERIC_WRITE 0x40000000u
#define GENERIC_ALL 0x10000000u

static wine_h2fd_t resolve_h2fd(void) {
    static wine_h2fd_t fn;
    void *h;
    if (fn)
        return fn;
    fn = (wine_h2fd_t)dlsym(RTLD_DEFAULT, "wine_server_handle_to_fd");
    if (fn)
        return fn;
    h = dlopen("ntdll.so", RTLD_NOW | RTLD_NOLOAD | RTLD_GLOBAL);
    if (!h)
        h = dlopen("ntdll.so", RTLD_NOW | RTLD_GLOBAL);
    if (h)
        fn = (wine_h2fd_t)dlsym(h, "wine_server_handle_to_fd");
    logmsg("resolve h2fd=%p ntdll=%p", (void *)fn, h);
    return fn;
}

/* Local (non-dynsym) Wine unix helpers live in win32u.so. */
typedef unsigned int d3dkmt_handle_t;
typedef d3dkmt_handle_t (*d3dkmt_open_resource_t)(d3dkmt_handle_t global, void *shared,
                                                  d3dkmt_handle_t *mutex_local, d3dkmt_handle_t *sync_local);
typedef int (*d3dkmt_object_get_fd_t)(d3dkmt_handle_t local);
typedef int (*d3dkmt_destroy_resource_t)(d3dkmt_handle_t local);
typedef d3dkmt_handle_t (*d3dkmt_open_sync_t)(d3dkmt_handle_t device, void *nt);
typedef int (*d3dkmt_destroy_sync_t)(d3dkmt_handle_t local);

static void *elf_local_sym(void *handle, const char *name) {
    struct link_map *lm = NULL;
    struct stat st;
    const ElfW(Ehdr) *eh;
    const ElfW(Shdr) *sh, *symtab = NULL, *strtab = NULL;
    const ElfW(Sym) *sym;
    const char *strs;
    void *map;
    void *found = NULL;
    int fd, i, n;

    if (!handle || !name)
        return NULL;
    if (dlinfo(handle, RTLD_DI_LINKMAP, &lm) != 0 || !lm || !lm->l_name || !lm->l_name[0])
        return NULL;
    fd = open(lm->l_name, O_RDONLY);
    if (fd < 0)
        return NULL;
    if (fstat(fd, &st) != 0 || st.st_size < (off_t)sizeof(ElfW(Ehdr))) {
        close(fd);
        return NULL;
    }
    map = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (map == MAP_FAILED)
        return NULL;
    eh = (const ElfW(Ehdr) *)map;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) != 0)
        goto out;
    sh = (const ElfW(Shdr) *)((const char *)map + eh->e_shoff);
    for (i = 0; i < eh->e_shnum; i++) {
        if (sh[i].sh_type == SHT_SYMTAB) {
            symtab = &sh[i];
            if (sh[i].sh_link < eh->e_shnum)
                strtab = &sh[sh[i].sh_link];
            break;
        }
    }
    if (!symtab || !strtab || !symtab->sh_entsize)
        goto out;
    strs = (const char *)map + strtab->sh_offset;
    sym = (const ElfW(Sym) *)((const char *)map + symtab->sh_offset);
    n = (int)(symtab->sh_size / symtab->sh_entsize);
    for (i = 0; i < n; i++) {
        if (!sym[i].st_name || ELF64_ST_TYPE(sym[i].st_info) != STT_FUNC)
            continue;
        if (strcmp(strs + sym[i].st_name, name) == 0) {
            found = (char *)lm->l_addr + sym[i].st_value;
            break;
        }
    }
out:
    munmap(map, (size_t)st.st_size);
    return found;
}

static int d3dkmt_handle_to_fd(void *nt_handle) {
    static int resolved;
    static d3dkmt_open_resource_t open_res;
    static d3dkmt_object_get_fd_t get_fd;
    static d3dkmt_destroy_resource_t destroy_res;
    d3dkmt_handle_t local, mutex = 0, sync = 0;
    int fd;
    void *h;

    if (!resolved) {
        resolved = 1;
        h = dlopen("win32u.so", RTLD_NOW | RTLD_NOLOAD);
        if (!h)
            h = dlopen("win32u.so", RTLD_NOW);
        open_res = (d3dkmt_open_resource_t)elf_local_sym(h, "d3dkmt_open_resource");
        get_fd = (d3dkmt_object_get_fd_t)elf_local_sym(h, "d3dkmt_object_get_fd");
        destroy_res = (d3dkmt_destroy_resource_t)elf_local_sym(h, "d3dkmt_destroy_resource");
        logmsg("d3dkmt win32u=%p open=%p get_fd=%p destroy=%p", h, (void *)open_res, (void *)get_fd,
               (void *)destroy_res);
    }
    if (!open_res || !get_fd)
        return -1;
    local = open_res(0, nt_handle, &mutex, &sync);
    if (!local) {
        logmsg("d3dkmt_open_resource failed handle=%p", nt_handle);
        return -1;
    }
    fd = get_fd(local);
    logmsg("d3dkmt open local=%u mutex=%u sync=%u fd=%d", local, mutex, sync, fd);
    if (destroy_res)
        destroy_res(local);
    return fd;
}

static int import_from_fd(void **out, const struct pe_extmem_desc *in, int unix_fd, const char *via) {
    struct pe_extmem_desc fd_desc;
    int err;

    logmsg("%s fd=%d — OpaqueFd size=%llu", via, unix_fd, (unsigned long long)in->size);
    memset(&fd_desc, 0, sizeof(fd_desc));
    fd_desc.type = HIP_MEM_OPAQUE_FD;
    fd_desc.handle.fd = dup(unix_fd);
    close(unix_fd);
    if (fd_desc.handle.fd < 0)
        return 2;
    fd_desc.size = in->size;
    fd_desc.flags = in->flags;
    if (g_nr_nfds < 16) {
        int keep = dup(fd_desc.handle.fd);
        if (keep >= 0)
            g_nr_fds[g_nr_nfds++] = keep;
    }
    err = real.p_hipImportExternalMemory(out, &fd_desc);
    if (err != 0) {
        const char *s = real.p_hipGetErrorString ? real.p_hipGetErrorString(err) : "?";
        logmsg("OpaqueFd import err=%d %s (fd=%d)", err, s, fd_desc.handle.fd);
        close(fd_desc.handle.fd);
    } else {
        logmsg("OpaqueFd import OK extMem=%p", *out);
    }
    return err;
}

static int import_native(void **out, const struct pe_extmem_desc *in) {
    wine_h2fd_t h2fd;
    int unix_fd = -1;
    unsigned int options = 0;
    int status;
    const unsigned char *raw;
    void *handle;
    char hex[160];
    unsigned i, n;

    if (!in || !out)
        return 1;
    raw = (const unsigned char *)in;
    n = 0;
    for (i = 0; i < 48 && n + 3 < sizeof(hex); i++)
        n += (unsigned)snprintf(hex + n, sizeof(hex) - n, "%02x", raw[i]);
    logmsg("import raw48 %s", hex);
    logmsg("import type=%u handle=%p name=%p size=%llu flags=%u", in->type, in->handle.win32.handle,
           in->handle.win32.name, (unsigned long long)in->size, in->flags);

    if (in->type == HIP_MEM_OPAQUE_FD)
        return real.p_hipImportExternalMemory(out, in);

    /* Padded layout (handle at +8). If nil, try packed (handle at +4 as 64-bit). */
    handle = in->handle.win32.handle;
    if (!handle) {
        memcpy(&handle, raw + 4, sizeof(handle));
        logmsg("packed handle try %p", handle);
    }
    if (!handle) {
        logmsg("cannot convert handle — falling back");
        return real.p_hipImportExternalMemory(out, in);
    }

    h2fd = resolve_h2fd();
    if (h2fd) {
        status = h2fd(handle, GENERIC_READ | GENERIC_WRITE, &unix_fd, &options);
        if (status != 0 || unix_fd < 0)
            status = h2fd(handle, GENERIC_ALL, &unix_fd, &options);
        if (status != 0 || unix_fd < 0)
            status = h2fd(handle, GENERIC_READ, &unix_fd, &options);
        if (status != 0 || unix_fd < 0)
            logmsg("handle_to_fd failed status=%d fd=%d — trying d3dkmt", status, unix_fd);
    }
    if (unix_fd < 0)
        unix_fd = d3dkmt_handle_to_fd(handle);
    if (unix_fd < 0) {
        logmsg("no dma-buf fd for handle=%p — falling back", handle);
        return real.p_hipImportExternalMemory(out, in);
    }
    return import_from_fd(out, in, unix_fd, "nt-handle");
}

/* Wine fence fd is a DRM syncobj, not a HIP timeline. Signal it ourselves. */
static void *stub_reg_fat(void *data) {
    logmsg("__hipRegisterFatBinary");
    if (ensure_hip() || !real.p___hipRegisterFatBinary)
        return 0;
    return real.p___hipRegisterFatBinary(data);
}

static void stub_unreg_fat(void **m) {
    if (ensure_hip() || !real.p___hipUnregisterFatBinary)
        return;
    real.p___hipUnregisterFatBinary(m);
}
static void stub_reg_fn(void **mo, const void *hf, char *df, const char *dn, unsigned int tl, void *tid,
                        void *bid, void *bd, void *gd, int *ws) {
    if (ensure_hip() || !real.p___hipRegisterFunction)
        return;
    real.p___hipRegisterFunction(mo, hf, df, dn, tl, tid, bid, bd, gd, ws);
    if (dn && hf) {
        if (strstr(dn, "k_flag_wait")) {
            g_flag_wait = (void *)hf;
            logmsg("kernel %s hf=%p", dn, hf);
        } else if (strstr(dn, "k_flag_set")) {
            g_flag_set = (void *)hf;
            logmsg("kernel %s hf=%p", dn, hf);
        } else if (strstr(dn, "k_export")) {
            g_k_export = (void *)hf;
            logmsg("kernel %s hf=%p", dn, hf);
        } else if (strstr(dn, "k_import")) {
            g_k_import = (void *)hf;
            logmsg("kernel %s hf=%p", dn, hf);
        }
    }
}
static void stub_reg_var(void **mo, void *var, char *hv, char *dv, int ext, u64 sz, int cnst,
                         int glob) {
    if (ensure_hip() || !real.p___hipRegisterVar)
        return;
    real.p___hipRegisterVar(mo, var, hv, dv, ext, sz, cnst, glob);
}
static int stub_push(dim3_t g, dim3_t b, u64 sh, void *st) {
    if (ensure_hip() || !real.p___hipPushCallConfiguration)
        return 3;
    return real.p___hipPushCallConfiguration(g, b, sh, st);
}
static int stub_pop(dim3_t *g, dim3_t *b, u64 *sh, void **st) {
    if (ensure_hip() || !real.p___hipPopCallConfiguration)
        return 3;
    return real.p___hipPopCallConfiguration(g, b, sh, st);
}
static int stub_devcount(int *c) {
    if (ensure_hip() || !real.p_hipGetDeviceCount)
        return 3;
    int e = real.p_hipGetDeviceCount(c);
    logmsg("hipGetDeviceCount err=%d count=%d", e, c ? *c : -1);
    return e;
}
static int stub_setdev(int d) {
    if (ensure_hip() || !real.p_hipSetDevice)
        return 3;
    logmsg("hipSetDevice %d", d);
    return real.p_hipSetDevice(d);
}
static int stub_props(void *p, int id) {
    if (ensure_hip() || !real.p_hipGetDevicePropertiesR0600)
        return 3;
    return real.p_hipGetDevicePropertiesR0600(p, id);
}
static int stub_drvver(int *v) {
    if (ensure_hip() || !real.p_hipDriverGetVersion)
        return 3;
    return real.p_hipDriverGetVersion(v);
}
static int stub_rtver(int *v) {
    if (ensure_hip() || !real.p_hipRuntimeGetVersion)
        return 3;
    return real.p_hipRuntimeGetVersion(v);
}
static int stub_malloc(void **p, u64 n) {
    if (ensure_hip() || !real.p_hipMalloc)
        return 3;
    return real.p_hipMalloc(p, n);
}
static int stub_free(void *p) {
    if (ensure_hip() || !real.p_hipFree)
        return 3;
    return real.p_hipFree(p);
}
static int stub_memcpy(void *d, const void *s, u64 n, int k) {
    if (ensure_hip() || !real.p_hipMemcpy)
        return 3;
    return real.p_hipMemcpy(d, s, n, k);
}
static int stub_memcpy_async(void *d, const void *s, u64 n, int k, void *st) {
    if (ensure_hip() || !real.p_hipMemcpyAsync)
        return 3;
    return real.p_hipMemcpyAsync(d, s, n, k, st);
}
static int stub_memcpy_sym(const void *sym, const void *s, u64 n, u64 off, int k) {
    if (ensure_hip() || !real.p_hipMemcpyToSymbol)
        return 3;
    return real.p_hipMemcpyToSymbol(sym, s, n, off, k);
}
static int stub_memset(void *d, int v, u64 n) {
    if (ensure_hip() || !real.p_hipMemset)
        return 3;
    return real.p_hipMemset(d, v, n);
}
static int stub_memset_async(void *d, int v, u64 n, void *st) {
    if (ensure_hip() || !real.p_hipMemsetAsync)
        return 3;
    return real.p_hipMemsetAsync(d, v, n, st);
}

/* Wait for NR kernels that already launched. k_flag_wait is FIRST (empty
 * queue) — never sync there. hipEventSynchronize on the last recorded event
 * plus a D2H of the output mapping waits for compute writing that dma-buf. */
#include "nr_ordered.c"

static int stub_launch(const void *f, dim3_t nb, dim3_t db, void **a, u64 sh, void *st) {
    int e;
    if (ensure_hip() || !real.p_hipLaunchKernel)
        return 3;
    if (nr_try_startup_probe(f, nb, db, a, sh, st, &e))
        return e;
    /* Do not launch HIP k_flag_wait first on the null stream: it would spin
     * before NR kernels and deadlock. Do not DeviceSynchronize here either
     * (queue still empty → 0 ms, then kernels run after residual). */
    if (g_flag_wait && f == g_flag_wait)
        return nr_begin_job(a, st);
    if (nr_job.error)
        return nr_job.error;
    if (g_k_import && f == g_k_import && !nr_job.active)
        return 3;
    if (nr_job.active && (st != nr_job.stream || nr_job.sealed))
        return nr_job_error(1);
    if (g_flag_set && f == g_flag_set) {
        e = nr_seal_job(a, st);
        if (e) return e;
        /* Preserve v0.3.0's completion/abort stores on the original stream.
         * Complete here, on the owning thread, before upstream can poll its
         * event elsewhere. This first port deliberately serializes jobs. */
        e = real.p_hipLaunchKernel(f, nb, db, a, sh, st);
        if (e) return nr_job_error(e);
        if (!real.p_hipStreamSynchronize) return nr_job_error(3);
        return nr_complete_job(real.p_hipStreamSynchronize(st));
    }
    if (g_nlaunch_log < 24) {
        g_nlaunch_log++;
        logmsg("launch #%u f=%p grid=%u,%u,%u block=%u,%u,%u st=%p set=%d exp=%d", g_nlaunch_log, f, nb.x,
               nb.y, nb.z, db.x, db.y, db.z, st, f == g_flag_set, f == g_k_export);
    }
    e = real.p_hipLaunchKernel(f, nb, db, a, sh, st);
    if (e && nr_job.active)
        return nr_job_error(e);
    return e;
}
static int stub_sync(void) {
    if (ensure_hip() || !real.p_hipDeviceSynchronize)
        return 3;
    /* Preserve the original HIP worker's synchronization. Completion is
     * published only after its explicit final marker and successful sync. */
    return nr_complete_job(real.p_hipDeviceSynchronize());
}
static int stub_lasterr(void) {
    if (ensure_hip() || !real.p_hipGetLastError)
        return 3;
    return real.p_hipGetLastError();
}
static const char *stub_errstr(int e) {
    if (ensure_hip() || !real.p_hipGetErrorString)
        return "hip bridge not ready";
    return real.p_hipGetErrorString(e);
}
static int stub_evcreate(void **e) {
    if (ensure_hip() || !real.p_hipEventCreate)
        return 3;
    return real.p_hipEventCreate(e);
}
static int stub_evcreate_flags(void **event, unsigned int flags) {
    if (ensure_hip() || !real.p_hipEventCreateWithFlags) return 3;
    return real.p_hipEventCreateWithFlags(event, flags);
}
static int stub_evquery(void *event) {
    if (ensure_hip() || !real.p_hipEventQuery) return 3;
    return real.p_hipEventQuery(event);
}
static int stub_streamcreate_flags(void **stream, unsigned int flags) {
    if (ensure_hip() || !real.p_hipStreamCreateWithFlags) return 3;
    return real.p_hipStreamCreateWithFlags(stream, flags);
}
static int stub_streamsync(void *stream) {
    if (ensure_hip() || !real.p_hipStreamSynchronize) return 3;
    int result = real.p_hipStreamSynchronize(stream);
    return nr_job.active && nr_job.stream == stream ? nr_complete_job(result) : result;
}
static int stub_evrec(void *e, void *st) {
    if (ensure_hip() || !real.p_hipEventRecord)
        return 3;
    return real.p_hipEventRecord(e, st);
}
static int stub_evsync(void *e) {
    if (ensure_hip() || !real.p_hipEventSynchronize)
        return 3;
    return real.p_hipEventSynchronize(e);
}
static int stub_evelapsed(float *ms, void *a, void *b) {
    if (ensure_hip() || !real.p_hipEventElapsedTime)
        return 3;
    return real.p_hipEventElapsedTime(ms, a, b);
}
static int stub_import(void **o, const void *d) {
    if (ensure_hip() || !real.p_hipImportExternalMemory)
        return 1;
    if (!o || !d)
        return 1;
    const struct pe_extmem_desc *desc = d;
    int rc = import_native(o, desc);
    if (!rc)
        nr_associate_import(desc->type == HIP_MEM_OPAQUE_FD ? (uint64_t)desc->handle.fd :
                (uint64_t)(uintptr_t)desc->handle.win32.handle, *o);
    return rc;
}
static int stub_mapbuf(void **p, void *m, const void *d) {
    int err;
    if (ensure_hip() || !real.p_hipExternalMemoryGetMappedBuffer)
        return 1;
    err = real.p_hipExternalMemoryGetMappedBuffer(p, m, d);
    if (!err && p && *p && d) {
        const uint64_t *desc = d;
        nr_associate_mapping(m, *p, desc[0], desc[1]);
    }
    if (!err && p && *p && g_nmap < 16) {
        const unsigned long long *desc = (const unsigned long long *)d;
        g_map_ptr[g_nmap] = *p;
        /* hipExternalMemoryBufferDesc: offset, size, flags */
        g_map_sz[g_nmap] = desc ? (u64)desc[1] : 0;
        g_nmap++;
    }
    return err;
}
static int stub_desext(void *m) {
    if (ensure_hip() || !real.p_hipDestroyExternalMemory)
        return 1;
    return real.p_hipDestroyExternalMemory(m);
}

__attribute__((constructor)) static void dlssnr_hip_init(void) {
    memset(&g_bridge, 0, sizeof(g_bridge));
    memset(&real, 0, sizeof(real));
    g_bridge.magic = DLSSNR_HIP_MAGIC;
    g_bridge.p___hipRegisterFatBinary = stub_reg_fat;
    g_bridge.p___hipUnregisterFatBinary = stub_unreg_fat;
    g_bridge.p___hipRegisterFunction = stub_reg_fn;
    g_bridge.p___hipRegisterVar = stub_reg_var;
    g_bridge.p___hipPushCallConfiguration = stub_push;
    g_bridge.p___hipPopCallConfiguration = stub_pop;
    g_bridge.p_hipGetDeviceCount = stub_devcount;
    g_bridge.p_hipSetDevice = stub_setdev;
    g_bridge.p_hipGetDevicePropertiesR0600 = stub_props;
    g_bridge.p_hipDriverGetVersion = stub_drvver;
    g_bridge.p_hipRuntimeGetVersion = stub_rtver;
    g_bridge.p_hipMalloc = stub_malloc;
    g_bridge.p_hipFree = stub_free;
    g_bridge.p_hipMemcpy = stub_memcpy;
    g_bridge.p_hipMemcpyAsync = stub_memcpy_async;
    g_bridge.p_hipMemcpyToSymbol = stub_memcpy_sym;
    g_bridge.p_hipMemset = stub_memset;
    g_bridge.p_hipMemsetAsync = stub_memset_async;
    g_bridge.p_hipLaunchKernel = stub_launch;
    g_bridge.p_hipDeviceSynchronize = stub_sync;
    g_bridge.p_hipGetLastError = stub_lasterr;
    g_bridge.p_hipGetErrorString = stub_errstr;
    g_bridge.p_hipEventCreate = stub_evcreate;
    g_bridge.p_hipEventCreateWithFlags = stub_evcreate_flags;
    g_bridge.p_hipEventQuery = stub_evquery;
    g_bridge.p_hipStreamCreateWithFlags = stub_streamcreate_flags;
    g_bridge.p_hipStreamSynchronize = stub_streamsync;
    g_bridge.p_hipEventRecord = stub_evrec;
    g_bridge.p_hipEventSynchronize = stub_evsync;
    g_bridge.p_hipEventElapsedTime = stub_evelapsed;
    g_bridge.p_hipImportExternalMemory = stub_import;
    g_bridge.p_hipExternalMemoryGetMappedBuffer = stub_mapbuf;
    g_bridge.p_hipDestroyExternalMemory = stub_desext;

    char buf[32];
    snprintf(buf, sizeof(buf), "%p", (void *)&g_bridge);
    setenv(DLSSNR_HIP_ENV, buf, 1);
    snprintf(buf, sizeof(buf), "%p", (void *)&nr_api);
    setenv(NR_ORDERED_ENV, buf, 1);
    logmsg("preload lazy table=%s (HIP not opened yet)", buf);
}
