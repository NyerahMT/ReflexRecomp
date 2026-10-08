#!/usr/bin/env python3
"""Patch one proven SSE2 translation trap in the private Reflex cache.

The baseline is owned by ReflexBuildInput and is never shipped or committed.
The pinned recomp-kit emits a recomp_unmodelled() abort at 0x007b6d4f for
CVTPD2PS XMM1,XMM0. This corrects the cached *generated code*, not the
original game or the pinned kit, before the host compiler runs.

CVTPD2PS converts two packed IEEE-754 doubles to 32-bit floats using MXCSR
rounding and zeros the upper 64 bits of the destination XMM register.
The headless recomp runtime currently uses the standard nearest-even mode.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "build" / "recomp" / "gen"
ADDRESS = 0x007B6D4F
MARKER = "Reflex CVTPD2PS 007b6d4f"
TRAP = re.compile(
    r"\brecomp_unmodelled\s*\(\s*c\s*,\s*0x0*7b6d4fu\s*\)\s*;\s*return\s*;",
    re.IGNORECASE,
)

# Self-contained C, valid in C++ too; generated chunks already include x86.h.
# Snapshot the two source doubles before writing XMM1. memcpy avoids type
# punning/aliasing and preserves IEEE bit patterns on little-endian ARM64.
REPLACEMENT = """{
    /* Reflex CVTPD2PS 007b6d4f: xmm1 <- {float(xmm0.q0), float(xmm0.q1), 0, 0} */
    const double reflex_cv_lo = xmm_f64(c, 0);
    const uint64_t reflex_cv_hi_bits =
        (uint64_t)c->xmm[0][2] | ((uint64_t)c->xmm[0][3] << 32);
    double reflex_cv_hi;
    memcpy(&reflex_cv_hi, &reflex_cv_hi_bits, sizeof reflex_cv_hi);
    const float reflex_cv_f0 = (float)reflex_cv_lo;
    const float reflex_cv_f1 = (float)reflex_cv_hi;
    memcpy(&c->xmm[1][0], &reflex_cv_f0, sizeof reflex_cv_f0);
    memcpy(&c->xmm[1][1], &reflex_cv_f1, sizeof reflex_cv_f1);
    c->xmm[1][2] = 0;
    c->xmm[1][3] = 0;
}"""


def patch_generated_sse(directory: Path) -> Path:
    files = sorted(directory.glob("chunk_*.c"))
    if not files:
        raise RuntimeError(f"no cached translation chunks under {directory}")
    previously_patched = [path for path in files if MARKER in path.read_text()]
    if previously_patched:
        if len(previously_patched) != 1:
            raise RuntimeError("multiple Reflex CVTPD2PS patches found")
        return previously_patched[0]

    hits = []
    for path in files:
        code = path.read_text()
        for match in TRAP.finditer(code):
            hits.append((path, code, match))
    if len(hits) != 1:
        raise RuntimeError(
            f"expected exactly one CVTPD2PS translation trap at {ADDRESS:08x}; "
            f"found {len(hits)}"
        )
    path, code, match = hits[0]
    path.write_text(code[:match.start()] + REPLACEMENT + code[match.end():])
    return path


# Reflex also reaches MULPS XMM0, [ESP+0x10] at 0x007b34d4.
# Four independent single-precision lane multiplies; the source is guest
# stack memory and must be read before each destination lane write.
MULPS_ADDRESS = 0x007B34D4
MULPS_MARKER = "Reflex MULPS 007b34d4"
MULPS_TRAP = re.compile(
    r"\brecomp_unmodelled\s*\(\s*c\s*,\s*0x0*7b34d4u\s*\)\s*;\s*return\s*;",
    re.IGNORECASE,
)
MULPS_REPLACEMENT = """{
    /* Reflex MULPS 007b34d4: xmm0.f[0:4] *= guest [ESP+0x10].f[0:4] */
    const uint32_t reflex_mul_src = c->r[R_ESP] + 0x10u;
    for (uint32_t reflex_mul_lane = 0; reflex_mul_lane < 4; ++reflex_mul_lane) {
        float reflex_mul_dst;
        memcpy(&reflex_mul_dst, &c->xmm[0][reflex_mul_lane], sizeof reflex_mul_dst);
        const float reflex_mul_rhs = rdf32(reflex_mul_src + 4u * reflex_mul_lane);
        const float reflex_mul_result = reflex_mul_dst * reflex_mul_rhs;
        memcpy(&c->xmm[0][reflex_mul_lane], &reflex_mul_result, sizeof reflex_mul_result);
    }
}"""


def patch_cached_mulps(directory: Path) -> Path:
    files = sorted(directory.glob("chunk_*.c"))
    patched = [path for path in files if MULPS_MARKER in path.read_text()]
    if patched:
        if len(patched) != 1:
            raise RuntimeError("multiple Reflex MULPS patches found")
        return patched[0]

    hits = []
    for path in files:
        code = path.read_text()
        for match in MULPS_TRAP.finditer(code):
            hits.append((path, code, match))
    if len(hits) != 1:
        raise RuntimeError(
            f"expected exactly one MULPS translation trap at {MULPS_ADDRESS:08x}; "
            f"found {len(hits)}"
        )
    path, code, match = hits[0]
    path.write_text(code[:match.start()] + MULPS_REPLACEMENT + code[match.end():])
    return path


# Later in the same setup routine: MULPS XMM1, XMM0 at 0x007b350a.
# Unlike the memory form, both operands are already in XMM registers.
MULPS_REG_ADDRESS = 0x007B350A
MULPS_REG_MARKER = "Reflex MULPS 007b350a"
MULPS_REG_TRAP = re.compile(
    r"\brecomp_unmodelled\s*\(\s*c\s*,\s*0x0*7b350au\s*\)\s*;\s*return\s*;",
    re.IGNORECASE,
)
MULPS_REG_REPLACEMENT = """{
    /* Reflex MULPS 007b350a: xmm1.f[0:4] *= xmm0.f[0:4] */
    for (uint32_t reflex_reg_lane = 0; reflex_reg_lane < 4; ++reflex_reg_lane) {
        float reflex_reg_lhs;
        float reflex_reg_rhs;
        memcpy(&reflex_reg_lhs, &c->xmm[1][reflex_reg_lane], sizeof reflex_reg_lhs);
        memcpy(&reflex_reg_rhs, &c->xmm[0][reflex_reg_lane], sizeof reflex_reg_rhs);
        const float reflex_reg_result = reflex_reg_lhs * reflex_reg_rhs;
        memcpy(&c->xmm[1][reflex_reg_lane], &reflex_reg_result,
               sizeof reflex_reg_result);
    }
}"""


def patch_cached_mulps_reg(directory: Path) -> Path:
    files = sorted(directory.glob("chunk_*.c"))
    patched = [path for path in files if MULPS_REG_MARKER in path.read_text()]
    if patched:
        if len(patched) != 1:
            raise RuntimeError("multiple register-register MULPS patches found")
        return patched[0]
    hits = []
    for path in files:
        code = path.read_text()
        for match in MULPS_REG_TRAP.finditer(code):
            hits.append((path, code, match))
    if len(hits) != 1:
        raise RuntimeError(
            f"expected exactly one MULPS trap at {MULPS_REG_ADDRESS:08x}; "
            f"found {len(hits)}"
        )
    path, code, match = hits[0]
    path.write_text(code[:match.start()] + MULPS_REG_REPLACEMENT + code[match.end():])
    return path


def main() -> None:
    path = patch_generated_sse(GEN)
    print(f"Patched Reflex CVTPD2PS at {ADDRESS:08x} in {path.name}")
    mulps_path = patch_cached_mulps(GEN)
    print(f"Patched Reflex MULPS at {MULPS_ADDRESS:08x} in {mulps_path.name}")
    mulps_reg_path = patch_cached_mulps_reg(GEN)
    print(f"Patched Reflex MULPS at {MULPS_REG_ADDRESS:08x} in {mulps_reg_path.name}")


if __name__ == "__main__":
    main()
