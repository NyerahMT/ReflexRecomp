#!/usr/bin/env python3
"""Add the D3D9 swap-chain COM interface Reflex reaches during startup.

The pinned recomp-kit currently stubs IDirect3DDevice9::GetSwapChain and
returns D3D_OK without writing ppSwapChain. Reflex immediately calls
IDirect3DSwapChain9::Present followed by Release, so the untouched out pointer
becomes a stale guest pointer and slot 2 is eventually called through null.

Patch the pinned kit with a real swap-chain view whose COM lifetime is tied to
its owning device. This is generic D3D9 interface behavior, not a Reflex call-
site bypass.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor for {marker!r}")
    path.write_text(text.replace(old, new, 1))


def patch_com_header(com: Path) -> None:
    replace_once(
        com,
        "    IF_D3D9,\n"
        "    IF_D3DDEVICE9,\n"
        "    IF_D3DXEFFECTPOOL,\n",
        "    IF_D3D9,\n"
        "    IF_D3DDEVICE9,\n"
        "    IF_D3DSWAPCHAIN9,\n"
        "    IF_D3DXEFFECTPOOL,\n",
        "IF_D3DSWAPCHAIN9",
    )
    replace_once(
        com,
        "    K_D3D9,           // the IDirect3D9 factory object\n"
        "    K_D3D9DEVICE,     // one device created from it\n"
        "    K_D3DXEFFECTPOOL, // the D3DX effect pool a game shares between effects\n",
        "    K_D3D9,           // the IDirect3D9 factory object\n"
        "    K_D3D9DEVICE,     // one device created from it\n"
        "    K_D3D9SWAPCHAIN,  // a swap-chain view owned by a D3D9 device\n"
        "    K_D3DXEFFECTPOOL, // the D3DX effect pool a game shares between effects\n",
        "K_D3D9SWAPCHAIN",
    )
    replace_once(
        com,
        "    uint32_t d9_vertex_shader = 0;\n"
        "    uint32_t d9_pixel_shader = 0;\n"
        "    bool in_scene = false;\n",
        "    uint32_t d9_vertex_shader = 0;\n"
        "    uint32_t d9_pixel_shader = 0;\n"
        "    uint32_t d9_primary_swapchain = 0; // weak id; swap chain owns a device ref\n"
        "    bool in_scene = false;\n",
        "d9_primary_swapchain",
    )


def patch_d3d9(d3d: Path) -> None:
    replace_once(
        d3d,
        "static const uint8_t IID_IDirect3DDevice9_[16] =\n"
        "    IID_BYTES(0xd0223b96, 0xbf7a, 0x43fd, 0x92, 0xbd, 0xa4, 0x3b, 0x0d, 0x82, 0xb9, 0xeb);\n",
        "static const uint8_t IID_IDirect3DDevice9_[16] =\n"
        "    IID_BYTES(0xd0223b96, 0xbf7a, 0x43fd, 0x92, 0xbd, 0xa4, 0x3b, 0x0d, 0x82, 0xb9, 0xeb);\n"
        "static const uint8_t IID_IDirect3DSwapChain9_[16] =\n"
        "    IID_BYTES(0x794950f2, 0xadfc, 0x458a, 0x90, 0x5e, 0x10, 0xa1, 0x0b, 0x0b, 0x50, 0x3b);\n",
        "IID_IDirect3DSwapChain9_",
    )

    for line in (
        "D9_STUB(CreateAdditionalSwapChain, 3)\n",
        "D9_STUB(GetSwapChain, 3)\n",
    ):
        text = d3d.read_text()
        if line in text:
            d3d.write_text(text.replace(line, "", 1))

    marker = "static const ComMethod g_swapchain9[]"
    text = d3d.read_text()
    if marker not in text:
        anchor = "static const ComMethod g_d3d9[] = {\n"
        if text.count(anchor) != 1:
            raise SystemExit(f"{d3d}: expected one D3D9 method-table anchor")
        implementation = r'''
static ComObj *swapchain_device(ComObj *swap) {
    return swap && swap->kind == K_D3D9SWAPCHAIN ? com_get(swap->dev_d3d) : nullptr;
}

static void swapchain_destroy(ComObj *swap) {
    ComObj *dev = swapchain_device(swap);
    if (!dev)
        return;
    if (dev->d9_primary_swapchain == swap->id)
        dev->d9_primary_swapchain = 0;
    com_release(dev);
}

static ComObj *new_swapchain(ComObj *dev) {
    if (!dev || dev->kind != K_D3D9DEVICE)
        return nullptr;
    ComObj *swap = com_new(K_D3D9SWAPCHAIN);
    if (!swap)
        return nullptr;
    swap->dev_d3d = dev->id;
    com_addref(dev); // the swap chain keeps its parent device alive
    return swap;
}

static bool swapchain_out(ComObj *swap, uint32_t out, bool add_ref) {
    if (!swap || !out || !gm_fits(out, 4))
        return false;
    uint32_t view = com_view(swap, IF_D3DSWAPCHAIN9);
    if (!view)
        return false;
    if (add_ref)
        com_addref(swap);
    com_out_ptr(out, view);
    return true;
}

void Dev_CreateAdditionalSwapChain(X86 *c) {
    ComObj *dev = this_device9(c);
    uint32_t out = arg(c, 2);
    if (!dev || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    com_out_ptr(out, 0);
    ComObj *swap = new_swapchain(dev);
    if (!swap || !swapchain_out(swap, out, false)) {
        if (swap)
            com_release(swap);
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    com_ret(c, D3D_OK9);
}

void Dev_GetSwapChain(X86 *c) {
    ComObj *dev = this_device9(c);
    uint32_t index = arg(c, 1), out = arg(c, 2);
    if (!dev || index != 0 || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    com_out_ptr(out, 0);

    ComObj *swap = com_get(dev->d9_primary_swapchain);
    const bool fresh = !swap;
    if (!swap) {
        swap = new_swapchain(dev);
        if (swap)
            dev->d9_primary_swapchain = swap->id;
    }
    if (!swap || !swapchain_out(swap, out, !fresh)) {
        if (fresh && swap)
            com_release(swap);
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    com_ret(c, D3D_OK9);
}

void Swap_Present(X86 *c) {
    ComObj *swap = com_this_arg(c, IF_D3DSWAPCHAIN9);
    ComObj *dev = swapchain_device(swap);
    uint32_t device_view = dev ? com_view(dev, IF_D3DDEVICE9) : 0;
    const uint32_t this_slot = c->r[R_ESP] + 4u;
    if (!device_view || !gm_fits(this_slot, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }

    // Device::Present has the same first four explicit arguments as
    // SwapChain::Present; the swap-chain-only Flags dword remains ignored.
    const uint32_t old_this = rd32(this_slot);
    wr32(this_slot, device_view);
    Dev_Present(c);
    wr32(this_slot, old_this);
}

void Swap_GetFrontBufferData(X86 *c) {
    // The CPU/GPU backends do not expose a front-buffer readback here yet.
    // Returning INVALIDCALL is safer than claiming to have filled the surface.
    com_ret(c, D3DERR_INVALIDCALL);
}

void Swap_GetBackBuffer(X86 *c) {
    ComObj *swap = com_this_arg(c, IF_D3DSWAPCHAIN9);
    ComObj *dev = swapchain_device(swap);
    const uint32_t back = arg(c, 1), out = arg(c, 3);
    if (!dev || back != 0 || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    com_out_ptr(out, 0);
    ComObj *surface = device_backbuffer(dev);
    uint32_t view = surface ? com_view(surface, IF_D3DSURFACE9) : 0;
    if (!view) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    com_addref(surface);
    com_out_ptr(out, view);
    com_ret(c, D3D_OK9);
}

void Swap_GetRasterStatus(X86 *c) {
    uint32_t out = arg(c, 1);
    if (!out || !gm_fits(out, 8)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    wr32(out + 0, 0); // InVBlank
    wr32(out + 4, 0); // ScanLine
    com_ret(c, D3D_OK9);
}

void Swap_GetDisplayMode(X86 *c) {
    uint32_t out = arg(c, 1);
    if (!out || !gm_fits(out, 16)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    put_display_mode(out);
    com_ret(c, D3D_OK9);
}

void Swap_GetDevice(X86 *c) {
    ComObj *swap = com_this_arg(c, IF_D3DSWAPCHAIN9);
    ComObj *dev = swapchain_device(swap);
    uint32_t out = arg(c, 1);
    if (!dev || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    uint32_t view = com_view(dev, IF_D3DDEVICE9);
    if (!view) {
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    com_addref(dev);
    com_out_ptr(out, view);
    com_ret(c, D3D_OK9);
}

void Swap_GetPresentParameters(X86 *c) {
    ComObj *swap = com_this_arg(c, IF_D3DSWAPCHAIN9);
    ComObj *dev = swapchain_device(swap);
    uint32_t out = arg(c, 1);
    if (!dev || !out || !gm_fits(out, 56)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    memset(gm_ptr(out), 0, 56);
    wr32(out + 0, dev->width);
    wr32(out + 4, dev->height);
    wr32(out + 8, 22);  // D3DFMT_X8R8G8B8
    wr32(out + 12, 1);  // BackBufferCount
    wr32(out + 16, dev->samples);
    wr32(out + 24, 1);  // D3DSWAPEFFECT_DISCARD
    wr32(out + 28, dev->hwnd);
    wr32(out + 32, 1);  // Windowed
    wr32(out + 52, 1);  // D3DPRESENT_INTERVAL_ONE
    com_ret(c, D3D_OK9);
}

static const ComMethod g_swapchain9[] = {
    {"QueryInterface", 3, com_QueryInterface},
    {"AddRef", 1, com_AddRef},
    {"Release", 1, com_Release},
    {"Present", 6, Swap_Present},
    {"GetFrontBufferData", 2, Swap_GetFrontBufferData},
    {"GetBackBuffer", 4, Swap_GetBackBuffer},
    {"GetRasterStatus", 2, Swap_GetRasterStatus},
    {"GetDisplayMode", 2, Swap_GetDisplayMode},
    {"GetDevice", 2, Swap_GetDevice},
    {"GetPresentParameters", 2, Swap_GetPresentParameters},
};

'''
        d3d.write_text(text.replace(anchor, implementation + anchor, 1))

    replace_once(
        d3d,
        '    com_define(IF_D3DDEVICE9, "d3d9.dll", "IDirect3DDevice9", g_device9, std::size(g_device9));\n'
        '    com_bind(IF_D3D9, K_D3D9);\n',
        '    com_define(IF_D3DDEVICE9, "d3d9.dll", "IDirect3DDevice9", g_device9, std::size(g_device9));\n'
        '    com_define(IF_D3DSWAPCHAIN9, "d3d9.dll", "IDirect3DSwapChain9", g_swapchain9,\n'
        '               std::size(g_swapchain9));\n'
        '    com_bind(IF_D3D9, K_D3D9);\n',
        "com_define(IF_D3DSWAPCHAIN9",
    )
    replace_once(
        d3d,
        "    com_bind(IF_D3D9, K_D3D9);\n"
        "    com_bind(IF_D3DDEVICE9, K_D3D9DEVICE);\n"
        "    com_register_iid(IF_D3D9, IID_IDirect3D9_);\n"
        "    com_register_iid(IF_D3DDEVICE9, IID_IDirect3DDevice9_);\n",
        "    com_bind(IF_D3D9, K_D3D9);\n"
        "    com_bind(IF_D3DDEVICE9, K_D3D9DEVICE);\n"
        "    com_bind(IF_D3DSWAPCHAIN9, K_D3D9SWAPCHAIN);\n"
        "    com_register_iid(IF_D3D9, IID_IDirect3D9_);\n"
        "    com_register_iid(IF_D3DDEVICE9, IID_IDirect3DDevice9_);\n"
        "    com_register_iid(IF_D3DSWAPCHAIN9, IID_IDirect3DSwapChain9_);\n",
        "com_bind(IF_D3DSWAPCHAIN9",
    )
    replace_once(
        d3d,
        "    com_set_destructor(K_D3D9QUERY, query_destroy);\n"
        "    imports_register(g_d3d9_exports, std::size(g_d3d9_exports));\n",
        "    com_set_destructor(K_D3D9QUERY, query_destroy);\n"
        "    com_set_destructor(K_D3D9SWAPCHAIN, swapchain_destroy);\n"
        "    imports_register(g_d3d9_exports, std::size(g_d3d9_exports));\n",
        "com_set_destructor(K_D3D9SWAPCHAIN",
    )



GET_RENDER_TARGET_IMPL = r'''// reflex-d3d9-getrender-target-v1
// The pinned D3D9 stub returned D3D_OK without writing ppRenderTarget.
// Reflex later dereferenced that null pointer at guest return 0079a627.
// Read back the actual bound target, with an owning COM reference.
void Dev_GetRenderTarget(X86 *c) {
    ComObj *dev = this_device9(c);
    const uint32_t index = arg(c, 1);
    const uint32_t out = arg(c, 2);
    if (!dev || index >= 4u || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    com_out_ptr(out, 0);
    D9Pipeline &pl = d9_pipeline(dev->id);
    ComObj *surface = com_get(pl.color_target[index]);

    // GetRenderTarget(0) must still expose the default back buffer, even
    // before the game has called SetRenderTarget. Do not invent a target for
    // additional slots; only index 0 is guaranteed to be bound by D3D9.
    if (index == 0u && (!surface || surface->kind != K_D3D9SURFACE)) {
        surface = com_get(dev->render_target);
        if (!surface || surface->kind != K_D3D9SURFACE)
            surface = device_backbuffer(dev);
        if (surface)
            pl.color_target[0] = surface->id;
    }
    if (!surface || surface->kind != K_D3D9SURFACE) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    const uint32_t view = com_view(surface, IF_D3DSURFACE9);
    if (!view) {
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    com_addref(surface);  // COM GetRenderTarget returns an owned interface ref.
    com_out_ptr(out, view);
    log_once("d3d9.getrt.implemented",
             "d3d9: GetRenderTarget returned a reference-counted surface");
    com_ret(c, D3D_OK9);
}
'''


def patch_render_target(d3d: Path) -> None:
    replace_once(
        d3d,
        "D9_STUB(GetRenderTarget, 3)\n",
        GET_RENDER_TARGET_IMPL + "\n",
        "reflex-d3d9-getrender-target-v1",
    )


def main() -> None:
    com = KIT / "dx" / "com.h"
    d3d = KIT / "dx" / "d3d9.cpp"
    if not com.is_file() or not d3d.is_file():
        raise SystemExit("kit/ is missing the pinned D3D9 runtime")
    patch_com_header(com)
    patch_d3d9(d3d)
    patch_render_target(d3d)
    print("Applied Reflex D3D9 swap-chain and render-target COM patch")


if __name__ == "__main__":
    main()
