#!/usr/bin/env python3
"""Compare the last original D3D9 compositing texture with Vulkan's backbuffer.

Read-only and opt-in. Runs after the existing frame probe, fixed function
quad bridge, and brightness probe. No guest pixel, shader, state, or timing
changes except the bounded source readback on six diagnostic frames.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("dx/d3d9.cpp")
MARKER = "reflex-composite-source-probe-v1"

BEFORE = r'''        host_d9_present(bb->id, bb->width, bb->height);
        // Sample first 2 and powers of two to 16384: 15 bounded readbacks.
'''
AFTER = r'''        host_d9_present(bb->id, bb->width, bb->height);
        // reflex-composite-source-probe-v1: measure the REAL source texture
        // feeding the final fixed-function backbuffer draw. Sampling this
        // before the fragment shader separates a dark render target from a
        // wrong texture channel/sample used by the compositing bridge.
        // Only the six already captured frames, only when explicitly enabled.
        const char *source_probe = std::getenv("REFLEX_COMPOSITE_PROBE");
        if (source_probe && source_probe[0] == '1' &&
            (n == 1u || n == 8u || n == 64u || n == 256u ||
             n == 4096u || n == 8192u) && dev) {
            D9Pipeline &p = d9_pipeline(dev->id);
            ComObj *tex = com_get(p.sampler_tex[0]);
            // No invented texture views: sample only true CPU-known 32-bit
            // native color layouts, not packed/float/depth unknown formats.
            const bool eligible = tex && tex->kind == K_D3D9TEXTURE &&
                (tex->rmask == 21u || tex->rmask == 22u ||
                 tex->rmask == 32u || tex->rmask == 33u) &&
                tex->width && tex->height &&
                uint64_t(tex->width) * tex->height <= 2048u * 2048u;
            LOGW("[reflex-composite] source n=%llu bb=%u tex=%u kind=%u fmt=%u "
                 "size=%ux%u eligible=%u", n, bb->id, tex ? tex->id : 0,
                 tex ? unsigned(tex->kind) : 0u,
                 tex ? tex->rmask : 0u, tex ? tex->width : 0u,
                 tex ? tex->height : 0u, eligible ? 1u : 0u);
            if (eligible) {
                const uint32_t pitch = tex->width * 4u;
                std::vector<uint8_t> pixels(size_t(pitch) * tex->height);
                const int ok = host_d9_texture_read(tex->id, 0u, 0u, pixels.data(), pitch);
                uint32_t rgb_peak = 0u, alpha_peak = 0u;
                uint32_t nonzero = 0u, above15 = 0u, n_pixels = 0u;
                if (ok) {
                    const size_t stride = std::max<size_t>(
                        1u, (size_t(tex->width) * tex->height) / 4096u);
                    for (size_t q = 0, end = size_t(tex->width) * tex->height;
                         q < end; q += stride) {
                        const uint8_t *rgba = pixels.data() + q * 4u;
                        const uint32_t val = std::max<uint32_t>(
                            rgba[0], std::max<uint32_t>(rgba[1], rgba[2]));
                        rgb_peak = std::max(rgb_peak, val);
                        alpha_peak = std::max<uint32_t>(alpha_peak, rgba[3]);
                        nonzero += val > 0u;
                        above15 += val > 15u;
                        ++n_pixels;
                    }
                }
                LOGW("[reflex-composite] texpixels n=%llu read=%d samples=%u "
                     "nonzero=%u rgb_gt15=%u rgb_peak=%u alpha_peak=%u",
                     n, ok, n_pixels, nonzero, above15, rgb_peak, alpha_peak);
            }
        }
        // Sample first 2 and powers of two to 16384: 15 bounded readbacks.
'''

def patch_composite_source_probe(kit: Path) -> None:
    path = kit / TARGET
    if not path.is_file():
        raise RuntimeError("Pinned D3D9 source missing")
    s = path.read_text()
    if MARKER in s:
        if (s.count(MARKER) != 1 or s.count(AFTER) != 1 or
            BEFORE in s):
            raise RuntimeError("Partial composite source probe installation")
        return
    if s.count(BEFORE) != 1:
        raise RuntimeError("Pinned post-present frame-probe source anchor changed")
    path.write_text(s.replace(BEFORE, AFTER, 1))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    args = parser.parse_args()
    patch_composite_source_probe(args.kit)
    print("Installed bounded real source-vs-backbuffer readback instrumentation")

if __name__ == "__main__":
    main()
