#pragma once
// Round an IEEE-754 binary32 float to IEEE-754 binary16 (round-to-nearest-even).
// D3DXFLOAT16 uses the bit layout of a Direct3D half, independent of host
// _Float16 availability and endianness. Input is raw f32 bits.
#include <cstdint>

namespace reflex_d3dx {

inline uint16_t f32_to_f16_bits(uint32_t bits) {
    const uint32_t sign = (bits >> 16) & 0x8000u;
    const uint32_t exp = (bits >> 23) & 0xffu;
    const uint32_t mantissa = bits & 0x7fffffu;
    if (exp == 0xffu) {
        if (mantissa) {
            // Quiet NaN: preserve a nonzero slice of source payload.
            return static_cast<uint16_t>(
                sign | 0x7c00u | 0x0200u | (mantissa >> 13));
        }
        return static_cast<uint16_t>(sign | 0x7c00u);
    }
    const int half_exp = static_cast<int>(exp) - 127 + 15;
    if (half_exp >= 31)
        return static_cast<uint16_t>(sign | 0x7c00u);
    if (half_exp <= 0) {
        if (half_exp < -10)
            return static_cast<uint16_t>(sign);
        const uint32_t normalized = mantissa | 0x800000u;
        const uint32_t shift = static_cast<uint32_t>(14 - half_exp);
        const uint32_t fraction = normalized >> shift;
        const uint32_t lost = normalized & ((1u << shift) - 1u);
        const uint32_t halfway = 1u << (shift - 1u);
        const uint32_t rounded = fraction +
            (lost > halfway || (lost == halfway && (fraction & 1u)));
        // Rounded subnormals may correctly carry into the smallest normal.
        return static_cast<uint16_t>(sign | rounded);
    }
    const uint32_t raw = (static_cast<uint32_t>(half_exp) << 10u) |
                         (mantissa >> 13u);
    const uint32_t lost = mantissa & 0x1fffu;
    const uint32_t rounded = raw +
        (lost > 0x1000u || (lost == 0x1000u && (raw & 1u)));
    return static_cast<uint16_t>(sign | rounded);
}

} // namespace reflex_d3dx
