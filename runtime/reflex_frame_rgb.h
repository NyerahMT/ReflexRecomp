#pragma once
// Portable, read-only RGB frame sampling for opt-in D3D9 bring-up evidence.
#include <cstddef>
#include <cstdint>
#include <cstdio>
namespace reflex_d3d9 {
// Sample first frames and bounded powers of two through 16,384 presents.
// Late readbacks verify whether a shader fix visibly changes the loading
// screen after the original game advances to its declaration-based draws.
inline bool should_readback(uint64_t presented) noexcept {
    return presented != 0u && presented <= 16384u &&
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
// Save only bounded host-side readback bytes, never dump game resources or
// guest allocations. P6 PPM is directly convertible to PNG for inspection.
inline bool write_frame_ppm(const char *filename, const uint8_t *rgb,
                            size_t cap, uint32_t w, uint32_t h) noexcept {
    if (!filename || !rgb || !w || !h || w > 4096u || h > 4096u ||
        uint64_t(w) * h * 3u > cap || uint64_t(w) * h * 3u > 12u * 1024u * 1024u)
        return false;
    std::FILE *fp = std::fopen(filename, "wb");
    if (!fp) return false;
    const size_t needed = size_t(w) * h * 3u;
    const bool success = std::fprintf(fp, "P6\n%u %u\n255\n", w, h) > 0 &&
                         std::fwrite(rgb, 1, needed, fp) == needed;
    const int closed = std::fclose(fp);
    if (!success || closed != 0) {
        std::remove(filename);
        return false;
    }
    return true;
}
} // namespace reflex_d3d9
