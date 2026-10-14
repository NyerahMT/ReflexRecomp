"""Regression coverage for the Reflex D3D9 swap-chain kit patch."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/patch_reflex_d3d9_swapchain.py"
spec = importlib.util.spec_from_file_location("swap_patch", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


COM_FIXTURE = """enum ComIface {
    IF_D3D9,
    IF_D3DDEVICE9,
    IF_D3DXEFFECTPOOL,
};
enum ComKind {
    K_D3D9,           // the IDirect3D9 factory object
    K_D3D9DEVICE,     // one device created from it
    K_D3DXEFFECTPOOL, // the D3DX effect pool a game shares between effects
};
struct ComObj {
    uint32_t d9_vertex_shader = 0;
    uint32_t d9_pixel_shader = 0;
    bool in_scene = false;
};
"""

D3D_FIXTURE = """static const uint8_t IID_IDirect3DDevice9_[16] =
    IID_BYTES(0xd0223b96, 0xbf7a, 0x43fd, 0x92, 0xbd, 0xa4, 0x3b, 0x0d, 0x82, 0xb9, 0xeb);

D9_STUB(CreateAdditionalSwapChain, 3)
D9_STUB(GetSwapChain, 3)
D9_STUB(GetRenderTarget, 3)

static const ComMethod g_d3d9[] = {
};

void d3d9_register() {
    com_define(IF_D3DDEVICE9, "d3d9.dll", "IDirect3DDevice9", g_device9, std::size(g_device9));
    com_bind(IF_D3D9, K_D3D9);
    com_bind(IF_D3DDEVICE9, K_D3D9DEVICE);
    com_register_iid(IF_D3D9, IID_IDirect3D9_);
    com_register_iid(IF_D3DDEVICE9, IID_IDirect3DDevice9_);
    com_set_destructor(K_D3D9QUERY, query_destroy);
    imports_register(g_d3d9_exports, std::size(g_d3d9_exports));
}
"""


def test_swapchain_patch_defines_real_com_interface(tmp_path):
    com = tmp_path / "com.h"
    d3d = tmp_path / "d3d9.cpp"
    com.write_text(COM_FIXTURE)
    d3d.write_text(D3D_FIXTURE)

    mod.patch_com_header(com)
    mod.patch_d3d9(d3d)
    mod.patch_render_target(d3d)

    ch = com.read_text()
    dx = d3d.read_text()
    assert "IF_D3DSWAPCHAIN9" in ch
    assert "K_D3D9SWAPCHAIN" in ch
    assert "d9_primary_swapchain" in ch

    assert "D9_STUB(GetSwapChain, 3)" not in dx
    assert "D9_STUB(CreateAdditionalSwapChain, 3)" not in dx
    assert "D9_STUB(GetRenderTarget, 3)" not in dx
    assert "void Dev_GetRenderTarget(X86 *c)" in dx
    assert "const uint32_t index = arg(c, 1);" in dx
    assert "const uint32_t out = arg(c, 2);" in dx
    assert "com_get(pl.color_target[index])" in dx
    assert "surface = device_backbuffer(dev);" in dx
    assert "com_addref(surface);" in dx
    assert "com_out_ptr(out, view);" in dx
    assert "com_ret(c, D3D_OK9);" in dx
    assert "void Dev_GetSwapChain(X86 *c)" in dx
    assert "void Dev_CreateAdditionalSwapChain(X86 *c)" in dx
    assert "static const ComMethod g_swapchain9[]" in dx
    assert '{"QueryInterface", 3, com_QueryInterface}' in dx
    assert '{"AddRef", 1, com_AddRef}' in dx
    assert '{"Release", 1, com_Release}' in dx
    assert '{"Present", 6, Swap_Present}' in dx
    assert dx.index('{"Release", 1, com_Release}') < dx.index('{"Present", 6, Swap_Present}')
    assert "com_addref(dev); // the swap chain keeps its parent device alive" in dx
    assert "com_release(dev);" in dx
    assert 'com_define(IF_D3DSWAPCHAIN9, "d3d9.dll", "IDirect3DSwapChain9"' in dx
    assert "com_bind(IF_D3DSWAPCHAIN9, K_D3D9SWAPCHAIN)" in dx
    assert "com_register_iid(IF_D3DSWAPCHAIN9, IID_IDirect3DSwapChain9_)" in dx
    assert "com_set_destructor(K_D3D9SWAPCHAIN, swapchain_destroy)" in dx

    # A second application must be a no-op rather than duplicating enum
    # entries, methods or registrations.
    first_com, first_d3d = ch, dx
    mod.patch_com_header(com)
    mod.patch_d3d9(d3d)
    mod.patch_render_target(d3d)
    assert com.read_text() == first_com
    assert d3d.read_text() == first_d3d
    assert dx.count("IF_D3DSWAPCHAIN9") >= 1
    assert dx.count("static const ComMethod g_swapchain9[]") == 1


def test_render_target_only_replaces_the_pinned_stub(tmp_path):
    d3d = tmp_path / "d3d9.cpp"
    d3d.write_text("D9_STUB(GetRenderTarget, 3)\nD9_STUB(GetTexture, 3)\n")
    mod.patch_render_target(d3d)
    changed = d3d.read_text()
    assert "D9_STUB(GetRenderTarget, 3)" not in changed
    assert "D9_STUB(GetTexture, 3)" in changed
    assert changed.count("void Dev_GetRenderTarget(X86 *c)") == 1
    assert "index >= 4u" in changed
    assert "if (!dev || index >= 4u || !out || !gm_fits(out, 4))" in changed
    assert "com_out_ptr(out, 0);" in changed
    assert changed.index("com_addref(surface);") < changed.index("com_out_ptr(out, view);")
    assert "return;" in changed
    mod.patch_render_target(d3d)
    assert d3d.read_text() == changed


def test_render_target_patch_rejects_unknown_pinned_kit_revision(tmp_path):
    d3d = tmp_path / "d3d9.cpp"
    d3d.write_text("D9_STUB(GetTexture, 3)\n")
    with pytest.raises(SystemExit, match="expected exactly one patch anchor"):
        mod.patch_render_target(d3d)
    assert d3d.read_text() == "D9_STUB(GetTexture, 3)\n"
