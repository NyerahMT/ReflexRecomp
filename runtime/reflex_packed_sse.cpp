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
                   uint32_t &source, bool &in_register) {
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
           source < GUEST_SIZE && 16 <= GUEST_SIZE - source;
}
}

extern "C" void reflex_packed_sse(X86 *c, uint32_t guest_pc) {
    uint32_t pc = guest_pc;
    uint8_t first = 0, opcode = 0, modrm = 0;
    if (!read_code(pc, first) || first != 0x0f ||
        !read_code(pc, opcode) ||
        (opcode != 0x58 && opcode != 0x59 && opcode != 0x5c) ||
        !read_code(pc, modrm)) {
        std::fprintf(stderr,
                     "[reflex-simd] unsupported packed-single encoding at %08x\n",
                     guest_pc);
        recomp_unmodelled(c, guest_pc);
        return;
    }

    const unsigned dest = (modrm >> 3) & 7u;
    uint32_t source = 0;
    bool reg = false;
    if (!decode_source(c, pc, modrm, source, reg)) {
        std::fprintf(stderr,
                     "[reflex-simd] invalid packed-single source at %08x\n",
                     guest_pc);
        recomp_unmodelled(c, guest_pc);
        return;
    }

    // Read the entire source before writing the destination. This supports
    // MULPS XMMn,XMMn and overlapping guest data safely.
    float rhs[4], lhs[4], result[4];
    for (unsigned i = 0; i < 4; ++i) {
        const uint32_t bits = reg ? c->xmm[source][i] : rd32(source + 4 * i);
        std::memcpy(&rhs[i], &bits, sizeof bits);
        std::memcpy(&lhs[i], &c->xmm[dest][i], sizeof(float));
    }
    for (unsigned i = 0; i < 4; ++i) {
        switch (opcode) {
        case 0x58: result[i] = lhs[i] + rhs[i]; break;
        case 0x59: result[i] = lhs[i] * rhs[i]; break;
        default: result[i] = lhs[i] - rhs[i]; break;
        }
    }
    for (unsigned i = 0; i < 4; ++i)
        std::memcpy(&c->xmm[dest][i], &result[i], sizeof(float));
}
