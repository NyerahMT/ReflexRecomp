// Reflex-specific import compatibility for the pinned recomp-kit runtime.
//
// This file contains only clean-room platform shims. It is copied into the
// pinned kit by tools/patch_reflex_runtime.py during CI; no recovered game code
// is stored here.

#include "imports.h"
#include "memory.h"
#include "reflex_crt_numeric.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cctype>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>
#include <utility>

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

void reflex_steam_register_callback(X86 *c) {
    // Offline bring-up has no Steam callback pump. This export is cdecl; the
    // no-op exists primarily so the import dispatcher preserves the ABI.
    set_eax(c, 0);
}

void reflex_steam_user_stats(X86 *c) {
    // No Steam backend is attached to the recompiled process yet.
    set_eax(c, 0);
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

// A hot resource-name lookup performs millions of MSVCR90 _stricmp calls.
// Compare directly in the guest arena rather than allocating two std::strings
// for every call. Match gm_str's 32 KiB bound and empty-string behavior for
// null/out-of-arena pointers; use unsigned chars before host tolower().
int guest_ascii_icmp(uint32_t lhs, uint32_t rhs) {
    constexpr size_t max_string = 0x8000u;
    const size_t n_l = lhs < GUEST_SIZE
        ? std::min<size_t>(max_string, GUEST_SIZE - lhs) : 0u;
    const size_t n_r = rhs < GUEST_SIZE
        ? std::min<size_t>(max_string, GUEST_SIZE - rhs) : 0u;
    const size_t common = std::min(n_l, n_r);
    for (size_t i = 0; i < common; ++i) {
        const unsigned char a = g_mem[lhs + i];
        const unsigned char b = g_mem[rhs + i];
        if (!a || !b)
            return a == b ? 0 : (!a ? -1 : 1);
        const int ac = std::tolower(a);
        const int bc = std::tolower(b);
        if (ac != bc) return ac < bc ? -1 : 1;
    }
    if (n_l == n_r) return 0;
    // Either read ran into the end of the guest arena or the other pointer
    // was invalid, which gm_str treats as a zero-length string.
    const unsigned char next_a = common < n_l ? g_mem[lhs + common] : 0u;
    const unsigned char next_b = common < n_r ? g_mem[rhs + common] : 0u;
    return next_a == next_b ? 0 : (!next_a ? -1 : 1);
}

void crt_stricmp(X86 *c) {
    const uint32_t left_ptr = arg(c, 0), right_ptr = arg(c, 1);
    int rc = guest_ascii_icmp(left_ptr, right_ptr);
    const uint32_t ret = gm_valid(c->r[R_ESP], 4) ? rd32(c->r[R_ESP]) : 0u;
    // Controlled startup experiment: the private MXUI index contains
    // "Intro.ENG", but the guest currently asks for "Intro.". A mismatch
    // here might be why startup spins. NEVER change ordinary CRT string
    // comparison semantics in production; this only runs with explicit
    // opt-in in our 30-second CI experiment.
    static const bool probe_intro_english = [] {
        const char *flag = std::getenv("REFLEX_PROBE_INTRO_ENGLISH");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    if (probe_intro_english && ret == 0x0084a8f0u &&
        gm_valid(left_ptr, sizeof("Intro.ENG")) &&
        gm_valid(right_ptr, sizeof("Intro.")) &&
        std::memcmp(g_mem + left_ptr, "Intro.ENG", sizeof("Intro.ENG")) == 0 &&
        std::memcmp(g_mem + right_ptr, "Intro.", sizeof("Intro.")) == 0) {
        static std::atomic<uint32_t> probe_hits{0};
        const uint32_t hit = probe_hits.fetch_add(1, std::memory_order_relaxed) + 1;
        if (hit <= 8 || (hit & (hit - 1)) == 0)
            std::fprintf(stderr, "[reflex-intro-probe] exact Intro. -> Intro.ENG match count=%u\n", hit);
        rc = 0;
    }
    if (ret == 0x0084a8f0u) {
        // Keep power-of-two samples for diagnosing the current UI lookup
        // loop, but only materialize names when a sample is emitted.
        static std::atomic<uint64_t> count{0};
        const uint64_t n = count.fetch_add(1, std::memory_order_relaxed) + 1;
        if ((n & (n - 1)) == 0) {
            const std::string left = gm_str(left_ptr, 64);
            const std::string right = gm_str(right_ptr, 64);
            fprintf(stderr,
                    "[reflex-stricmp] call=%llu ret=%08x lhs=%08x \"%s\" rhs=%08x \"%s\" rc=%d esi=%08x edi=%08x ebx=%08x ecx=%08x\n",
                    static_cast<unsigned long long>(n), ret, left_ptr,
                    left.c_str(), right_ptr, right.c_str(), rc,
                    c->r[R_ESI], c->r[R_EDI], c->r[R_EBX], c->r[R_ECX]);
        }
    }
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

void crt_strstr(X86 *c) {
    const uint32_t hay_ptr = arg(c, 0);
    const uint32_t needle_ptr = arg(c, 1);
    if (!hay_ptr || !needle_ptr) {
        set_eax(c, 0);
        return;
    }
    const std::string hay = gm_str(hay_ptr, 0x100000);
    const std::string needle = gm_str(needle_ptr, 0x100000);
    const size_t pos = hay.find(needle);
    set_eax(c, pos == std::string::npos ? 0u : hay_ptr + static_cast<uint32_t>(pos));
}

void crt_strncat(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t src = arg(c, 1);
    const uint32_t count = arg(c, 2);
    if (!dst || !src) {
        set_eax(c, dst);
        return;
    }

    const std::string current = gm_str(dst, 0x100000);
    const std::string source = gm_str(src, 0x100000);
    const uint32_t append =
        static_cast<uint32_t>(std::min<size_t>(source.size(), count));
    const uint64_t end64 = uint64_t(dst) + current.size();
    if (end64 > 0xffffffffu) {
        set_eax(c, dst);
        return;
    }
    const uint32_t end = static_cast<uint32_t>(end64);
    if (!gm_valid(end, append + 1u)) {
        set_eax(c, dst);
        return;
    }
    if (append)
        memcpy(g_mem + end, source.data(), append);
    g_mem[end + append] = 0;
    set_eax(c, dst);
}

void crt_strpbrk(X86 *c) {
    const uint32_t src = arg(c, 0);
    const uint32_t accept = arg(c, 1);
    if (!src || !accept) {
        set_eax(c, 0);
        return;
    }
    const std::string chars = gm_str(accept, 0x100000);
    for (uint32_t i = 0; i < 0x100000u && gm_valid(src + i, 1); ++i) {
        const char ch = static_cast<char>(g_mem[src + i]);
        if (!ch)
            break;
        if (chars.find(ch) != std::string::npos) {
            set_eax(c, src + i);
            return;
        }
    }
    set_eax(c, 0);
}

std::mutex g_file_mutex;
std::unordered_map<uint32_t, std::FILE *> g_guest_files;
// Diagnostic-only handle for the three-character language.txt startup read.
uint32_t g_guest_language_file = 0;

std::string host_path_for_guest(std::string path) {
    std::replace(path.begin(), path.end(), '\\', '/');
    const bool absolute =
        (!path.empty() && path.front() == '/') ||
        (path.size() >= 2 && std::isalpha(static_cast<unsigned char>(path[0])) &&
         path[1] == ':');
    if (absolute)
        return path;

    const char *exe_env = std::getenv("RECOMP_EXE");
    if (!exe_env || !*exe_env)
        return path;

    std::string exe(exe_env);
    std::replace(exe.begin(), exe.end(), '\\', '/');
    const size_t slash = exe.find_last_of('/');
    if (slash == std::string::npos)
        return path;
    return exe.substr(0, slash + 1) + path;
}

std::FILE *guest_file_locked(uint32_t handle) {
    const auto it = g_guest_files.find(handle);
    return it == g_guest_files.end() ? nullptr : it->second;
}

void crt_fopen(X86 *c) {
    const std::string guest_path = gm_str(arg(c, 0), 4096);
    const std::string mode = gm_str(arg(c, 1), 64);
    const std::string host_path = host_path_for_guest(guest_path);
    std::FILE *file = std::fopen(host_path.c_str(), mode.c_str());
    if (!file) {
        fprintf(stderr,
                "[recomp] fopen failed: guest=\"%s\" host=\"%s\" mode=\"%s\"\\n",
                guest_path.c_str(), host_path.c_str(), mode.c_str());
        set_eax(c, 0);
        return;
    }

    constexpr uint32_t kGuestFileSize = 32;
    const uint32_t handle = heap_alloc(kGuestFileSize, true);
    if (!handle) {
        std::fclose(file);
        set_eax(c, 0);
        return;
    }

    // Keep a plausible VS2008 FILE shell in guest memory. Reflex normally
    // treats FILE* as opaque, but the _file field is useful if anything peeks.
    wr32(handle + 16, 3);
    {
        std::lock_guard<std::mutex> lock(g_file_mutex);
        g_guest_files.emplace(handle, file);
        if (guest_path == "language.txt")
            g_guest_language_file = handle;
    }
    fprintf(stderr,
            "[recomp] fopen ok: guest=\"%s\" mode=\"%s\" handle=%08x\\n",
            guest_path.c_str(), mode.c_str(), handle);
    set_eax(c, handle);
}

void crt_fclose(X86 *c) {
    const uint32_t handle = arg(c, 0);
    std::FILE *file = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_file_mutex);
        const auto it = g_guest_files.find(handle);
        if (it != g_guest_files.end()) {
            file = it->second;
            g_guest_files.erase(it);
            if (g_guest_language_file == handle)
                g_guest_language_file = 0;
        }
    }
    if (!file) {
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    const int rc = std::fclose(file);
    if (heap_owns(handle))
        heap_free(handle);
    set_eax(c, static_cast<uint32_t>(rc));
}

void crt_fread(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const uint32_t size = arg(c, 1);
    const uint32_t count = arg(c, 2);
    const uint32_t handle = arg(c, 3);
    if (!size || !count) {
        set_eax(c, 0);
        return;
    }
    const uint64_t bytes = uint64_t(size) * uint64_t(count);
    if (bytes > 0xffffffffu || !dst ||
        !gm_valid(dst, static_cast<uint32_t>(bytes))) {
        set_eax(c, 0);
        return;
    }

    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    if (!file) {
        set_eax(c, 0);
        return;
    }
    set_eax(c, static_cast<uint32_t>(
                   std::fread(g_mem + dst, size, count, file)));
}

void crt_fwrite(X86 *c) {
    const uint32_t src = arg(c, 0);
    const uint32_t size = arg(c, 1);
    const uint32_t count = arg(c, 2);
    const uint32_t handle = arg(c, 3);
    if (!size || !count) {
        set_eax(c, 0);
        return;
    }
    const uint64_t bytes = uint64_t(size) * uint64_t(count);
    if (bytes > 0xffffffffu || !src ||
        !gm_valid(src, static_cast<uint32_t>(bytes))) {
        set_eax(c, 0);
        return;
    }

    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    if (!file) {
        set_eax(c, 0);
        return;
    }
    set_eax(c, static_cast<uint32_t>(
                   std::fwrite(g_mem + src, size, count, file)));
}

void crt_fgets(X86 *c) {
    const uint32_t dst = arg(c, 0);
    const int32_t cap = static_cast<int32_t>(arg(c, 1));
    const uint32_t handle = arg(c, 2);
    if (!dst || cap <= 0 || !gm_valid(dst, static_cast<uint32_t>(cap))) {
        set_eax(c, 0);
        return;
    }

    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    if (!file) {
        set_eax(c, 0);
        return;
    }
    char *line = std::fgets(reinterpret_cast<char *>(g_mem + dst), cap, file);
    if (handle == g_guest_language_file) {
        // The game opens language.txt at 0088175e and passes a 4-byte
        // character buffer to fgets at 00881773. Record the real source
        // bytes, not resource-manager synchronization state. Never read past
        // cap or past the guest arena and never alter the stream.
        uint32_t bytes[4] = {};
        if (line) {
            for (uint32_t i = 0; i < 4 && i < static_cast<uint32_t>(cap); ++i)
                bytes[i] = g_mem[dst + i];
        }
        std::fprintf(stderr,
                     "[reflex-locale] language.txt fgets cap=%d ok=%u "
                     "bytes=%02x:%02x:%02x:%02x\n",
                     cap, line ? 1u : 0u, bytes[0], bytes[1],
                     bytes[2], bytes[3]);
    }
    set_eax(c, line ? dst : 0u);
}

void crt_fseek(X86 *c) {
    const uint32_t handle = arg(c, 0);
    const int32_t offset = static_cast<int32_t>(arg(c, 1));
    const int origin = static_cast<int>(arg(c, 2));
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    set_eax(c, file ? static_cast<uint32_t>(std::fseek(file, offset, origin))
                    : static_cast<uint32_t>(-1));
}

void crt_ftell(X86 *c) {
    const uint32_t handle = arg(c, 0);
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    if (!file) {
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    const long pos = std::ftell(file);
    if (pos < 0 || static_cast<unsigned long>(pos) > 0x7ffffffful)
        set_eax(c, static_cast<uint32_t>(-1));
    else
        set_eax(c, static_cast<uint32_t>(pos));
}

void crt_feof(X86 *c) {
    const uint32_t handle = arg(c, 0);
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    set_eax(c, file ? static_cast<uint32_t>(std::feof(file)) : 1u);
}

void crt_fgetc(X86 *c) {
    const uint32_t handle = arg(c, 0);
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    set_eax(c, file ? static_cast<uint32_t>(std::fgetc(file))
                    : static_cast<uint32_t>(-1));
}

void crt_ungetc(X86 *c) {
    const int ch = static_cast<int>(arg(c, 0));
    const uint32_t handle = arg(c, 1);
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    set_eax(c, file ? static_cast<uint32_t>(std::ungetc(ch, file))
                    : static_cast<uint32_t>(-1));
}

void crt_rewind(X86 *c) {
    const uint32_t handle = arg(c, 0);
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    if (file)
        std::rewind(file);
    set_eax(c, 0);
}

void crt_fflush(X86 *c) {
    const uint32_t handle = arg(c, 0);
    std::lock_guard<std::mutex> lock(g_file_mutex);
    std::FILE *file = guest_file_locked(handle);
    set_eax(c, file ? static_cast<uint32_t>(std::fflush(file))
                    : static_cast<uint32_t>(-1));
}

void crt_cipow(X86 *c) {
    // MSVC's _CIpow is cdecl with a compiler-known x87 convention:
    // ST(0)=exponent, ST(1)=base, and it consumes both values leaving x^y.
    const uint32_t y_slot = c->fpu_top & 7u;
    const uint32_t x_slot = (c->fpu_top + 1u) & 7u;
    const uint16_t y_tag = (c->fpu_tag >> (2u * y_slot)) & 3u;
    const uint16_t x_tag = (c->fpu_tag >> (2u * x_slot)) & 3u;
    if (y_tag == 3u || x_tag == 3u) {
        set_eax(c, 0);
        return;
    }

    const double result = std::pow(c->st[x_slot], c->st[y_slot]);
    c->fpu_tag |= static_cast<uint16_t>(3u << (2u * y_slot));
    c->fpu_top = (c->fpu_top + 1u) & 7u;
    c->st[x_slot] = result;
    c->st_bits[x_slot] = 0;
    c->st_exact[x_slot] = 0;
    c->fpu_tag &= static_cast<uint16_t>(~(3u << (2u * x_slot)));
    c->fpu_sw =
        static_cast<uint16_t>((c->fpu_sw & ~0x3800u) | ((c->fpu_top & 7u) << 11));
    set_eax(c, 0);
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

// Safe-string exports must not report success when they cannot copy or
// terminate the caller's destination. MSVC returns errno_t and expects the
// destination to become an empty string on valid-buffer failure.
void crt_strcpy_s(X86 *c) {
    const uint32_t dst = arg(c, 0), cap = arg(c, 1), src = arg(c, 2);
    if (!dst || !cap || !gm_valid(dst, 1) || !gm_valid(dst, cap)) {
        set_eax(c, EINVAL);
        return;
    }
    if (!src || !gm_valid(src, 1)) {
        g_mem[dst] = 0;
        set_eax(c, EINVAL);
        return;
    }
    const std::string data = gm_str(src, 0x100000u);
    if (data.size() >= cap) {
        g_mem[dst] = 0;
        set_eax(c, ERANGE);
        return;
    }
    memmove(g_mem + dst, data.c_str(), data.size() + 1);
    set_eax(c, 0);
}

void crt_strlwr_s(X86 *c) {
    const uint32_t ptr = arg(c, 0), cap = arg(c, 1);
    if (!ptr || !cap || !gm_valid(ptr, cap)) {
        set_eax(c, EINVAL);
        return;
    }
    uint32_t length = 0;
    while (length < cap && g_mem[ptr + length]) ++length;
    if (length == cap) {
        g_mem[ptr] = 0;
        set_eax(c, EINVAL);
        return;
    }
    for (uint32_t i = 0; i < length; ++i) {
        const uint8_t v = g_mem[ptr + i];
        g_mem[ptr + i] =
            static_cast<uint8_t>(std::tolower(static_cast<unsigned char>(v)));
    }
    set_eax(c, 0);
}

// MSVCR90's internal SSE2 math helpers use XMM0 as both argument and
// return register (not x87 ST(0), and not the normal stack double ABI).
// Verified against Wine's 32-bit MSVCR implementation and export table.
void crt_libm_sse2_exp(X86 *c) {
    xmm_set_f64(c, 0, std::exp(xmm_f64(c, 0)));
}

void crt_libm_sse2_expf(X86 *c) {
    xmm_set_f32(c, 0, std::exp(xmm_f32(c, 0)));
}

// MSVC x86 RTTI uses absolute guest pointers (unlike x64's relative RVAs).
// The vfptr[-1] locator names the complete type and its base class table.
// Support unambiguous, public, nonvirtual or virtual base conversions without
// guessing an object when metadata is absent. A pointer cast legitimately
// returns null on mismatch. Reference bad_cast exceptions are not yet bridged.
bool rtti_add(uint32_t base, int64_t delta, uint32_t &out) {
    const int64_t value = static_cast<int64_t>(base) + delta;
    if (value < 0x10000 || value >= static_cast<int64_t>(0x10000000u))
        return false;
    out = static_cast<uint32_t>(value);
    return true;
}

bool rtti_type_equal(uint32_t left, uint32_t right) {
    if (left == right) return left != 0;
    if (!left || !right || !gm_valid(left + 8u, 1) ||
        !gm_valid(right + 8u, 1)) return false;
    const std::string a = gm_str(left + 8u, 256);
    const std::string b = gm_str(right + 8u, 256);
    return !a.empty() && a == b;
}

// MSVCR90 _setjmp3 stores the x86 nonvolatile registers, caller ESP and
// return EIP in its 64-byte jmp_buf, followed by the SEH registration and
// optional unwind metadata. Saving the context is important: reporting
// success while leaving jmp_buf uninitialized corrupts a later longjmp.
void crt_setjmp3(X86 *c) {
    const uint32_t jmp = arg(c, 0);
    const uint32_t count = arg(c, 1);
    if (!jmp || !gm_valid(jmp, 64) || count > 64u) {
        set_eax(c, static_cast<uint32_t>(EINVAL));
        return;
    }
    wr32(jmp + 0u, c->r[R_EBP]);
    wr32(jmp + 4u, c->r[R_EBX]);
    wr32(jmp + 8u, c->r[R_EDI]);
    wr32(jmp + 12u, c->r[R_ESI]);
    wr32(jmp + 16u, c->r[R_ESP]);
    wr32(jmp + 20u, gm_valid(c->r[R_ESP], 4) ? rd32(c->r[R_ESP]) : 0);
    const uint32_t registration =
        gm_valid(c->fs_base, 4) ? rd32(c->fs_base) : 0xffffffffu;
    wr32(jmp + 24u, registration);
    uint32_t try_level = 0xffffffffu;
    if (registration != 0xffffffffu && registration &&
        gm_valid(registration + 12u, 4))
        try_level = rd32(registration + 12u);
    wr32(jmp + 28u, count > 1 ? arg(c, 3) : try_level);
    wr32(jmp + 32u, 0x56433230u); // MSVCRT_JMP_MAGIC
    wr32(jmp + 36u, count ? arg(c, 2) : 0u);
    for (uint32_t i = 0; i < 6; ++i)
        wr32(jmp + 40u + 4u * i, count > i + 2 ? arg(c, 4 + i) : 0u);
    set_eax(c, 0);
}

void crt_debugger_hook(X86 *c) {
    // _crt_debugger_hook(int) is a debugger integration hook, not a
    // program-control or math operation. No debugger is attached.
    set_eax(c, 0);
}

void crt_rt_dynamic_cast(X86 *c) {
    const uint32_t input = arg(c, 0);
    const int32_t vf_delta = static_cast<int32_t>(arg(c, 1));
    const uint32_t source = arg(c, 2), target = arg(c, 3);
    const bool reference = arg(c, 4) != 0;
    uint32_t result = 0, vf_at = 0, complete = 0;
    uint32_t col = 0, hierarchy = 0, count = 0;

    if (input && source && target && rtti_type_equal(source, target)) {
        // Identity casts never require moving the pointer.
        result = input;
    } else if (input && source && target &&
               rtti_add(input, vf_delta, vf_at) && gm_valid(vf_at, 4)) {
        const uint32_t vtable = rd32(vf_at);
        if (vtable >= 0x10004u && gm_valid(vtable - 4u, 4))
            col = rd32(vtable - 4u);
        if (col && gm_valid(col, 20) && rd32(col) == 0u &&
            rd32(col + 4u) < 0x100000u &&
            rtti_add(vf_at, -static_cast<int64_t>(rd32(col + 4u)), complete)) {
            hierarchy = rd32(col + 16u);
            if (hierarchy && gm_valid(hierarchy, 16)) {
                count = rd32(hierarchy + 8u);
                const uint32_t bases = rd32(hierarchy + 12u);
                if (count > 0 && count <= 2048 &&
                    bases && gm_valid(bases, count * 4u)) {
                    bool source_found = false;
                    bool target_found = false;
                    bool ambiguous = false;
                    uint32_t candidate = 0;
                    for (uint32_t i = 0; i < count; ++i) {
                        const uint32_t base = rd32(bases + i * 4u);
                        if (!base || !gm_valid(base, 24)) continue;
                        const uint32_t type = rd32(base);
                        if (rtti_type_equal(type, source)) source_found = true;
                        if (!rtti_type_equal(type, target)) continue;
                        const uint32_t attributes = rd32(base + 20u);
                        // Not visible, ambiguous, and private/protected base
                        // descriptors cannot supply an accessible cast.
                        if (attributes & 0x0fu) continue;
                        const int32_t mdisp = static_cast<int32_t>(rd32(base + 8u));
                        const int32_t pdisp = static_cast<int32_t>(rd32(base + 12u));
                        const int32_t vdisp = static_cast<int32_t>(rd32(base + 16u));
                        uint32_t address = 0;
                        if (!rtti_add(complete, mdisp, address)) continue;
                        if (pdisp != -1) {
                            uint32_t vbptr_addr = 0, vbindex = 0;
                            if (!rtti_add(complete, pdisp, vbptr_addr) ||
                                !gm_valid(vbptr_addr, 4)) continue;
                            const uint32_t vbtable = rd32(vbptr_addr);
                            if (!rtti_add(vbtable, vdisp, vbindex) ||
                                !gm_valid(vbindex, 4)) continue;
                            const int32_t vb_adjust =
                                static_cast<int32_t>(rd32(vbindex));
                            if (!rtti_add(address, vb_adjust, address)) continue;
                        }
                        if (!gm_valid(address, 1)) continue;
                        if (target_found && candidate != address) ambiguous = true;
                        candidate = address;
                        target_found = true;
                    }
                    if (source_found && target_found && !ambiguous)
                        result = candidate;
                }
            }
        }
    }
    fprintf(stderr,
            "[reflex-rtti] __RTDynamicCast input=%08x vfdelta=%d source=%08x target=%08x ref=%u col=%08x hierarchy=%08x bases=%u complete=%08x result=%08x\n",
            input, vf_delta, source, target, reference ? 1u : 0u,
            col, hierarchy, count, complete, result);
    if (reference && !result)
        fprintf(stderr, "[reflex-rtti] reference bad_cast still unsupported\n");
    set_eax(c, result);
}

void crt_copysign(X86 *c) {
    // MSVCR90.dll!_copysign(double, double) takes two 64-bit stack
    // arguments and returns double in x87 ST(0) on 32-bit Windows.
    const uint32_t args = c->r[R_ESP] + 4;
    if (!gm_valid(args, 16)) {
        fpush(c, 0.0);
        return;
    }
    const double magnitude = rdf64(args);
    const double sign = rdf64(args + 8);
    fpush(c, std::copysign(magnitude, sign));
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

void crt_toupper(X86 *c) {
    const int32_t v = static_cast<int32_t>(arg(c, 0));
    if (v >= 0 && v <= 255)
        set_eax(c, static_cast<uint32_t>(std::toupper(static_cast<unsigned char>(v))));
    else
        set_eax(c, static_cast<uint32_t>(v));
}

template <int (*Pred)(int)>
void crt_ctype_predicate(X86 *c) {
    const int32_t v = static_cast<int32_t>(arg(c, 0));
    if (v < 0 || v > 255) {
        set_eax(c, 0);
        return;
    }
    set_eax(c, Pred(static_cast<unsigned char>(v)) ? 1u : 0u);
}

void crt_isdigit(X86 *c) { crt_ctype_predicate<std::isdigit>(c); }
void crt_isalpha(X86 *c) { crt_ctype_predicate<std::isalpha>(c); }
void crt_isalnum(X86 *c) { crt_ctype_predicate<std::isalnum>(c); }
void crt_isspace(X86 *c) { crt_ctype_predicate<std::isspace>(c); }
void crt_isxdigit(X86 *c) { crt_ctype_predicate<std::isxdigit>(c); }
void crt_islower(X86 *c) { crt_ctype_predicate<std::islower>(c); }
void crt_isupper(X86 *c) { crt_ctype_predicate<std::isupper>(c); }
void crt_ispunct(X86 *c) { crt_ctype_predicate<std::ispunct>(c); }

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

void crt_aligned_realloc(X86 *c) {
    const uint32_t old_ptr = arg(c, 0);
    const uint32_t new_size = arg(c, 1);
    uint32_t alignment = arg(c, 2);
    if (alignment < 16)
        alignment = 16;
    if ((alignment & (alignment - 1)) != 0) {
        set_eax(c, 0);
        return;
    }
    if (!old_ptr) {
        set_eax(c, heap_alloc(new_size, false, alignment));
        return;
    }
    if (!new_size) {
        heap_free(old_ptr);
        set_eax(c, 0);
        return;
    }

    const uint32_t old_size = heap_size(old_ptr);
    if (old_size == 0xffffffffu) {
        set_eax(c, 0);
        return;
    }

    // heap_realloc() only guarantees the base 16-byte alignment. Allocate a
    // new aligned block explicitly so MSVC's _aligned_realloc contract remains
    // true even when the allocation has to move.
    const uint32_t fresh = heap_alloc(new_size, false, alignment);
    if (!fresh) {
        set_eax(c, 0);
        return;
    }
    const uint32_t copy = std::min(old_size, new_size);
    if (copy)
        std::memmove(g_mem + fresh, g_mem + old_ptr, copy);
    heap_free(old_ptr);
    set_eax(c, fresh);
}

void crt_aligned_free(X86 *c) {
    const uint32_t p = arg(c, 0);
    if (p)
        heap_free(p);
    set_eax(c, 0);
}

void crt_atol(X86 *c) {
    const uint32_t src = arg(c, 0);
    const std::string input = src && gm_valid(src, 1) ? gm_str(src, 4096) : "";
    set_eax(c, reflex_crt::parse_signed32(input, 10).value);
}

void crt_strtoul(X86 *c) {
    const uint32_t src = arg(c, 0), end_out = arg(c, 1);
    const int base = static_cast<int>(arg(c, 2));
    if (!src || !gm_valid(src, 1) || !reflex_crt::valid_base(base)) {
        if (end_out && gm_valid(end_out, 4))
            wr32(end_out, src);
        set_eax(c, 0);
        return;
    }

    const std::string input = gm_str(src, 4096);
    const auto result = reflex_crt::parse_unsigned32(input, base);
    if (end_out && gm_valid(end_out, 4))
        wr32(end_out, src + static_cast<uint32_t>(result.consumed));
    set_eax(c, result.value);
}

// All five functions below are cdecl MSVCR90 exports. Import shims never
// modify the guest ESP; the dispatcher pops only the return address. The
// floating-point conversion functions return their double in x87 ST(0),
// not EAX (unlike the integer parsers).
void crt_strtol(X86 *c) {
    const uint32_t src = arg(c, 0), end_out = arg(c, 1);
    const int base = static_cast<int>(arg(c, 2));
    if (!src || !gm_valid(src, 1) || !reflex_crt::valid_base(base)) {
        if (end_out && gm_valid(end_out, 4))
            wr32(end_out, src);
        set_eax(c, 0);
        return;
    }
    const std::string input = gm_str(src, 4096);
    const auto result = reflex_crt::parse_signed32(input, base);
    if (end_out && gm_valid(end_out, 4))
        wr32(end_out, src + static_cast<uint32_t>(result.consumed));
    set_eax(c, result.value);
}

void crt_strtod(X86 *c) {
    const uint32_t src = arg(c, 0), end_out = arg(c, 1);
    if (!src || !gm_valid(src, 1)) {
        if (end_out && gm_valid(end_out, 4)) wr32(end_out, src);
        fpush(c, 0.0);
        return;
    }
    const std::string data = gm_str(src, 4096);
    errno = 0;
    char *end = nullptr;
    const double result = std::strtod(data.c_str(), &end);
    const size_t consumed = end && end >= data.c_str()
        ? static_cast<size_t>(end - data.c_str()) : 0;
    if (end_out && gm_valid(end_out, 4))
        wr32(end_out, src + static_cast<uint32_t>(std::min(consumed, data.size())));
    fpush(c, result);
}

void crt_atof(X86 *c) {
    const uint32_t src = arg(c, 0);
    const std::string data = src && gm_valid(src, 1) ? gm_str(src, 4096) : "";
    fpush(c, std::strtod(data.c_str(), nullptr));
}

void crt_strcspn(X86 *c) {
    const uint32_t src = arg(c, 0), reject = arg(c, 1);
    if (!src || !reject || !gm_valid(src, 1) || !gm_valid(reject, 1)) {
        set_eax(c, 0);
        return;
    }
    const std::string hay = gm_str(src, 0x100000);
    const std::string chars = gm_str(reject, 0x100000);
    const size_t pos = hay.find_first_of(chars);
    set_eax(c, static_cast<uint32_t>(pos == std::string::npos ? hay.size() : pos));
}

// VS2008's struct lconv begins with ten x86 char* fields followed by
// one-byte format codes. Host pointers are never exposed to guest code.
std::mutex g_crt_locale_mutex;
uint32_t g_crt_locale = 0;
void crt_localeconv(X86 *c) {
    std::lock_guard<std::mutex> lock(g_crt_locale_mutex);
    if (!g_crt_locale || !heap_owns(g_crt_locale)) {
        const uint32_t block = heap_alloc(64, true, 16);
        const uint32_t point = heap_alloc(2, true, 16);
        const uint32_t empty = heap_alloc(1, true, 16);
        if (!block || !point || !empty) {
            if (block) heap_free(block);
            if (point) heap_free(point);
            if (empty) heap_free(empty);
            set_eax(c, 0);
            return;
        }
        g_mem[point] = '.';
        g_mem[point + 1] = 0;
        g_mem[empty] = 0;
        // decimal_point + 9 additional pointers: all empty in the C locale.
        wr32(block, point);
        for (unsigned i = 1; i < 10; ++i) wr32(block + i * 4, empty);
        // CHAR_MAX denotes an unavailable international monetary field.
        memset(g_mem + block + 40, 0x7f, 24);
        g_crt_locale = block;
    }
    set_eax(c, g_crt_locale);
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

// IUnknown and D3DX9 GUIDs in little-endian x86 memory order.
// IID_ID3DXConstantTable changes at SDK 43; this DLL uses the SDK 43 IID.
// The table also inherits ID3DXBuffer and therefore supports that IID.
static const uint8_t kIidIUnknown[16] =
    {0,0,0,0,0,0,0,0,0xc0,0,0,0,0,0,0,0x46};
static const uint8_t kIidD3dxBuffer[16] =
    {0x08,0xfb,0xa5,0x8b,0x95,0x51,0xe2,0x40,0xac,0x58,0x0d,0x98,0x9c,0x3a,0x01,0x02};
static const uint8_t kIidD3dxConstantTable43[16] =
    {0x8f,0x75,0x3c,0xab,0x3e,0x09,0x56,0x43,0xb7,0x62,0x4d,0xb1,0x8f,0x1b,0x3a,0x01};

bool d3dx_supported_iid(uint32_t iid, bool constant_table) {
    if (!iid || !gm_valid(iid, 16))
        return false;
    return memcmp(g_mem + iid, kIidIUnknown, 16) == 0 ||
           memcmp(g_mem + iid, kIidD3dxBuffer, 16) == 0 ||
           (constant_table &&
            memcmp(g_mem + iid, kIidD3dxConstantTable43, 16) == 0);
}

uint32_t g_d3dx_buffer_vtable = 0;

void d3dx_buffer_query_interface(X86 *c) {
    const uint32_t self = arg(c, 0), iid = arg(c, 1), out = arg(c, 2);
    if (!out || !gm_valid(out, 4)) {
        set_eax(c, 0x80004003u); // E_POINTER
        return;
    }
    wr32(out, 0);
    if (!self || !gm_valid(self, 16) || !d3dx_supported_iid(iid, false)) {
        set_eax(c, 0x80004002u); // E_NOINTERFACE
        return;
    }
    const uint32_t refs = rd32(self + 4);
    if (refs != UINT32_MAX)
        wr32(self + 4, refs + 1);
    wr32(out, self);
    set_eax(c, 0); // S_OK
}

void d3dx_buffer_addref(X86 *c) {
    const uint32_t self = arg(c, 0);
    if (!self || !gm_valid(self, 16)) {
        set_eax(c, 0);
        return;
    }
    uint32_t refs = rd32(self + 4);
    if (refs != UINT32_MAX)
        ++refs;
    wr32(self + 4, refs);
    set_eax(c, refs);
}

void d3dx_buffer_release(X86 *c) {
    const uint32_t self = arg(c, 0);
    if (!self || !gm_valid(self, 16)) {
        set_eax(c, 0);
        return;
    }
    uint32_t refs = rd32(self + 4);
    if (refs)
        --refs;
    if (!refs) {
        const uint32_t data = rd32(self + 8);
        if (data && heap_owns(data))
            heap_free(data);
        if (heap_owns(self))
            heap_free(self);
    } else {
        wr32(self + 4, refs);
    }
    set_eax(c, refs);
}

void d3dx_buffer_pointer(X86 *c) {
    const uint32_t self = arg(c, 0);
    set_eax(c, self && gm_valid(self, 16) ? rd32(self + 8) : 0);
}

void d3dx_buffer_size(X86 *c) {
    const uint32_t self = arg(c, 0);
    set_eax(c, self && gm_valid(self, 16) ? rd32(self + 12) : 0);
}

uint32_t d3dx_buffer_vtable() {
    if (g_d3dx_buffer_vtable && heap_owns(g_d3dx_buffer_vtable))
        return g_d3dx_buffer_vtable;

    const uint32_t vt = heap_alloc(5 * 4, true, 16);
    if (!vt)
        return 0;

    const struct {
        const char *name;
        uint8_t argc;
        void (*fn)(X86 *);
    } methods[] = {
        {"ID3DXBuffer::QueryInterface", 3, d3dx_buffer_query_interface},
        {"ID3DXBuffer::AddRef", 1, d3dx_buffer_addref},
        {"ID3DXBuffer::Release", 1, d3dx_buffer_release},
        {"ID3DXBuffer::GetBufferPointer", 1, d3dx_buffer_pointer},
        {"ID3DXBuffer::GetBufferSize", 1, d3dx_buffer_size},
    };

    for (uint32_t i = 0; i < 5; ++i) {
        const uint32_t tramp = imports_alloc_trampoline(
            "d3dx9_43.dll", methods[i].name, methods[i].fn, methods[i].argc);
        if (!tramp) {
            heap_free(vt);
            return 0;
        }
        wr32(vt + i * 4, tramp);
    }
    g_d3dx_buffer_vtable = vt;
    return vt;
}

uint32_t d3dx_make_source_buffer(uint32_t src, uint32_t size) {
    const uint32_t vt = d3dx_buffer_vtable();
    if (!vt || !src || !size || !gm_valid(src, size))
        return 0;

    const uint32_t data = heap_alloc(size + 1, true, 16);
    const uint32_t obj = heap_alloc(16, true, 16);
    if (!data || !obj) {
        if (data)
            heap_free(data);
        if (obj)
            heap_free(obj);
        return 0;
    }

    memcpy(g_mem + data, g_mem + src, size);
    wr32(obj + 0, vt);
    wr32(obj + 4, 1);
    wr32(obj + 8, data);
    wr32(obj + 12, size);
    return obj;
}

void d3dx_compile_shader_bridge(X86 *c) {
    // Reflex compiles a small set of embedded SM3 fullscreen shaders at
    // startup. For bring-up, expose the source through a correct ID3DXBuffer
    // object so the game's COM lifetime and GetBufferPointer calls are valid.
    // The pinned D3D9 Create*Shader methods are currently non-consuming stubs;
    // real HLSL -> SM3 compilation is the next renderer milestone.
    const uint32_t shader_out = arg(c, 7);
    const uint32_t error_out = arg(c, 8);
    const uint32_t constants_out = arg(c, 9);
    for (uint32_t out : {shader_out, error_out, constants_out})
        if (out && gm_valid(out, 4))
            wr32(out, 0);

    const uint32_t src = arg(c, 0);
    const uint32_t size = arg(c, 1);
    if (!shader_out || !gm_valid(shader_out, 4) || !src || !size || !gm_valid(src, size)) {
        set_eax(c, 0x80070057u); // E_INVALIDARG
        return;
    }

    const uint32_t buffer = d3dx_make_source_buffer(src, size);
    if (!buffer) {
        set_eax(c, 0x8007000eu); // E_OUTOFMEMORY
        return;
    }

    wr32(shader_out, buffer);
    const std::string entry = gm_str(arg(c, 4), 128);
    const std::string profile = gm_str(arg(c, 5), 128);
    fprintf(stderr, "[recomp] D3DXCompileShader bridge: entry=%s profile=%s bytes=%u buffer=%08x\\n",
            entry.c_str(), profile.c_str(), size, buffer);
    set_eax(c, 0); // S_OK
}

// D3DX9 shader constant tables are COM objects which also implement ID3DXBuffer.
// Keep their vtables and backing metadata in guest memory: the translated x86
// code dereferences both directly after D3DXGetShaderConstantTable succeeds.
struct ReflexConstant {
    uint32_t desc = 0; // stable D3DXHANDLE, points at a guest D3DXCONSTANT_DESC
    uint32_t name = 0;
    uint32_t register_set = 0;
    uint32_t register_index = 0;
};

struct ReflexConstantTable {
    uint32_t refs = 1;
    uint32_t ctab = 0;
    uint32_t ctab_size = 0;
    uint32_t creator = 0;
    uint32_t version = 0;
    std::vector<ReflexConstant> constants;
};

std::mutex g_d3dx_ctab_mutex;
std::unordered_map<uint32_t, ReflexConstantTable> g_d3dx_ctabs;
uint32_t g_d3dx_ctab_vtable = 0;

constexpr uint32_t kD3dInvalidCall = 0x8876086cu;
constexpr uint32_t kD3dxInvalidData = 0x88760b59u;
constexpr uint32_t kNoInterface = 0x80004002u;
constexpr uint32_t kOutOfMemory = 0x8007000eu;

bool ctab_range(uint32_t size, uint32_t offset, uint32_t bytes) {
    return offset <= size && bytes <= size - offset;
}

uint32_t ctab_offset_ptr(uint32_t base, uint32_t size, uint32_t offset) {
    return offset && ctab_range(size, offset, 1) ? base + offset : 0;
}

ReflexConstantTable *d3dx_table(uint32_t object) {
    auto it = g_d3dx_ctabs.find(object);
    return it == g_d3dx_ctabs.end() ? nullptr : &it->second;
}

const ReflexConstant *d3dx_constant(const ReflexConstantTable &table, uint32_t handle) {
    for (const auto &entry : table.constants)
        if (entry.desc == handle) return &entry;
    return nullptr;
}

void d3dx_ctab_query_interface(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const uint32_t self = arg(c, 0), iid = arg(c, 1), out = arg(c, 2);
    if (!out || !gm_valid(out, 4)) {
        set_eax(c, 0x80004003u); // E_POINTER
        return;
    }
    wr32(out, 0);
    ReflexConstantTable *table = d3dx_table(self);
    if (!table || !d3dx_supported_iid(iid, true)) {
        set_eax(c, kNoInterface);
        return;
    }
    if (table->refs != UINT32_MAX)
        ++table->refs;
    wr32(out, self);
    set_eax(c, 0);
}

void d3dx_ctab_addref(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    ReflexConstantTable *table = d3dx_table(arg(c, 0));
    set_eax(c, table ? ++table->refs : 0);
}

void d3dx_ctab_release(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const uint32_t self = arg(c, 0);
    auto it = g_d3dx_ctabs.find(self);
    if (it == g_d3dx_ctabs.end()) { set_eax(c, 0); return; }
    if (--it->second.refs) { set_eax(c, it->second.refs); return; }
    for (const auto &entry : it->second.constants)
        heap_free(entry.desc);
    heap_free(it->second.ctab);
    heap_free(self);
    g_d3dx_ctabs.erase(it);
    set_eax(c, 0);
}

void d3dx_ctab_get_buffer_pointer(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    set_eax(c, table ? table->ctab : 0);
}

void d3dx_ctab_get_buffer_size(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    set_eax(c, table ? table->ctab_size : 0);
}

void d3dx_ctab_get_desc(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    const uint32_t out = arg(c, 1);
    if (!table || !out || !gm_valid(out, 12)) {
        set_eax(c, kD3dInvalidCall);
        return;
    }
    wr32(out + 0, table->creator);
    wr32(out + 4, table->version);
    wr32(out + 8, static_cast<uint32_t>(table->constants.size()));
    fprintf(stderr, "[reflex-d3dx] ConstantTable::GetDesc version=%08x constants=%zu\n",
            table->version, table->constants.size());
    set_eax(c, 0);
}

void d3dx_ctab_get_constant_desc(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    const uint32_t desc = arg(c, 2), count = arg(c, 3);
    if (!table || !count || !gm_valid(count, 4)) {
        set_eax(c, kD3dInvalidCall);
        return;
    }
    const auto *entry = d3dx_constant(*table, arg(c, 1));
    const uint32_t capacity = rd32(count);
    wr32(count, entry ? 1 : 0);
    if (!entry || !capacity || !desc || !gm_valid(desc, 48)) {
        set_eax(c, kD3dInvalidCall);
        return;
    }
    memcpy(g_mem + desc, g_mem + entry->desc, 48);
    set_eax(c, 0);
}

void d3dx_ctab_get_sampler_index(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    const auto *entry = table ? d3dx_constant(*table, arg(c, 1)) : nullptr;
    set_eax(c, entry && entry->register_set == 3 ? entry->register_index : 0xffffffffu);
}

void d3dx_ctab_get_constant(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    const uint32_t parent = arg(c, 1), index = arg(c, 2);
    set_eax(c, table && !parent && index < table->constants.size()
                   ? table->constants[index].desc : 0);
}

void d3dx_ctab_get_constant_by_name(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    const uint32_t parent = arg(c, 1), name = arg(c, 2);
    if (!table || parent || !name || !gm_valid(name, 1)) {
        set_eax(c, 0);
        return;
    }
    const std::string wanted = gm_str(name, 256);
    for (const auto &entry : table->constants) {
        if (gm_str(entry.name, 256) == wanted) {
            set_eax(c, entry.desc);
            return;
        }
    }
    set_eax(c, 0);
}

void d3dx_ctab_get_constant_element(X86 *c) {
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const auto *table = d3dx_table(arg(c, 0));
    const auto *entry = table ? d3dx_constant(*table, arg(c, 1)) : nullptr;
    // Scalar/first-element handles are identical. Nested arrays need a
    // descriptor expansion pass when they are first used by the guest.
    set_eax(c, entry && arg(c, 2) == 0 ? entry->desc : 0);
}

void d3dx_ctab_set_unsupported(X86 *c) {
    // Shader constant writes require forwarding to the host device. Do not
    // claim a successful render-state update until that bridge exists.
    set_eax(c, kD3dInvalidCall);
}

void d3dx_ctab_set_defaults(X86 *c) {
    // No default values have been applied; explicit setters remain unsupported.
    set_eax(c, kD3dInvalidCall);
}

uint32_t d3dx_ctab_vtable() {
    if (g_d3dx_ctab_vtable && heap_owns(g_d3dx_ctab_vtable))
        return g_d3dx_ctab_vtable;
    // ABI from d3dx9shader.h: IUnknown(3), ID3DXBuffer(2), then 20
    // constant-table methods. Including these two inherited methods is
    // essential: GetDesc is slot 5, not slot 3.
    const struct {
        const char *name;
        uint8_t argc;
        void (*fn)(X86 *);
    } methods[] = {
        {"QueryInterface", 3, d3dx_ctab_query_interface},
        {"AddRef", 1, d3dx_ctab_addref},
        {"Release", 1, d3dx_ctab_release},
        {"GetBufferPointer", 1, d3dx_ctab_get_buffer_pointer},
        {"GetBufferSize", 1, d3dx_ctab_get_buffer_size},
        {"GetDesc", 2, d3dx_ctab_get_desc},
        {"GetConstantDesc", 4, d3dx_ctab_get_constant_desc},
        {"GetSamplerIndex", 2, d3dx_ctab_get_sampler_index},
        {"GetConstant", 3, d3dx_ctab_get_constant},
        {"GetConstantByName", 3, d3dx_ctab_get_constant_by_name},
        {"GetConstantElement", 3, d3dx_ctab_get_constant_element},
        {"SetDefaults", 2, d3dx_ctab_set_defaults},
        {"SetValue", 5, d3dx_ctab_set_unsupported},
        {"SetBool", 4, d3dx_ctab_set_unsupported},
        {"SetBoolArray", 5, d3dx_ctab_set_unsupported},
        {"SetInt", 4, d3dx_ctab_set_unsupported},
        {"SetIntArray", 5, d3dx_ctab_set_unsupported},
        {"SetFloat", 4, d3dx_ctab_set_unsupported},
        {"SetFloatArray", 5, d3dx_ctab_set_unsupported},
        {"SetVector", 4, d3dx_ctab_set_unsupported},
        {"SetVectorArray", 5, d3dx_ctab_set_unsupported},
        {"SetMatrix", 4, d3dx_ctab_set_unsupported},
        {"SetMatrixArray", 5, d3dx_ctab_set_unsupported},
        {"SetMatrixPointerArray", 5, d3dx_ctab_set_unsupported},
        {"SetMatrixTranspose", 4, d3dx_ctab_set_unsupported},
        {"SetMatrixTransposeArray", 5, d3dx_ctab_set_unsupported},
        {"SetMatrixTransposePointerArray", 5, d3dx_ctab_set_unsupported},
    };
    static_assert(sizeof(methods) / sizeof(methods[0]) == 27, "D3DX constant-table ABI");
    const uint32_t vt = heap_alloc(sizeof(methods) / sizeof(methods[0]) * 4, true, 16);
    if (!vt) return 0;
    for (uint32_t i = 0; i < sizeof(methods) / sizeof(methods[0]); ++i) {
        const std::string name = std::string("ID3DXConstantTable::") + methods[i].name;
        const uint32_t trampoline = imports_alloc_trampoline(
            "d3dx9_43.dll", name.c_str(), methods[i].fn, methods[i].argc);
        if (!trampoline) { heap_free(vt); return 0; }
        wr32(vt + 4 * i, trampoline);
    }
    g_d3dx_ctab_vtable = vt;
    return vt;
}

// Locate the CTAB shader comment and copy it to owned guest memory. CTAB
// offsets are byte offsets relative to its 28-byte header, not the shader.
bool d3dx_parse_ctab(uint32_t bytecode, ReflexConstantTable &table) {
    if (!bytecode || !gm_valid(bytecode, 4)) return false;
    const uint32_t version = rd32(bytecode);
    if ((version >> 16) != 0xfffeu && (version >> 16) != 0xffffu)
        return false;

    for (uint32_t i = 1; i < 65536; ++i) {
        const uint64_t pos64 = uint64_t(bytecode) + uint64_t(i) * 4;
        if (pos64 > 0xffffffffu || !gm_valid(static_cast<uint32_t>(pos64), 4))
            return false;
        const uint32_t pos = static_cast<uint32_t>(pos64);
        const uint32_t token = rd32(pos);
        if (token == 0xffffu) return false; // D3DSIO_END
        if ((token & 0xffffu) != 0xfffeu) continue; // D3DSIO_COMMENT
        const uint32_t count = (token >> 16) & 0x7fffu;
        if (!count || uint64_t(i) + count >= 65536 ||
            !gm_valid(pos + 4, count * 4)) return false;
        if (rd32(pos + 4) != 0x42415443u) { i += count; continue; } // 'CTAB'
        const uint32_t src = pos + 8, size = (count - 1) * 4;
        if (size < 28 || !gm_valid(src, size) || rd32(src) != 28) return false;
        const uint32_t constants = rd32(src + 12);
        const uint32_t info_offset = rd32(src + 16);
        if (constants > 4096 || !ctab_range(size, info_offset, constants * 20))
            return false;
        table.ctab = heap_alloc(size, false, 16);
        if (!table.ctab) return false;
        memcpy(g_mem + table.ctab, g_mem + src, size);
        table.ctab_size = size;
        table.version = rd32(table.ctab + 8);
        table.creator = ctab_offset_ptr(table.ctab, size, rd32(table.ctab + 4));
        if (table.creator && !memchr(g_mem + table.creator, 0,
                                    size - (table.creator - table.ctab))) return false;
        for (uint32_t j = 0; j < constants; ++j) {
            const uint32_t info = table.ctab + info_offset + 20 * j;
            const uint32_t name = ctab_offset_ptr(table.ctab, size, rd32(info));
            const uint32_t type_offset = rd32(info + 12);
            const uint32_t default_value = ctab_offset_ptr(table.ctab, size, rd32(info + 16));
            if (!name || !memchr(g_mem + name, 0, size - (name - table.ctab)) ||
                !ctab_range(size, type_offset, 16)) return false;
            const uint32_t type = table.ctab + type_offset;
            ReflexConstant entry;
            entry.desc = heap_alloc(48, true, 16);
            if (!entry.desc) return false;
            entry.name = name;
            entry.register_set = rd16(info + 4);
            entry.register_index = rd16(info + 6);
            // D3DXCONSTANT_DESC is twelve 32-bit words on x86.
            const uint32_t rows = rd16(type + 4), cols = rd16(type + 6);
            const uint32_t elements = std::max<uint32_t>(1, rd16(type + 8));
            wr32(entry.desc + 0, name);
            wr32(entry.desc + 4, entry.register_set);
            wr32(entry.desc + 8, entry.register_index);
            wr32(entry.desc + 12, rd16(info + 8));
            wr32(entry.desc + 16, rd16(type + 0));
            wr32(entry.desc + 20, rd16(type + 2));
            wr32(entry.desc + 24, rows);
            wr32(entry.desc + 28, cols);
            wr32(entry.desc + 32, elements);
            wr32(entry.desc + 36, rd16(type + 10));
            wr32(entry.desc + 40, 4u * rows * cols * elements);
            wr32(entry.desc + 44, default_value);
            table.constants.push_back(entry);
        }
        return true;
    }
    return false;
}

void d3dx_get_shader_constant_table(X86 *c) {
    const uint32_t shader = arg(c, 0), out = arg(c, 1);
    if (!out || !gm_valid(out, 4)) { set_eax(c, kD3dInvalidCall); return; }
    wr32(out, 0);
    ReflexConstantTable table;
    if (!d3dx_parse_ctab(shader, table)) {
        for (const auto &entry : table.constants) heap_free(entry.desc);
        if (table.ctab) heap_free(table.ctab);
        fprintf(stderr, "[reflex-d3dx] D3DXGetShaderConstantTable: invalid/missing CTAB at %08x\n", shader);
        set_eax(c, kD3dxInvalidData);
        return;
    }
    std::lock_guard<std::mutex> lock(g_d3dx_ctab_mutex);
    const uint32_t vtable = d3dx_ctab_vtable();
    const uint32_t object = heap_alloc(4, true, 16);
    if (!vtable || !object) {
        if (object) heap_free(object);
        for (const auto &entry : table.constants) heap_free(entry.desc);
        heap_free(table.ctab);
        set_eax(c, kOutOfMemory);
        return;
    }
    wr32(object, vtable);
    wr32(out, object);
    const uint32_t n = static_cast<uint32_t>(table.constants.size());
    g_d3dx_ctabs.emplace(object, std::move(table));
    fprintf(stderr, "[reflex-d3dx] D3DXGetShaderConstantTable: shader=%08x object=%08x constants=%u\n",
            shader, object, n);
    set_eax(c, 0);
}

void fmod_ok(X86 *c) {
    set_eax(c, 0); // FMOD_OK
}

void fmod_fail(X86 *c) {
    set_eax(c, 1); // any nonzero FMOD_RESULT is failure
}

// Minimal FMOD Ex / Designer object model for startup. Reflex creates the
// EventSystem, immediately asks virtual slot 7 for its low-level System, then
// calls the ordinary exported System methods. Returning success with a null
// EventSystem was therefore worse than returning an error: the next virtual
// dispatch dereferenced address zero.
uint32_t g_fmod_event_system = 0;
uint32_t g_fmod_event_vtable = 0;
uint32_t g_fmod_system = 0;
uint32_t g_fmod_channel_group = 0;
uint32_t g_fmod_sound_group = 0;

uint32_t fmod_opaque(uint32_t &slot) {
    if (!slot || !heap_owns(slot))
        slot = heap_alloc(8, true, 16);
    return slot;
}

void fmod_system_get_version(X86 *c) {
    const uint32_t out = arg(c, 1); // __stdcall member: [this, version*]
    if (!out || !gm_valid(out, 4)) {
        set_eax(c, 1);
        return;
    }
    // Reflex only reports this value during startup; 4.26 is contemporary
    // with the FMOD Ex ABI used by the executable.
    wr32(out, 0x00042600u);
    set_eax(c, 0);
}

void fmod_system_get_master_channel_group(X86 *c) {
    const uint32_t out = arg(c, 1);
    const uint32_t group = fmod_opaque(g_fmod_channel_group);
    if (!out || !gm_valid(out, 4) || !group) {
        set_eax(c, 1);
        return;
    }
    wr32(out, group);
    set_eax(c, 0);
}

void fmod_system_get_master_sound_group(X86 *c) {
    const uint32_t out = arg(c, 1);
    const uint32_t group = fmod_opaque(g_fmod_sound_group);
    if (!out || !gm_valid(out, 4) || !group) {
        set_eax(c, 1);
        return;
    }
    wr32(out, group);
    set_eax(c, 0);
}

void fmod_event_get_system_object(X86 *c) {
    const uint32_t out = arg(c, 1); // [this, FMOD::System **]
    const uint32_t system = fmod_opaque(g_fmod_system);
    if (!out || !gm_valid(out, 4) || !system) {
        set_eax(c, 1);
        return;
    }
    wr32(out, system);
    set_eax(c, 0);
}

void fmod_event_get_version(X86 *c) {
    const uint32_t out = arg(c, 1);
    if (!out || !gm_valid(out, 4)) {
        set_eax(c, 1);
        return;
    }
    wr32(out, 0x00042600u);
    set_eax(c, 0);
}

void fmod_fail_out_ptr(X86 *c) {
    const uint32_t out = arg(c, 1); // __stdcall member: [this, out]
    if (out && gm_valid(out, 4))
        wr32(out, 0);
    set_eax(c, 1);
}

uint32_t fmod_event_system_vtable() {
    if (g_fmod_event_vtable && heap_owns(g_fmod_event_vtable))
        return g_fmod_event_vtable;

    // FMOD Designer EventSystem ABI reached by Reflex:
    //   0 init, 1 release, 2 update, 3 setMediaPath, 4 setPluginPath,
    //   5 getVersion, 6 getInfo, 7 getSystemObject, 8 getMusicSystem.
    const uint32_t vt = heap_alloc(9 * 4, true, 16);
    if (!vt)
        return 0;

    const struct {
        const char *name;
        uint8_t argc;
        void (*fn)(X86 *);
    } methods[] = {
        {"FMOD::EventSystem::init", 5, fmod_ok},
        {"FMOD::EventSystem::release", 1, fmod_ok},
        {"FMOD::EventSystem::update", 1, fmod_ok},
        {"FMOD::EventSystem::setMediaPath", 2, fmod_ok},
        {"FMOD::EventSystem::setPluginPath", 2, fmod_ok},
        {"FMOD::EventSystem::getVersion", 2, fmod_event_get_version},
        {"FMOD::EventSystem::getInfo", 2, fmod_fail},
        {"FMOD::EventSystem::getSystemObject", 2, fmod_event_get_system_object},
        {"FMOD::EventSystem::getMusicSystem", 2, fmod_fail_out_ptr},
    };

    for (uint32_t i = 0; i < 9; ++i) {
        const uint32_t tramp = imports_alloc_trampoline(
            "fmod_eventL.dll", methods[i].name, methods[i].fn, methods[i].argc);
        if (!tramp) {
            heap_free(vt);
            return 0;
        }
        wr32(vt + i * 4, tramp);
    }
    g_fmod_event_vtable = vt;
    return vt;
}

void fmod_event_system_create(X86 *c) {
    const uint32_t out = arg(c, 0);
    if (!out || !gm_valid(out, 4)) {
        set_eax(c, 1);
        return;
    }

    const uint32_t vt = fmod_event_system_vtable();
    if (!vt) {
        wr32(out, 0);
        set_eax(c, 1);
        return;
    }

    if (!g_fmod_event_system || !heap_owns(g_fmod_event_system)) {
        g_fmod_event_system = heap_alloc(8, true, 16);
        if (!g_fmod_event_system) {
            wr32(out, 0);
            set_eax(c, 1);
            return;
        }
        wr32(g_fmod_event_system, vt);
        wr32(g_fmod_event_system + 4, 1);
    }

    wr32(out, g_fmod_event_system);
    fprintf(stderr, "[recomp] FMOD EventSystem bridge: event=%08x system=%08x\\n",
            g_fmod_event_system, fmod_opaque(g_fmod_system));
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

    if (fmt == 0x00972f38u || dst == 0x00a957fcu) {
        fprintf(stderr,
                "[reflex-crt] _vsnprintf esp=%08x dst=%08x cap=%08x fmt=%08x va=%08x "
                "esi=%08x edi=%08x rendered=%zu\\n",
                c->r[R_ESP], dst, cap, fmt, va, c->r[R_ESI], c->r[R_EDI], res.size());
    }

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

    // A copy-constructed string can alias a source's inline storage in
    // corrupted/overlapping guest layouts. Snapshot the SSO payload before
    // clearing the destination. Allocate long-string storage *before*
    // overwriting the destination, so OOM does not leave half an object.
    if (self == src)
        return true;
    if (n <= 15) {
        char inline_copy[16] = {};
        if (n)
            memcpy(inline_copy, g_mem + source, n);
        memset(g_mem + self, 0, 24);
        if (n)
            memcpy(g_mem + self, inline_copy, n);
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
    memset(g_mem + self, 0, 24);
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

    const uint32_t n = static_cast<uint32_t>(value.size());
    uint32_t data = 0;
    if (n > 15) {
        data = heap_alloc(n + 1, false);
        if (!data) {
            set_eax(c, 0);
            return;
        }
        memcpy(g_mem + data, value.data(), n);
        g_mem[data + n] = 0;
    }
    memset(g_mem + self, 0, 24);
    if (n <= 15) {
        if (n)
            memcpy(g_mem + self, value.data(), n);
        g_mem[self + n] = 0;
        wr32(self + 16, n);
        wr32(self + 20, 15);
    } else {
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

// VS2008 basic_string copy assignment uses x86 thiscall (ECX=this,
// one callee-cleaned const basic_string& stack argument).
// Snapshot first: the destination's old heap allocation may be released.
bool msvcp_string_assign_from(uint32_t self, uint32_t src) {
    if (!self || !src || !gm_valid(self, 24) || !gm_valid(src, 24))
        return false;
    if (self == src)
        return true;
    const uint32_t n = rd32(src + 16);
    const uint32_t capacity = rd32(src + 20);
    const uint32_t data = msvcp_string_data(src);
    if (n > 0x0fffffffu || n > capacity ||
        !data || !gm_valid(data, n + 1u))
        return false;
    const std::string snapshot(reinterpret_cast<const char *>(g_mem + data), n);
    return msvcp_string_assign_value(self, snapshot);
}

void msvcp_string_assign_copy(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    set_eax(c, msvcp_string_assign_from(self, arg(c, 0)) ? self : 0);
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

// MSVC 2008 x86 basic_string<char>::swap(basic_string&) is a thiscall:
// ECX is 'this', and the other string is the one callee-cleaned stack
// argument. The 24-byte representation consists of a 16-byte SSO or heap
// pointer union and 32-bit size and capacity fields. Swapping complete
// representations transfers any owned heap allocation without copying it,
// and also handles the inline/heap combination correctly.
void msvcp_string_swap(X86 *c) {
    const uint32_t self = c->r[R_ECX];
    const uint32_t other = arg(c, 0);
    if (!self || !other || !gm_valid(self, 24) || !gm_valid(other, 24)) {
        fprintf(stderr, "[reflex-msvcp] basic_string::swap invalid operands this=%08x other=%08x\n",
                self, other);
        set_eax(c, 0);
        return;
    }
    if (self != other) {
        uint8_t temporary[24];
        memcpy(temporary, g_mem + self, 24);
        memcpy(g_mem + self, g_mem + other, 24);
        memcpy(g_mem + other, temporary, 24);
    }
    set_eax(c, 0);
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
        fprintf(stderr, "[recomp] _initterm invalid range %08x..%08x\\n", first, last);
        set_eax(c, 0);
        return;
    }
    fprintf(stderr, "[recomp] _initterm range %08x..%08x entries=%u\\n",
            first, last, (last - first) / 4);
    uint32_t index = 0;
    for (uint32_t p = first; p < last; p += 4, ++index) {
        const uint32_t fn = rd32(p);
        if (fn) {
            fprintf(stderr, "[recomp] _initterm[%u] -> %08x\\n", index, fn);
            guest_call(c, fn);
        }
    }
    set_eax(c, 0);
}

void crt_initterm_e(X86 *c) {
    const uint32_t first = arg(c, 0);
    const uint32_t last = arg(c, 1);
    if (last < first || ((last - first) & 3u) || !gm_valid(first, last - first)) {
        fprintf(stderr, "[recomp] _initterm_e invalid range %08x..%08x\\n", first, last);
        set_eax(c, static_cast<uint32_t>(-1));
        return;
    }
    fprintf(stderr, "[recomp] _initterm_e range %08x..%08x entries=%u\\n",
            first, last, (last - first) / 4);
    uint32_t index = 0;
    for (uint32_t p = first; p < last; p += 4, ++index) {
        const uint32_t fn = rd32(p);
        if (!fn)
            continue;
        fprintf(stderr, "[recomp] _initterm_e[%u] -> %08x\\n", index, fn);
        const uint32_t rc = guest_call(c, fn);
        if (rc) {
            set_eax(c, rc);
            return;
        }
    }
    set_eax(c, 0);
}

// XInput 1.3's ordinal exports are used directly by Reflex. In the
// headless probe there is no gamepad attached: a real XInput DLL returns
// ERROR_DEVICE_NOT_CONNECTED rather than success with an uninitialized
// XINPUT_STATE/XINPUT_CAPABILITIES output buffer. This is also important for
// guest ABI integrity: the imports dispatcher must pop the exact stdcall
// argument count after each ordinal call.
constexpr uint32_t kErrorDeviceNotConnected = 1167u;

void xinput_controller_not_connected(X86 *c) {
    // Do not touch caller-owned output memory on an error result.
    set_eax(c, kErrorDeviceNotConnected);
}

void xinput_enable(X86 *c) {
    // XInputEnable(BOOL) is void, with one stdcall argument.
    // The headless backend does not have an XInput device to toggle.
    set_eax(c, 0);
}

const ImportShim k_reflex_shims[] = {
    // XInput 1.3 uses real numeric PE export ordinals (see Wine's
    // xinput1_3.spec). Register both ordinal and named exports: some
    // versions of the game/middleware import the latter.
    // ord2 = XInputGetState(DWORD, XINPUT_STATE*)              [2]
    // ord4 = XInputGetCapabilities(DWORD, DWORD, ...*)        [3]
    {"XINPUT1_3.dll", "ord2", 2, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputGetState", 2, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "ord4", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputGetCapabilities", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "ord3", 2, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputSetState", 2, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "ord5", 1, xinput_enable},
    {"XINPUT1_3.dll", "XInputEnable", 1, xinput_enable},
    {"XINPUT1_3.dll", "ord6", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputGetDSoundAudioDeviceGuids", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "ord7", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputGetBatteryInformation", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "ord8", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputGetKeystroke", 3, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "ord100", 2, xinput_controller_not_connected},
    {"XINPUT1_3.dll", "XInputGetStateEx", 2, xinput_controller_not_connected},

    // Win32 ABI fixes observed during Reflex startup.
    {"KERNEL32.dll", "InterlockedCompareExchange", 3, reflex_interlocked_compare_exchange},
    {"USER32.dll", "RegisterRawInputDevices", 3, reflex_register_raw_input_devices},

    // Steam's flat C API uses cdecl.
    {"steam_api.dll", "SteamAPI_RestartAppIfNecessary", ARGC_CDECL,
     reflex_steam_restart_app_if_necessary},
    {"steam_api.dll", "SteamAPI_Init", ARGC_CDECL, reflex_steam_init},
    {"steam_api.dll", "SteamAPI_RegisterCallback", ARGC_CDECL,
     reflex_steam_register_callback},
    {"steam_api.dll", "SteamUserStats", ARGC_CDECL, reflex_steam_user_stats},

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
    {"MSVCR90.dll", "strstr", ARGC_CDECL, crt_strstr},
    {"MSVCR90.dll", "strncat", ARGC_CDECL, crt_strncat},
    {"MSVCR90.dll", "strpbrk", ARGC_CDECL, crt_strpbrk},
    {"MSVCR90.dll", "strchr", ARGC_CDECL, crt_strchr},
    {"MSVCR90.dll", "strcpy_s", ARGC_CDECL, crt_strcpy_s},
    {"MSVCR90.dll", "_strlwr_s", ARGC_CDECL, crt_strlwr_s},
    {"MSVCR90.dll", "_copysign", ARGC_CDECL, crt_copysign},
    {"MSVCR90.dll", "__libm_sse2_exp", ARGC_CDECL, crt_libm_sse2_exp},
    {"MSVCR90.dll", "__libm_sse2_expf", ARGC_CDECL, crt_libm_sse2_expf},
    {"MSVCR90.dll", "__RTDynamicCast", ARGC_CDECL, crt_rt_dynamic_cast},
    {"MSVCR90.dll", "_setjmp3", ARGC_CDECL, crt_setjmp3},
    {"MSVCR90.dll", "_crt_debugger_hook", ARGC_CDECL, crt_debugger_hook},
    {"MSVCR90.dll", "_invalid_parameter_noinfo", ARGC_CDECL,
     crt_invalid_parameter_noinfo},
    {"MSVCR90.dll",
     "?_name_internal_method@type_info@@QBEPBDPAU__type_info_node@@@Z",
     1, crt_type_info_name_internal},
    {"MSVCR90.dll", "tolower", ARGC_CDECL, crt_tolower},
    {"MSVCR90.dll", "toupper", ARGC_CDECL, crt_toupper},
    {"MSVCR90.dll", "isdigit", ARGC_CDECL, crt_isdigit},
    {"MSVCR90.dll", "isalpha", ARGC_CDECL, crt_isalpha},
    {"MSVCR90.dll", "isalnum", ARGC_CDECL, crt_isalnum},
    {"MSVCR90.dll", "isspace", ARGC_CDECL, crt_isspace},
    {"MSVCR90.dll", "isxdigit", ARGC_CDECL, crt_isxdigit},
    {"MSVCR90.dll", "islower", ARGC_CDECL, crt_islower},
    {"MSVCR90.dll", "isupper", ARGC_CDECL, crt_isupper},
    {"MSVCR90.dll", "ispunct", ARGC_CDECL, crt_ispunct},
    {"MSVCR90.dll", "atol", ARGC_CDECL, crt_atol},
    {"MSVCR90.dll", "strtoul", ARGC_CDECL, crt_strtoul},
    {"MSVCR90.dll", "strtol", ARGC_CDECL, crt_strtol},
    {"MSVCR90.dll", "strtod", ARGC_CDECL, crt_strtod},
    {"MSVCR90.dll", "atof", ARGC_CDECL, crt_atof},
    {"MSVCR90.dll", "strcspn", ARGC_CDECL, crt_strcspn},
    {"MSVCR90.dll", "localeconv", ARGC_CDECL, crt_localeconv},

    {"MSVCR90.dll", "_aligned_malloc", ARGC_CDECL, crt_aligned_malloc},
    {"MSVCR90.dll", "_aligned_realloc", ARGC_CDECL, crt_aligned_realloc},
    {"MSVCR90.dll", "_aligned_free", ARGC_CDECL, crt_aligned_free},
    {"MSVCR90.dll", "_encode_pointer", ARGC_CDECL, crt_pointer_identity},
    {"MSVCR90.dll", "_decode_pointer", ARGC_CDECL, crt_pointer_identity},
    {"MSVCR90.dll", "_lock", ARGC_CDECL, crt_noop},
    {"MSVCR90.dll", "_unlock", ARGC_CDECL, crt_noop},
    {"MSVCR90.dll", "srand", ARGC_CDECL, crt_srand},
    {"MSVCR90.dll", "_CIpow", ARGC_CDECL, crt_cipow},

    // Host-backed stdio. FILE* values exposed to the guest are opaque guest
    // handles; host FILE* pointers never escape into the 32-bit address space.
    {"MSVCR90.dll", "fopen", ARGC_CDECL, crt_fopen},
    {"MSVCR90.dll", "fclose", ARGC_CDECL, crt_fclose},
    {"MSVCR90.dll", "fread", ARGC_CDECL, crt_fread},
    {"MSVCR90.dll", "fwrite", ARGC_CDECL, crt_fwrite},
    {"MSVCR90.dll", "fgets", ARGC_CDECL, crt_fgets},
    {"MSVCR90.dll", "fseek", ARGC_CDECL, crt_fseek},
    {"MSVCR90.dll", "ftell", ARGC_CDECL, crt_ftell},
    {"MSVCR90.dll", "feof", ARGC_CDECL, crt_feof},
    {"MSVCR90.dll", "fgetc", ARGC_CDECL, crt_fgetc},
    {"MSVCR90.dll", "ungetc", ARGC_CDECL, crt_ungetc},
    {"MSVCR90.dll", "rewind", ARGC_CDECL, crt_rewind},
    {"MSVCR90.dll", "fflush", ARGC_CDECL, crt_fflush},
    {"MSVCR90.dll", "__dllonexit", ARGC_CDECL, crt_onexit},
    {"MSVCR90.dll", "_except_handler4_common", ARGC_CDECL, crt_exception_continue_search},

    // Reached external middleware imports. Model the ABI and fail explicitly
    // when the host does not yet provide the underlying service.
    {"d3dx9_43.dll", "D3DXCompileShader", 10, d3dx_compile_shader_bridge},
    {"d3dx9_43.dll", "D3DXGetShaderConstantTable", 2, d3dx_get_shader_constant_table},
    {"fmodexL.dll", "FMOD_Debug_SetLevel", 1, fmod_ok},
    {"fmodexL.dll", "FMOD_Memory_Initialize", 6, fmod_ok},
    {"fmod_eventL.dll", "_FMOD_EventSystem_Create@4", 1,
     fmod_event_system_create},
    {"fmodexL.dll",
     "?setSoftwareChannels@System@FMOD@@QAG?AW4FMOD_RESULT@@H@Z",
     2, fmod_ok},
    {"fmodexL.dll",
     "?setAdvancedSettings@System@FMOD@@QAG?AW4FMOD_RESULT@@PAUFMOD_ADVANCEDSETTINGS@@@Z",
     2, fmod_ok},
    {"fmodexL.dll",
     "?set3DSettings@System@FMOD@@QAG?AW4FMOD_RESULT@@MMM@Z",
     4, fmod_ok},
    {"fmodexL.dll",
     "?getMasterChannelGroup@System@FMOD@@QAG?AW4FMOD_RESULT@@PAPAVChannelGroup@2@@Z",
     2, fmod_system_get_master_channel_group},
    {"fmodexL.dll",
     "?getMasterSoundGroup@System@FMOD@@QAG?AW4FMOD_RESULT@@PAPAVSoundGroup@2@@Z",
     2, fmod_system_get_master_sound_group},
    {"fmodexL.dll",
     "?getVersion@System@FMOD@@QAG?AW4FMOD_RESULT@@PAI@Z",
     2, fmod_system_get_version},

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
     "?swap@?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAEXAAV12@@Z",
     1, msvcp_string_swap},

    {"MSVCP90.dll",
     "??4?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@QAEAAV01@ABV01@@Z",
     1, msvcp_string_assign_copy},
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
// CI trigger: trace null producer at 007add45.
