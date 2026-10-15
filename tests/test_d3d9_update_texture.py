"""D3D9 UpdateTexture: strict patch anchors and native complete-chain copy ABI."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "updatetex", ROOT / "tools" / "patch_reflex_d3d9_update_texture.py"
)
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


def pinned_fixture(tmp_path):
    kit = tmp_path / "kit"
    target = kit / "dx" / "d3d9.cpp"
    target.parent.mkdir(parents=True)
    target.write_text(
        "#include \"com.h\"\n"
        "D9_STUB(UpdateTexture, 3)\n"
        "void Dev_StretchRect(X86 *c) { (void)c; }\n"
    )
    return kit, target


def test_patch_is_idempotent_and_fails_closed(tmp_path):
    kit, path = pinned_fixture(tmp_path)
    PATCH.patch_update_texture(kit)
    patched = path.read_text()
    assert patched.count(PATCH.MARKER) == 1
    assert "D9_STUB(UpdateTexture, 3)" not in patched
    assert "void Dev_UpdateTexture(X86 *c)" in patched
    assert "gpu_after_unlock(b, 0u," in patched
    assert "d9_raster_invalidate(b->id);" in patched
    PATCH.patch_update_texture(kit)
    assert path.read_text() == patched
    bad = patched.replace(PATCH.MARKER, "broken-marker")
    path.write_text(bad)
    with pytest.raises(RuntimeError, match="Pinned UpdateTexture"):
        PATCH.patch_update_texture(kit)
    assert path.read_text() == bad


MOCK = r"""
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdarg>
#include <map>
#include <vector>
#include <cstdio>
#include <algorithm>
constexpr int K_D3D9TEXTURE = 1, K_D3D9SURFACE = 2, K_D3D9DEVICE = 3;
constexpr uint32_t D3D_OK9 = 0u, D3DERR_INVALIDCALL = 0x8876086cu;
struct ComObj {
    int kind = 0;
    uint32_t id = 0, dev_d3d = 0, caps = 0, rmask = 21;
    uint32_t width = 4, height = 4, front_obj = 0, pitch = 16;
    uint32_t lock_count = 0;
    std::vector<uint32_t> surfaces;
    std::vector<uint8_t> blob;
};
struct X86 {
    uint32_t a[3] = {};
    uint32_t result = 0xffffffffu;
};
static std::map<uint32_t, ComObj> objs;
static uint32_t next_id = 1;
static uint32_t gpu_reads = 0, gpu_writes = 0, invalidations = 0;
static bool gpu_enabled = true;
static uint32_t device_id;
ComObj &make(int kind, uint32_t dev = 0) {
    auto &o = objs[++next_id];
    o.kind = kind;
    o.id = next_id;
    o.dev_d3d = dev;
    return o;
}
ComObj *com_get(uint32_t id) {
    auto it = objs.find(id);
    return it == objs.end() ? nullptr : &it->second;
}
ComObj *com_this(uint32_t id) { return com_get(id); }
uint32_t arg(X86 *c, int n) { return c->a[n]; }
ComObj *this_device9(X86 *) { return com_get(device_id); }
void com_ret(X86 *c, uint32_t result) { c->result = result; }
bool gpu_on() { return gpu_enabled; }
void gpu_before_lock(ComObj *) { ++gpu_reads; }
void gpu_after_unlock(ComObj *, uint32_t, uint32_t) { ++gpu_writes; }
void d9_raster_invalidate(uint32_t) { ++invalidations; }
void logw(const char *, ...) {}
#define LOGW logw
"""

EXECUTE = r"""
int main() {
    ComObj &dev = make(K_D3D9DEVICE);
    device_id = dev.id;
    ComObj &src = make(K_D3D9TEXTURE, dev.id);
    ComObj &dst = make(K_D3D9TEXTURE, dev.id);
    src.width = dst.width = 4;
    src.height = dst.height = 4;
    for (unsigned n = 0; n < 2; ++n) {
        ComObj &a = make(K_D3D9SURFACE, dev.id);
        ComObj &b = make(K_D3D9SURFACE, dev.id);
        a.front_obj = src.id; b.front_obj = dst.id;
        a.width = b.width = 4u >> n;
        a.height = b.height = 4u >> n;
        a.pitch = b.pitch = 16u >> n;
        a.blob.assign(size_t(a.pitch) * a.height, uint8_t(0x60u + n));
        b.blob.assign(a.blob.size(), 0x33u);
        src.surfaces.push_back(a.id);
        dst.surfaces.push_back(b.id);
    }
    X86 c{};
    c.a[1] = src.id; c.a[2] = dst.id;
    Dev_UpdateTexture(&c);
    assert(c.result == D3D_OK9);
    assert(gpu_reads == 2 && gpu_writes == 2 && invalidations == 2);
    for (size_t n = 0; n < 2; ++n)
        assert(com_get(src.surfaces[n])->blob == com_get(dst.surfaces[n])->blob);

    // No partial write when a later mip has the wrong pitch.
    ComObj *first = com_get(dst.surfaces[0]);
    first->blob.assign(first->blob.size(), 0x44u);
    ComObj *last = com_get(dst.surfaces[1]);
    const uint32_t original_pitch = last->pitch;
    last->pitch = 5u;
    const uint32_t old_writes = gpu_writes;
    c.result = 99u;
    Dev_UpdateTexture(&c);
    assert(c.result == D3DERR_INVALIDCALL && gpu_writes == old_writes);
    assert(first->blob[0] == 0x44u);
    last->pitch = original_pitch;

    last->lock_count = 1;
    Dev_UpdateTexture(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    last->lock_count = 0;

    // Mismatched formats, sizes, aliasing and missing references are rejected.
    dst.rmask = 22;
    Dev_UpdateTexture(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    dst.rmask = 21;
    c.a[2] = src.id;
    Dev_UpdateTexture(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    c.a[2] = 0;
    Dev_UpdateTexture(&c);
    assert(c.result == D3DERR_INVALIDCALL);
    c.a[2] = dst.id;

    // CPU-backed copies also update destination bytes and invalidate cache.
    gpu_enabled = false;
    Dev_UpdateTexture(&c);
    assert(c.result == D3D_OK9);
    assert(gpu_reads == 2 && gpu_writes == 4 && invalidations == 4);
    assert(first->blob[0] == 0x60u);
}
"""


def test_update_texture_full_chain_native_guest_contract(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("No C++ compiler")
    kit, target = pinned_fixture(tmp_path)
    PATCH.patch_update_texture(kit)
    text = target.read_text()
    body = text.split("void Dev_UpdateTexture(X86 *c) {", 1)[1].split(
        "\nvoid Dev_StretchRect(X86 *c)", 1
    )[0]
    source = tmp_path / "texture.cpp"
    binary = tmp_path / "texture"
    source.write_text(MOCK + "\nvoid Dev_UpdateTexture(X86 *c) {" + body + EXECUTE)
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", source,
         "-o", binary],
        check=True, capture_output=True, text=True
    )
    subprocess.run([binary], check=True, capture_output=True, text=True)
