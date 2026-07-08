/*
 * nvenc_fix.c - LD_PRELOAD interposer to fix NVENC in multi-GPU containers
 *   Vendored from flexgrip/nvidia-gpu-enumeration (https://github.com/flexgrip/nvidia-gpu-enumeration)
 *   to avoid a build-time network fetch of a low-traffic repo. Pinned at the
 *   initial 2026-05-07 release. Upgrades: re-vendor from upstream.
 *
 * Problem: On NVIDIA driver >= 570, when NVENC initializes inside a container
 * that has only a subset of the host's GPUs assigned (e.g. 1 GPU on a 4-GPU
 * Vast host), libnvidia-encode queries /dev/nvidiactl for ALL host GPUs
 * (NV0000_CTRL_CMD_GPU_GET_ATTACHED_IDS, cmd 0x2A). When it sees multiple GPUs,
 * it tries to peer-init with the others, fails because their /dev/nvidiaX nodes
 * aren't mounted, and returns NV_ENC_ERR_UNSUPPORTED_DEVICE — even though the
 * one GPU we DO have is perfectly fine. (nvidia-container-toolkit #1249.)
 *
 * Fix: Intercept ioctl(), let it pass through to the real kernel driver, then
 * post-process the GET_ATTACHED_IDS response to only keep GPUs whose
 * /dev/nvidiaX device nodes actually exist in this container. NVENC then sees a
 * single-GPU system, takes the single-GPU init path, and works.
 *
 * Build:
 *   gcc -shared -fPIC -O2 -o libnvenc_fix.so nvenc_fix.c -ldl
 *
 * Usage (DpadCloud gates this behind DPAD_NVENC_FIX=1; auto-enabled by the
 * entrypoint when host GPU count > mounted GPU count on driver 570..609):
 *   LD_PRELOAD=/opt/dpadcloud/libnvenc_fix.so
 *
 * Logging (NVENC_FIX_DEBUG environment variable):
 *   unset or empty                      -> no logging (production default)
 *   NVENC_FIX_DEBUG=1                   -> log to stderr
 *   NVENC_FIX_DEBUG=stderr              -> log to stderr
 *   NVENC_FIX_DEBUG=/tmp/nvenc_fix.log  -> log to file (appended)
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <errno.h>
#include <dirent.h>

/* ============================================================
 * NVIDIA RM ioctl structures (from open-gpu-kernel-modules)
 * ============================================================ */

typedef uint32_t NvV32;
typedef uint32_t NvU32;
typedef NvU32    NvHandle;
typedef void*    NvP64;

#define NV_ALIGN_BYTES(size) __attribute__((aligned(size)))

#define NV_IOCTL_MAGIC 'F'
#define NV_ESC_RM_CONTROL 0x2A

typedef struct {
    NvHandle hClient;
    NvHandle hObject;
    NvV32    cmd;
    NvU32    flags;
    NvP64    params NV_ALIGN_BYTES(8);
    NvU32    paramsSize;
    NvV32    status;
} NVOS54_PARAMETERS;

#define NV0000_CTRL_CMD_GPU_GET_ATTACHED_IDS 0x0201
#define NV0000_CTRL_GPU_MAX_ATTACHED_GPUS    32
#define NV0000_CTRL_GPU_INVALID_ID           0xFFFFFFFF

typedef struct {
    NvU32 gpuIds[NV0000_CTRL_GPU_MAX_ATTACHED_GPUS];
} NV0000_CTRL_GPU_GET_ATTACHED_IDS_PARAMS;

#define NV0000_CTRL_CMD_GPU_GET_ID_INFO 0x0202

typedef struct {
    NvU32 gpuId;
    NvU32 gpuFlags;
    NvU32 deviceInstance;
    NvU32 subDeviceInstance;
    NvU32 boardId;
    NvU32 szName;
    NvU32 sliStatus;
    NvU32 numaId;
} NV0000_CTRL_GPU_GET_ID_INFO_PARAMS;

/* ============================================================
 * Logging
 * ============================================================ */

static int   log_initialized = 0;
static int   log_enabled     = 0;
static FILE *log_file        = NULL;

