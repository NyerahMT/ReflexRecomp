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


GET_RT_HARNESS_BEFORE = r"""
#include <cassert>
#include <cstdint>

static constexpr uint32_t D3DERR_INVALIDCALL = 0x8876086cu;
static constexpr uint32_t E_OUTOFMEMORY = 0x8007000eu;
static constexpr uint32_t D3D_OK9 = 0u;
static constexpr uint32_t K_D3D9SURFACE = 1u;
static constexpr uint32_t IF_D3DSURFACE9 = 1u;

struct ComObj {
    uint32_t id = 0u;
    uint32_t kind = 0u;
    uint32_t refs = 1u;
    uint32_t render_target = 0u;
};
struct X86 {
    ComObj *device = nullptr;
    uint32_t args[3] = {};
    uint32_t result = 0xffffffffu;
};
struct D9Pipeline {
    uint32_t color_target[4] = {};
};
static ComObj device{1u, 0u, 1u, 0u};
static ComObj surface{2u, K_D3D9SURFACE, 1u, 0u};
static D9Pipeline pipeline;
static uint32_t guest_output = 0xffffffffu;

uint32_t arg(X86 *c, unsigned idx) { return c->args[idx]; }
bool gm_fits(uint32_t out, uint32_t bytes) { return out == 256u && bytes == 4u; }
ComObj *this_device9(X86 *c) { return c->device; }
ComObj *com_get(uint32_t id) { return id == 2u ? &surface : nullptr; }
D9Pipeline &d9_pipeline(uint32_t) { return pipeline; }
ComObj *device_backbuffer(ComObj *dev) {
    dev->render_target = surface.id;
    return &surface;
}
uint32_t com_view(ComObj *o, uint32_t iface) {
    return o == &surface && iface == IF_D3DSURFACE9 ? 0x1002u : 0u;
}
void com_addref(ComObj *o) { ++o->refs; }
void com_out_ptr(uint32_t addr, uint32_t value) {
    assert(addr == 256u);
    guest_output = value;
}
void com_ret(X86 *c, uint32_t result) { c->result = result; }
void log_once(const char *, const char *) {}
"""

GET_RT_HARNESS_AFTER = r"""
int main() {
    X86 c{};
    c.device = &device;
    c.args[1] = 0u;
    c.args[2] = 256u;
    Dev_GetRenderTarget(&c);
    assert(c.result == D3D_OK9);
    assert(guest_output == 0x1002u);
    assert(surface.refs == 2u);
    assert(pipeline.color_target[0] == 2u);
    assert(device.render_target == 2u);

    guest_output = 0xffffffffu;
    c.args[1] = 1u;
    Dev_GetRenderTarget(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    assert(guest_output == 0u);
    assert(surface.refs == 2u);

    pipeline.color_target[1] = surface.id;
    Dev_GetRenderTarget(&c);
    assert(c.result == D3D_OK9);
    assert(guest_output == 0x1002u);
    assert(surface.refs == 3u);

    c.args[1] = 4u;
    Dev_GetRenderTarget(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    assert(surface.refs == 3u);

    c.args[1] = 0u;
    c.args[2] = 257u;
    Dev_GetRenderTarget(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    assert(surface.refs == 3u);

    c.args[2] = 256u;
    c.device = nullptr;
    Dev_GetRenderTarget(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    assert(surface.refs == 3u);
}
"""


def test_get_render_target_native_surface_contract(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    source = tmp_path / "get_render_target.cpp"
    executable = tmp_path / "get_render_target"
    source.write_text(GET_RT_HARNESS_BEFORE + mod.GET_RENDER_TARGET_IMPL + GET_RT_HARNESS_AFTER)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(source), "-o", str(executable)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
