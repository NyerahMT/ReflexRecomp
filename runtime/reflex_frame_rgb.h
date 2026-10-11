#pragma once
// Portable, read-only RGB frame sampling for opt-in D3D9 bring-up evidence.
#include <cstddef>
#include <cstdint>
namespace reflex_d3d9 {
// Sample first frames and exponentially spaced later frames: 9 readbacks at
// most, independent of FPS or a long-running render loop.
inline bool should_readback(uint64_t presented) noexcept {
    return presented != 0u && presented <= 256u &&
           (presented <= 2u || (presented & (presented - 1u)) == 0u);
}
struct FrameStats {
    uint32_t sampled = 0, nonblack = 0;
    uint64_t hash = UINT64_C(1469598103934665603);
};
inline bool frame_stats(const uint8_t *rgb, size_t cap, uint32_t w, uint32_t h,
                        FrameStats *result) noexcept {
    if (!rgb || !result || !w || !h || w > 8192 || h > 8192 ||
        uint64_t(w) * h * 3u > cap)
        return false;
    FrameStats out;
    const uint64_t size = uint64_t(w) * h;
    for (uint64_t i = 0; i < size; i += 97u) {
        const uint8_t *p = rgb + i * 3u;
        ++out.sampled;
        if (uint32_t(p[0]) + p[1] + p[2] > 3u)
            ++out.nonblack;
        for (int k = 0; k < 3; ++k) {
            out.hash ^= p[k];
            out.hash *= UINT64_C(1099511628211);
        }
    }
    *result = out;
    return true;
}
} // namespace reflex_d3d9