static void log_init(void) {
    if (log_initialized) return;
    log_initialized = 1;
    const char *val = getenv("NVENC_FIX_DEBUG");
    if (!val || val[0] == '\0') { log_enabled = 0; return; }
    log_enabled = 1;
    if (strcmp(val, "1") == 0 || strcmp(val, "stderr") == 0) {
        log_file = stderr;
    } else {
        log_file = fopen(val, "a");
        if (!log_file) { log_file = stderr; }
    }
}

static void log_msg(const char *fmt, ...) {
    log_init();
    if (!log_enabled) return;
    va_list ap;
    va_start(ap, fmt);
    fprintf(log_file, "[nvenc_fix] ");
    vfprintf(log_file, fmt, ap);
    fprintf(log_file, "\n");
    fflush(log_file);
    va_end(ap);
}

/* ============================================================
 * Real ioctl
 * ============================================================ */

typedef int (*ioctl_fn_t)(int fd, unsigned long request, ...);
static ioctl_fn_t real_ioctl = NULL;

static void ensure_real_ioctl(void) {
    if (!real_ioctl) {
        real_ioctl = (ioctl_fn_t)dlsym(RTLD_NEXT, "ioctl");
        if (!real_ioctl) { fprintf(stderr, "[nvenc_fix] FATAL: cannot find real ioctl\n"); _exit(1); }
    }
}

/* ============================================================
 * Device node helpers
 * ============================================================ */

static int device_node_exists(NvU32 device_instance) {
    char path[64];
    snprintf(path, sizeof(path), "/dev/nvidia%u", device_instance);
    return (access(path, F_OK) == 0);
}

static uint32_t get_available_devices(void) {
    /* Optional override: the entrypoint sets NVENC_FIX_AVAILABLE to the bitmask
     * of nvidia-smi-visible (actually CUDA-usable) GPU minors. This is needed on
     * hosts where the container mounts /dev/nvidiaX for GPUs it can't use
     * (e.g. NVIDIA_VISIBLE_DEVICES=void on Vast) — the mounted-node scan below
     * would keep too many GPUs and NVENC still fails peer-init. */
    const char *override = getenv("NVENC_FIX_AVAILABLE");
    if (override && override[0] != '\0') {
        uint32_t mask = (uint32_t)strtoul(override, NULL, 0);
        log_msg("using NVENC_FIX_AVAILABLE=0x%x (nvidia-smi-visible GPUs)", mask);
        return mask;
    }
    uint32_t mask = 0;
    for (int i = 0; i < 32; i++)
        if (device_node_exists(i)) mask |= (1u << i);
    return mask;
}

/* ============================================================
 * Strategy 1: ioctl-based GPU ID resolution
 * ============================================================ */

static NvU32 resolve_gpu_id_to_device(int fd, NvHandle hClient, NvU32 gpuId) {
    NV0000_CTRL_GPU_GET_ID_INFO_PARAMS id_info;
    memset(&id_info, 0, sizeof(id_info));
    id_info.gpuId = gpuId;
    NVOS54_PARAMETERS ctrl;
    memset(&ctrl, 0, sizeof(ctrl));
    ctrl.hClient    = hClient;
    ctrl.hObject    = hClient;
    ctrl.cmd        = NV0000_CTRL_CMD_GPU_GET_ID_INFO;
    ctrl.params     = &id_info;
    ctrl.paramsSize = sizeof(id_info);
    unsigned long req = _IOC(_IOC_READ|_IOC_WRITE, NV_IOCTL_MAGIC, NV_ESC_RM_CONTROL, sizeof(NVOS54_PARAMETERS));
    int ret = real_ioctl(fd, req, &ctrl);
    if (ret != 0 || ctrl.status != 0) {
        log_msg("GET_ID_INFO failed for gpuId 0x%x: ioctl=%d status=0x%x", gpuId, ret, ctrl.status);
        return (NvU32)-1;
    }
    log_msg("gpuId 0x%x -> deviceInstance %u", gpuId, id_info.deviceInstance);
    return id_info.deviceInstance;
}

/* ============================================================
 * Strategy 2: /proc-based GPU matching
 * ============================================================ */

#define MAX_GPU_MAP 32

typedef struct {
    unsigned int domain, bus, slot, func;
    int device_minor;
} gpu_proc_entry_t;

static int gpu_map_count = 0;
static gpu_proc_entry_t gpu_map[MAX_GPU_MAP];
static int gpu_map_loaded = 0;

