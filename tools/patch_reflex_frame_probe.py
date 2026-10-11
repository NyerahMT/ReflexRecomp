#!/usr/bin/env python3
"""Report actual D3D9 presents, shaderless skips, and opt-in RGB evidence.

Must run after Reflex's shader, swap-chain, FVF and FLOAT16 patches. This
never forces a draw or modifies the guest's graphics data/control flow.
"""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
MARKER = "reflex-frame-probe-v1"


def only(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} anchor; got {count}")
    return text.replace(old, new, 1)


def patch_frame_probe(kit: Path, runtime: Path) -> None:
    file = kit / "dx" / "d3d9.cpp"
    hdr = runtime / "reflex_frame_rgb.h"
    if not file.is_file() or not hdr.is_file():
        raise RuntimeError("Missing D3D9 kit source or frame RGB header")
    text = file.read_text()
    if MARKER in text:
        if text.count(MARKER) != 1 or text.count("[reflex-frame] present") != 1 or \
                text.count("[reflex-frame] shaderless-skip") != 1 or \
                not (kit / "dx" / hdr.name).is_file():
            raise RuntimeError("Partial frame probe installation")
        return

    text = only(text, '#include "com.h"\n',
                '#include "com.h"\n#include "reflex_frame_rgb.h"\n'
                '#include <atomic>\n#include <cstdlib>\n', "includes")
    text = only(text,
                '    if (pl.vs.empty() || pl.ps.empty()) {\n'
                '        log_once("d3d9.gpu.ffp",',
                '''    if (pl.vs.empty() || pl.ps.empty()) {
        static std::atomic<unsigned long long> skips{0};
        const unsigned long long n = skips.fetch_add(1) + 1;
        if (n <= 8 || ((n & (n - 1)) == 0))
            LOGW("[reflex-frame] shaderless-skip n=%llu fvf=%08x decl=%u vs=%zu ps=%zu prim=%u count=%u",
                 n, dev->d9_fvf_current, pl.declaration, pl.vs.size(),
                 pl.ps.size(), d.primitive, d.primitive_count);
        log_once("d3d9.gpu.ffp",''', "GPU shaderless draw")
    text = only(text,
                '''void Dev_Present(X86 *c) {
    ComObj *dev = this_device9(c);
    ComObj *bb = dev ? device_backbuffer(dev) : nullptr;
''',
                '''void Dev_Present(X86 *c) {
    ComObj *dev = this_device9(c);
    ComObj *bb = dev ? device_backbuffer(dev) : nullptr;
    // reflex-frame-probe-v1: count completed D3D9 Present calls, not draws.
    static std::atomic<unsigned long long> presents{0};
    const unsigned long long n = presents.fetch_add(1) + 1;
    if (n <= 8 || ((n & (n - 1)) == 0))
        LOGW("[reflex-frame] present n=%llu bb=%u size=%ux%u gpu=%u",
             n, bb ? bb->id : 0, bb ? bb->width : 0,
             bb ? bb->height : 0, gpu_on() ? 1u : 0u);
''', "Present entry")
    text = only(text,
                '''        host_d9_present(bb->id, bb->width, bb->height);
        ddraw_external_present_end();''',
                '''        host_d9_present(bb->id, bb->width, bb->height);
        // Sample first 2 and powers of two up to 256: 9 bounded readbacks.
        const char *probe = std::getenv("REFLEX_FRAME_PROBE");
        if (probe && probe[0] == '1' && reflex_d3d9::should_readback(n) &&
            bb->width && bb->height &&
            uint64_t(bb->width) * bb->height * 3u <= 12u * 1024u * 1024u) {
            std::vector<uint8_t> rgb(size_t(bb->width) * bb->height * 3u);
            uint32_t w = 0, h = 0;
            const int read = host_d9_read_presented(
                rgb.data(), uint32_t(rgb.size()), &w, &h);
            reflex_d3d9::FrameStats st;
            if (read && reflex_d3d9::frame_stats(
                    rgb.data(), rgb.size(), w, h, &st))
                LOGW("[reflex-frame] rgb n=%llu size=%ux%u sampled=%u lit=%u hash=%016llx",
                     n, w, h, st.sampled, st.nonblack,
                     static_cast<unsigned long long>(st.hash));
            else
                LOGW("[reflex-frame] rgb-unavailable n=%llu rc=%d size=%ux%u",
                     n, read, w, h);
        }
        ddraw_external_present_end();''', "GPU present/readback")

    # Fail closed before touching either pinned source or helper on disk.
    (kit / "dx" / hdr.name).write_bytes(hdr.read_bytes())
    file.write_text(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, default=ROOT / "kit")
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    args = parser.parse_args()
    patch_frame_probe(args.kit, args.runtime)
    print("Installed Reflex D3D9 frame frontier probe")


if __name__ == "__main__":
    main()
