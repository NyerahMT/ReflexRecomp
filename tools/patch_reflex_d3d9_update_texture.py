#!/usr/bin/env python3
"""Implement D3D9 UpdateTexture for exact-layout 2D textures in the pinned kit.

The original Reflex startup calls UpdateTexture immediately before binding its
first post-loading shader. The pinned kit previously returned D3D_OK without
copying any mip bytes. Implement conservative complete-chain copies; reject
unsupported cube/partial-level shapes rather than faking success.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
MARKER = "reflex-d3d9-updatetexture-v1"
STUB = "D9_STUB(UpdateTexture, 3)\n"
ANCHOR = "void Dev_StretchRect(X86 *c) {"

IMPLEMENTATION = r"""
// reflex-d3d9-updatetexture-v1: full mip-chain copy from a system-memory
// texture into a destination texture; GPU mirror is dirtied per copied level.
// Do not return success for unsupported layouts or silently lose texels.
// (this, pSourceTexture, pDestinationTexture).
void Dev_UpdateTexture(X86 *c) {
    ComObj *dev = this_device9(c);
    ComObj *src = com_this(arg(c, 1));
    ComObj *dst = com_this(arg(c, 2));
    if (!dev || !src || !dst || src == dst ||
        src->kind != K_D3D9TEXTURE || dst->kind != K_D3D9TEXTURE ||
        src->caps || dst->caps ||
        src->dev_d3d != dev->id || dst->dev_d3d != dev->id ||
        src->rmask != dst->rmask ||
        src->width != dst->width || src->height != dst->height ||
        src->surfaces.empty() || src->surfaces.size() != dst->surfaces.size()) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    // Preflight every level before writing any destination bytes. Mip-chain
    // mismatches must not leave an observable partially updated texture.
    std::vector<ComObj *> from, to;
    for (size_t i = 0; i < src->surfaces.size(); ++i) {
        ComObj *a = com_get(src->surfaces[i]);
        ComObj *b = com_get(dst->surfaces[i]);
        if (!a || !b || a == b || a->kind != K_D3D9SURFACE ||
            b->kind != K_D3D9SURFACE || a->front_obj != src->id ||
            b->front_obj != dst->id ||
            a->rmask != b->rmask || a->width != b->width ||
            a->height != b->height || a->pitch != b->pitch ||
            a->blob.empty() || a->blob.size() != b->blob.size() ||
            a->lock_count || b->lock_count) {
            com_ret(c, D3DERR_INVALIDCALL);
            return;
        }
        from.push_back(a);
        to.push_back(b);
    }
    for (size_t i = 0; i < from.size(); ++i) {
        ComObj *a = from[i], *b = to[i];
        if (gpu_on())
            gpu_before_lock(a); // read back an updated 32-bit source if needed
        std::memcpy(b->blob.data(), a->blob.data(), a->blob.size());
        d9_raster_invalidate(b->id);
        gpu_after_unlock(b, 0u, static_cast<uint32_t>(b->blob.size()));
    }
    static std::atomic<unsigned long long> updates{0};
    const unsigned long long n = updates.fetch_add(1) + 1;
    if (n <= 8u || ((n & (n - 1u)) == 0u))
        LOGW("[reflex-d3d9] UpdateTexture n=%llu src=%u dst=%u levels=%zu "
             "format=%u size=%ux%u",
             n, src->id, dst->id, from.size(), src->rmask,
             src->width, src->height);
    com_ret(c, D3D_OK9);
}
""".lstrip()


def patch_update_texture(kit: Path) -> None:
    target = kit / "dx" / "d3d9.cpp"
    if not target.is_file():
        raise RuntimeError("Missing pinned D3D9 kit source")
    text = target.read_text()
    if MARKER in text:
        if text.count(MARKER) != 1 or STUB in text or                 text.count("void Dev_UpdateTexture(X86 *c)") != 1:
            raise RuntimeError("Partial UpdateTexture patch installation")
        return
    if text.count(STUB) != 1 or text.count(ANCHOR) != 1:
        raise RuntimeError("Pinned UpdateTexture stub or insert anchor changed")
    # Fail closed: do not mutate source until every anchor is validated.
    modified = text.replace(STUB, "", 1)
    modified = modified.replace(ANCHOR, IMPLEMENTATION + "\n" + ANCHOR, 1)
    target.write_text(modified)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    args = parser.parse_args()
    patch_update_texture(args.kit)
    print("Installed exact-layout D3D9 UpdateTexture mip-chain copy")


if __name__ == "__main__":
    main()