static void load_gpu_map(void) {
    if (gpu_map_loaded) return;
    gpu_map_loaded = 1;
    gpu_map_count = 0;
    DIR *dir = opendir("/proc/driver/nvidia/gpus");
    if (!dir) { log_msg("WARNING: cannot open /proc/driver/nvidia/gpus"); return; }
    struct dirent *ent;
    while ((ent = readdir(dir)) != NULL && gpu_map_count < MAX_GPU_MAP) {
        if (ent->d_name[0] == '.') continue;
        unsigned int domain, bus, slot, func;
        if (sscanf(ent->d_name, "%x:%x:%x.%x", &domain, &bus, &slot, &func) != 4) continue;
        char info_path[512];
        snprintf(info_path, sizeof(info_path), "/proc/driver/nvidia/gpus/%s/information", ent->d_name);
        FILE *f = fopen(info_path, "r");
        if (!f) continue;
        int dev_minor = -1;
        char line[256];
        while (fgets(line, sizeof(line), f))
            if (sscanf(line, "Device Minor: %d", &dev_minor) == 1) break;
        fclose(f);
        if (dev_minor < 0) continue;
        gpu_map[gpu_map_count].domain = domain;
        gpu_map[gpu_map_count].bus = bus;
        gpu_map[gpu_map_count].slot = slot;
        gpu_map[gpu_map_count].func = func;
        gpu_map[gpu_map_count].device_minor = dev_minor;
        gpu_map_count++;
        log_msg("proc map: %04x:%02x:%02x.%x -> Device Minor %d", domain, bus, slot, func, dev_minor);
    }
    closedir(dir);
    log_msg("loaded %d GPU entries from /proc", gpu_map_count);
}

static int match_gpuid_to_minor(NvU32 gpuId) {
    load_gpu_map();
    /* The RM gpuId encodes the PCI address as slot | (bus << 8) | (domain << 16):
     *   gpuId 0x11800 -> domain 0x0001, bus 0x18, slot 0x00 -> 0001:18:00.0
     *   gpuId 0x00007 -> domain 0x0000, bus 0x00, slot 0x07 -> 0000:00:07.0
     * The original flexgrip heuristic matched on BUS only (gpuId>>8 & 0xFF), which
     * breaks on single-bus multi-GPU hosts where every GPU shares bus 0 and differs
     * only by slot — it matched every gpuId to the FIRST proc entry (all -> minor
     * 0) and then gave up ('not filtering'), so NVENC still failed. Match the full
     * domain:bus:slot address first; fall back to the bus-only / domain:bus
     * heuristics only if no full match (preserves prior behaviour on hosts where
     * the encoding differs). */
    unsigned int extracted_slot   = gpuId & 0xFF;
    unsigned int extracted_bus    = (gpuId >> 8) & 0xFF;
    unsigned int extracted_domain = (gpuId >> 16) & 0xFFFF;
    unsigned int extracted_full   = gpuId >> 8;
    for (int i = 0; i < gpu_map_count; i++) {
        if (gpu_map[i].domain == extracted_domain &&
            gpu_map[i].bus == extracted_bus &&
            gpu_map[i].slot == extracted_slot) {
            log_msg("gpuId 0x%x: full PCI %04x:%02x:%02x.%x -> minor %d",
                    gpuId, gpu_map[i].domain, gpu_map[i].bus,
                    gpu_map[i].slot, gpu_map[i].func, gpu_map[i].device_minor);
            return gpu_map[i].device_minor;
        }
    }
    for (int i = 0; i < gpu_map_count; i++) {
        if (gpu_map[i].bus == extracted_bus) {
            log_msg("gpuId 0x%x: bus-only fallback 0x%02x matches %04x:%02x:%02x.%x -> minor %d",
                    gpuId, extracted_bus, gpu_map[i].domain, gpu_map[i].bus,
                    gpu_map[i].slot, gpu_map[i].func, gpu_map[i].device_minor);
            return gpu_map[i].device_minor;
        }
        unsigned int combined = (gpu_map[i].domain << 8) | gpu_map[i].bus;
        if (combined == extracted_full) {
            log_msg("gpuId 0x%x: domain:bus fallback 0x%x matches %04x:%02x:%02x.%x -> minor %d",
                    gpuId, extracted_full, gpu_map[i].domain, gpu_map[i].bus,
                    gpu_map[i].slot, gpu_map[i].func, gpu_map[i].device_minor);
            return gpu_map[i].device_minor;
        }
    }
    log_msg("gpuId 0x%x: no /proc match (dom=0x%x bus=0x%02x slot=0x%02x full=0x%x)",
            gpuId, extracted_domain, extracted_bus, extracted_slot, extracted_full);
    return -1;
}

