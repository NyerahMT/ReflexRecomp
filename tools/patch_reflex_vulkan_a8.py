#!/usr/bin/env python3
"""Correct Vulkan sampler swizzle for D3DFMT_A8 in pinned recomp-kit.

D3D9 A8 is an alpha-only texture whose sampled RGB defaults to white.
The CPU raster's decode of A8 already does this (RGBA=255,255,255,alpha);
the Vulkan backend formerly set RGB to ZERO, so UI glyphs could not
modulate a white textured quad correctly. This patch never changes raw
texture bytes or guest Direct3D states.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
MARKER = "reflex-vulkan-a8-rgb-one-v1"
TARGET = Path("host/gpu/vulkan/d3d9_vulkan.cpp")
BEFORE = """        if (alpha_only)
            vci.components = {VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_ZERO,
                              VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_R};
"""
AFTER = """        // reflex-vulkan-a8-rgb-one-v1: D3DFMT_A8 reads as (1,1,1,A),
        // matching the kit's CPU decoder, not as (0,0,0,A).
        if (alpha_only)
            vci.components = {VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_ONE,
                              VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_R};
"""


def patch_vulkan_a8(kit: Path) -> None:
    path = kit / TARGET
    if not path.is_file():
        raise RuntimeError("Missing pinned Vulkan D3D9 backend")
    text = path.read_text()
    if MARKER in text:
        if text.count(MARKER) != 1 or text.count(AFTER) != 1 or BEFORE in text:
            raise RuntimeError("Partial Vulkan A8 swizzle patch")
        return
    if text.count(BEFORE) != 1:
        raise RuntimeError("Pinned Vulkan A8 sample swizzle changed")
    # Only one verified shader view swizzle is replaced, not all R8 views.
    path.write_text(text.replace(BEFORE, AFTER, 1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    args = parser.parse_args()
    patch_vulkan_a8(args.kit)
    print("Corrected D3D9 Vulkan A8 sampler to white RGB + original alpha")


if __name__ == "__main__":
    main()
