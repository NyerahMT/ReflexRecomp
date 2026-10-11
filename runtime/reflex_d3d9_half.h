#pragma once
// Direct3D9 D3DDECLTYPE_FLOAT16_2 / FLOAT16_4 decoding for the CPU
// rasterizer and draw diagnostics. Guest vertices are little-endian.
// This must not depend on host _Float16 support (not portable to all runners).
#include <cstdint>
#include <cstring>

namespace reflex_d3d9 {

inline float float16_to_float32(uint16_t half) {
    const uint32_t sign = uint32_t(half & 0x8000u) << 16u;
    const uint32_t exponent = (half >> 10u) & 0x1fu;
    uint32_t fraction = half & 0x03ffu;
    uint32_t bits;
    if (exponent == 0) {
        if (fraction == 0) {
            bits = sign; // +0 / -0
        } else {
            uint32_t exp32 = 127u - 14u;
            while ((fraction & 0x0400u) == 0) {
                fraction <<= 1u;
                --exp32;
            }
            bits = sign | (exp32 << 23u) |
                   ((fraction & 0x03ffu) << 13u);
        }
    } else if (exponent == 31u) {
        bits = sign | 0x7f800000u | (fraction << 13u); // +/-inf, NaN
    } else {
        bits = sign | ((exponent + 112u) << 23u) | (fraction << 13u);
    }
    float out;
    std::memcpy(&out, &bits, sizeof(out));
    return out;
}

inline float float16_component(const uint8_t *little_endian, uint32_t index) {
    const uint32_t offset = index * 2u;
    const uint16_t bits = static_cast<uint16_t>(
        uint16_t(little_endian[offset]) |
        uint16_t(uint16_t(little_endian[offset + 1u]) << 8u));
    return float16_to_float32(bits);
}

// Bytes required to read an entire supported D3DVERTEXELEMENT9 declaration.
// Return zero for unknown types (never perform an unbounded vertex read).
inline uint32_t vertex_element_bytes(uint8_t type) {
    switch (type) {
    case 0: return 4;   // FLOAT1
    case 1: return 8;   // FLOAT2
    case 2: return 12;  // FLOAT3
    case 3: return 16;  // FLOAT4
    case 4: return 4;   // D3DCOLOR
    case 5: return 4;   // UBYTE4
    case 6: return 4;   // SHORT2
    case 7: return 8;   // SHORT4
    case 8: return 4;   // UBYTE4N
    case 9: return 4;   // SHORT2N
    case 10: return 8;  // SHORT4N
    case 11: return 4;  // USHORT2N
    case 12: return 8;  // USHORT4N
    case 13: return 4;  // UDEC3
    case 14: return 4;  // DEC3N
    case 15: return 4;  // FLOAT16_2
    case 16: return 8;  // FLOAT16_4
    default: return 0;
    }
}

} // namespace reflex_d3d9
