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

} // namespace reflex_crt_fast
