#!/usr/bin/env python3
"""Decode Reflex's FLOAT16_2/FLOAT16_4 vertex formats in D3D9's CPU path.

Reflex's first observed UI draws use POSITION0 FLOAT16_2,
TEXCOORD0 FLOAT16_2 and COLOR0 D3DCOLOR with 12-byte vertices. The pinned
CPU shader rasterizer does not decode FLOAT16 attributes; its diagnostic
printer instead interprets packed half floats as unrelated 32-bit floats.

This patch changes neither shader state nor draw acceptance: it fixes vertex
input decoding and diagnostics once shaders execute.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
MARKER = "reflex-float16-diagnostic-v1"


def once(source: str, old: str, new: str, label: str) -> str:
    n = source.count(old)
    if n != 1:
        raise RuntimeError(f"Expected one {label}, found {n}")
    return source.replace(old, new, 1)


def patch_float16(kit: Path, runtime: Path) -> None:
    raster = kit / "dx" / "d3d9_raster.cpp"
    d3d = kit / "dx" / "d3d9.cpp"
    helper = runtime / "reflex_d3d9_half.h"
    if not (raster.is_file() and d3d.is_file() and helper.is_file()):
        raise RuntimeError("Missing pinned D3D9 sources or Reflex FLOAT16 helper")
    s = raster.read_text()
    t = d3d.read_text()
    if MARKER in t:
        if t.count(MARKER) != 1 or "case 15: // FLOAT16_2" not in s or \
                '#include "reflex_d3d9_half.h"' not in s or \
                not (kit / "dx" / "reflex_d3d9_half.h").is_file():
            raise RuntimeError("Partially installed FLOAT16 bridge")
        return

    s = once(s, '#include "d3d9_raster.h"\n',
             '#include "d3d9_raster.h"\n#include "reflex_d3d9_half.h"\n',
             "raster include")
    s = once(
        s,
        "    case 7:\n"
        "        for (int k = 0; k < 4; ++k)\n"
        "            v[k] = (int16_t)(c[2 * k] | c[2 * k + 1] << 8);\n"
        "        break;\n"
        "    default:\n",
        "    case 7:\n"
        "        for (int k = 0; k < 4; ++k)\n"
        "            v[k] = (int16_t)(c[2 * k] | c[2 * k + 1] << 8);\n"
        "        break;\n"
        "    case 15: // FLOAT16_2: two IEEE-754 binary16 components\n"
        "        v[0] = reflex_d3d9::float16_component(c, 0);\n"
        "        v[1] = reflex_d3d9::float16_component(c, 1);\n"
        "        break;\n"
        "    case 16: // FLOAT16_4: four IEEE-754 binary16 components\n"
        "        for (int k = 0; k < 4; ++k)\n"
        "            v[k] = reflex_d3d9::float16_component(c, k);\n"
        "        break;\n"
        "    default:\n",
        "CPU vertex type switch",
    )
    s = once(
        s,
        "e.offset + 4u <= call.stride)\n"
        "                        m.in[d.index & 15] = fetch(vp, e);",
        "e.offset <= call.stride &&\n"
        "                        reflex_d3d9::vertex_element_bytes(e.type) &&\n"
        "                        reflex_d3d9::vertex_element_bytes(e.type) <=\n"
        "                            call.stride - e.offset)\n"
        "                        m.in[d.index & 15] = fetch(vp, e);",
        "CPU declaration bounds",
    )

    t = once(t, '#include "com.h"\n',
             '#include "com.h"\n#include "reflex_d3d9_half.h"\n',
             "device diagnostic include")
    original = r'''    for (uint32_t v = 0; v < nverts && v < 4; ++v) {
        uint32_t base = vertices + v * stride;
        char line[256];
        size_t used = 0;
        for (uint32_t o = 0; o + 4 <= stride && o < 40; o += 4)
            used += (size_t)snprintf(
                line + used, sizeof line - used, " %g", (double)[&] {
                    float f;
                    uint32_t bits = rd32(base + o);
                    memcpy(&f, &bits, 4);
                    return f;
                }());
        LOGW("d3d9:   vertex %u:%s", v, line);
    }
'''
    replacement = r'''    // reflex-float16-diagnostic-v1: report the declared half-floats, not
    // 32-bit reinterpretations of two adjacent IEEE-754 half components.
    for (uint32_t v = 0; v < nverts && v < 4; ++v) {
        const uint64_t base64 = uint64_t(vertices) + uint64_t(v) * stride;
        if (base64 > UINT32_MAX || !gm_fits(uint32_t(base64), stride)) {
            LOGW("d3d9:   vertex %u: invalid guest range", v);
            continue;
        }
        const uint32_t base = uint32_t(base64);
        char line[512] = {};
        size_t used = 0;
        if (decl && decl->kind == K_D3D9DECL) {
            for (size_t i = 0; i + 8 <= decl->blob.size(); i += 8) {
                const uint16_t stream = uint16_t(decl->blob[i] | decl->blob[i+1] << 8);
                if (stream == 0xff) break;
                if (stream != 0) continue;
                const uint32_t off = uint32_t(decl->blob[i+2] | decl->blob[i+3] << 8);
                const uint8_t type = decl->blob[i+4];
                const uint8_t usage = decl->blob[i+6];
                const uint8_t index = decl->blob[i+7];
                const uint32_t bytes = reflex_d3d9::vertex_element_bytes(type);
                if (!bytes || off > stride || bytes > stride - off || used >= sizeof line)
                    continue;
                const uint8_t *data = gm_ptr(base + off);
                char part[112] = {};
                if (type == 15) {
                    snprintf(part, sizeof part, " %u:%u=(%g,%g)",
                             unsigned(usage), unsigned(index),
                             double(reflex_d3d9::float16_component(data, 0)),
                             double(reflex_d3d9::float16_component(data, 1)));
                } else if (type == 16) {
                    snprintf(part, sizeof part, " %u:%u=(%g,%g,%g,%g)",
                             unsigned(usage), unsigned(index),
                             double(reflex_d3d9::float16_component(data, 0)),
                             double(reflex_d3d9::float16_component(data, 1)),
                             double(reflex_d3d9::float16_component(data, 2)),
                             double(reflex_d3d9::float16_component(data, 3)));
                } else if (type == 4) {
                    const uint32_t argb = uint32_t(data[0]) | uint32_t(data[1]) << 8 |
                                          uint32_t(data[2]) << 16 | uint32_t(data[3]) << 24;
                    snprintf(part, sizeof part, " %u:%u=ARGB%08x",
                             unsigned(usage), unsigned(index), argb);
                }
                if (part[0]) {
                    const size_t available = sizeof line - used;
                    const int n = snprintf(line + used, available, "%s", part);
                    used += n > 0 ? std::min<size_t>(size_t(n), available - 1) : 0;
                }
            }
        }
        if (!used) {
            for (uint32_t o = 0; o + 4 <= stride && o < 40 && used < sizeof line; o += 4) {
                float f;
                const uint32_t bits = rd32(base + o);
                memcpy(&f, &bits, 4);
                const size_t available = sizeof line - used;
                const int n = snprintf(line + used, available, " raw=%g", double(f));
                used += n > 0 ? std::min<size_t>(size_t(n), available - 1) : 0;
            }
        }
        LOGW("d3d9:   vertex %u:%s", v, line);
    }
'''
    t = once(t, original, replacement, "DrawPrimitiveUP diagnostic loop")
    # All preconditions validated; commit changes together.
    (kit / "dx" / "reflex_d3d9_half.h").write_bytes(helper.read_bytes())
    raster.write_text(s)
    d3d.write_text(t)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=KIT)
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    args = parser.parse_args()
    patch_float16(args.kit, args.runtime)
    print("Installed D3D9 FLOAT16 input decode and diagnostic fix")


if __name__ == "__main__":
    main()
