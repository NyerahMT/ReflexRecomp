#!/usr/bin/env python3
"""Opt-in SM3 fixed-function textured quad fallback for Reflex's FVF 0x104.

Run after shader, swap-chain, FVF, FLOAT16, and frame diagnostics patches.
Avoid modifying the guest's shader bindings; synthesize shader input locally
for precisely the legacy XYZRHW+TEX1 mode observed in real runtime logs.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
MARKER = "reflex-ffp-quad-v1"


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def patch_ffp_quad(kit: Path, runtime: Path) -> None:
    target = kit / "dx" / "d3d9.cpp"
    header = runtime / "reflex_d3d9_ffp_quad.h"
    if not target.is_file() or not header.is_file():
        raise RuntimeError("Missing pinned D3D9 runtime or fallback shader header")
    src = target.read_text()
    if MARKER in src:
        if src.count(MARKER) != 1 or \
                src.count("[reflex-ffp] textured-fvf") != 1 or \
                not (kit / "dx" / header.name).is_file():
            raise RuntimeError("Partial fixed-function fallback installation")
        return
    src = replace_one(
        src, '#include "com.h"\n',
        '#include "com.h"\n#include "reflex_d3d9_ffp_quad.h"\n',
        "D3D9 include",
    )
    src = replace_one(
        src,
        '''    D9Pipeline &pl = d9_pipeline(dev->id);
    if (pl.vs.empty() || pl.ps.empty()) {
        static std::atomic<unsigned long long> skips{0};''',
        '''    D9Pipeline &pl = d9_pipeline(dev->id);
    // reflex-ffp-quad-v1: only the known pretransformed textured format.
    const char *ffp_flag = std::getenv("REFLEX_FFP_QUAD");
    const bool shaderless = pl.vs.empty() && pl.ps.empty();
    // reflex-ffp-declaration-quad-v1: permit only the observed equivalent
    // POSITIONT/FLOAT4 + TEXCOORD0/FLOAT2 declaration and exact byte stride.
    // Never use an object ID as a stand-in for verified vertex semantics.
    ComObj *ffp_decl = com_get(pl.declaration);
    const uint32_t ffp_stride = d.inline_vertices ?
        d.stream[0].stride : pl.stream[0].stride;
    const bool declaration_quad = dev->d9_fvf_current == 0u &&
        ffp_decl && ffp_decl->kind == K_D3D9DECL &&
        reflex_ffp::supported_decl(ffp_decl->blob.data(),
                                   ffp_decl->blob.size(), ffp_stride);
    const bool fixed_function_quad =
        reflex_ffp::supported(dev->d9_fvf_current, pl.sampler_tex[0],
                              pl.tss[0][1], pl.tss[0][2], pl.tss[0][3],
                              pl.tss[0][4], pl.tss[0][5], pl.tss[1][1]) ||
        (declaration_quad &&
         reflex_ffp::supported(0x00000104u, pl.sampler_tex[0],
                              pl.tss[0][1], pl.tss[0][2], pl.tss[0][3],
                              pl.tss[0][4], pl.tss[0][5], pl.tss[1][1]));
    const bool fallback = shaderless && ffp_flag && ffp_flag[0] == '1' &&
        ffp_flag[1] == '\\0' && fixed_function_quad;
    if (fallback && declaration_quad) {
        static std::atomic<unsigned long long> accepted_decl{0};
        const unsigned long long accepted = accepted_decl.fetch_add(1) + 1;
        if (accepted <= 8 || ((accepted & (accepted - 1)) == 0))
            LOGW("[reflex-ffp] textured-decl n=%llu accepted=1 id=%u stride=%u "
                 "tex0=%u target=%u", accepted, pl.declaration,
                 ffp_stride, pl.sampler_tex[0], pl.color_target[0]);
    }
    if (shaderless && ffp_flag && ffp_flag[0] == '1') {
        static std::atomic<unsigned long long> attempts{0};
        const unsigned long long n = attempts.fetch_add(1) + 1;
        if (n <= 8 || ((n & (n - 1)) == 0))
            LOGW("[reflex-ffp] textured-fvf n=%llu eligible=%u fvf=%08x tex0=%u "
                 "c0=%u ca1=%u ca2=%u a0=%u aa1=%u c1=%u",
                 n, fallback ? 1u : 0u, dev->d9_fvf_current,
                 pl.sampler_tex[0], pl.tss[0][1], pl.tss[0][2],
                 pl.tss[0][3], pl.tss[0][4], pl.tss[0][5], pl.tss[1][1]);
        // reflex-ffp-decl-profile-v1: describe only the bounded, unhandled
        // shaderless shape. Never substitute a shader on an unknown layout.
        if (!fallback) {
            static std::atomic<unsigned long long> declined{0};
            const unsigned long long m = declined.fetch_add(1) + 1;
            if (m <= 2 || m == 32) {
                ComObj *decl = com_get(pl.declaration);
                const bool valid_decl = decl && decl->kind == K_D3D9DECL;
                const size_t bytes = valid_decl ? decl->blob.size() : 0u;
                LOGW("[reflex-ffp] declined-decl n=%llu id=%u bytes=%zu tex0=%u "
                     "stream0_stride=%u inline_stride=%u target=%u",
                     m, pl.declaration, bytes, pl.sampler_tex[0],
                     pl.stream[0].stride, d.stream[0].stride, pl.color_target[0]);
                if (valid_decl) {
                    const size_t limit = std::min<size_t>(bytes, 128u);
                    for (size_t off = 0; off + 8u <= limit; off += 8u) {
                        const uint8_t *e = decl->blob.data() + off;
                        const uint32_t stream = uint32_t(e[0]) | (uint32_t(e[1]) << 8u);
                        const uint32_t offset = uint32_t(e[2]) | (uint32_t(e[3]) << 8u);
                        if (stream == 0xffu) break; // D3DDECL_END
                        LOGW("[reflex-ffp] decl-element n=%llu idx=%zu stream=%u "
                             "offset=%u type=%u method=%u usage=%u usage_index=%u",
                             m, off / 8u, stream, offset,
                             e[4], e[5], e[6], e[7]);
                    }
                }
            }
        }
    }
    if ((pl.vs.empty() || pl.ps.empty()) && !fallback) {
        static std::atomic<unsigned long long> skips{0};''',
        "post-frame-probe GPU draw dispatch",
    )
    src = replace_one(
        src,
        '''    if (!pl.vs_key)
        pl.vs_key = d9sh::code_key(pl.vs.data(), pl.vs.size());
    if (!pl.ps_key)
        pl.ps_key = d9sh::code_key(pl.ps.data(), pl.ps.size());
    const d9sh::Program &vs = d9sh::program_for_key(pl.vs_key, pl.vs.data(), pl.vs.size());
    const d9sh::Program &ps = d9sh::program_for_key(pl.ps_key, pl.ps.data(), pl.ps.size());
    d.vs_key = pl.vs_key;
    d.ps_key = pl.ps_key;
    d.vs = pl.vs.data();
    d.vs_size = (uint32_t)pl.vs.size();
    d.ps = pl.ps.data();
    d.ps_size = (uint32_t)pl.ps.size();
    d.vconst = &pl.vconst[0][0];
    d.vconst_count = std::min<uint32_t>(vs.max_const, 256);
    d.pconst = &pl.pconst[0][0];
    d.pconst_count = std::min<uint32_t>(ps.max_const, 32);''',
        '''    const std::vector<uint8_t> &vs_bytes =
        fallback ? reflex_ffp::quad_vs() : pl.vs.vec();
    const std::vector<uint8_t> &ps_bytes =
        fallback ? reflex_ffp::quad_ps() : pl.ps.vec();
    if (!fallback) {
        if (!pl.vs_key)
            pl.vs_key = d9sh::code_key(pl.vs.data(), pl.vs.size());
        if (!pl.ps_key)
            pl.ps_key = d9sh::code_key(pl.ps.data(), pl.ps.size());
    }
    const uint64_t vs_key = fallback
        ? d9sh::code_key(vs_bytes.data(), vs_bytes.size()) : pl.vs_key;
    const uint64_t ps_key = fallback
        ? d9sh::code_key(ps_bytes.data(), ps_bytes.size()) : pl.ps_key;
    const d9sh::Program &vs =
        d9sh::program_for_key(vs_key, vs_bytes.data(), vs_bytes.size());
    const d9sh::Program &ps =
        d9sh::program_for_key(ps_key, ps_bytes.data(), ps_bytes.size());
    float ffp_constants[2][4] = {};
    if (fallback && !reflex_ffp::clip_constants(
            float(d.viewport[0]), float(d.viewport[1]),
            float(d.viewport[2]), float(d.viewport[3]), ffp_constants)) {
        log_once("reflex.ffp.invalidviewport",
                 "Reflex FFP fallback: invalid viewport; skipping draw");
        return;
    }
    d.vs_key = vs_key;
    d.ps_key = ps_key;
    d.vs = vs_bytes.data();
    d.vs_size = static_cast<uint32_t>(vs_bytes.size());
    d.ps = ps_bytes.data();
    d.ps_size = static_cast<uint32_t>(ps_bytes.size());
    d.vconst = fallback ? &ffp_constants[0][0] : &pl.vconst[0][0];
    d.vconst_count = std::min<uint32_t>(vs.max_const, 256);
    d.pconst = &pl.pconst[0][0];
    d.pconst_count = std::min<uint32_t>(ps.max_const, 32);''',
        "native GPU shader selection",
    )
    # Every pinned anchor was verified. Do not mutate game code or shader state.
    (kit / "dx" / header.name).write_bytes(header.read_bytes())
    target.write_text(src)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    args = parser.parse_args()
    patch_ffp_quad(args.kit, args.runtime)
    print("Installed opt-in Reflex D3D9 fixed-function textured quad fallback")


if __name__ == "__main__":
    main()
