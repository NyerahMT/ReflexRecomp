#!/usr/bin/env python3
"""Bounded evidence: distinguish low-alpha source textures vs low-brightness blending.

Never modifies guest shader state, texture bytes or frame pixels.
Runs AFTER patch_reflex_d3d9_update_texture and the FFP bridge; the
REFLEX_BRIGHTNESS_PROBE=1 environment flag enables the actual logs.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("dx/d3d9.cpp")
MARKER = "reflex-ui-brightness-source-probe-v1"

UPDATE_OLD = r'''    const unsigned long long n = updates.fetch_add(1) + 1;
    if (n <= 8u || ((n & (n - 1u)) == 0u))
'''
UPDATE_NEW = r'''    const unsigned long long n = updates.fetch_add(1) + 1;
    // reflex-ui-brightness-source-probe-v1: profile *original* CPU texture
    // bytes before blaming output blending. Sampling is bounded to 4096
    // source bytes; it never modifies the texture or guest-visible state.
    const char *brightness_probe = std::getenv("REFLEX_BRIGHTNESS_PROBE");
    if (brightness_probe && brightness_probe[0] == '1' &&
        (n <= 8u || ((n & (n - 1u)) == 0u)) && !from.empty()) {
        const std::vector<uint8_t> &b = from[0]->blob;
        const size_t stride = std::max<size_t>(1u, b.size() / 4096u);
        uint32_t peak = 0u, low = 0u, high = 0u, total = 0u;
        for (size_t j = 0; j < b.size(); j += stride) {
            const uint32_t val = b[j];
            peak = std::max<uint32_t>(peak, val);
            low += val > 0u && val <= 15u;
            high += val > 15u;
            ++total;
        }
        LOGW("[reflex-brightness] texture n=%llu fmt=%u size=%ux%u "
             "src=%u dst=%u samples=%u nonzero-le15=%u gt15=%u peak=%u",
             n, src->rmask, src->width, src->height, src->id, dst->id,
             total, low, high, peak);
    }
    if (n <= 8u || ((n & (n - 1u)) == 0u))
'''
DRAW_OLD = r'''    d.label = pl.label;
    host_d9_draw(&d);
'''
DRAW_NEW = r'''    d.label = pl.label;
    // Original game render-state profile. A src-alpha blend can explain a
    // uniformly 15/255 framebuffer even when input texture bytes reach 255.
    // Print first eight draws, power-of-two draws, and first 32 to the real
    // backbuffer; no per-frame flood during extended original-game tests.
    const char *brightness_env = std::getenv("REFLEX_BRIGHTNESS_PROBE");
    if (brightness_env && brightness_env[0] == '1') {
        static std::atomic<unsigned long long> draws{0}, bb_draws{0};
        const unsigned long long n = draws.fetch_add(1) + 1;
        const ComObj *bb = device_backbuffer(dev);
        const bool backbuffer = bb && pl.color_target[0] == bb->id;
        const unsigned long long bn =
            backbuffer ? bb_draws.fetch_add(1) + 1 : 0;
        if (n <= 8u || ((n & (n - 1u)) == 0u) ||
            (backbuffer && (bn <= 8u || ((bn & (bn - 1u)) == 0u)))) {
            LOGW("[reflex-brightness] draw n=%llu bbdraw=%llu bb=%u target=%u "
                 "texture0=%u vsbytes=%zu psbytes=%zu blend=%u src=%u dst=%u "
                 "blendop=%u alpha=%u alphatest=%u alpharef=%u "
                 "colorwrite=%x factor=%08x srgbwrite=%u pconst0=%g,%g,%g,%g",
                 n, bn, backbuffer ? 1u : 0u, pl.color_target[0],
                 pl.sampler_tex[0], pl.vs.size(), pl.ps.size(),
                 pl.rs[27], pl.rs[19], pl.rs[20], pl.rs[171],
                 pl.rs[207], pl.rs[15], pl.rs[24],
                 pl.rs[168], pl.rs[193], pl.rs[194],
                 double(pl.pconst[0][0]), double(pl.pconst[0][1]),
                 double(pl.pconst[0][2]), double(pl.pconst[0][3]));
        }
    }
    // reflex-offscreen-rgb-alpha-probe-v1: read-only GPU checkpoints around
    // original offscreen draws; never replace shaders, states or pixels.
    const char *off_flag = std::getenv("REFLEX_BRIGHTNESS_PROBE");
    const bool tracing = off_flag && off_flag[0] == '1' && off_flag[1] == '\0';
    ComObj *off_rt = tracing ? com_get(pl.color_target[0]) : nullptr;
    const ComObj *bb = tracing ? device_backbuffer(dev) : nullptr;
    const bool offscreen = off_rt && off_rt->kind == K_D3D9SURFACE &&
        (!bb || off_rt->id != bb->id);
    static std::atomic<unsigned long long> offdraws{0};
    const unsigned long long od = offscreen ? offdraws.fetch_add(1) + 1 : 0;
    const bool checkpoint = off_flag && off_flag[0] == '1' &&
        (od == 1u || od == 8u || od == 64u || od == 512u ||
         od == 8192u || od == 65536u);
    uint32_t slot = 0;
    ComObj *owner = checkpoint ? com_get(mirror_slot(off_rt, &slot)) : nullptr;
    const bool readable = owner && owner->kind == K_D3D9TEXTURE &&
        (owner->rmask == 21u || owner->rmask == 22u ||
         owner->rmask == 32u || owner->rmask == 33u) &&
        off_rt->width && off_rt->height &&
        uint64_t(off_rt->width) * off_rt->height <= 2048u * 2048u;
    HostD9Surface surface{};
    uint32_t pitch = 0;
    std::vector<uint8_t> pixels;
    if (checkpoint) {
        LOGW("[reflex-offscreen] candidate od=%llu rt=%u owner=%u fmt=%u "
             "size=%ux%u eligible=%u tex0=%u blend=%u src=%u dst=%u "
             "colorwrite=%x vsbytes=%zu psbytes=%zu",
             od, off_rt ? off_rt->id : 0u,
             owner ? owner->id : 0u, owner ? owner->rmask : 0u,
             off_rt ? off_rt->width : 0u, off_rt ? off_rt->height : 0u,
             readable ? 1u : 0u, pl.sampler_tex[0], pl.rs[27],
             pl.rs[19], pl.rs[20], pl.rs[168],
             pl.vs.size(), pl.ps.size());
        if (readable) {
            surface = surface_ref(off_rt);
            pitch = off_rt->width * 4u;
            pixels.resize(size_t(pitch) * off_rt->height);
        }
    }
    // reflex-source-alpha-probe-v1: inspect the *bound* original texture on
    // the same six draws. Decode raw 32-bit textures only; unsupported formats
    // are reported, never interpreted as RGBA. No shader or blend overrides.
    ComObj *sampler0 = checkpoint ? com_get(pl.sampler_tex[0]) : nullptr;
    const bool sampleable = sampler0 && sampler0->kind == K_D3D9TEXTURE &&
        (sampler0->rmask == 21u || sampler0->rmask == 22u ||
         sampler0->rmask == 32u || sampler0->rmask == 33u) &&
        sampler0->width && sampler0->height &&
        uint64_t(sampler0->width) * sampler0->height <= 2048u * 2048u;
    if (checkpoint) {
        LOGW("[reflex-source-alpha] bound od=%llu tex=%u kind=%u fmt=%u "
             "size=%ux%u eligible=%u psbytes=%zu c0=%g,%g,%g,%g",
             od, sampler0 ? sampler0->id : 0u,
             sampler0 ? unsigned(sampler0->kind) : 0u,
             sampler0 ? sampler0->rmask : 0u,
             sampler0 ? sampler0->width : 0u,
             sampler0 ? sampler0->height : 0u,
             sampleable ? 1u : 0u, pl.ps.size(),
             double(pl.pconst[0][0]), double(pl.pconst[0][1]),
             double(pl.pconst[0][2]), double(pl.pconst[0][3]));
    }
    if (sampleable) {
        const uint32_t src_pitch = sampler0->width * 4u;
        const size_t total = size_t(sampler0->width) * sampler0->height;
        std::vector<uint8_t> src_rgba(size_t(src_pitch) * sampler0->height);
        const int ok = host_d9_texture_read(
            sampler0->id, 0u, 0u, src_rgba.data(), src_pitch);
        uint32_t rgb_peak = 0, alpha_peak = 0, a0 = 0, a1_15 = 0;
        uint32_t a16_254 = 0, a255 = 0, rgb_gt15 = 0, sampled = 0;
        if (ok) {
            const size_t stride = std::max<size_t>(1u, total / 4096u);
            for (size_t i = 0; i < total; i += stride) {
                const uint8_t *p = src_rgba.data() + i * 4u;
                const uint32_t rgb = std::max<uint32_t>(
                    p[0], std::max<uint32_t>(p[1], p[2]));
                rgb_peak = std::max(rgb_peak, rgb);
                alpha_peak = std::max<uint32_t>(alpha_peak, p[3]);
                rgb_gt15 += rgb > 15u;
                a0 += p[3] == 0u;
                a1_15 += p[3] > 0u && p[3] <= 15u;
                a16_254 += p[3] > 15u && p[3] < 255u;
                a255 += p[3] == 255u;
                ++sampled;
            }
        }
        LOGW("[reflex-source-alpha] pixels od=%llu read=%d sampled=%u "
             "rgb_gt15=%u rgb_peak=%u alpha_peak=%u "
             "a0=%u a1_15=%u a16_254=%u a255=%u",
             od, ok, sampled, rgb_gt15, rgb_peak, alpha_peak,
             a0, a1_15, a16_254, a255);
    }
    auto snap = [&](const char *phase) {
        if (!readable)
            return;
        const int ok = host_d9_texture_read(
            owner->id, surface.face, surface.level, pixels.data(), pitch);
        uint32_t peak = 0, alpha = 0, above15 = 0, nonzero = 0, sampled = 0;
        if (ok) {
            const size_t total = size_t(off_rt->width) * off_rt->height;
            const size_t stride = std::max<size_t>(1u, total / 4096u);
            for (size_t i = 0; i < total; i += stride) {
                const uint8_t *p = pixels.data() + i * 4u;
                uint32_t rgb = std::max<uint32_t>(
                    p[0], std::max<uint32_t>(p[1], p[2]));
                peak = std::max(peak, rgb);
                alpha = std::max<uint32_t>(alpha, p[3]);
                above15 += rgb > 15u;
                nonzero += rgb > 0u;
                ++sampled;
            }
        }
        LOGW("[reflex-offscreen] pixels od=%llu phase=%s read=%d "
             "samples=%u nonzero=%u gt15=%u rgb_peak=%u alpha_peak=%u",
             od, phase, ok, sampled, nonzero, above15, peak, alpha);
    };
    if (readable)
        snap("before");
    host_d9_draw(&d);
    if (readable)
        snap("after");
'''

def only(src: str, old: str, new: str, name: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {name} anchor; got {count}")
    return src.replace(old, new, 1)

def patch_brightness_probe(kit: Path) -> None:
    path = kit / TARGET
    if not path.is_file():
        raise RuntimeError("Missing pinned D3D9 source")
    text = path.read_text()
    if MARKER in text:
        if (text.count(MARKER) != 1 or
            text.count("[reflex-brightness] texture") != 1 or
            text.count("[reflex-brightness] draw") != 1 or
            UPDATE_OLD in text or DRAW_OLD in text or
            text.count("reflex-offscreen-rgb-alpha-probe-v1") != 1 or
            text.count("[reflex-offscreen] candidate") != 1 or
            text.count("[reflex-offscreen] pixels") != 1 or
            text.count("reflex-source-alpha-probe-v1") != 1 or
            text.count("[reflex-source-alpha] bound") != 1 or
            text.count("[reflex-source-alpha] pixels") != 1):
            raise RuntimeError("Partially installed brightness diagnostic patch")
        return
    modified = only(text, UPDATE_OLD, UPDATE_NEW, "UpdateTexture instrumentation")
    modified = only(modified, DRAW_OLD, DRAW_NEW, "GPU draw instrumentation")
    path.write_text(modified)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    args = parser.parse_args()
    patch_brightness_probe(args.kit)
    print("Installed bounded D3D9 texture-source and GPU blend-state diagnostics")

if __name__ == "__main__":
    main()
