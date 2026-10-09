#!/usr/bin/env python3
"""Inject Reflex-only runtime compatibility into the pinned recomp-kit checkout."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "kit"
SOURCE = ROOT / "runtime" / "reflex_compat.cpp"
NUMERIC_HEADER = ROOT / "runtime" / "reflex_crt_numeric.h"


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    if not (KIT / "runtime" / "CMakeLists.txt").is_file():
        raise SystemExit("kit/ is missing the pinned recomp-kit runtime")
    if not SOURCE.is_file():
        raise SystemExit(f"missing {SOURCE}")

    target = KIT / "runtime" / "reflex_compat.cpp"
    shutil.copyfile(SOURCE, target)
    if not NUMERIC_HEADER.is_file():
        raise SystemExit(f"missing {NUMERIC_HEADER}")
    shutil.copyfile(NUMERIC_HEADER, KIT / "runtime" / NUMERIC_HEADER.name)
    # The SIMD decoder is a separately linked guest CPU helper. Both its
    # declaration and implementation must be staged into the pinned kit.
    for filename in ("reflex_packed_sse.h", "reflex_packed_sse.cpp"):
        source = ROOT / "runtime" / filename
        if not source.is_file():
            raise SystemExit(f"missing {source}")
        shutil.copyfile(source, KIT / "runtime" / filename)

    cmake = KIT / "runtime" / "CMakeLists.txt"
    replace_once(
        cmake,
        "  media_foundation.cpp layout.cpp interp.cpp discovery.cpp)",
        "  media_foundation.cpp layout.cpp interp.cpp discovery.cpp reflex_compat.cpp reflex_packed_sse.cpp)",
        "reflex_packed_sse.cpp)",
    )

    imports = KIT / "runtime" / "imports.cpp"
    replace_once(
        imports,
        "    extern void msimg32_register();\n"
        "    msimg32_register();\n"
        "}",
        "    extern void msimg32_register();\n"
        "    msimg32_register();\n"
        "    extern void reflex_compat_register();\n"
        "    reflex_compat_register();\n"
        "}",
        "reflex_compat_register();",
    )

    cpu = KIT / "runtime" / "cpu.cpp"
    replace_once(
        cpu,
        "void recomp_div_error(X86 *c, uint32_t addr) {\n"
        "    LOGW(\"divide error at %08x (EAX=%08x EDX=%08x)\", addr, c->r[R_EAX], c->r[R_EDX]);\n"
        "}\n",
        "void recomp_div_error(X86 *c, uint32_t addr) {\n"
        "    auto dump4 = [](uint32_t p) -> uint32_t { return (p && gm_valid(p, 4)) ? rd32(p) : 0u; };\n"
        "    const uint32_t edi = c->r[R_EDI];\n"
        "    const uint32_t ecx = c->r[R_ECX];\n"
        "    const uint32_t ebp = c->r[R_EBP];\n"
        "    LOGW(\"divide error at %08x (EAX=%08x EDX=%08x ECX=%08x EDI=%08x EBP=%08x ESP=%08x)\",\n"
        "         addr, c->r[R_EAX], c->r[R_EDX], ecx, edi, ebp, c->r[R_ESP]);\n"
        "    if (addr == 0x00843534u || addr == 0x0084df97u || addr == 0x0088048eu) {\n"
        "        LOGW(\"hash-div state: edi[%08x,%08x,%08x,%08x,%08x,%08x,%08x] ecx[%08x,%08x,%08x,%08x,%08x,%08x,%08x]\",\n"
        "             dump4(edi + 0x00), dump4(edi + 0x04), dump4(edi + 0x08), dump4(edi + 0x0c),\n"
        "             dump4(edi + 0x10), dump4(edi + 0x14), dump4(edi + 0x18),\n"
        "             dump4(ecx + 0x00), dump4(ecx + 0x04), dump4(ecx + 0x08), dump4(ecx + 0x0c),\n"
        "             dump4(ecx + 0x10), dump4(ecx + 0x14), dump4(ecx + 0x18));\n"
        "    }\n"
        "    if (addr == 0x0084df97u) {\n"
        "        const uint32_t sp = c->r[R_ESP];\n"
        "        LOGW(\"hash-grow state: new_count=%08x xmm0=%08x xmm1=%08x grow_const=%08x load_const=%08x container[%08x,%08x,%08x,%08x,%08x,%08x,%08x]\",\n"
        "             dump4(sp + 0x18), c->xmm[0][0], c->xmm[1][0], dump4(0x009322a4u), dump4(0x00935aa8u),\n"
        "             dump4(ebp + 0x00), dump4(ebp + 0x04), dump4(ebp + 0x08), dump4(ebp + 0x0c),\n"
        "             dump4(ebp + 0x10), dump4(ebp + 0x14), dump4(ebp + 0x18));\n"
        "    }\n"
        "}\n",
        "hash-grow state:",
    )

    replace_once(
        cpu,
        "    uint32_t ret = rd32(c->r[R_ESP]);\n"
        "    // Windows maps nothing in the first 64 KB, so a call there - through a nil\n",
        "    uint32_t ret = rd32(c->r[R_ESP]);\n"
        "    if (target == 0 && ret == 0x008244e8u) {\n"
        "        const uint32_t wrapper = c->r[R_ESI];\n"
        "        const uint32_t cs = (wrapper && gm_valid(wrapper, 8)) ? rd32(wrapper) : 0;\n"
        "        const uint32_t aux = (wrapper && gm_valid(wrapper, 8)) ? rd32(wrapper + 4) : 0;\n"
        "        const uint32_t obj = (cs && gm_valid(cs + 0x18, 4)) ? rd32(cs + 0x18) : 0;\n"
        "        const uint32_t vt = (obj && gm_valid(obj, 4)) ? rd32(obj) : 0;\n"
        "        const uint32_t slot = (vt && gm_valid(vt + 0xe4, 4)) ? rd32(vt + 0xe4) : 0;\n"
        "        const uint32_t a0 = gm_valid(c->r[R_ESP] + 4, 12) ? rd32(c->r[R_ESP] + 4) : 0;\n"
        "        const uint32_t a1 = gm_valid(c->r[R_ESP] + 8, 8) ? rd32(c->r[R_ESP] + 8) : 0;\n"
        "        const uint32_t a2 = gm_valid(c->r[R_ESP] + 12, 4) ? rd32(c->r[R_ESP] + 12) : 0;\n"
        "        LOGW(\"reflex frontier 008244e8: wrapper=%08x cs=%08x aux=%08x ecx=%08x obj=%08x vt=%08x slot_e4=%08x args=%08x,%08x,%08x\",\n"
        "             wrapper, cs, aux, c->r[R_ECX], obj, vt, slot, a0, a1, a2);\n"
        "    }\n"
        "    if (target == 0 && ret == 0x007ade7au) {\n"
        "        const uint32_t obj = gm_valid(c->r[R_ESP] + 4, 4) ? rd32(c->r[R_ESP] + 4) : 0;\n"
        "        const uint32_t out = gm_valid(c->r[R_ESP] + 8, 4) ? rd32(c->r[R_ESP] + 8) : 0;\n"
        "        const uint32_t vt = (obj && gm_valid(obj, 4)) ? rd32(obj) : 0;\n"
        "        const uint32_t slot = (vt && gm_valid(vt + 0x0c, 4)) ? rd32(vt + 0x0c) : 0;\n"
        "        LOGW(\"reflex frontier 007ade7a: obj=%08x vt=%08x slot_0c=%08x out=%08x esi=%08x edi=%08x\",\n"
        "             obj, vt, slot, out, c->r[R_ESI], c->r[R_EDI]);\n"
        "    }\n"
        "    // Windows maps nothing in the first 64 KB, so a call there - through a nil\n",
        "reflex frontier 008244e8:",
    )

    kernel32 = KIT / "runtime" / "kernel32.cpp"
    # Trace resource-worker thread startup without per-import log flooding.
    replace_once(
        kernel32,
        "    LOGV(\"CreateThread(%08x, param=%08x, flags=%08x) -> handle %08x id %u\", start, param, flags, h,\n"
        "         t->id);\n"
        "    set_eax(c, h);",
        "    LOGV(\"CreateThread(%08x, param=%08x, flags=%08x) -> handle %08x id %u\", start, param, flags, h,\n"
        "         t->id);\n"
        "    fprintf(stderr, \"[reflex-thread] CreateThread start=%08x param=%08x flags=%08x handle=%08x tid=%u suspended=%d\\n\",\n"
        "            start, param, flags, h, t->id, t->suspend_count);\n"
        "    set_eax(c, h);",
        "[reflex-thread] CreateThread start=",
    )

    replace_once(
        kernel32,
        "void create_event_named(X86 *c, const std::string &name) {\n"
        "    if (reuse_named_object(c, name, H_EVENT))\n"
        "        return;\n"
        "    uint32_t h = handle_new(H_EVENT);\n"
        "    handles()[h].manual_reset = arg(c, 1) != 0;\n"
        "    handles()[h].signalled = arg(c, 2) != 0;\n"
        "    handles()[h].object_name = name;\n"
        "    set_last_error(ERROR_SUCCESS_);\n"
        "    set_eax(c, h);\n"
        "}\n",
        "void create_event_named(X86 *c, const std::string &name) {\n"
        "    const bool reflex_fmod_event = name == \"FMODQueueProcessEvent\";\n"
        "    if (reuse_named_object(c, name, H_EVENT)) {\n"
        "        fprintf(stderr, \"[reflex-sync] CreateEventA reuse name=%s result=%08x last_error=%u\\n\",\n"
        "                name.c_str(), c->r[R_EAX], get_last_error());\n"
        "        return;\n"
        "    }\n"
        "    uint32_t h = handle_new(H_EVENT);\n"
        "    handles()[h].manual_reset = arg(c, 1) != 0;\n"
        "    handles()[h].signalled = arg(c, 2) != 0;\n"
        "    handles()[h].object_name = name;\n"
        "    set_last_error(ERROR_SUCCESS_);\n"
        "    set_eax(c, h);\n"
        "    fprintf(stderr, \"[reflex-sync] CreateEventA name=%s handle=%08x manual=%u initial=%u handles=%zu\\n\",\n"
        "            name.c_str(), h, handles()[h].manual_reset ? 1u : 0u,\n"
        "            handles()[h].signalled ? 1u : 0u, handles().size());\n"
        "}\n",
        "[reflex-sync] CreateEventA",
    )

    replace_once(
        kernel32,
        "void k_SetEvent(X86 *c) {\n"
        "    HObj *o = handle_get(arg(c, 0), H_EVENT);\n"
        "    if (o) {\n"
        "        o->signalled = true;\n"
        "        sched_wake_all();\n"
        "    }\n"
        "    set_eax(c, o ? 1 : 0);\n"
        "}\n",
        "void k_SetEvent(X86 *c) {\n"
        "    const uint32_t h = arg(c, 0);\n"
        "    HObj *o = handle_get(h, H_EVENT);\n"
        "    const uint32_t reflex_h = gm_valid(0x00d67ce8u, 4) ? rd32(0x00d67ce8u) : 0u;\n"
        "    const bool trace = !o || h == reflex_h || (o && (o->object_name == \"FMODQueueProcessEvent\" || o->object_name == \"DatabaseThreadEvent\" || o->object_name == \"LoadingThreadEvent\" || o->object_name == \"CacheThreadEvent\"));\n"
        "    if (trace)\n"
        "        fprintf(stderr, \"[reflex-sync] SetEvent handle=%08x guest_global=%08x valid=%u signalled_before=%u\\n\",\n"
        "                h, reflex_h, o ? 1u : 0u, (o && o->signalled) ? 1u : 0u);\n"
        "    if (o) {\n"
        "        o->signalled = true;\n"
        "        sched_wake_all();\n"
        "    }\n"
        "    set_eax(c, o ? 1 : 0);\n"
        "}\n",
        "[reflex-sync] SetEvent",
    )

    replace_once(
        kernel32,
        "void k_ResetEvent(X86 *c) {\n"
        "    HObj *o = handle_get(arg(c, 0), H_EVENT);\n"
        "    if (o)\n"
        "        o->signalled = false;\n"
        "    set_eax(c, o ? 1 : 0);\n"
        "}\n",
        "void k_ResetEvent(X86 *c) {\n"
        "    const uint32_t h = arg(c, 0);\n"
        "    HObj *o = handle_get(h, H_EVENT);\n"
        "    if (!o)\n"
        "        fprintf(stderr, \"[reflex-sync] ResetEvent INVALID handle=%08x handles=%zu\\n\", h, handles().size());\n"
        "    if (o)\n"
        "        o->signalled = false;\n"
        "    set_eax(c, o ? 1 : 0);\n"
        "}\n",
        "[reflex-sync] ResetEvent INVALID",
    )

    replace_once(
        kernel32,
        "void k_WaitForSingleObject(X86 *c) {\n"
        "    uint32_t h = arg(c, 0);\n"
        "    set_eax(c, sched_wait_objects(&h, 1, false, arg(c, 1)));\n"
        "}\n",
        "void k_WaitForSingleObject(X86 *c) {\n"
        "    uint32_t h = arg(c, 0);\n"
        "    const uint32_t timeout = arg(c, 1);\n"
        "    HObj *before = handle_any(h);\n"
        "    const uint32_t reflex_h = gm_valid(0x00d67ce8u, 4) ? rd32(0x00d67ce8u) : 0u;\n"
        "    const uint32_t ret = gm_valid(c->r[R_ESP], 4) ? rd32(c->r[R_ESP]) : 0u;\n"
        "    if (!h && ret == 0x00806017u) {\n"
        "        HObj *queue = handle_any(reflex_h);\n"
        "        if (queue && queue->kind == H_EVENT && queue->object_name == \"FMODQueueProcessEvent\") {\n"
        "            fprintf(stderr, \"[reflex-sync] WaitForSingleObject FMOD bridge ret=%08x null_handle -> %08x timeout=%08x\\n\",\n"
        "                    ret, reflex_h, timeout);\n"
        "            h = reflex_h;\n"
        "            before = queue;\n"
        "        }\n"
        "    }\n"
        "    const bool trace = !before || h == reflex_h || (before && (before->object_name == \"FMODQueueProcessEvent\" || before->object_name == \"DatabaseThreadEvent\" || before->object_name == \"LoadingThreadEvent\" || before->object_name == \"CacheThreadEvent\"));\n"
        "    if (trace)\n"
        "        fprintf(stderr, \"[reflex-sync] WaitForSingleObject enter tid=%u handle=%08x guest_global=%08x valid=%u kind=%d timeout=%08x signalled=%u handles=%zu\\n\",\n"
        "                cur_thread_id(), h, reflex_h, before ? 1u : 0u, before ? (int)before->kind : -1,\n"
        "                timeout, (before && before->signalled) ? 1u : 0u, handles().size());\n"
        "    const uint32_t rc = sched_wait_objects(&h, 1, false, timeout);\n"
        "    if (trace) {\n"
        "        HObj *after = handle_any(h);\n"
        "        fprintf(stderr, \"[reflex-sync] WaitForSingleObject exit tid=%u handle=%08x result=%08x last_error=%u valid_after=%u signalled_after=%u handles=%zu\\n\",\n"
        "                cur_thread_id(), h, rc, get_last_error(), after ? 1u : 0u,\n"
        "                (after && after->signalled) ? 1u : 0u, handles().size());\n"
        "    }\n"
        "    set_eax(c, rc);\n"
        "}\n",
        "[reflex-sync] WaitForSingleObject enter",
    )

    replace_once(
        kernel32,
        "void k_CloseHandle(X86 *c) {\n"
        "    uint32_t h = arg(c, 0);\n"
        "    HObj *o = handle_any(h);\n"
        "    if (!o) {\n"
        "        set_last_error(ERROR_INVALID_HANDLE_);\n"
        "        set_eax(c, 0);\n"
        "        return;\n"
        "    }\n",
        "void k_CloseHandle(X86 *c) {\n"
        "    uint32_t h = arg(c, 0);\n"
        "    HObj *o = handle_any(h);\n"
        "    const uint32_t reflex_h = gm_valid(0x00d67ce8u, 4) ? rd32(0x00d67ce8u) : 0u;\n"
        "    if (h == reflex_h || (o && (o->object_name == \"FMODQueueProcessEvent\" || o->object_name == \"DatabaseThreadEvent\" || o->object_name == \"LoadingThreadEvent\" || o->object_name == \"CacheThreadEvent\")))\n"
        "        fprintf(stderr, \"[reflex-sync] CloseHandle handle=%08x guest_global=%08x valid=%u kind=%d refs=%u handles=%zu\\n\",\n"
        "                h, reflex_h, o ? 1u : 0u, o ? (int)o->kind : -1, o ? o->references : 0u, handles().size());\n"
        "    if (!o) {\n"
        "        set_last_error(ERROR_INVALID_HANDLE_);\n"
        "        set_eax(c, 0);\n"
        "        return;\n"
        "    }\n",
        "[reflex-sync] CloseHandle",
    )

    print("Applied Reflex runtime import/ABI compatibility patch")


if __name__ == "__main__":
    main()
