#!/usr/bin/env python3
"""Patch the pinned recomp-kit D3D9 device with real shader COM objects.

Reflex reaches IDirect3DDevice9::CreateVertexShader/CreatePixelShader during
startup. The pinned kit currently returns D3D_OK without writing the output
pointer, which leaves Reflex holding null shader objects. This patch gives the
device proper IDirect3DVertexShader9/IDirect3DPixelShader9 objects, preserves
their bytecode, and binds real SM2/SM3 bytecode into D9Pipeline.

The temporary D3DXCompileShader bring-up bridge still returns HLSL source
rather than compiled SM3 bytecode. Those source-backed objects are retained
for correct COM lifetime but intentionally are not fed to the bytecode parser.
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


def main() -> None:
    com = KIT / "dx" / "com.h"
    d3d = KIT / "dx" / "d3d9.cpp"
    if not com.is_file() or not d3d.is_file():
        raise SystemExit("kit/ is missing the pinned D3D9 runtime")

    replace_once(
        com,
        "    IF_D3DVERTEXDECL9,\n"
        "    IF_D3DQUERY9,\n",
        "    IF_D3DVERTEXDECL9,\n"
        "    IF_D3DVERTEXSHADER9,\n"
        "    IF_D3DPIXELSHADER9,\n"
        "    IF_D3DQUERY9,\n",
        "IF_D3DVERTEXSHADER9",
    )

    replace_once(
        com,
        "    K_D3D9DECL,       // a vertex declaration\n"
        "    K_D3D9QUERY,      // an occlusion or event query\n",
        "    K_D3D9DECL,       // a vertex declaration\n"
        "    K_D3D9VS,         // a vertex shader and its token stream\n"
        "    K_D3D9PS,         // a pixel shader and its token stream\n"
        "    K_D3D9QUERY,      // an occlusion or event query\n",
        "K_D3D9VS",
    )

    replace_once(
        com,
        "    uint32_t current_viewport = 0;\n"
        "    bool in_scene = false;\n",
        "    uint32_t current_viewport = 0;\n"
        "    uint32_t d9_vertex_shader = 0;\n"
        "    uint32_t d9_pixel_shader = 0;\n"
        "    bool in_scene = false;\n",
        "d9_vertex_shader",
    )

    replace_once(
        d3d,
        "static const uint8_t IID_IDirect3DDevice9_[16] =\n"
        "    IID_BYTES(0xd0223b96, 0xbf7a, 0x43fd, 0x92, 0xbd, 0xa4, 0x3b, 0x0d, 0x82, 0xb9, 0xeb);\n",
        "static const uint8_t IID_IDirect3DDevice9_[16] =\n"
        "    IID_BYTES(0xd0223b96, 0xbf7a, 0x43fd, 0x92, 0xbd, 0xa4, 0x3b, 0x0d, 0x82, 0xb9, 0xeb);\n"
        "static const uint8_t IID_IDirect3DVertexShader9_[16] =\n"
        "    IID_BYTES(0xefc5557e, 0x6265, 0x4613, 0x8a, 0x94, 0x43, 0x85, 0x78, 0x89, 0xeb, 0x36);\n"
        "static const uint8_t IID_IDirect3DPixelShader9_[16] =\n"
        "    IID_BYTES(0x6d3bdbdc, 0x5b02, 0x4415, 0xb8, 0x52, 0xce, 0x5e, 0x8b, 0xcc, 0xb2, 0x89);\n",
        "IID_IDirect3DVertexShader9_",
    )

    for line in (
        "D9_STUB(CreateVertexShader, 3)\n",
        "D9_STUB(SetVertexShader, 2)\n",
        "D9_STUB(GetVertexShader, 2)\n",
        "D9_STUB(CreatePixelShader, 3)\n",
        "D9_STUB(SetPixelShader, 2)\n",
        "D9_STUB(GetPixelShader, 2)\n",
    ):
        text = d3d.read_text()
        if line in text:
            d3d.write_text(text.replace(line, "", 1))

    replace_once(
        d3d,
        "static const ComMethod g_decl9[] = {\n"
        "    {\"QueryInterface\", 3, com_QueryInterface},\n"
        "    {\"AddRef\", 1, com_AddRef},\n"
        "    {\"Release\", 1, com_Release},\n"
        "    {\"GetDevice\", 2, Res_GetDevice},\n"
        "    {\"GetDeclaration\", 3, Decl_GetDeclaration},\n"
        "};\n\n"
        "static const ComMethod g_query9[] = {\n",
        "static const ComMethod g_decl9[] = {\n"
        "    {\"QueryInterface\", 3, com_QueryInterface},\n"
        "    {\"AddRef\", 1, com_AddRef},\n"
        "    {\"Release\", 1, com_Release},\n"
        "    {\"GetDevice\", 2, Res_GetDevice},\n"
        "    {\"GetDeclaration\", 3, Decl_GetDeclaration},\n"
        "};\n\n"
        "// IDirect3DVertexShader9 / IDirect3DPixelShader9 share the same five-slot ABI.\n"
        "void Shader_GetFunction(X86 *c) {\n"
        "    ComObj *sh = com_this_arg(c);\n"
        "    uint32_t data = arg(c, 1), sizep = arg(c, 2);\n"
        "    if (!sh || !sizep || !gm_fits(sizep, 4)) {\n"
        "        com_ret(c, D3DERR_INVALIDCALL);\n"
        "        return;\n"
        "    }\n"
        "    uint32_t capacity = rd32(sizep);\n"
        "    uint32_t need = (uint32_t)sh->blob.size();\n"
        "    wr32(sizep, need);\n"
        "    if (!data) {\n"
        "        com_ret(c, D3D_OK9);\n"
        "        return;\n"
        "    }\n"
        "    if (capacity < need || !gm_fits(data, need)) {\n"
        "        com_ret(c, D3DERR_INVALIDCALL);\n"
        "        return;\n"
        "    }\n"
        "    if (need)\n"
        "        memcpy(gm_ptr(data), sh->blob.data(), need);\n"
        "    com_ret(c, D3D_OK9);\n"
        "}\n\n"
        "static const ComMethod g_vs9[] = {\n"
        "    {\"QueryInterface\", 3, com_QueryInterface},\n"
        "    {\"AddRef\", 1, com_AddRef},\n"
        "    {\"Release\", 1, com_Release},\n"
        "    {\"GetDevice\", 2, Res_GetDevice},\n"
        "    {\"GetFunction\", 3, Shader_GetFunction},\n"
        "};\n\n"
        "static const ComMethod g_ps9[] = {\n"
        "    {\"QueryInterface\", 3, com_QueryInterface},\n"
        "    {\"AddRef\", 1, com_AddRef},\n"
        "    {\"Release\", 1, com_Release},\n"
        "    {\"GetDevice\", 2, Res_GetDevice},\n"
        "    {\"GetFunction\", 3, Shader_GetFunction},\n"
        "};\n\n"
        "static const ComMethod g_query9[] = {\n",
        "static const ComMethod g_vs9[]",
    )

    pipeline_anchor = (
        "D9Pipeline &d9_pipeline(uint32_t device_id) {\n"
        "    // Records are never erased and map nodes do not move, so the last one\n"
        "    // asked for can be handed out again without a lookup.\n"
        "    static auto *records = new std::map<uint32_t, D9Pipeline>();\n"
        "    static thread_local uint32_t last_id = 0;\n"
        "    static thread_local D9Pipeline *last = nullptr;\n"
        "    if (last && last_id == device_id)\n"
        "        return *last;\n"
        "    last = &(*records)[device_id];\n"
        "    last_id = device_id;\n"
        "    return *last;\n"
        "}\n\n"
    )
    shader_impl = pipeline_anchor + r'''static bool d9_shader_version(uint32_t token, bool vertex) {
    return (token & 0xffff0000u) == (vertex ? 0xfffe0000u : 0xffff0000u);
}

// Capture either a real D3D9 token stream or the temporary HLSL source buffer
// produced by Reflex's D3DXCompileShader bring-up bridge.
static bool capture_d9_shader(uint32_t function, bool vertex, std::vector<uint8_t> &out) {
    if (!function || !gm_fits(function, 4))
        return false;
    uint32_t first = rd32(function);
    if (d9_shader_version(first, vertex)) {
        constexpr uint32_t kMaxDwords = 65536;
        for (uint32_t i = 0; i < kMaxDwords; ++i) {
            uint32_t at = function + i * 4u;
            if (!gm_fits(at, 4))
                return false;
            const uint8_t *p = gm_ptr(at);
            out.insert(out.end(), p, p + 4);
            if (rd32(at) == 0x0000ffffu)
                return true;
        }
        return false;
    }

    std::string source = gm_str(function, 65535);
    if (source.empty())
        return false;
    out.assign(source.begin(), source.end());
    out.push_back(0);
    return true;
}

static bool shader_has_bytecode(const ComObj *sh, bool vertex) {
    if (!sh || sh->blob.size() < 4)
        return false;
    uint32_t version = 0;
    memcpy(&version, sh->blob.data(), 4);
    return d9_shader_version(version, vertex);
}

static void create_d9_shader(X86 *c, bool vertex) {
    ComObj *dev = this_device9(c);
    uint32_t function = arg(c, 1), out = arg(c, 2);
    if (!dev || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    com_out_ptr(out, 0);

    std::vector<uint8_t> bytes;
    if (!capture_d9_shader(function, vertex, bytes)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }

    ComObj *sh = com_new(vertex ? K_D3D9VS : K_D3D9PS);
    if (!sh) {
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    sh->dev_d3d = dev->id;
    sh->blob = bytes;
    ComIface iface = vertex ? IF_D3DVERTEXSHADER9 : IF_D3DPIXELSHADER9;
    uint32_t view = com_view(sh, iface);
    if (!view) {
        com_release(sh);
        com_ret(c, E_OUTOFMEMORY);
        return;
    }

    LOGV("d3d9: Create%sShader captured %u bytes (%s) -> %08x",
         vertex ? "Vertex" : "Pixel", (uint32_t)bytes.size(),
         shader_has_bytecode(sh, vertex) ? "bytecode" : "source", view);
    com_out_ptr(out, view);
    com_ret(c, D3D_OK9);
}

static void set_d9_shader(X86 *c, bool vertex) {
    ComObj *dev = this_device9(c);
    ComObj *sh = com_this(arg(c, 1));
    if (!dev || (sh && sh->kind != (vertex ? K_D3D9VS : K_D3D9PS))) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }

    D9Pipeline &pl = d9_pipeline(dev->id);
    D9ShaderBytes &dst = vertex ? pl.vs : pl.ps;
    uint64_t &key = vertex ? pl.vs_key : pl.ps_key;
    uint32_t &bound = vertex ? dev->d9_vertex_shader : dev->d9_pixel_shader;
    bound = sh ? sh->id : 0;
    key = 0;
    dst.bytes.reset();

    if (sh && shader_has_bytecode(sh, vertex))
        dst.bytes = std::make_shared<const std::vector<uint8_t>>(sh->blob);
    else if (sh)
        log_once(vertex ? "d3d9.shader.vs.source" : "d3d9.shader.ps.source",
                 "d3d9: source-backed startup shader retained but not bound as D3D9 bytecode");

    com_ret(c, D3D_OK9);
}

static void get_d9_shader(X86 *c, bool vertex) {
    ComObj *dev = this_device9(c);
    uint32_t out = arg(c, 1);
    if (!dev || !out || !gm_fits(out, 4)) {
        com_ret(c, D3DERR_INVALIDCALL);
        return;
    }
    uint32_t id = vertex ? dev->d9_vertex_shader : dev->d9_pixel_shader;
    ComObj *sh = com_get(id);
    if (!sh) {
        com_out_ptr(out, 0);
        com_ret(c, D3D_OK9);
        return;
    }
    ComIface iface = vertex ? IF_D3DVERTEXSHADER9 : IF_D3DPIXELSHADER9;
    uint32_t view = com_view(sh, iface);
    if (!view) {
        com_ret(c, E_OUTOFMEMORY);
        return;
    }
    com_addref(sh);
    com_out_ptr(out, view);
    com_ret(c, D3D_OK9);
}

void Dev_CreateVertexShader(X86 *c) { create_d9_shader(c, true); }
void Dev_SetVertexShader(X86 *c) { set_d9_shader(c, true); }
void Dev_GetVertexShader(X86 *c) { get_d9_shader(c, true); }
void Dev_CreatePixelShader(X86 *c) { create_d9_shader(c, false); }
void Dev_SetPixelShader(X86 *c) { set_d9_shader(c, false); }
void Dev_GetPixelShader(X86 *c) { get_d9_shader(c, false); }

'''
    replace_once(
        d3d,
        pipeline_anchor,
        shader_impl,
        "capture_d9_shader(",
    )

    replace_once(
        d3d,
        "    com_define(IF_D3DVERTEXDECL9, \"d3d9.dll\", \"IDirect3DVertexDeclaration9\", g_decl9,\n"
        "               std::size(g_decl9));\n"
        "    com_define(IF_D3DQUERY9, \"d3d9.dll\", \"IDirect3DQuery9\", g_query9, std::size(g_query9));\n",
        "    com_define(IF_D3DVERTEXDECL9, \"d3d9.dll\", \"IDirect3DVertexDeclaration9\", g_decl9,\n"
        "               std::size(g_decl9));\n"
        "    com_define(IF_D3DVERTEXSHADER9, \"d3d9.dll\", \"IDirect3DVertexShader9\", g_vs9,\n"
        "               std::size(g_vs9));\n"
        "    com_define(IF_D3DPIXELSHADER9, \"d3d9.dll\", \"IDirect3DPixelShader9\", g_ps9,\n"
        "               std::size(g_ps9));\n"
        "    com_define(IF_D3DQUERY9, \"d3d9.dll\", \"IDirect3DQuery9\", g_query9, std::size(g_query9));\n",
        "com_define(IF_D3DVERTEXSHADER9",
    )

    replace_once(
        d3d,
        "    com_bind(IF_D3DVERTEXDECL9, K_D3D9DECL);\n"
        "    com_bind(IF_D3DQUERY9, K_D3D9QUERY);\n",
        "    com_bind(IF_D3DVERTEXDECL9, K_D3D9DECL);\n"
        "    com_bind(IF_D3DVERTEXSHADER9, K_D3D9VS);\n"
        "    com_bind(IF_D3DPIXELSHADER9, K_D3D9PS);\n"
        "    com_bind(IF_D3DQUERY9, K_D3D9QUERY);\n"
        "    com_register_iid(IF_D3DVERTEXSHADER9, IID_IDirect3DVertexShader9_);\n"
        "    com_register_iid(IF_D3DPIXELSHADER9, IID_IDirect3DPixelShader9_);\n",
        "com_bind(IF_D3DVERTEXSHADER9",
    )

    print("Applied Reflex D3D9 shader object/binding patch")


if __name__ == "__main__":
    main()
