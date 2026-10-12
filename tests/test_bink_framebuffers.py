"""Regression tests for the original Bink 1 external YUV frame-buffer API."""
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "reflex_bink_patch", ROOT / "tools" / "patch_reflex_bink.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

HARNESS = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstddef>
#include <vector>
#include "reflex_bink_framebuffers.h"

int main() {
    using namespace reflex_bink;
    static_assert(sizeof(FrameBuffers) == 120);
    static_assert(offsetof(FrameBuffers, frames) == 24);
    static_assert(offsetof(FrameBuffers, frames[1]) == 72);
    static_assert(offsetof(Frame, cb) == 24);
    static_assert(offsetof(Frame, alpha) == 36);
    FrameBuffers info{};
    assert(initialize(info, 1280, 1024));
    assert(info.total_frames == 2u);
    assert(info.ya_width == 1280u && info.ya_height == 1024u);
    assert(info.crc_width == 640u && info.crc_height == 512u);
    assert(info.frame_num == 0u);
    for (const auto &frame : info.frames) {
        assert(frame.y.allocate == 1u);
        assert(frame.cr.allocate == 1u);
        assert(frame.cb.allocate == 1u);
        assert(frame.alpha.allocate == 0u);
    }
    assert(!initialize(info, 0, 1024));
    assert(!initialize(info, UINT32_MAX, 1024));
    assert(initialize(info, 4, 4));
    std::vector<uint8_t> guest(2048, 0xaa);
    uint8_t y[16] = {
        1,2,3,4, 5,6,7,8, 9,10,11,12, 13,14,15,16
    };
    uint8_t cr[4] = {31,32,33,34}, cb[4] = {41,42,43,44};
    // Frame 1 uses buffer index 0, frame 2 index 1.
    info.frames[0].y.buffer = 100;
    info.frames[0].y.pitch = 8;
    info.frames[0].cr.buffer = 200;
    info.frames[0].cr.pitch = 4;
    info.frames[0].cb.buffer = 300;
    info.frames[0].cb.pitch = 4;
    info.frames[1].y.buffer = 400;
    info.frames[1].y.pitch = 8;
    info.frames[1].cr.buffer = 500;
    info.frames[1].cr.pitch = 4;
    info.frames[1].cb.buffer = 600;
    info.frames[1].cb.pitch = 4;
    assert(copy_yuv420_frame(guest.data(), guest.size(), info, 1,
                            y, 4, cr, 2, cb, 2, 4, 4));
    assert(guest[100] == 1 && guest[103] == 4 && guest[108] == 5);
    assert(guest[200] == 31 && guest[204] == 33);
    assert(guest[300] == 41 && guest[304] == 43);
    assert(guest[400] == 0xaa);
    assert(copy_yuv420_frame(guest.data(), guest.size(), info, 2,
                            y, 4, cr, 2, cb, 2, 4, 4));
    assert(guest[400] == 1 && guest[600] == 41);

    // Missing chroma registration must NOT partially overwrite luma.
    info.frames[0].cr.buffer = 0;
    guest[100] = 0xaau;
    assert(!copy_yuv420_frame(guest.data(), guest.size(), info, 1,
                             y, 4, cr, 2, cb, 2, 4, 4));
    assert(guest[100] == 0xaa);
    // Reject dangerous pitch/overflow.
    info.frames[0].cr.buffer = 200;
    info.frames[0].y.pitch = 0xffffffffu;
    assert(!copy_yuv420_frame(guest.data(), guest.size(), info, 1,
                             y, 4, cr, 2, cb, 2, 4, 4));
    assert(!copy_plane(guest.data(), guest.size(), info.frames[0].y,
                       y, -1, 4, 4));
}
"""


def test_bink_framebuffer_abi_yuv420_copy_and_full_validation(tmp_path):
    cxx = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not cxx:
        pytest.skip("C++ compiler unavailable")
    source = tmp_path / "bink_yuv_native.cpp"
    binary = tmp_path / "bink_yuv_native"
    source.write_text(HARNESS)
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "runtime"), str(source), "-o", str(binary)],
                   capture_output=True, text=True, check=True)
    subprocess.run([str(binary)], capture_output=True, text=True, check=True)


# Minimal fixture assembled from exact pinned-upstream patch anchors, not
# original proprietary game source or binary.
PINNED_SNIPPET = r'''
#include "video_frame.h"
    uint32_t t0 = 0, paused_at = 0, count = 0, current = 1;
    if (p.paused || !p.audio || p.failed || p.audio_unavailable)
                host_audio_play(&play);
// Decode exactly one visible frame. Audio prefetch may already have retained
            p->have_frame = true;
            service_audio(rec, *p);
void BinkDDSurfaceType(X86 *c) {
    BINK(GetRects, 8, BinkGetRects),
'''


def test_pinned_bink_patch_is_idempotent_and_registers_all_missing_imports():
    once = patcher.patch_source(PINNED_SNIPPET)
    assert once.count(patcher.MARKER) == 1
    assert "BINK(GetFrameBuffersInfo, 8, BinkGetFrameBuffersInfo)" in once
    assert "BINK(RegisterFrameBuffers, 8, BinkRegisterFrameBuffers)" in once
    assert "BINK(SetSoundOnOff, 8, BinkSetSoundOnOff)" in once
    assert "BINK(SetVolume, 12, BinkSetVolume)" in once
    assert "BINK(ShouldSkip, 4, BinkShouldSkip)" in once
    assert "BINK(Goto, 12, BinkGoto)" in once
    assert "host_audio_set_volume(p->channel, p->volume_mb)" in once
    assert "av_seek_frame(p->input, p->video_index, pts," in once
    assert "p->frame->best_effort_timestamp < p->seek_target_pts" in once
    assert "p->pending.clear();" in once
    assert "reflex_copy_registered_frame" in once
    assert patcher.patch_source(once) == once


def test_pinned_bink_patch_rejects_unexpected_upstream_source():
    with pytest.raises(RuntimeError, match="anchor mismatch"):
        patcher.patch_source('BINK(GetRects, 8, BinkGetRects),')


def test_bink_patch_updates_trigger_original_game_fast_iteration():
    workflow = (ROOT / ".github" / "workflows" / "fast-iterate.yml").read_text()
    triggers = workflow.split("  push:", 1)[1].split("\npermissions:", 1)[0]
    assert '"tools/patch_reflex_bink.py"' in triggers
    assert '"tests/test_bink_framebuffers.py"' in triggers
