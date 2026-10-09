// Clean-room x86 packed-single SSE bridge for cached Reflex translations.
//
// In the pinned recomp-kit baseline, selected packed-single operations are
// emitted as recomp_unmodelled() traps. Decode the original instruction bytes
// in the already-mapped guest PE rather than guessing operands from a mnemonic.
// Unsupported prefixes, malformed instructions and inaccessible guest sources
// retain the original trap, not a fabricated result.
//
// Initial subset: ADDPS (0f58), MULPS (0f59), SUBPS (0f5c), both XMM register
// and modrm/SIB based memory sources in 32-bit address mode. No MXCSR flags,
// DAZ or FTZ emulation yet; this path uses IEEE float arithmetic on the host.
#include "reflex_packed_sse.h"
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <cmath>

namespace {
bool read_code(uint32_t &pc, uint8_t &out) {
    if (pc < GUEST_NULL_LIMIT || pc >= GUEST_SIZE)
        return false;
    out = rd8(pc++);
    return true;
}

bool read_disp32(uint32_t &pc, uint32_t &out) {
    if (pc < GUEST_NULL_LIMIT || pc > GUEST_SIZE - 4)
        return false;
    out = rd32(pc);
    pc += 4;
    return true;
}

bool decode_source(X86 *c, uint32_t &pc, uint8_t modrm,
                   uint32_t &source, bool &in_register, uint32_t bytes) {
    const unsigned mode = modrm >> 6;
    const unsigned rm = modrm & 7u;
    in_register = mode == 3u;
    if (in_register) {
        source = rm;
        return true;
    }

    uint32_t base = 0, index = 0;
    bool disp_only = mode == 0 && rm == 5;
    bool has_sib = rm == 4;
    if (has_sib) {
        uint8_t sib = 0;
        if (!read_code(pc, sib))
            return false;
        const unsigned scale = sib >> 6;
        const unsigned index_reg = (sib >> 3) & 7u;
        const unsigned base_reg = sib & 7u;
        if (index_reg != 4)
            index = c->r[index_reg] << scale;
        disp_only = mode == 0 && base_reg == 5;
        if (!disp_only)
            base = c->r[base_reg];
    } else if (!disp_only) {
        base = c->r[rm];
    }

    uint32_t disp = 0;
    if (mode == 1) {
        uint8_t byte_disp;
        if (!read_code(pc, byte_disp))
            return false;
        disp = static_cast<uint32_t>(static_cast<int32_t>(
            static_cast<int8_t>(byte_disp)));
    } else if (mode == 2 || disp_only) {
        if (!read_disp32(pc, disp))
            return false;
    }

    source = base + index + disp; // x86 effective addresses wrap at 32 bits.
    return source >= GUEST_NULL_LIMIT &&
           source < GUEST_SIZE && bytes <= GUEST_SIZE - source;
}
// Convert raw guest lane bits by memcpy: no pointer punning or host ABI
// assumptions, and the source XMM snapshot is valid on ARM64 as well.
float lane_f32(uint32_t bits) {
    float value;
    std::memcpy(&value, &bits, sizeof value);
    return value;
}

double lane_f64(const uint32_t *pair) {
    double value;
    std::memcpy(&value, pair, sizeof value);
    return value;
}

void store_f32(uint32_t &out, float value) {
    std::memcpy(&out, &value, sizeof value);
}

void store_f64(uint32_t *out, double value) {
    std::memcpy(out, &value, sizeof value);
}

// Compare-mask semantics for the SSE CMP*PS/SS/SD imm8 predicates (0..7).
// NLE and NEQ are *unordered* comparisons; NaN therefore produces true.
template <typename T>
bool cmp_predicate(T lhs, T rhs, uint8_t pred) {
    const bool unordered = std::isnan(lhs) || std::isnan(rhs);
    switch (pred) {
    case 0: return !unordered && lhs == rhs;
    case 1: return !unordered && lhs < rhs;
    case 2: return !unordered && lhs <= rhs;
    case 3: return unordered;
    case 4: return unordered || lhs != rhs;
    case 5: return unordered || !(lhs < rhs);
    case 6: return unordered || !(lhs <= rhs);
    case 7: return !unordered;
    default: return false;
    }
}
} // namespace

