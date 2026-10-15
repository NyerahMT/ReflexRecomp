"""Bounded GPU readback analysis, strict native RGB sampling and pin tests."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

patch = load("frame_patch", "tools/patch_reflex_frame_probe.py")
analysis = load("frame_stats", "tools/summarize_reflex_render.py")

CPP = r"""
#include "reflex_frame_rgb.h"
#include <cassert>
#include <vector>
int main(int argc, char **argv) {
    assert(argc >= 2);
    std::vector<uint8_t> pixels(100 * 3);
    reflex_d3d9::FrameStats s;
    assert(reflex_d3d9::frame_stats(pixels.data(), pixels.size(), 10, 10, &s));
    assert(s.sampled == 2 && s.nonblack == 0);
    const auto old = s.hash;
    pixels[0] = 255;
    assert(reflex_d3d9::frame_stats(pixels.data(), pixels.size(), 10, 10, &s));
    assert(s.nonblack == 1 && s.hash != old);
    const uint64_t sampled[] = {1, 2, 4, 8, 16, 32, 64, 128, 256,
                                512, 1024, 2048, 4096, 8192, 16384};
    for (uint64_t n : sampled)
        assert(reflex_d3d9::should_readback(n));
    const uint64_t skipped[] = {0, 3, 5, 7, 9, 255, 257, 16383, 16385, 32768, 65536};
    for (uint64_t n : skipped)
        assert(!reflex_d3d9::should_readback(n));
    assert(!reflex_d3d9::frame_stats(pixels.data(), pixels.size()-1, 10, 10, &s));
    assert(!reflex_d3d9::frame_stats(pixels.data(), pixels.size(), 0, 10, &s));
    assert(!reflex_d3d9::frame_stats(pixels.data(), pixels.size(), 8193, 10, &s));
    assert(!reflex_d3d9::frame_stats(nullptr, pixels.size(), 10, 10, &s));
    assert(!reflex_d3d9::frame_stats(pixels.data(), pixels.size(), 10, 10, nullptr));
    assert(reflex_d3d9::write_frame_ppm(argv[1], pixels.data(), pixels.size(), 10, 10));
    assert(!reflex_d3d9::write_frame_ppm(argv[1], pixels.data(), pixels.size()-1, 10, 10));
    assert(!reflex_d3d9::write_frame_ppm(argv[1], pixels.data(), pixels.size(), 0, 10));
    assert(!reflex_d3d9::write_frame_ppm(argv[1], pixels.data(), pixels.size(), 5000, 10));
}
"""

def test_native_frame_samples(tmp_path):
    cxx = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if cxx is None: pytest.skip("C++ compiler unavailable")
    source, binary = tmp_path / "frame.cpp", tmp_path / "frame"
    source.write_text(CPP)
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "runtime"), str(source), "-o", str(binary)],
                   check=True, capture_output=True, text=True)
    ppm = tmp_path / "preview.ppm"
    subprocess.run([str(binary), str(ppm)], check=True, capture_output=True, text=True)
    payload = ppm.read_bytes()
    prefix = b"P6\n10 10\n255\n"
    assert payload.startswith(prefix)
    assert len(payload) == len(prefix) + 300
    assert payload[len(prefix)] == 255

def test_pinned_probe_patch_idempotent_and_safe(tmp_path):
    original = ROOT / "kit" / "dx" / "d3d9.cpp"
    if not original.is_file(): pytest.skip("Pinned kit only checked out in CI")
    kit = tmp_path / "kit"
    (kit / "dx").mkdir(parents=True)
    target = kit / "dx" / "d3d9.cpp"
    shutil.copyfile(original, target)
    patch.patch_frame_probe(kit, ROOT / "runtime")
    current = target.read_text()
    assert current.count(patch.MARKER) == 1
    assert current.count("[reflex-frame] shaderless-skip") == 1
    assert current.count("[reflex-frame] present") == 1
    assert "n == 4096u || n == 8192u" in current
    assert "n == 4096u || n == 16384u" not in current
    patch.patch_frame_probe(kit, ROOT / "runtime")
    assert target.read_text() == current
    wrong = original.read_text().replace(
        "        host_d9_present(bb->id, bb->width, bb->height);",
        "        /* changed */ host_d9_present(bb->id, bb->width, bb->height);", 1)
    target.write_text(wrong)
    with pytest.raises(RuntimeError, match="GPU present/readback"):
        patch.patch_frame_probe(kit, ROOT / "runtime")
    assert target.read_text() == wrong

def test_metrics_never_invent_frames():
    assert analysis.measure("no markers")["presents"] is None
    data = analysis.measure(
        "d3d9: draw 8: triangle list\n"
        "[reflex-frame] shaderless-skip n=16 fvf=00000144 decl=22 vs=0 ps=0 prim=4 count=2\n"
        "[reflex-frame] present n=4 bb=33 size=1280x720 gpu=1\n"
        "[reflex-frame] rgb n=2 size=1280x720 sampled=9502 lit=6 hash=abc012ef\n")
    assert data["last_draw"] == 8
    assert data["shaderless_skips"] == 16
    assert data["presents"] == 4
    assert data["last_fvf"] == "00000144"
    assert data["rgb"]["lit"] == 6


def test_first_nonblack_sample_is_not_lost():
    data = analysis.measure(
        "[reflex-frame] rgb n=1 size=1280x720 sampled=9502 lit=0 hash=aa11\n"
        "[reflex-frame] rgb n=2 size=1280x720 sampled=9502 lit=0 hash=aa11\n"
        "[reflex-frame] rgb n=8 size=1280x720 sampled=9502 lit=77 hash=cd12\n"
        "[reflex-frame] rgb n=16 size=1280x720 sampled=9502 lit=0 hash=aa11\n")
    assert data["readbacks"] == 4
    assert data["first_nonblack"]["present"] == 8
    assert data["first_nonblack"]["lit"] == 77
    assert data["rgb"]["present"] == 16
    empty = analysis.measure("[reflex-frame] present n=64 bb=4 size=1280x720 gpu=1")
    assert empty["first_nonblack"] is None
    assert empty["readbacks"] == 0
