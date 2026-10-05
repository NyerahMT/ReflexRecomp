// Reflex-specific import compatibility for the pinned recomp-kit runtime.
//
// This file contains only clean-room platform shims. It is copied into the
// pinned kit by tools/patch_reflex_runtime.py during CI; no recovered game code
// is stored here.

#include "imports.h"
#include "memory.h"

#include <cctype>
#include <cstdio>
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

uint32_t g_iob_addr = 0;

// VS2008's 32-bit FILE is eight dwords. The first startup users only need
// stable stdin/stdout/stderr objects; stream I/O itself can be layered later.
void crt_iob_func(X86 *c) {
    constexpr uint32_t kFileSize = 32;
    if (!g_iob_addr || !heap_owns(g_iob_addr)) {
        g_iob_addr = heap_alloc(kFileSize * 3, true);
        if (g_iob_addr) {
            for (uint32_t i = 0; i < 3; ++i)
                wr32(g_iob_addr + i * kFileSize + 16, i); // _file
            wr32(g_iob_addr + 0 * kFileSize + 12, 0x0001u); // _IOREAD
            wr32(g_iob_addr + 1 * kFileSize + 12, 0x0002u); // _IOWRT
            wr32(g_iob_addr + 2 * kFileSize + 12, 0x0002u); // _IOWRT
        }
    }
    set_eax(c, g_iob_addr);
}

std::string guest_printf_format(uint32_t fmt_ptr, uint32_t va) {
    std::string fmt = gm_str(fmt_ptr, 4096);
    std::string res;
    size_t i = 0;
    while (i < fmt.size()) {
        char ch = fmt[i++];
        if (ch != '%') {
            res.push_back(ch);
            continue;
        }
        if (i < fmt.size() && fmt[i] == '%') {
            res.push_back('%');
            ++i;
            continue;
        }

        std::string spec = "%";
        while (i < fmt.size() && strchr("-+ #0", fmt[i]))
            spec.push_back(fmt[i++]);
        while (i < fmt.size() && isdigit(static_cast<unsigned char>(fmt[i])))
            spec.push_back(fmt[i++]);
        if (i < fmt.size() && fmt[i] == '.') {
            spec.push_back(fmt[i++]);
            while (i < fmt.size() && isdigit(static_cast<unsigned char>(fmt[i])))
                spec.push_back(fmt[i++]);
        }
        // Win32 long is 32-bit; consume the size prefix but format through the
        // fixed-width host type below rather than Linux's 64-bit long.
        while (i < fmt.size() && (fmt[i] == 'l' || fmt[i] == 'h'))
            ++i;
        if (i >= fmt.size())
            break;

        const char conv = fmt[i++];
        if (!gm_valid(va, 4)) {
            res += "<?>";
            break;
        }
        const uint32_t v = rd32(va);
        va += 4;

        char buf[1024] = {};
        switch (conv) {
        case 's': {
            std::string value = gm_str(v, 4096);
            spec.push_back('s');
            std::snprintf(buf, sizeof buf, spec.c_str(), value.c_str());
            break;
        }
        case 'c':
            spec.push_back('c');
            std::snprintf(buf, sizeof buf, spec.c_str(), int(v & 0xffu));
            break;
        case 'd':
        case 'i':
            spec.push_back('d');
            std::snprintf(buf, sizeof buf, spec.c_str(), static_cast<int32_t>(v));
            break;
        case 'u':
            spec.push_back('u');
            std::snprintf(buf, sizeof buf, spec.c_str(), v);
            break;
        case 'x':
            spec.push_back('x');
            std::snprintf(buf, sizeof buf, spec.c_str(), v);
            break;
        case 'X':
            spec.push_back('X');
            std::snprintf(buf, sizeof buf, spec.c_str(), v);
            break;
        case 'p':
            std::snprintf(buf, sizeof buf, "0x%08x", v);
            break;
        default:
            std::snprintf(buf, sizeof buf, "%%%c", conv);
            va -= 4;
            break;
        }
        res += buf;
    }
    return res;
}

void crt_snprintf(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t cap = arg(c, 1);
    const uint32_t fmt = arg(c, 2);
    const uint32_t va = c->r[R_ESP] + 16;
    const std::string res = guest_printf_format(fmt, va);

    if (!cap) {
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    if (!dst || !gm_valid(dst, cap)) {
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }

    if (res.size() >= cap) {
        memcpy(g_mem + dst, res.data(), cap);
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    memcpy(g_mem + dst, res.data(), res.size());
    g_mem[dst + res.size()] = 0;
    set_eax(c, static_cast<uint32_t>(res.size()));
}

// MSVC 2008 x86 basic_string<char>: 16-byte small buffer/pointer union,
// followed by 32-bit size and capacity. This is the one constructor Reflex
// reaches during startup.
void msvcp_string_ctor_cstr(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    const std::string value = gm_str(arg(c, 0), 0x100000);
    if (!self || !gm_valid(self, 24)) {
        set_eax(c, 0);
        return;
    }

    memset(g_mem + self, 0, 24);
    const uint32_t n = static_cast<uint32_t>(value.size());
    if (n <= 15) {
        memcpy(g_mem + self, value.data(), n);
        g_mem[self + n] = 0;
        wr32(self + 16, n);
        wr32(self + 20, 15);
    } else {
        const uint32_t data = heap_alloc(n + 1, false);
        if (!data) {
            set_eax(c, 0);
            return;
        }
        memcpy(g_mem + data, value.data(), n);
        g_mem[data + n] = 0;
        wr32(self, data);
        wr32(self + 16, n);
        wr32(self + 20, n);
    }
    set_eax(c, self);
}

void msvcp_string_dtor(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    if (self && gm_valid(self, 24)) {
        const uint32_t capacity = rd32(self + 20);
        if (capacity > 15) {
            const uint32_t data = rd32(self);
            if (data && heap_owns(data))
                heap_free(data);
        }
        memset(g_mem + self, 0, 24);
    }
    set_eax(c, self);
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
    {"MSVCR90.dll", "__iob_func", ARGC_CDECL, crt_iob_func},
    {"MSVCR90.dll", "_snprintf", ARGC_CDECL, crt_snprintf},
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

    // MSVC thiscall: ECX carries this; one explicit constructor argument is
    // callee-cleaned, while the destructor has no stack arguments.
    {"MSVCP90.dll",
     "??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@PBD@Z",
     1, msvcp_string_ctor_cstr},
    {"MSVCP90.dll",
     "??1?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@XZ",
     0, msvcp_string_dtor},
};

} // namespace

void reflex_compat_register() {
    imports_register(k_reflex_shims, sizeof k_reflex_shims / sizeof k_reflex_shims[0]);
}