/* ============================================================
 * Main ioctl interposer
 * ============================================================ */

int ioctl(int fd, unsigned long request, ...) {
    ensure_real_ioctl();
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);

    int ret = real_ioctl(fd, request, arg);
    if (ret != 0) return ret;
    if (_IOC_NR(request) != NV_ESC_RM_CONTROL) return ret;

    NVOS54_PARAMETERS *ctrl = (NVOS54_PARAMETERS *)arg;
    if (!ctrl || !ctrl->params) return ret;
    if (ctrl->cmd != NV0000_CTRL_CMD_GPU_GET_ATTACHED_IDS) return ret;
    if (ctrl->status != 0) return ret;

    NV0000_CTRL_GPU_GET_ATTACHED_IDS_PARAMS *gpu_params =
        (NV0000_CTRL_GPU_GET_ATTACHED_IDS_PARAMS *)ctrl->params;

    int total_host_gpus = 0;
    for (int i = 0; i < NV0000_CTRL_GPU_MAX_ATTACHED_GPUS; i++) {
        if (gpu_params->gpuIds[i] == NV0000_CTRL_GPU_INVALID_ID) break;
        total_host_gpus++;
    }
    log_msg("GET_ATTACHED_IDS returned %d GPUs from host", total_host_gpus);
    if (total_host_gpus <= 1) return ret;

    uint32_t available = get_available_devices();
    log_msg("available device node bitmask: 0x%08x", available);
    if (available == 0) { log_msg("WARNING: no /dev/nvidiaX nodes found, not filtering"); return ret; }

    NvU32 filtered[NV0000_CTRL_GPU_MAX_ATTACHED_GPUS];
    int filtered_count = 0, resolve_failures = 0;

    /* Strategy 1: ioctl-based resolve */
    for (int i = 0; i < total_host_gpus; i++) {
        NvU32 dev_inst = resolve_gpu_id_to_device(fd, ctrl->hClient, gpu_params->gpuIds[i]);
        if (dev_inst == (NvU32)-1) { resolve_failures++; continue; }
        if (dev_inst < 32 && (available & (1u << dev_inst))) {
            log_msg("KEEPING gpuId 0x%x (deviceInstance %u via ioctl)", gpu_params->gpuIds[i], dev_inst);
            filtered[filtered_count++] = gpu_params->gpuIds[i];
        } else {
            log_msg("REMOVING gpuId 0x%x (deviceInstance %u - not in container)", gpu_params->gpuIds[i], dev_inst);
        }
    }

    /* Strategy 2: /proc-based matching */
    if (resolve_failures == total_host_gpus) {
        log_msg("all GET_ID_INFO calls failed, trying /proc-based matching");
        filtered_count = 0;
        for (int i = 0; i < total_host_gpus; i++) {
            int dev_minor = match_gpuid_to_minor(gpu_params->gpuIds[i]);
            if (dev_minor >= 0 && dev_minor < 32 && (available & (1u << dev_minor))) {
                log_msg("KEEPING gpuId 0x%x (minor %d via /proc)", gpu_params->gpuIds[i], dev_minor);
                filtered[filtered_count++] = gpu_params->gpuIds[i];
            } else if (dev_minor >= 0) {
                log_msg("REMOVING gpuId 0x%x (minor %d - not in container)", gpu_params->gpuIds[i], dev_minor);
            }
        }
    }

    if (filtered_count == 0) {
        log_msg("WARNING: could not determine correct GPU, not filtering (NVENC may fail)");
        return ret;
    }

    /* Write back the filtered list */
    for (int i = 0; i < filtered_count; i++)
        gpu_params->gpuIds[i] = filtered[i];
    for (int i = filtered_count; i < NV0000_CTRL_GPU_MAX_ATTACHED_GPUS; i++)
        gpu_params->gpuIds[i] = NV0000_CTRL_GPU_INVALID_ID;
    log_msg("filtered: %d -> %d GPUs", total_host_gpus, filtered_count);

    return ret;
}