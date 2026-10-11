#pragma once
// Narrow, opt-in Direct3D9 fixed-function rendering bridge.
//
// Scope: FVF XYZRHW | TEX1 (0x104), stage-0 MODULATE(texture, current),
// stage-0 alpha SELECTARG1(texture), stage 1 disabled. Unlike fabricated
// placeholder graphics this emits actual SM3 tokens for the existing native
// GLSL/MSL D3D9 compiler. Do not alter the guest's bound shader state.
//
// Guest POSITIONT xy are window/viewport pixel coordinates; map them into
// homogeneous clip space using c0/c1. z stays [0,1], w becomes 1. Texture
// coordinates are passed through; stage 0 is sampled by the pixel shader.
#include <cstdint>
#include <initializer_list>
#include <vector>

namespace reflex_ffp {

inline std::vector<uint8_t> shader_words(std::initializer_list<uint32_t> words) {
    std::vector<uint8_t> bytes;
    bytes.reserve(words.size() * 4u);
    for (uint32_t word : words) {
        bytes.push_back(static_cast<uint8_t>(word));
        bytes.push_back(static_cast<uint8_t>(word >> 8u));
        bytes.push_back(static_cast<uint8_t>(word >> 16u));
        bytes.push_back(static_cast<uint8_t>(word >> 24u));
    }
    return bytes;
}

// vs_3_0: dcl_positiont v0, dcl_texcoord v1,
//         dcl_position o0, dcl_texcoord o1
//         mul r0, v0, c0; add o0, r0, c1; mov o1, v1.
inline const std::vector<uint8_t> &quad_vs() {
    static const std::vector<uint8_t> code = shader_words({
        0xfffe0300u,
        0x0200001fu, 0x00000009u, 0x900f0000u,
        0x0200001fu, 0x00000005u, 0x900f0001u,
        0x0200001fu, 0x00000000u, 0xe00f0000u,
        0x0200001fu, 0x00000005u, 0xe00f0001u,
        0x03000005u, 0x800f0000u, 0x90e40000u, 0xa0e40000u,
        0x03000002u, 0xe00f0000u, 0x80e40000u, 0xa0e40001u,
        0x02000001u, 0xe00f0001u, 0x90e40001u,
        0x0000ffffu,
    });
    return code;
}

// ps_3_0: dcl_texcoord v0, dcl_2d s0;
//         texld r0, v0, s0; mov oC0, r0.
inline const std::vector<uint8_t> &quad_ps() {
    static const std::vector<uint8_t> code = shader_words({
        0xffff0300u,
        0x0200001fu, 0x00000005u, 0x900f0000u,
        0x0200001fu, 0x10000000u, 0xa00f0800u,
        0x03000042u, 0x800f0000u, 0x90e40000u, 0xa0e40800u,
        0x02000001u, 0x800f0800u, 0x80e40000u,
        0x0000ffffu,
    });
    return code;
}

// All conditions must hold before replacing legacy fixed-function draws.
// A missing texture cannot be replaced with fabricated UI or placeholder art.
inline bool supported(uint32_t fvf, uint32_t texture0,
                      uint32_t colorop, uint32_t colorarg1, uint32_t colorarg2,
                      uint32_t alphaop, uint32_t alphaarg1,
                      uint32_t stage1_colorop) {
    return fvf == 0x00000104u && texture0 != 0 &&
           colorop == 4u && colorarg1 == 2u && colorarg2 == 1u &&
           alphaop == 2u && alphaarg1 == 2u && stage1_colorop == 1u;
}

inline bool clip_constants(float x, float y, float width, float height,
                           float out[2][4]) {
    if (!out || !(width > 0.0f) || !(height > 0.0f) ||
        width > 8192.0f || height > 8192.0f)
        return false;
    out[0][0] = 2.0f / width;
    out[0][1] = -2.0f / height;
    out[0][2] = 1.0f;
    out[0][3] = 0.0f;
    out[1][0] = -1.0f - 2.0f * x / width;
    out[1][1] = 1.0f + 2.0f * y / height;
    out[1][2] = 0.0f;
    out[1][3] = 1.0f;
    return true;
}

} // namespace reflex_ffp
