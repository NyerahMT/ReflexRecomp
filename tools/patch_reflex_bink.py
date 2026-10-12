#!/usr/bin/env python3
"""Supply missing Bink 1 Y/Cr/Cb frame-buffer APIs in pinned recomp-kit.

Original assets and FFmpeg decoder remain the source of actual video content.
Adds three missing Bink imports using their documented 32-bit stdcall ABI.
No game-code bypass, synthetic video, or guest-readiness modification.
"""
from pathlib import Path
import argparse

MARKER = "REFLEX_BINK_FRAMEBUFFERS_V1"

def patch_source(original: str) -> str:
    if MARKER in original:
        if original.count(MARKER) != 1:
            raise RuntimeError("Partial Bink framebuffer patch marker")
        return original
    replacements = [
        (
            '#include "video_frame.h"\n',
            '#include "video_frame.h"\n'
            '#include "../runtime/reflex_bink_framebuffers.h"\n'
        ),
        (
            "    uint32_t t0 = 0, paused_at = 0, count = 0, current = 1;\n",
            "    uint32_t t0 = 0, paused_at = 0, count = 0, current = 1;\n"
            "    uint32_t registered_frame_buffers = 0;\n"
            "    bool sound_enabled = true;\n"
            "    int32_t volume_mb = 0;\n"
            "    int64_t seek_target_pts = AV_NOPTS_VALUE;\n"
        ),
        (
            "    if (p.paused || !p.audio || p.failed || p.audio_unavailable)\n",
            "    if (p.paused || !p.audio || p.failed || p.audio_unavailable || !p.sound_enabled)\n"
        ),
        (
            "// Decode exactly one visible frame. Audio prefetch may already have retained",
            """// Copy actual decoded YUV420P pixels into the buffer planes registered by
// the original game. BinkGetFrameBuffersInfo supplies the required dimensions;
// the guest owns every destination texture and its pitch.
bool reflex_copy_registered_frame(BinkPlayer &p) {
    if (!p.registered_frame_buffers)
        return true;
    if (!gm_valid(p.registered_frame_buffers, sizeof(reflex_bink::FrameBuffers)))
        return video_error("registered Bink frame-buffer descriptor is invalid");
    reflex_bink::FrameBuffers info{};
    memcpy(&info, g_mem + p.registered_frame_buffers, sizeof info);
    const uint32_t idx = (p.current ? p.current - 1u : 0u) %
                         (info.total_frames ? info.total_frames : 1u);
    if (!reflex_bink::copy_yuv420_frame(
            g_mem, GUEST_SIZE, info, p.current,
            p.frame->data[0], p.frame->linesize[0],
            p.frame->data[2], p.frame->linesize[2],
            p.frame->data[1], p.frame->linesize[1],
            static_cast<uint32_t>(p.frame->width),
            static_cast<uint32_t>(p.frame->height)))
        return video_error("registered Bink YUV420 buffers are invalid");
    wr32(p.registered_frame_buffers +
         offsetof(reflex_bink::FrameBuffers, frame_num), idx);
    return true;
}

// Decode exactly one visible frame. Audio prefetch may already have retained"""
        ),
        (
            "                host_audio_play(&play);\n",
            "                host_audio_play(&play);\n"
            "                host_audio_set_volume(p.channel, p.volume_mb);\n"
        ),
        (
            "            p->have_frame = true;\n            service_audio(rec, *p);\n",
            "            if (p->seek_target_pts != AV_NOPTS_VALUE &&\n"
            "                p->frame->best_effort_timestamp != AV_NOPTS_VALUE &&\n"
            "                p->frame->best_effort_timestamp < p->seek_target_pts) {\n"
            "                av_frame_unref(p->frame);\n"
            "                continue;\n"
            "            }\n"
            "            p->seek_target_pts = AV_NOPTS_VALUE;\n"
            "            p->have_frame = true;\n"
            "            if (!reflex_copy_registered_frame(*p)) {\n"
            "                p->failed = true;\n"
            "                break;\n"
            "            }\n"
            "            service_audio(rec, *p);\n"
        ),
        (
            "void BinkDDSurfaceType(X86 *c) {\n",
            """// REFLEX_BINK_FRAMEBUFFERS_V1
// Bink 1 SDK 32-bit layout: 24-byte header + two 48-byte plane sets.
void BinkGetFrameBuffersInfo(X86 *c) {
    const uint32_t rec = arg(c, 0), address = arg(c, 1);
    set_eax(c, 0); // SDK declares this stdcall as void.
    if (!gm_valid(rec, 8) ||
        !gm_valid(address, sizeof(reflex_bink::FrameBuffers))) {
        LOGW("bink: invalid GetFrameBuffersInfo args rec=%08x dst=%08x",
             rec, address);
        return;
    }
    reflex_bink::FrameBuffers info{};
    if (!reflex_bink::initialize(info, rd32(rec), rd32(rec + 4))) {
        LOGW("bink: invalid video dimensions in record %08x", rec);
        return;
    }
    memcpy(g_mem + address, &info, sizeof info);
    LOGW("bink: YUV buffer info %ux%u UV=%ux%u frames=%u rec=%08x",
         info.ya_width, info.ya_height, info.crc_width, info.crc_height,
         info.total_frames, rec);
}

void BinkRegisterFrameBuffers(X86 *c) {
    const uint32_t rec = arg(c, 0), address = arg(c, 1);
#ifdef RECOMP_HAVE_FFMPEG
    if (BinkPlayer *p = player_for(rec)) {
        if (gm_valid(address, sizeof(reflex_bink::FrameBuffers))) {
            p->registered_frame_buffers = address;
            LOGW("bink: registered YUV guest frame buffers rec=%08x info=%08x",
                 rec, address);
        } else {
            video_error("invalid registered Bink frame-buffer address");
        }
    }
#else
    (void)rec;
    (void)address;
#endif
    set_eax(c, 0); // SDK declares this stdcall as void.
}

void BinkSetSoundOnOff(X86 *c) {
    const uint32_t rec = arg(c, 0);
    const bool enabled = arg(c, 1) != 0u;
    uint32_t result = 0;
#ifdef RECOMP_HAVE_FFMPEG
    if (BinkPlayer *p = player_for(rec)) {
        p->sound_enabled = enabled;
        if (!enabled && p->channel >= 0)
            host_audio_stop(p->channel);
        result = 1;
    }
#else
    (void)rec;
    (void)enabled;
#endif
    set_eax(c, result);
}

// The Bink 1 SDK uses 0..32768 amplitude; the host audio channel
// accepts attenuation in hundredths of a decibel.
void BinkSetVolume(X86 *c) {
#ifdef RECOMP_HAVE_FFMPEG
    if (BinkPlayer *p = player_for(arg(c, 0))) {
        const int32_t requested = static_cast<int32_t>(arg(c, 2));
        const double gain = std::max(0.0, std::min(1.0,
                              static_cast<double>(requested) / 32768.0));
        p->volume_mb = gain <= 0.0 ? -10000
                       : static_cast<int32_t>(std::max(-10000.0,
                             2000.0 * std::log10(gain)));
        if (p->channel >= 0)
            host_audio_set_volume(p->channel, p->volume_mb);
    }
#endif
    set_eax(c, 0); // void stdcall
}

// A frame is skippable only when the next frame's presentation deadline
// already passed. Never advance the video/decoder inside this query.
void BinkShouldSkip(X86 *c) {
    uint32_t skip = 0;
#ifdef RECOMP_HAVE_FFMPEG
    if (BinkPlayer *p = player_for(arg(c, 0))) {
        if (!p->paused && !p->failed && p->have_frame &&
            p->current < p->count) {
            const int64_t next_due = av_rescale_rnd(
                static_cast<int64_t>(p->current) * 1000,
                p->fps.den, p->fps.num, AV_ROUND_DOWN);
            skip = next_due >= 0 &&
                   static_cast<uint64_t>(host_millis() - p->t0) >
                       static_cast<uint64_t>(next_due);
        }
    }
#endif
    set_eax(c, skip);
}

// Honor the SDK's 1-based target frame. Seek actual compressed video,
// then flush demuxer queues, codecs, pending PCM, and the presentation timer.
void BinkGoto(X86 *c) {
#ifdef RECOMP_HAVE_FFMPEG
    const uint32_t rec = arg(c, 0);
    if (BinkPlayer *p = player_for(rec)) {
        const uint32_t frame = std::max(1u, std::min(arg(c, 1), p->count));
        AVStream *stream = p->input->streams[p->video_index];
        const int64_t pts = av_rescale_q(
            static_cast<int64_t>(frame - 1u), av_inv_q(p->fps),
            stream->time_base);
        if (av_seek_frame(p->input, p->video_index, pts,
                          AVSEEK_FLAG_BACKWARD) < 0) {
            video_error("BinkGoto could not seek compressed video");
            set_eax(c, 0);
            return;
        }
        avcodec_flush_buffers(p->video);
        if (p->audio)
            avcodec_flush_buffers(p->audio);
        for (AVPacket *packet : p->video_packets)
            av_packet_free(&packet);
        p->video_packets.clear();
        p->pending.clear();
        p->pending_pos = 0;
        if (p->channel >= 0) {
            host_audio_stop(p->channel);
            dx_free_audio_channel(p->channel);
            p->channel = -1;
        }
        p->audio_started = false;
        p->have_frame = false;
        p->eof = p->flushed = p->failed = false;
        p->current = frame;
        p->seek_target_pts = pts;
        const uint32_t now = host_millis();
        const int64_t playback_ms = av_rescale_rnd(
            static_cast<int64_t>(frame - 1u) * 1000,
            p->fps.den, p->fps.num, AV_ROUND_DOWN);
        p->t0 = now - static_cast<uint32_t>(playback_ms);
        if (p->paused)
            p->paused_at = now;
        write_frame_count(rec, *p);
    }
#endif
    set_eax(c, 0); // void stdcall
}

void BinkDDSurfaceType(X86 *c) {
"""
        ),
        (
            "    BINK(GetRects, 8, BinkGetRects),\n",
            "    BINK(GetRects, 8, BinkGetRects),\n"
            "    BINK(GetFrameBuffersInfo, 8, BinkGetFrameBuffersInfo),\n"
            "    BINK(RegisterFrameBuffers, 8, BinkRegisterFrameBuffers),\n"
            "    BINK(SetSoundOnOff, 8, BinkSetSoundOnOff),\n"
            "    BINK(SetVolume, 12, BinkSetVolume),\n"
            "    BINK(ShouldSkip, 4, BinkShouldSkip),\n"
            "    BINK(Goto, 12, BinkGoto),\n"
        ),
    ]
    # Validate every exact anchor before mutating any upstream source.
    for old, _ in replacements:
        if original.count(old) != 1:
            raise RuntimeError(f"Pinned upstream Bink ABI patch anchor mismatch: {old[:64]!r}")
    output = original
    for old, new in replacements:
        output = output.replace(old, new, 1)
    if output.count(MARKER) != 1:
        raise RuntimeError("Bink patch marker missing or duplicated")
    return output


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("pinned_bink", type=Path)
    args = p.parse_args()
    original = args.pinned_bink.read_text()
    modified = patch_source(original)
    args.pinned_bink.write_text(modified)
    print("Installed Bink 1 guest frame-buffer compatibility APIs")


if __name__ == "__main__":
    main()
