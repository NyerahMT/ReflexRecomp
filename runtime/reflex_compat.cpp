// Reflex-specific import compatibility for the pinned recomp-kit runtime.
//
// This file contains only clean-room platform shims. It is copied into the
// pinned kit by tools/patch_reflex_runtime.py during CI; no recovered game code
// is stored here.

#include "imports.h"
#include "memory.h"

#include <cctype>
#include <cstdlib>
#include <cstring>
#include <string>

namespace {

void reflex_interlocked_compare_exchange(X86 *c) {
    const uint32_t p = arg(c, 0);
    const uint32_t exchange = arg(c, 1);
    const uint32_t comparand = arg(c, 2);
    if (!p || !gm_valid(p, 4)) {
        set_eax(c, 0);
        return;
    }
    const uint32_t old = rd32(p);
    if (old == comparand)
        wr32(p, exchange);
    set_eax(c, old);
}

void reflex_register_raw_input_devices(X86 *c) {
    // Initial bring-up: input is supplied by the host compatibility layers.
    // Accept registration so Reflex does not abort while we are still using
    // the existing DirectInput/native input bridge.
    set_eax(c, 1);
}

void reflex_steam_restart_app_if_necessary(X86 *c) {
    // The recompiled app is already the process we want to run.
    set_eax(c, 0);
}

void reflex_steam_init(X86 *c) {
    // Permit offline/local startup. Individual Steam interfaces can be added
    // as the game reaches them.
    set_eax(c, 1);
}

void crt_memcpy(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t src = arg(c, 1);
    const uint32_t count = arg(c, 2);
    if (count && gm_valid(dst, count) && gm_valid(src, count))
        memcpy(g_mem + dst, g_mem + src, count);
    set_eax(c, dst);
}

void crt_memset(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t count = arg(c, 2);
    if (count && gm_valid(dst, count))
        memset(g_mem + dst, int(arg(c, 1) & 0xffu), count);
    set_eax(c, dst);
}

void crt_strncpy(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t src = arg(c, 1);
    const uint32_t count = arg(c, 2);
    if (!count || !gm_valid(dst, count)) {
        set_eax(c, dst);
        return;
    }

    bool nul_seen = false;
    for (uint32_t i = 0; i < count; ++i) {
        uint8_t ch = 0;
        if (!nul_seen && gm_valid(src + i, 1)) {
            ch = g_mem[src + i];
            if (!ch)
                nul_seen = true;
        } else {
            nul_seen = true;
        }
        g_mem[dst + i] = ch;
    }
    set_eax(c, dst);
}

int ascii_icmp(const std::string &a, const std::string &b) {
    const size_t common = a.size() < b.size() ? a.size() : b.size();
    for (size_t i = 0; i < common; ++i) {
        const int ac = std::tolower(static_cast<unsigned char>(a[i]));
        const int bc = std::tolower(static_cast<unsigned char>(b[i]));
        if (ac < bc)
            return -1;
        if (ac > bc)
            return 1;
    }
    if (a.size() < b.size())
        return -1;
    if (a.size() > b.size())
        return 1;
    return 0;
}

void crt_stricmp(X86 *c) {
    const int rc = ascii_icmp(gm_str(arg(c, 0)), gm_str(arg(c, 1)));
    set_eax(c, static_cast<uint32_t>(static_cast<int32_t>(rc)));
}

void crt_strcmp(X86 *c) {
    const std::string a = gm_str(arg(c, 0));
    const std::string b = gm_str(arg(c, 1));
    const int rc = a < b ? -1 : (a > b ? 1 : 0);
    set_eax(c, static_cast<uint32_t>(static_cast<int32_t>(rc)));
}

void crt_strlen(X86 *c) {
    set_eax(c, static_cast<uint32_t>(gm_str(arg(c, 0)).size()));
}

void crt_tolower(X86 *c) {
    const int32_t v = static_cast<int32_t>(arg(c, 0));
    if (v >= 0 && v <= 255)
        set_eax(c, static_cast<uint32_t>(std::tolower(static_cast<unsigned char>(v))));
    else
        set_eax(c, static_cast<uint32_t>(v));
}

void crt_aligned_malloc(X86 *c) {
    const uint32_t size = arg(c, 0);
    uint32_t alignment = arg(c, 1);
    if (alignment < 16)
        alignment = 16;
    if ((alignment & (alignment - 1)) != 0) {
        set_eax(c, 0);
        return;
    }
    set_eax(c, heap_alloc(size, false, alignment));
}

void crt_aligned_free(X86 *c) {
    const uint32_t p = arg(c, 0);
    if (p)
        heap_free(p);
    set_eax(c, 0);
}

void crt_pointer_identity(X86 *c) {
    set_eax(c, arg(c, 0));
}

void crt_noop(X86 *c) {
    set_eax(c, 0);
}

void crt_srand(X86 *c) {
    std::srand(arg(c, 0));
    set_eax(c, 0);
}

uint32_t guest_scalar(uint32_t &slot, uint32_t initial) {
    if (!slot || !heap_owns(slot)) {
        slot = heap_alloc(4, true);
        if (slot)
            wr32(slot, initial);
    }
    return slot;
}

uint32_t g_fmode_addr = 0;
uint32_t g_commode_addr = 0;
uint32_t g_controlfp = 0x0009001fu;
uint32_t g_argv_addr = 0;
uint32_t g_argv0_addr = 0;
uint32_t g_envp_addr = 0;

void crt_set_app_type(X86 *c) {
    set_eax(c, 0);
}

void crt_p_fmode(X86 *c) {
    set_eax(c, guest_scalar(g_fmode_addr, 0x4000u)); // _O_TEXT
}

void crt_p_commode(X86 *c) {
    set_eax(c, guest_scalar(g_commode_addr, 0));
}

void crt_controlfp_s(X86 *c) {
    const uint32_t current = arg(c, 0);
    const uint32_t value = arg(c, 1);
    const uint32_t mask = arg(c, 2);
    g_controlfp = (g_controlfp & ~mask) | (value & mask);
    if (current && gm_valid(current, 4))
        wr32(current, g_controlfp);
    set_eax(c, 0);
}

void crt_onexit(X86 *c) {
    // Startup only needs registration to succeed. We do not run host-side
    // atexit callbacks during forced CI termination.
    set_eax(c, arg(c, 0));
}

void crt_getmainargs(X86 *c) {
    const uint32_t argc_out = arg(c, 0);
    const uint32_t argv_out = arg(c, 1);
    const uint32_t env_out = arg(c, 2);

    if (!g_argv0_addr || !heap_owns(g_argv0_addr)) {
        static const char exe_name[] = "MXReflex.exe";
        g_argv0_addr = heap_alloc(sizeof exe_name, true);
        if (g_argv0_addr)
            memcpy(g_mem + g_argv0_addr, exe_name, sizeof exe_name);
    }
    if (!g_argv_addr || !heap_owns(g_argv_addr)) {
        g_argv_addr = heap_alloc(8, true);
        if (g_argv_addr) {
            wr32(g_argv_addr, g_argv0_addr);
            wr32(g_argv_addr + 4, 0);
        }
    }
    if (!g_envp_addr || !heap_owns(g_envp_addr))
        g_envp_addr = heap_alloc(4, true);

    if (argc_out && gm_valid(argc_out, 4))
        wr32(argc_out, 1);
    if (argv_out && gm_valid(argv_out, 4))
        wr32(argv_out, g_argv_addr);
    if (env_out && gm_valid(env_out, 4))
        wr32(env_out, g_envp_addr);
    set_eax(c, 0);
}

void crt_malloc(X86 *c) {
    set_eax(c, heap_alloc(arg(c, 0), false));
}

void crt_calloc(X86 *c) {
    const uint64_t total = uint64_t(arg(c, 0)) * uint64_t(arg(c, 1));
    set_eax(c, total <= 0xffffffffu ? heap_alloc(uint32_t(total), true) : 0);
}

void crt_realloc(X86 *c) {
    const uint32_t p = arg(c, 0);
    const uint32_t size = arg(c, 1);
    if (!p) {
        set_eax(c, heap_alloc(size, false));
        return;
    }
    if (!size) {
        heap_free(p);
        set_eax(c, 0);
        return;
    }
    set_eax(c, heap_realloc(p, size, false));
}

void crt_free(X86 *c) {
    const uint32_t p = arg(c, 0);
    if (p)
        heap_free(p);
    set_eax(c, 0);
}

void crt_exception_continue_search(X86 *c) {
    set_eax(c, 1); // ExceptionContinueSearch
}

void crt_initterm(X86 *c) {
    const uint32_t first = arg(c, 0);
    const uint32_t last = arg(c, 1);
    if (last < first || ((last - first) & 3u) || !gm_valid(first, last - first)) {
        set_eax(c, 0);
        return;
    }
    for (uint32_t p = first; p < last; p += 4) {
        const uint32_t fn = rd32(p);
        if (fn)
            guest_call(c, fn);
    }
    set_eax(c, 0);
}

void crt_initterm_e(X86 *c) {
    const uint32_t first = arg(c, 0);
    const uint32_t last = arg(c, 1);
    if (last < first || ((last - first) & 3u) || !gm_valid(first, last - first)) {
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    for (uint32_t p = first; p < last; p += 4) {
        const uint32_t fn = rd32(p);
        if (!fn)
            continue;
        const uint32_t rc = guest_call(c, fn);
        if (rc) {
            set_eax(c, rc);
            return;
        }
    }
    set_eax(c, 0);
}

const ImportShim k_reflex_shims[] = {
    // Win32 ABI fixes observed during Reflex startup.
    {"KERNEL32.dll", "InterlockedCompareExchange", 3, reflex_interlocked_compare_exchange},
    {"USER32.dll", "RegisterRawInputDevices", 3, reflex_register_raw_input_devices},

    // Steam's flat C API uses cdecl.
    {"steam_api.dll", "SteamAPI_RestartAppIfNecessary", ARGC_CDECL,
     reflex_steam_restart_app_if_necessary},
    {"steam_api.dll", "SteamAPI_Init", ARGC_CDECL, reflex_steam_init},

    // Visual C++ 2008 CRT. Explicit cdecl registration is important even for
    // logging-only entries: it prevents the import dispatcher from treating
    // them as unknown stdcall functions and corrupting the guest ESP.
    {"MSVCR90.dll", "__set_app_type", ARGC_CDECL, crt_set_app_type},
    {"MSVCR90.dll", "__p__fmode", ARGC_CDECL, crt_p_fmode},
    {"MSVCR90.dll", "__p__commode", ARGC_CDECL, crt_p_commode},
    {"MSVCR90.dll", "_controlfp_s", ARGC_CDECL, crt_controlfp_s},
    {"MSVCR90.dll", "_onexit", ARGC_CDECL, crt_onexit},
    {"MSVCR90.dll", "__getmainargs", ARGC_CDECL, crt_getmainargs},
    {"MSVCR90.dll", "malloc", ARGC_CDECL, crt_malloc},
    {"MSVCR90.dll", "calloc", ARGC_CDECL, crt_calloc},
    {"MSVCR90.dll", "realloc", ARGC_CDECL, crt_realloc},
    {"MSVCR90.dll", "free", ARGC_CDECL, crt_free},
    {"MSVCR90.dll", "__CxxFrameHandler3", ARGC_CDECL, crt_exception_continue_search},
    {"MSVCR90.dll", "_initterm_e", ARGC_CDECL, crt_initterm_e},
    {"MSVCR90.dll", "_initterm", ARGC_CDECL, crt_initterm},
    {"MSVCR90.dll", "memcpy", ARGC_CDECL, crt_memcpy},
    {"MSVCR90.dll", "memset", ARGC_CDECL, crt_memset},
    {"MSVCR90.dll", "strncpy", ARGC_CDECL, crt_strncpy},
    {"MSVCR90.dll", "_stricmp", ARGC_CDECL, crt_stricmp},
    {"MSVCR90.dll", "strcmp", ARGC_CDECL, crt_strcmp},
    {"MSVCR90.dll", "strlen", ARGC_CDECL, crt_strlen},
    {"MSVCR90.dll", "tolower", ARGC_CDECL, crt_tolower},
    {"MSVCR90.dll", "_aligned_malloc", ARGC_CDECL, crt_aligned_malloc},
    {"MSVCR90.dll", "_aligned_free", ARGC_CDECL, crt_aligned_free},
    {"MSVCR90.dll", "_encode_pointer", ARGC_CDECL, crt_pointer_identity},
    {"MSVCR90.dll", "_decode_pointer", ARGC_CDECL, crt_pointer_identity},
    {"MSVCR90.dll", "_lock", ARGC_CDECL, crt_noop},
    {"MSVCR90.dll", "_unlock", ARGC_CDECL, crt_noop},
    {"MSVCR90.dll", "srand", ARGC_CDECL, crt_srand},

    // Signature-only for the first pass. Returning zero is preferable to
    // inventing FILE/SEH/onexit semantics, while the cdecl ABI remains correct.
    {"MSVCR90.dll", "fopen", ARGC_CDECL, nullptr},
    {"MSVCR90.dll", "__dllonexit", ARGC_CDECL, crt_onexit},
    {"MSVCR90.dll", "_except_handler4_common", ARGC_CDECL, crt_exception_continue_search},
};

} // namespace

void reflex_compat_register() {
    imports_register(k_reflex_shims, sizeof k_reflex_shims / sizeof k_reflex_shims[0]);
}
