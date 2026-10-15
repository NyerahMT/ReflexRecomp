#!/usr/bin/env python3
"""Implement SM3 pixel shader R_MISC inputs in pinned D3D9 shader translator.

D3DSHADER_MISCTYPE_POSITION (vPos, 0) supplies pixel-center screen xy;
D3DSHADER_MISCTYPE_FACE (vFace, 1) supplies +1 front / -1 back.
Previously the GPU shader generator rejected both as register type 17.
Generated source uses the host's actual fragment builtins (no fake colors).
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("dx/d3d9_shadergen.cpp")
MARKER = "reflex-sm3-misc-vpos-vface-v1"

SOURCE_OLD = r'''        case R_LOOP:
            return F4 + (wgsl() ? "(f32(aL))" : "(float(aL))");
        default:
'''
SOURCE_NEW = r'''        case R_LOOP:
            return F4 + (wgsl() ? "(f32(aL))" : "(float(aL))");
        // reflex-sm3-misc-vpos-vface-v1: D3DSHADER_MISCTYPE_POSITION (0)
        // and D3DSHADER_MISCTYPE_FACE (1), valid only in ps_3_0.
        case R_MISC:
            if (!p.pixel || p.major < 3 || s.index > 1) {
                fail("unsupported misc register " + std::to_string(s.index));
                return F4 + "(0.0)";
            }
            if (s.index == 0) {
                // Pixel-center window-space xy. D3D9 does not define zw.
                return glsl() ? "vec4(gl_FragCoord.xy, 0.0, 0.0)"
                              : F4 + "(vin.pos.xy, 0.0, 0.0)";
            }
            // vFace.x = +1 for front and -1 for back. Scalar is replicated
            // to four components for normal source swizzle/modifier paths.
            if (wgsl())
                return "vec4f(select(-1.0, 1.0, face))";
            return F4 + "(" + (glsl() ? "gl_FrontFacing" : "face") +
                   " ? 1.0 : -1.0)";
        default:
'''
MSL_OLD = r'''    s += ") {\n"
         "    float4 r[32] = {};\n"
         "    float4 tc[8] = { vin.t0, vin.t1, vin.t2, vin.t3, vin.t4, vin.t5, vin.t6, vin.t7 };\n"
'''
MSL_NEW = r'''    // D3D9 vFace derives from the hardware front-facing primitive,
    // not a synthesized constant or a shader uniform.
    s += ",\n                         bool face [[front_facing]]";
    s += ") {\n"
         "    float4 r[32] = {};\n"
         "    float4 tc[8] = { vin.t0, vin.t1, vin.t2, vin.t3, vin.t4, vin.t5, vin.t6, vin.t7 };\n"
'''
WGSL_OLD = r'''    s += "};\n"
         "@fragment fn ps_main(vin: V2F) -> FOut {\n"
'''
WGSL_NEW = r'''    s += "};\n"
         "@fragment fn ps_main(vin: V2F, @builtin(front_facing) face: bool) -> FOut {\n"
'''

def only(text: str, old: str, new: str, name: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one pinned {name} anchor, found {count}")
    return text.replace(old, new, 1)

def patch_misc_inputs(kit: Path) -> None:
    path = kit / TARGET
    if not path.is_file():
        raise RuntimeError("Missing pinned shader generator")
    source = path.read_text()
    if MARKER in source:
        if (source.count(MARKER) != 1 or
                source.count(SOURCE_NEW) != 1 or
                source.count(MSL_NEW) != 1 or
                source.count(WGSL_NEW) != 1):
            raise RuntimeError("Partially installed SM3 misc input shader patch")
        return
    modified = only(source, SOURCE_OLD, SOURCE_NEW, "source register decoder")
    modified = only(modified, MSL_OLD, MSL_NEW, "Metal fragment signature")
    modified = only(modified, WGSL_OLD, WGSL_NEW, "WGSL fragment signature")
    path.write_text(modified)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    args = parser.parse_args()
    patch_misc_inputs(args.kit)
    print("Installed real Shader Model 3 pixel position and front-facing inputs")

if __name__ == "__main__":
    main()
