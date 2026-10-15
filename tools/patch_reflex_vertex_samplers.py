#!/usr/bin/env python3
"""Make genuine D3D9 vertex-texture fetches legal on Vulkan and Metal.

The pinned shadergen emits tx0.sample/texture(tx0) in vertex programs but
declares texture/sampler handles exclusively in fragment entry points.
Vulkan also hides the shared descriptors from vertex stages and binds only
pixel-shader-used samplers. Reflex's original Vulkan log reports undeclared
'tx0' in a vertex shader. Patch all sides, never replace game shader code.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "reflex-vertex-sampler-bridge-v1"

SHADERGEN = Path("dx/d3d9_shadergen.cpp")
VULKAN = Path("host/gpu/vulkan/d3d9_vulkan.cpp")
METAL = Path("host/gpu/metal/d3d9_metal.mm")

MSL_OLD = r'''    s += "vertex D9V2F vs_main(D9VIn vin [[stage_in]], constant float4 *c [[buffer(16)]],\n"
         "                     constant D9VSParams &P [[buffer(17)]]) {\n"
         "    float4 r[32] = {};\n"
'''
MSL_NEW = r'''    // reflex-vertex-sampler-bridge-v1: shader-model-3 vertex texture fetch.
    s += "vertex D9V2F vs_main(D9VIn vin [[stage_in]], constant float4 *c [[buffer(16)]],\n"
         "                     constant D9VSParams &P [[buffer(17)]]";
    for (uint32_t st : g.stages) {
        const char *kind = g.kind_of(st) == S_CUBE ? "texturecube<float>" : "texture2d<float>";
        const std::string n = std::to_string(st);
        s += ",\n                     " + std::string(kind) + " tx" + n +
             " [[texture(" + n + ")]], sampler sm" + n + " [[sampler(" + n + ")]]";
    }
    s += ") {\n"
         "    float4 r[32] = {};\n"
'''

GLSL_OLD = r'''    s += kVaryingsOut;
    s += "void main() {\n"
'''
GLSL_NEW = r'''    // Vertex shaders may use texld / texldl too: declare the same
    // shared bindings as fragment samplers, with the vertex shader's type.
    for (uint32_t st : g.stages) {
        const char *kind = g.kind_of(st) == d9sh::S_CUBE ? "samplerCube" : "sampler2D";
        s += "layout(set = 0, binding = " + std::to_string(kSamplerBinding + st) +
             ") uniform " + kind + " tx" + std::to_string(st) + ";\n";
    }
    s += kVaryingsOut;
    s += "void main() {\n"
'''

VK_LAYOUT_OLD = r'''                b[i].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
                b[i].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
'''
VK_LAYOUT_NEW = r'''                b[i].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
                b[i].stageFlags = VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT;
'''
VK_USED_OLD = r'''        uint32_t used = (uint32_t)pp.sampler_mask;
        SetKey sk{};
'''
VK_USED_NEW = r'''        // A vertex texture fetch must bind its texture even when PS never
        // samples it (shared slots 4..19 in the Vulkan descriptor layout).
        uint32_t used = (uint32_t)pp.sampler_mask |
                        d9msl::pixel_sampler_mask(vp);
        SetKey sk{};
'''
METAL_USED_OLD = r'''        uint32_t used = (uint32_t)pp.sampler_mask;
        for (uint32_t s = 0; s < 16; ++s) {
'''
METAL_USED_NEW = r'''        const uint32_t vertex_used = d9msl::pixel_sampler_mask(vp);
        uint32_t used = (uint32_t)pp.sampler_mask | vertex_used;
        for (uint32_t s = 0; s < 16; ++s) {
'''
METAL_BIND_OLD = r'''            if (smp != es_.sampler[s]) {
                [enc_ setFragmentSamplerState:smp atIndex:s];
                es_.sampler[s] = smp;
            }
'''
METAL_BIND_NEW = r'''            if (smp != es_.sampler[s]) {
                [enc_ setFragmentSamplerState:smp atIndex:s];
                es_.sampler[s] = smp;
            }
            if (vertex_used >> s & 1u) {
                [enc_ setVertexTexture:use atIndex:s];
                [enc_ setVertexSamplerState:smp atIndex:s];
            }
'''

def only(src: str, old: str, new: str, name: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one pinned {name} anchor, got {count}")
    return src.replace(old, new, 1)

def patch_vertex_samplers(kit: Path) -> None:
    paths = [kit / SHADERGEN, kit / VULKAN, kit / METAL]
    if not all(path.is_file() for path in paths):
        raise RuntimeError("Missing pinned shader generator or GPU backend")
    shadergen, vulkan, metal = (p.read_text() for p in paths)
    if MARKER in shadergen:
        if (shadergen.count(MARKER) != 1 or
                "VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT" not in vulkan or
                "d9msl::pixel_sampler_mask(vp)" not in vulkan or
                "[enc_ setVertexTexture:use atIndex:s]" not in metal or
                MSL_NEW not in shadergen or GLSL_NEW not in shadergen):
            raise RuntimeError("Partial D3D9 vertex sampler bridge installation")
        return
    # Validate every pinned anchor before modifying any of three files.
    shadergen = only(shadergen, MSL_OLD, MSL_NEW, "MSL vertex entry")
    shadergen = only(shadergen, GLSL_OLD, GLSL_NEW, "GLSL vertex entry")
    vulkan = only(vulkan, VK_LAYOUT_OLD, VK_LAYOUT_NEW, "Vulkan sampler stage flags")
    vulkan = only(vulkan, VK_USED_OLD, VK_USED_NEW, "Vulkan vertex binding mask")
    metal = only(metal, METAL_USED_OLD, METAL_USED_NEW, "Metal vertex binding mask")
    metal = only(metal, METAL_BIND_OLD, METAL_BIND_NEW, "Metal vertex texture bind")
    for path, value in zip(paths, (shadergen, vulkan, metal)):
        path.write_text(value)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    args = parser.parse_args()
    patch_vertex_samplers(args.kit)
    print("Installed D3D9 vertex texture samplers for Vulkan and Metal")

if __name__ == "__main__":
    main()