extern "C" void reflex_packed_sse(X86 *c, uint32_t guest_pc) {
    uint32_t pc = guest_pc;
    uint8_t prefix = 0, first = 0, opcode = 0, modrm = 0;
    if (!read_code(pc, first)) {
        recomp_unmodelled(c, guest_pc);
        return;
    }
    if (first == 0x66 || first == 0xf2 || first == 0xf3) {
        prefix = first;
        if (!read_code(pc, first)) {
            recomp_unmodelled(c, guest_pc);
            return;
        }
    }
    if (first != 0x0f || !read_code(pc, opcode) ||
        !read_code(pc, modrm)) {
        std::fprintf(stderr, "[reflex-simd] invalid opcode at %08x\n", guest_pc);
        recomp_unmodelled(c, guest_pc);
        return;
    }

    const bool packed_arithmetic =
        prefix == 0 && (opcode == 0x58 || opcode == 0x59 ||
                        opcode == 0x5c || opcode == 0x5e ||
                        opcode == 0x51 || opcode == 0x5d || opcode == 0x5f);
    const bool convert_ps_pd = prefix == 0 && opcode == 0x5a;
    const bool convert_pd_ps = prefix == 0x66 && opcode == 0x5a;
    const bool compare_packed = prefix == 0 && opcode == 0xc2;
    const bool compare_scalar_ss = prefix == 0xf3 && opcode == 0xc2;
    const bool compare_scalar_sd = prefix == 0xf2 && opcode == 0xc2;

    if (!packed_arithmetic && !convert_ps_pd && !convert_pd_ps &&
        !compare_packed && !compare_scalar_ss && !compare_scalar_sd) {
        std::fprintf(stderr, "[reflex-simd] unsupported opcode at %08x prefix=%02x op=%02x\n",
                     guest_pc, prefix, opcode);
        recomp_unmodelled(c, guest_pc);
        return;
    }

    // Memory source sizes are encoded by the instruction family. In
    // particular, CVTPS2PD reads only 64 bits from m64 and CMPSS only m32;
    // validating 16 bytes here would reject legal near-boundary operands.
    const uint32_t source_bytes = convert_ps_pd ? 8u :
                                  compare_scalar_ss ? 4u :
                                  compare_scalar_sd ? 8u : 16u;
    const unsigned dest = (modrm >> 3) & 7u;
    uint32_t source = 0;
    bool reg = false;
    if (!decode_source(c, pc, modrm, source, reg, source_bytes)) {
        std::fprintf(stderr, "[reflex-simd] invalid source at %08x\n", guest_pc);
        recomp_unmodelled(c, guest_pc);
        return;
    }

    uint8_t predicate = 0;
    if (compare_packed || compare_scalar_ss || compare_scalar_sd) {
        if (!read_code(pc, predicate) || predicate > 7) {
            std::fprintf(stderr, "[reflex-simd] invalid compare predicate at %08x\n", guest_pc);
            recomp_unmodelled(c, guest_pc);
            return;
        }
    }

    // Snapshot all read lanes before touching the destination. It is legal
    // for the source XMM and destination XMM to be the same register.
    uint32_t rhs[4] = {}, lhs[4] = {}, result[4] = {};
    const unsigned words = reg ? 4u : source_bytes / 4u;
    for (unsigned n = 0; n < words; ++n)
        rhs[n] = reg ? c->xmm[source][n] : rd32(source + 4u * n);
    for (unsigned n = 0; n < 4; ++n)
        lhs[n] = result[n] = c->xmm[dest][n];

    if (convert_ps_pd) {
        // CVTPS2PD xmm, xmm/m64: two f32 -> two f64 (all 128 bits).
        const double a = static_cast<double>(lane_f32(rhs[0]));
        const double b = static_cast<double>(lane_f32(rhs[1]));
        store_f64(&result[0], a);
        store_f64(&result[2], b);
    } else if (convert_pd_ps) {
        // CVTPD2PS xmm, xmm/m128: two f64 -> two f32, high qword zero.
        store_f32(result[0], static_cast<float>(lane_f64(&rhs[0])));
        store_f32(result[1], static_cast<float>(lane_f64(&rhs[2])));
        result[2] = result[3] = 0;
    } else if (compare_scalar_sd) {
        const bool pass = cmp_predicate(lane_f64(lhs), lane_f64(rhs), predicate);
        result[0] = result[1] = pass ? 0xffffffffu : 0u;
    } else if (compare_scalar_ss) {
        const bool pass = cmp_predicate(lane_f32(lhs[0]), lane_f32(rhs[0]), predicate);
        result[0] = pass ? 0xffffffffu : 0u;
    } else if (compare_packed) {
        for (unsigned n = 0; n < 4; ++n)
            result[n] = cmp_predicate(lane_f32(lhs[n]), lane_f32(rhs[n]), predicate)
                ? 0xffffffffu : 0u;
    } else {
        for (unsigned n = 0; n < 4; ++n) {
            const float a = lane_f32(lhs[n]), b = lane_f32(rhs[n]);
            switch (opcode) {
            case 0x58: store_f32(result[n], a + b); break; // ADDPS
            case 0x59: store_f32(result[n], a * b); break; // MULPS
            case 0x5c: store_f32(result[n], a - b); break; // SUBPS
            case 0x5e: store_f32(result[n], a / b); break; // DIVPS
            case 0x51: store_f32(result[n], std::sqrt(b)); break; // SQRTPS
            case 0x5d: result[n] = a < b ? lhs[n] : rhs[n]; break; // MINPS
            case 0x5f: result[n] = a > b ? lhs[n] : rhs[n]; break; // MAXPS
            }
        }
    }

    for (unsigned n = 0; n < 4; ++n)
        c->xmm[dest][n] = result[n];
}
