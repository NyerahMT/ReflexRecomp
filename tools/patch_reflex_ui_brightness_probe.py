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
    host_d9_draw(&d);
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
            UPDATE_OLD in text or DRAW_OLD in text):
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
