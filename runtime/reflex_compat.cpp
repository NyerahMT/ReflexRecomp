// Reflex-specific import compatibility for the pinned recomp-kit runtime.
//
// This file contains only clean-room platform shims. It is copied into the
// pinned kit by tools/patch_reflex_runtime.py during CI; no recovered game code
// is stored here.

#include "imports.h"
#include "memory.h"

#include <algorithm>
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

void crt_strchr(X86 *c) {
    const uint32_t src = arg(c, 0);
    const uint8_t needle = static_cast<uint8_t>(arg(c, 1) & 0xffu);
    if (!src) {
        set_eax(c, 0);
        return;
    }
    for (uint32_t i = 0; i < 0x100000u && gm_valid(src + i, 1); ++i) {
        const uint8_t ch = g_mem[src + i];
        if (ch == needle) {
            set_eax(c, src + i);
            return;
        }
        if (!ch)
            break;
    }
    set_eax(c, 0);
}

void crt_invalid_parameter_noinfo(X86 *c) {
    // The retail CRT reports the contract violation through its invalid
    // parameter handler. Bring-up only needs the call to preserve the ABI.
    set_eax(c, 0);
}

void crt_type_info_name_internal(X86 *c) {
    // VS2008 x86 type_info is { vtable*, cached_name*, mangled[] }.
    // Returning the in-object raw name is sufficient for startup diagnostics;
    // strip the leading '.' used by MSVC's stored decorated name.
    const uint32_t self = c->r[R_ECX];
    if (!self || !gm_valid(self, 9)) {
        set_eax(c, 0);
        return;
    }
    const uint32_t cached = rd32(self + 4);
    if (cached && gm_valid(cached, 1)) {
        set_eax(c, cached);
        return;
    }
    uint32_t raw = self + 8;
    if (g_mem[raw] == '.' && gm_valid(raw + 1, 1))
        ++raw;
    set_eax(c, raw);
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
        case 'f':
        case 'F':
        case 'e':
        case 'E':
        case 'g':
        case 'G':
        case 'a':
        case 'A': {
            if (!gm_valid(va - 4, 8)) {
                std::snprintf(buf, sizeof buf, "<?>");
                break;
            }
            uint64_t bits = rd64(va - 4);
            double value = 0.0;
            memcpy(&value, &bits, sizeof value);
            va += 4; // x86 varargs pass the promoted double in two dwords
            spec.push_back(conv);
            std::snprintf(buf, sizeof buf, spec.c_str(), value);
            break;
        }
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

void crt_vsnprintf(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t cap = arg(c, 1);
    const uint32_t fmt = arg(c, 2);
    const uint32_t va = arg(c, 3);
    const std::string res = guest_printf_format(fmt, va);

    if (!cap) {
        set_eax(c, res.empty() ? 0u : static_cast<uint32_t>(-1));
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

void crt_sprintf(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t fmt = arg(c, 1);
    const uint32_t va = c->r[R_ESP] + 12;
    const std::string res = guest_printf_format(fmt, va);
    const uint64_t bytes = uint64_t(res.size()) + 1u;
    if (!dst || bytes > 0xffffffffu || !gm_valid(dst, static_cast<uint32_t>(bytes))) {
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    memcpy(g_mem + dst, res.data(), res.size());
    g_mem[dst + res.size()] = 0;
    set_eax(c, static_cast<uint32_t>(res.size()));
}

void crt_memmove_s(X86 *c) {
    constexpr uint32_t kEINVAL = 22;
    constexpr uint32_t kERANGE = 34;
    const uint32_t dst = arg(c, 0);
    const uint32_t dst_size = arg(c, 1);
    const uint32_t src = arg(c, 2);
    const uint32_t count = arg(c, 3);

    if (!count) {
        set_eax(c, 0);
        return;
    }
    if (!dst || !src) {
        if (dst && dst_size && gm_valid(dst, dst_size))
            memset(g_mem + dst, 0, dst_size);
        set_eax(c, kEINVAL);
        return;
    }
    if (count > dst_size || !gm_valid(dst, dst_size) || !gm_valid(src, count)) {
        if (dst && dst_size && gm_valid(dst, dst_size))
            memset(g_mem + dst, 0, dst_size);
        set_eax(c, kERANGE);
        return;
    }
    memmove(g_mem + dst, g_mem + src, count);
    set_eax(c, 0);
}

void crt_mbstowcs_s(X86 *c) {
    constexpr uint32_t kEINVAL = 22;
    constexpr uint32_t kERANGE = 34;
    constexpr uint32_t kSTRUNCATE = 80;
    constexpr uint32_t kTRUNCATE = 0xffffffffu;

    const uint32_t converted_out = arg(c, 0);
    const uint32_t dst = arg(c, 1);
    const uint32_t dst_words = arg(c, 2);
    const uint32_t src = arg(c, 3);
    const uint32_t count = arg(c, 4);

    if (converted_out && !gm_valid(converted_out, 4)) {
        set_eax(c, kEINVAL);
        return;
    }
    if (!src) {
        if (converted_out)
            wr32(converted_out, 0);
        if (dst && dst_words && gm_valid(dst, 2))
            wr16(dst, 0);
        set_eax(c, kEINVAL);
        return;
    }

    const std::string input = gm_str(src, 0x100000);
    const uint32_t requested =
        count == kTRUNCATE ? static_cast<uint32_t>(input.size())
                           : static_cast<uint32_t>(std::min<size_t>(input.size(), count));

    // MS secure CRT permits a query with a null destination and zero capacity.
    if (!dst && dst_words == 0) {
        if (converted_out)
            wr32(converted_out, requested + 1);
        set_eax(c, 0);
        return;
    }
    if (!dst || !dst_words || dst_words > 0x7fffffffu ||
        !gm_valid(dst, dst_words * 2u)) {
        if (converted_out)
            wr32(converted_out, 0);
        set_eax(c, kEINVAL);
        return;
    }

    uint32_t to_write = requested;
    uint32_t rc = 0;
    if (to_write + 1 > dst_words) {
        if (count == kTRUNCATE) {
            to_write = dst_words - 1;
            rc = kSTRUNCATE;
        } else {
            wr16(dst, 0);
            if (converted_out)
                wr32(converted_out, 0);
            set_eax(c, kERANGE);
            return;
        }
    }

    for (uint32_t i = 0; i < to_write; ++i)
        wr16(dst + i * 2u, static_cast<unsigned char>(input[i]));
    wr16(dst + to_write * 2u, 0);
    if (converted_out)
        wr32(converted_out, to_write + 1);
    set_eax(c, rc);
}

void crt_rtc_initw(X86 *c) {
    // MSVCR90's _CRT_RTC_INITW is cdecl with five arguments. The retail CRT
    // can return no user RTC callback; Wine models that valid case as NULL.
    set_eax(c, 0);
}

// MSVC 2008 x86 basic_string<char>: 16-byte small buffer/pointer union,
// followed by 32-bit size and capacity. This is the one constructor Reflex
// reaches during startup.
void msvcp_string_ctor_default(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    if (!self || !gm_valid(self, 24)) {
        set_eax(c, 0);
        return;
    }

    memset(g_mem + self, 0, 24);
    wr32(self + 16, 0);   // size
    wr32(self + 20, 15);  // small-string capacity
    set_eax(c, self);
}

uint32_t msvcp_string_data(uint32_t object) {
    if (!object || !gm_valid(object, 24))
        return 0;
    return rd32(object + 20) <= 15 ? object : rd32(object);
}

bool msvcp_string_copy_into(uint32_t self, uint32_t src) {
    if (!self || !src || !gm_valid(self, 24) || !gm_valid(src, 24))
        return false;

    const uint32_t n = rd32(src + 16);
    const uint32_t source = msvcp_string_data(src);
    if (n > 0x0fffffffu || !source || (n && !gm_valid(source, n)))
        return false;

    memset(g_mem + self, 0, 24);
    if (n <= 15) {
        if (n)
            memcpy(g_mem + self, g_mem + source, n);
        g_mem[self + n] = 0;
        wr32(self + 16, n);
        wr32(self + 20, 15);
        return true;
    }

    const uint32_t data = heap_alloc(n + 1, false);
    if (!data)
        return false;
    memcpy(g_mem + data, g_mem + source, n);
    g_mem[data + n] = 0;
    wr32(self, data);
    wr32(self + 16, n);
    wr32(self + 20, n);
    return true;
}

void msvcp_string_ctor_copy(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    set_eax(c, msvcp_string_copy_into(self, arg(c, 0)) ? self : 0);
}

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

bool msvcp_string_assign_value(uint32_t self, const std::string &value) {
    if (!self || !gm_valid(self, 24) || value.size() > 0x0fffffffu)
        return false;

    const uint32_t n = static_cast<uint32_t>(value.size());
    uint32_t fresh = 0;
    if (n > 15) {
        fresh = heap_alloc(n + 1, false);
        if (!fresh)
            return false;
        if (n)
            memcpy(g_mem + fresh, value.data(), n);
        g_mem[fresh + n] = 0;
    }

    const uint32_t old_capacity = rd32(self + 20);
    const uint32_t old_data = old_capacity > 15 ? rd32(self) : 0;
    if (old_data && heap_owns(old_data))
        heap_free(old_data);

    memset(g_mem + self, 0, 24);
    if (n <= 15) {
        if (n)
            memcpy(g_mem + self, value.data(), n);
        g_mem[self + n] = 0;
        wr32(self + 16, n);
        wr32(self + 20, 15);
    } else {
        wr32(self, fresh);
        wr32(self + 16, n);
        wr32(self + 20, n);
    }
    return true;
}

void msvcp_string_assign_cstr(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    const std::string value = gm_str(arg(c, 0), 0x100000);
    set_eax(c, msvcp_string_assign_value(self, value) ? self : 0);
}

void msvcp_string_resize(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    const uint32_t requested = arg(c, 0);
    if (!self || !gm_valid(self, 24) || requested > 0x01000000u) {
        set_eax(c, 0);
        return;
    }

    const uint32_t old_size = rd32(self + 16);
    const uint32_t old_data = msvcp_string_data(self);
    if (old_size > 0x01000000u ||
        (old_size && (!old_data || !gm_valid(old_data, old_size)))) {
        set_eax(c, 0);
        return;
    }

    std::string value;
    if (old_size)
        value.assign(reinterpret_cast<const char *>(g_mem + old_data), old_size);
    value.resize(requested, '\0');
    set_eax(c, msvcp_string_assign_value(self, value) ? self : 0);
}

void msvcp_char_traits_copy_s(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t dst_size = arg(c, 1);
    const uint32_t src = arg(c, 2);
    const uint32_t count = arg(c, 3);
    if (!count) {
        set_eax(c, dst);
        return;
    }
    if (!dst || !src || count > dst_size ||
        !gm_valid(dst, count) || !gm_valid(src, count)) {
        set_eax(c, 0);
        return;
    }
    memmove(g_mem + dst, g_mem + src, count);
    set_eax(c, dst);
}

int msvcp_string_compare(uint32_t left, uint32_t right) {
    if (!left || !right || !gm_valid(left, 24) || !gm_valid(right, 24))
        return 0;

    const uint32_t left_size = rd32(left + 16);
    const uint32_t right_size = rd32(right + 16);
    const uint32_t left_data = msvcp_string_data(left);
    const uint32_t right_data = msvcp_string_data(right);
    if ((left_size && (!left_data || !gm_valid(left_data, left_size))) ||
        (right_size && (!right_data || !gm_valid(right_data, right_size))))
        return 0;

    const uint32_t common = left_size < right_size ? left_size : right_size;
    if (common) {
        const int rc = memcmp(g_mem + left_data, g_mem + right_data, common);
        if (rc < 0)
            return -1;
        if (rc > 0)
            return 1;
    }
    return left_size < right_size ? -1 : (left_size > right_size ? 1 : 0);
}

void msvcp_string_less(X86 *c) {
    set_eax(c, msvcp_string_compare(arg(c, 0), arg(c, 1)) < 0 ? 1u : 0u);
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
    {"MSVCR90.dll", "_vsnprintf", ARGC_CDECL, crt_vsnprintf},
    {"MSVCR90.dll", "sprintf", ARGC_CDECL, crt_sprintf},
    {"MSVCR90.dll", "memmove_s", ARGC_CDECL, crt_memmove_s},
    {"MSVCR90.dll", "mbstowcs_s", ARGC_CDECL, crt_mbstowcs_s},
    {"MSVCR90.dll", "_CRT_RTC_INITW", ARGC_CDECL, crt_rtc_initw},
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
    {"MSVCR90.dll", "strchr", ARGC_CDECL, crt_strchr},
    {"MSVCR90.dll", "_invalid_parameter_noinfo", ARGC_CDECL,
     crt_invalid_parameter_noinfo},
    {"MSVCR90.dll",
     "?_name_internal_method@type_info@@QBEPBDPAU__type_info_node@@@Z",
     1, crt_type_info_name_internal},
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
     "??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@XZ",
     0, msvcp_string_ctor_default},
    {"MSVCP90.dll",
     "??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@PBD@Z",
     1, msvcp_string_ctor_cstr},
    {"MSVCP90.dll",
     "??0?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@ABV01@@Z",
     1, msvcp_string_ctor_copy},
    {"MSVCP90.dll",
     "??1?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAE@XZ",
     0, msvcp_string_dtor},
    {"MSVCP90.dll",
     "?resize@?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAEXI@Z",
     1, msvcp_string_resize},
    {"MSVCP90.dll",
     "??4?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAEAAV01@PBD@Z",
     1, msvcp_string_assign_cstr},
    {"MSVCP90.dll",
     "?_Copy_s@?$char_traits@D@std@@SAPADPADIPBDI@Z",
     ARGC_CDECL, msvcp_char_traits_copy_s},
    {"MSVCP90.dll",
     "??$?MDU?$char_traits@D@std@@V?$allocator@D@1@@std@@YA_NABV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@0@0@Z",
     ARGC_CDECL, msvcp_string_less},
};

} // namespace

void reflex_compat_register() {
    imports_register(k_reflex_shims, sizeof k_reflex_shims / sizeof k_reflex_shims[0]);
}
