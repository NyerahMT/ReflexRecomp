#pragma once
// D3D9 fixed-function FVF to D3DVERTEXELEMENT9 translation.
//
// Pure layout conversion: usable in native tests without recomp-kit or game
// assets. The generated eight-byte elements are little-endian and end with
// D3DDECL_END (stream=0xff, type=17).
#include <cstdint>
#include <vector>

namespace reflex_d3d9 {

inline bool fvf_declaration(uint32_t fvf, std::vector<uint8_t> &result) {
    constexpr uint32_t kPositionMask = 0x400eu;
    constexpr uint32_t kNormal = 0x0010u;
    constexpr uint32_t kPointSize = 0x0020u;
    constexpr uint32_t kDiffuse = 0x0040u;
    constexpr uint32_t kSpecular = 0x0080u;
    constexpr uint32_t kTexCountMask = 0x0f00u;
    constexpr uint32_t kLastUbyte4 = 0x1000u;
    constexpr uint32_t kLastColor = 0x8000u;
    constexpr uint32_t kTexSizeBits = 0xffff0000u;
    constexpr uint32_t kValidMask = kPositionMask | kNormal | kPointSize |
        kDiffuse | kSpecular | kTexCountMask | kLastUbyte4 |
        kLastColor | kTexSizeBits;
    const uint32_t position = fvf & kPositionMask;
    const uint32_t tex_count = (fvf & kTexCountMask) >> 8u;
    if ((fvf & ~kValidMask) || tex_count > 8 || (fvf & kLastUbyte4 && fvf & kLastColor))
        return false;
    // 0x002=XYZ, 0x004=XYZRHW, 0x006..0x00e=XYZB1..XYZB5,
    // 0x4002=XYZW. All other position encodings are invalid.
    if (position != 0x002u && position != 0x004u && position != 0x4002u &&
        (position < 0x006u || position > 0x00eu || (position & 1u)))
        return false;
    const bool rhw = position == 0x004u;
    const bool blend_position = position >= 0x006u && position <= 0x00eu;
    const uint32_t blend_count = blend_position ? (position - 0x004u) / 2u : 0u;
    const bool indexed = !!(fvf & (kLastUbyte4 | kLastColor));
    if ((rhw && (fvf & kNormal)) || (indexed && !blend_position))
        return false;

    std::vector<uint8_t> elements;
    elements.reserve(8u * 21u);
    uint32_t offset = 0;
    const auto add = [&elements, &offset](uint8_t type, uint8_t usage,
                                           uint8_t index, uint32_t size) {
        if (offset + size > 0xffffu)
            return false;
        elements.push_back(0); // Stream 0, little endian
        elements.push_back(0);
        elements.push_back(static_cast<uint8_t>(offset));
        elements.push_back(static_cast<uint8_t>(offset >> 8u));
        elements.push_back(type);
        elements.push_back(0); // D3DDECLMETHOD_DEFAULT
        elements.push_back(usage);
        elements.push_back(index);
        offset += size;
        return true;
    };
    // D3DDECLTYPE_FLOAT3=2, FLOAT4=3, POSITION=0, POSITIONT=9.
    if (!add(rhw || position == 0x4002u ? 3 : 2,
             rhw ? 9 : 0, 0, rhw || position == 0x4002u ? 16 : 12))
        return false;

    uint32_t weights = blend_count - (indexed ? 1u : 0u);
    // More than four weights are expressed as consecutive declarations,
    // with the second BLENDWEIGHT element carrying the fifth.
    if (weights) {
        const uint32_t first = weights > 4 ? 4 : weights;
        if (!add(static_cast<uint8_t>(first - 1), 1, 0, first * 4u))
            return false;
        if (weights > 4 && !add(0, 1, 1, 4))
            return false;
    }
    if (indexed && !add((fvf & kLastColor) ? 4 : 5, 2, 0, 4))
        return false;
    if (fvf & kNormal)
        if (!add(2, 3, 0, 12))
            return false;
    if (fvf & kPointSize)
        if (!add(0, 4, 0, 4))
            return false;
    if (fvf & kDiffuse)
        if (!add(4, 10, 0, 4))
            return false;
    if (fvf & kSpecular)
        if (!add(4, 10, 1, 4))
            return false;

    // D3DFVF_TEXCOORDSIZE2 is encoded as 00 (default).
    // 01=>FLOAT3, 10=>FLOAT4, 11=>FLOAT1.
    constexpr uint8_t kTexComponents[4] = {2, 3, 4, 1};
    for (uint32_t i = 0; i < tex_count; ++i) {
        const uint32_t packed = (fvf >> (16u + i * 2u)) & 3u;
        const uint32_t comps = kTexComponents[packed];
        if (!add(static_cast<uint8_t>(comps - 1), 5,
                 static_cast<uint8_t>(i), comps * 4u))
            return false;
    }
    // Reject texture coordinate size bits for unused texture sets.
    const uint32_t active_bits = tex_count == 8u ? 0xffffu
        : ((1u << (tex_count * 2u)) - 1u);
    if (((fvf >> 16u) & ~active_bits) != 0)
        return false;

    constexpr uint8_t kEnd[8] = {0xff, 0, 0, 0, 17, 0, 0, 0};
    elements.insert(elements.end(), kEnd, kEnd + 8);
    result = std::move(elements);
    return true;
}

} // namespace reflex_d3d9
