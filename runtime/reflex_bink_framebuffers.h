// Clean-room guest Bink 1 frame-buffer ABI for the pinned 32-bit runtime.
// The RAD SDK exposes two sets of four {allocate,buffer,pitch} planes.
// All pointers in this structure are *guest 32-bit offsets*, never host ptrs.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace reflex_bink {
struct Plane {
    uint32_t allocate, buffer, pitch;
};
struct Frame {
    Plane y, cr, cb, alpha;
};
struct FrameBuffers {
    uint32_t total_frames, ya_width, ya_height, crc_width, crc_height, frame_num;
    Frame frames[2];
};
static_assert(sizeof(Plane) == 12, "Bink 1 32-bit plane ABI mismatch");
static_assert(sizeof(Frame) == 48, "Bink 1 32-bit frame ABI mismatch");
static_assert(sizeof(FrameBuffers) == 120, "Bink 1 32-bit buffer ABI mismatch");

inline uint32_t align16(uint32_t n) {
    return (n + 15u) & ~15u;
}

inline bool initialize(FrameBuffers &out, uint32_t width, uint32_t height) {
    if (!width || !height || width > 16384u || height > 16384u)
        return false;
    std::memset(&out, 0, sizeof out);
    out.total_frames = 2u;
    out.ya_width = align16(width);
    out.ya_height = align16(height);
    out.crc_width = align16((width + 1u) / 2u);
    out.crc_height = align16((height + 1u) / 2u);
    for (Frame &frame : out.frames) {
        frame.y.allocate = 1u;
        frame.cr.allocate = 1u;
        frame.cb.allocate = 1u;
        // Alpha is only required if an alpha channel is decoded.
        frame.alpha.allocate = 0u;
    }
    return true;
}

// Validate an entire destination before copying any YUV rows. This avoids
// overflow, partial guest writes, and invalid host-frame access.
inline bool copy_plane(
    uint8_t *guest, uint32_t guest_size, const Plane &dst,
    const uint8_t *src, int src_pitch, uint32_t width, uint32_t height
) {
    if (!width || !height)
        return true;
    if (!guest || !src || !dst.buffer || dst.pitch < width ||
        src_pitch < 0 || static_cast<uint32_t>(src_pitch) < width)
        return false;
    const uint64_t end = static_cast<uint64_t>(dst.buffer) +
                         static_cast<uint64_t>(height - 1u) * dst.pitch + width;
    if (end > guest_size)
        return false;
    for (uint32_t y = 0; y < height; ++y)
        std::memcpy(guest + dst.buffer + static_cast<size_t>(y) * dst.pitch,
                    src + static_cast<size_t>(y) * src_pitch, width);
    return true;
}

inline bool copy_yuv420_frame(
    uint8_t *guest, uint32_t guest_size, const FrameBuffers &registered,
    uint32_t current_frame, const uint8_t *y, int y_pitch,
    const uint8_t *cr, int cr_pitch, const uint8_t *cb, int cb_pitch,
    uint32_t width, uint32_t height
) {
    if (!registered.total_frames || registered.total_frames > 2u ||
        !width || !height || width > 16384u || height > 16384u)
        return false;
    const Frame &frame = registered.frames[
        (current_frame ? current_frame - 1u : 0u) % registered.total_frames];
    const uint32_t cw = (width + 1u) / 2u, ch = (height + 1u) / 2u;
    // Preflight all three buffers so an invalid plane cannot leave a partially
    // updated frame. copy_plane repeats bounds checks for defense in depth.
    auto valid = [guest_size](const Plane &p, uint32_t w, uint32_t h,
                              const uint8_t *src, int pitch) {
        return src && p.buffer && p.pitch >= w && pitch >= 0 &&
               static_cast<uint32_t>(pitch) >= w &&
               static_cast<uint64_t>(p.buffer) +
                   static_cast<uint64_t>(h - 1u) * p.pitch + w <= guest_size;
    };
    if (!guest || !valid(frame.y, width, height, y, y_pitch) ||
        !valid(frame.cr, cw, ch, cr, cr_pitch) ||
        !valid(frame.cb, cw, ch, cb, cb_pitch))
        return false;
    return copy_plane(guest, guest_size, frame.y, y, y_pitch, width, height) &&
           copy_plane(guest, guest_size, frame.cr, cr, cr_pitch, cw, ch) &&
           copy_plane(guest, guest_size, frame.cb, cb, cb_pitch, cw, ch);
}
} // namespace reflex_bink
