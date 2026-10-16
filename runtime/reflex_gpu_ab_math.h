#pragma once
// Pure, host-independent blend reference for diagnosing real D3D9 draw output.
// This is never a shader override or a change to any original game pixel.
#include <cstdint>

namespace reflex_gpu_ab {

// D3DBLEND_SRCALPHA + D3DBLEND_INVSRCALPHA over a cleared black
// target. UNORM quantization is nearest, with a 1 LSB tolerance for
// backend rounding differences when comparing real GPU readbacks.
inline uint8_t src_over_black(uint8_t rgb, uint8_t alpha) {
    return static_cast<uint8_t>(
        (static_cast<unsigned>(rgb) * alpha + 127u) / 255u);
}

inline unsigned abs_diff(uint8_t a, uint8_t b) {
    return a >= b ? static_cast<unsigned>(a - b)
                  : static_cast<unsigned>(b - a);
}

}  // namespace reflex_gpu_ab
