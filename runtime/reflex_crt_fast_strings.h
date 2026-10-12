// Bounded, allocation-free MSVCR90 narrow-string reads over the guest arena.
// Match pinned recomp-kit's gm_str(addr, 0x8000) behavior:
// null/out-of-arena pointers are empty; scan at most 32768 bytes or the arena
// boundary; compare unsigned byte values as std::string::compare does.
// This header is original compatibility code, not recovered game code.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace reflex_crt_fast {

inline size_t bounded_length(
    const uint8_t *mem, uint32_t arena_bytes, uint32_t guest_ptr,
    size_t max_len = 0x8000u
) {
    if (!mem || !guest_ptr || guest_ptr >= arena_bytes) return 0u;
    const size_t bound = std::min<size_t>(
        max_len, static_cast<size_t>(arena_bytes - guest_ptr));
    if (!bound) return 0u;
    const void *zero = std::memchr(mem + guest_ptr, 0, bound);
    return zero ? static_cast<const uint8_t *>(zero) - (mem + guest_ptr)
                : bound;
}

inline int bounded_compare(
    const uint8_t *mem, uint32_t arena_bytes,
    uint32_t lhs_ptr, uint32_t rhs_ptr,
    size_t max_len = 0x8000u
) {
    const size_t lhs_size = bounded_length(mem, arena_bytes, lhs_ptr, max_len);
    const size_t rhs_size = bounded_length(mem, arena_bytes, rhs_ptr, max_len);
    const size_t shared = std::min(lhs_size, rhs_size);
    if (shared) {
        const int rc = std::memcmp(mem + lhs_ptr, mem + rhs_ptr, shared);
        if (rc) return rc < 0 ? -1 : 1;
    }
    return lhs_size < rhs_size ? -1 : lhs_size > rhs_size ? 1 : 0;
}


inline int bounded_ncompare(const uint8_t *memory, uint32_t arena,
                            uint32_t a, uint32_t b, uint32_t count,
                            bool ascii_casefold = false) {
    if (!count) return 0;
    const auto get = [=](uint32_t ptr, uint64_t index) -> uint8_t {
        const uint64_t address = static_cast<uint64_t>(ptr) + index;
        return memory && ptr && address < arena ? memory[address] : 0;
    };
    // The runtime bounds individual guest strings to 1 MiB for CRT searches.
    const uint64_t limit = std::min<uint64_t>(count, 0x100000u);
    for (uint64_t i = 0; i < limit; ++i) {
        uint8_t lhs = get(a, i), rhs = get(b, i);
        if (ascii_casefold) {
            if (lhs >= 'A' && lhs <= 'Z') lhs += 'a' - 'A';
            if (rhs >= 'A' && rhs <= 'Z') rhs += 'a' - 'A';
        }
        if (lhs != rhs) return lhs < rhs ? -1 : 1;
        if (!lhs) return 0;
    }
    return 0;
}

inline uint32_t bounded_strrchr(const uint8_t *memory, uint32_t arena,
                                uint32_t ptr, uint8_t target,
                                uint32_t max_len = 0x100000u) {
    if (!memory || !ptr || ptr >= arena) return 0;
    const uint32_t limit = static_cast<uint32_t>(std::min<uint64_t>(
        max_len, static_cast<uint64_t>(arena) - ptr));
    uint32_t last = 0;
    for (uint32_t i = 0; i < limit; ++i) {
        const uint8_t ch = memory[ptr + i];
        if (ch == target) last = ptr + i;
        if (!ch) return last; // NUL is searchable, too.
    }
    // Do not return an unterminated string's speculative pointer.
    return 0;
}

} // namespace reflex_crt_fast
