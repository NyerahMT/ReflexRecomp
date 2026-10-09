# ReflexRecomp compatibility audit — 2026-10-08

## Scope and limits

Reviewed the clean-room runtime compatibility C++, Windows CRT/ABI, MSVCP90 strings, D3DX, FMOD, generated-code patch scripts, GitHub build gates, and UI startup traces. The original game binary and private assembly are not committed here.

A successful 30-second headless Linux gate does **not** prove a rendered menu or playable iOS build. The repeated unresolved Intro/Intro. resource lookups remain an active frontier.

## High-confidence bugs corrected in this audit

| Area | Issue | Correction |
| --- | --- | --- |
| CRT integer conversions | The host's 64-bit long width gives incorrect Win32 negative overflow and some unsigned negative values | Extract 32-bit signed/unsigned parsing with explicit saturation, unsigned wraparound and ERANGE, backed by native C++ tests |
| MSVCP90 string copy | Copying overlapping inline storage could be overwritten by zeroing the destination too early | Snapshot small-string bytes before clearing; allocate large destination before modifying object |
| MSVCP90 C-string construction | A failed large allocation could leave the destination cleared | Allocate first, mutate only after success |
| Translation coverage | Four exact-address SSE fixes did not reveal the total unsupported opcode inventory | Inventory all remaining generated recomp_unmodelled sites, join with recovered mnemonics and upload the report in private CI |
| Build dependencies | The new numeric helper header needs to be in the pinned runtime directory | Copy it alongside the compatibility source during kit patching |

Native unit tests cover the numeric helper, actual copied MSVCP90 string-constructor implementation, and the unsupported-opcode scanner. Full workflow results must be checked before calling the latest commits validated.

## Menu startup evidence — 2026-10-08

The first family-wide SIMD pass reduced translation traps from 38,368 to
7,605 (about 80%). The native Linux application built, but its runtime gate
still failed while querying the private MXUI database repeatedly for `Intro`
and `Intro.`, although localization keys such as `Intro.ENG` appear in the
loaded database.

**Important disassembly correction:** offsets `0x62b3c`, `0x62b54`, and
`0x62b6c` in the resource manager are 24-byte synchronization objects,
not MSVC string objects. The constructor initializes them as three separate
24-byte structures, and the resource lookup passes `this + 0x62b54` to
an imported synchronization call. Do not overwrite these objects with a
language string. The temporary `suffix_dword` trace only probes lock memory
and should not be interpreted as a language-code value.

Next investigation: inspect the `language.txt` reader near `0x008814a0`
and the actual resource-key assembly path near `0x0084a7f0`/`0x0084a890`.
Confirm the producer of `Intro.` and the string/locale passed to the lookup
before changing runtime lookup semantics. The code that retries the lookup is
not itself evidence of a defective retry mechanism.

## Unresolved priorities

| Priority | Area | Evidence / next validation |
| --- | --- | --- |
| P0 | Menu initialization | Headless boot repeatedly seeks Intro and Intro.; trace guest virtual dispatch and resource key creation rather than assuming 30-second survival is a boot |
| P0 | iOS ARM64 | Current fast gate runs on Linux; verify native rendering, touch/controller input, app lifecycle and frame output on an iOS device |
| P1 | Direct3D | D3DX constant-table setter methods intentionally return D3DERR_INVALIDCALL; device/shader constant forwarding must be implemented and tested |
| P1 | FMOD | Some event/channel shims are initialization-only; a functional audio backend is still missing |
| P1 | Exceptions / RTTI | Partial setjmp3, C++ reference bad_cast, and x86 unwind semantics need guest-call validation |
| P1 | Opcode coverage | Use CI inventory to fix entire SSE/mnemonic families, with numerical lane-level tests, rather than individual addresses |
| P2 | Win32 paths | A case-sensitive host filesystem is not equivalent to Windows resource lookup; add guarded case-insensitive resolution if mismatches are confirmed |
| P2 | Concurrency | Validate global file/COM/string caches and shutdown under actual guest multithreading |

## Test gates

1. Native Linux and macOS tests exercise width semantics, string lifetime and code-generation scripts.
2. Full private cached translation compiles into a native host executable.
3. The headless runtime probe checks for ABI faults, and flags known live-but-stalled lookups; it archives bounded logs and remaining unsupported opcodes.
4. Rendering readiness requires first-frame and menu navigation tests beyond a 30-second process survival gate.
5. The iOS port still needs physical-device ARM64 validation, touch/gamepad controls and performance measurements.

Risks are tracked separately from confirmed defects. Static inspection cannot replace actual runtime execution.
