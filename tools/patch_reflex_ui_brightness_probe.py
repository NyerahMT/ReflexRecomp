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
    // reflex-shader-output-alpha-trace-v1: decode the ORIGINAL bound pixel
    // program, not a replacement. Report aggregate destination masks and
    // opcode classes only (no proprietary instruction stream or textures).
    // The Vulkan raster state already proves SRCALPHA/INVSRCALPHA; this
    // identifies whether the shader writes oC0.a or leaves it at default 0.
    if (checkpoint) {
        uint32_t color0_writes = 0, color0_alpha_writes = 0;
        uint32_t color0_rgb_writes = 0, color0_last_mask = 0;
        uint32_t color0_last_op = 0, alpha_last_op = 0;
        uint32_t alpha_last_mask = 0, tex_ops = 0, condition_ops = 0;
        uint32_t saturated_color_writes = 0, temp_alpha_writes = 0;
        for (const d9sh::Inst &in : ps.code) {
            if (in.op == d9sh::OP_TEX || in.op == d9sh::OP_TEXLDL)
                ++tex_ops;
            if (in.op == d9sh::OP_IF || in.op == d9sh::OP_IFC ||
                in.op == d9sh::OP_CMP)
                ++condition_ops;
            if (!in.has_dst)
                continue;
            if (in.dst.type == d9sh::R_TEMP && (in.dst.mask & 8u))
                ++temp_alpha_writes;
            if (in.dst.type != d9sh::R_COLOROUT || in.dst.index != 0u)
                continue;
            ++color0_writes;
            color0_rgb_writes += (in.dst.mask & 7u) != 0u;
            color0_last_mask = in.dst.mask;
            color0_last_op = in.op;
            saturated_color_writes += in.dst.saturate ? 1u : 0u;
            if (in.dst.mask & 8u) {
                ++color0_alpha_writes;
                alpha_last_op = in.op;
                alpha_last_mask = in.dst.mask;
            }
        }
        LOGW("[reflex-shader-alpha] original od=%llu pskey=%016llx "
             "ok=%u sm=%u.%u inst=%zu color0_writes=%u "
             "color0_rgb_writes=%u color0_alpha_writes=%u "
             "last_color_mask=%x last_color_op=%u "
             "last_alpha_mask=%x last_alpha_op=%u "
             "saturate_color=%u temp_alpha_writes=%u "
             "texture_ops=%u conditions=%u",
             od, static_cast<unsigned long long>(d.ps_key),
             ps.ok ? 1u : 0u, ps.major, ps.minor, ps.code.size(),
             color0_writes, color0_rgb_writes, color0_alpha_writes,
             color0_last_mask, color0_last_op,
             alpha_last_mask, alpha_last_op,
             saturated_color_writes, temp_alpha_writes,
             tex_ops, condition_ops);
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
    // reflex-gpu-ab-draw8-v1: ONE bounded, opt-in, GPU-side replay of the
    // exact original draw into two PRIVATE scratch render targets. Never
    // redirect the original draw, guest texture, or guest device states.
    // Existing target #6 was blank before original offscreen draw #8.
    // A: identical blend/write mask into transparent black.
    // B: disable blending and enable all color channels to expose the actual
    // fragment output RGBA. This tests shader versus blend in ONE run.
    const char *ab_env = std::getenv("REFLEX_GPU_AB");
    if (readable && od == 8u && ab_env &&
        ab_env[0] == '1' && ab_env[1] == '\0' &&
        off_rt->width <= 1280u && off_rt->height <= 720u &&
        pl.rs[27] == 1u && pl.rs[19] == 5u &&
        pl.rs[20] == 6u && pl.rs[168] == 7u &&
        !com_get(0xfff80011u) && !com_get(0xfff80012u)) {
        // Guard against feedback: a shader that samples its real destination
        // cannot be faithfully replayed after the original draw completes.
        bool feedback = false;
        for (const uint32_t source : d.sampler_texture)
            feedback |= source == owner->id;
        if (feedback) {
            LOGW("[reflex-gpu-ab] skipped od=%llu reason=feedback", od);
        } else {
            const size_t total = size_t(off_rt->width) * off_rt->height;
            std::vector<uint8_t> replay_blend(total * 4u);
            std::vector<uint8_t> replay_shader(total * 4u);
            uint32_t rs_original[256];
            uint32_t rs_shader[256];
            memcpy(rs_original, pl.rs, sizeof rs_original);
            memcpy(rs_shader, pl.rs, sizeof rs_shader);
            rs_shader[27] = 0u;   // D3DRS_ALPHABLENDENABLE off, scratch only
            rs_shader[168] = 15u; // capture alpha along with RGB in scratch
            const uint32_t scratch_ids[2] = {0xfff80011u, 0xfff80012u};
            int read_ok[2] = {};
            for (unsigned side = 0; side < 2u; ++side) {
                HostD9TextureDesc td{};
                td.id = scratch_ids[side];
                td.kind = HOST_D9_TEX_2D;
                td.width = off_rt->width;
                td.height = off_rt->height;
                td.levels = 1u;
                td.format = 21u; // BGRA8, actual offscreen format
                td.usage = HOST_D9_USAGE_RENDERTARGET;
                td.samples = 1u;
                host_d9_texture_define(&td);
                HostD9Draw dry = d;  // original shaders, vertices, textures
                dry.target = HostD9Target{};
                dry.target.color[0] = HostD9Surface{td.id, 0u, 0u};
                dry.target.depth = HostD9Surface{}; // scratch has no guest depth
                dry.render_state = side == 0u ? rs_original : rs_shader;
                dry.state_version = 0u; // force a fresh snapshot of test state
                host_d9_clear(&dry.target, dry.viewport, 0u, nullptr,
                              1u, 0u, 1.0f, 0u);
                host_d9_draw(&dry);
                uint8_t *out = side == 0u
                    ? replay_blend.data() : replay_shader.data();
                read_ok[side] = host_d9_texture_read(
                    td.id, 0u, 0u, out, td.width * 4u);
                host_d9_texture_drop(td.id);
            }
            // Same pixel locations in all three images, unlike unrelated
            // global brightness maxima from earlier diagnostics.
            uint32_t direct_peak = 0, direct_alpha_peak = 0;
            uint32_t blended_peak = 0, actual_peak = 0;
            uint32_t shader_nonzero = 0, original_nonzero = 0;
            uint32_t active_samples = 0, matches_within2 = 0;
            uint32_t max_blend_error = 0, max_original_error = 0;
            uint32_t shader_alpha_low = 0, shader_alpha_high = 0;
            if (read_ok[0] && read_ok[1]) {
                const size_t stride = std::max<size_t>(1u, total / 4096u);
                for (size_t i = 0; i < total; i += stride) {
                    const uint8_t *s = replay_shader.data() + i * 4u;
                    const uint8_t *b = replay_blend.data() + i * 4u;
                    const uint8_t *o = pixels.data() + i * 4u;
                    uint32_t srgb = std::max<uint32_t>(
                        s[0], std::max<uint32_t>(s[1], s[2]));
                    uint32_t brgb = std::max<uint32_t>(
                        b[0], std::max<uint32_t>(b[1], b[2]));
                    uint32_t orgb = std::max<uint32_t>(
                        o[0], std::max<uint32_t>(o[1], o[2]));
                    direct_peak = std::max(direct_peak, srgb);
                    direct_alpha_peak = std::max<uint32_t>(
                        direct_alpha_peak, s[3]);
                    blended_peak = std::max(blended_peak, brgb);
                    actual_peak = std::max(actual_peak, orgb);
                    shader_nonzero += srgb > 0u;
                    original_nonzero += orgb > 0u;
                    shader_alpha_low += s[3] > 0u && s[3] <= 15u;
                    shader_alpha_high += s[3] >= 128u;
                    if (srgb == 0u)
                        continue;
                    ++active_samples;
                    uint32_t pixel_blend_error = 0u;
                    uint32_t pixel_original_error = 0u;
                    for (unsigned ch = 0u; ch < 3u; ++ch) {
                        // SRCALPHA/INVSRCALPHA over a cleared black target.
                        const int expected = int((unsigned(s[ch]) *
                            unsigned(s[3]) + 127u) / 255u);
                        pixel_blend_error = std::max<uint32_t>(
                            pixel_blend_error,
                            uint32_t(std::abs(int(b[ch]) - expected)));
                        pixel_original_error = std::max<uint32_t>(
                            pixel_original_error,
                            uint32_t(std::abs(int(o[ch]) - int(b[ch]))));
                    }
                    max_blend_error = std::max(max_blend_error, pixel_blend_error);
                    max_original_error = std::max(
                        max_original_error, pixel_original_error);
                    matches_within2 += pixel_blend_error <= 2u;
                }
            }
            LOGW("[reflex-gpu-ab] od=%llu read_original=1 "
                 "read_blend=%d read_direct=%d "
                 "direct_rgb=%u direct_alpha=%u blend_rgb=%u original_rgb=%u "
                 "direct_nonzero=%u original_nonzero=%u "
                 "active=%u within2=%u max_blend_error=%u "
                 "max_original_error=%u shader_alpha_low=%u shader_alpha_high=%u "
                 "depth_detached=1",
                 od, read_ok[0], read_ok[1], direct_peak, direct_alpha_peak,
                 blended_peak, actual_peak, shader_nonzero, original_nonzero,
                 active_samples, matches_within2, max_blend_error,
                 max_original_error, shader_alpha_low, shader_alpha_high);
        }
    }
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
            text.count("[reflex-source-alpha] pixels") != 1 or
            text.count("reflex-shader-output-alpha-trace-v1") != 1 or
            text.count("[reflex-shader-alpha] original") != 1 or
            text.count("reflex-gpu-ab-draw8-v1") != 1 or
            text.count("[reflex-gpu-ab] od=") != 1):
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
