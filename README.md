# MX vs. ATV Reflex — Native iOS Recompilation

**The original Reflex. A new platform.**

[![Project status](https://img.shields.io/badge/status-active%20development-2563eb)](https://github.com/NyerahMT/ReflexRecomp/commits/main)
[![Target](https://img.shields.io/badge/target-iOS%20%2F%20iPadOS-111827)](https://github.com/NyerahMT/ReflexRecomp)
[![Architecture](https://img.shields.io/badge/architecture-ARM64-475569)](https://github.com/NyerahMT/ReflexRecomp)

**ReflexRecomp** is an experimental effort to bring the **Windows PC version of MX vs. ATV Reflex** to iPhone and iPad by statically recompiling its original 32-bit x86 game code into a native ARM64 application.

Not a remake. Not a mobile lookalike. The goal is to preserve the actual game—including the handling and systems that make Reflex feel like Reflex—while replacing the Windows-specific plumbing it depends on.

> **Current status:** Under active development. The native startup/runtime and original-asset loading path are being brought up, but **there is no publicly playable iOS build yet**.

## Why Reflex?

Reflex is more than another motocross game. Its rider-and-bike control, distinctive physics, terrain deformation, and sense of speed are exactly the things a faithful port should keep.

The aim is simple: **get the original experience running on modern Apple hardware without rewriting the game into something else.**

### What this project is aiming for

- **Authentic gameplay:** Keep the game's original translated code, behavior, and feel wherever possible.
- **Native Apple hardware support:** Compile ahead of time for ARM64 rather than relying on an x86 interpreter or just-in-time compiler.
- **No jailbreak required:** Work within the constraints of ordinary iOS and iPadOS devices.
- **A proper platform bridge:** Replace Windows API, graphics, audio, input, and filesystem dependencies with compatible native implementations.
- **Faithful presentation:** Bring the original assets, interface, and rendering behavior forward—not redesign Reflex as a mobile game.

These are **project goals**, not a list of features already working on-device.

## How it works

The project takes the original Windows executable through a static recompilation pipeline, then supplies native equivalents for the operating-system services the game expects.

```text
Original Windows game (32-bit x86)
             |
      Ghidra analysis
             |
   recomp-kit translation
       (x86 -> C)
             |
    Native ARM64 compile
             |
   Compatibility runtime
    |          |         |
  Win32      Audio     D3D9 -> Metal
             |
       iOS / iPadOS
```

**Why static recompilation?** Instead of decoding x86 instructions while the game runs, translation happens ahead of time. That gives the project a route toward native execution on Apple silicon without requiring JIT, while retaining the original gameplay logic. It also makes compatibility work exceptionally detailed: calling conventions, memory behavior, DLL imports, and graphics semantics all have to be handled correctly.

## Where things stand

The project has progressed beyond a proof-of-concept pipeline into **original-game startup bring-up**:

- Original x86 code is being translated and integrated with a native runtime.
- Windows and C runtime compatibility work covers startup behavior, calling conventions, string/math functions, and other game imports.
- Graphics and audio compatibility are being built out, including Direct3D-era helpers and FMOD interfaces.
- Original UI, engine-dependency, and other resource packages are being identified and staged for startup.
- Automated checks and build workflows are used to catch regressions as the port advances.

**The next big visible milestone is a reliably loaded, usable main menu.** After that come rendering correctness, input and audio integration, gameplay loading, and hands-on device testing. A successful compile or headless startup test is **not** the same thing as a playable port.

### Milestones

| Milestone | Status |
| --- | --- |
| Establish executable analysis and recompilation workflow | In place |
| Build and test native compatibility infrastructure | In progress |
| Resolve original game startup and resource loading | In progress |
| Reach a usable, correctly rendered main menu | Next major goal |
| Load and control gameplay on-device | Not yet verified |
| Release a playable iOS build | Not available |

For current activity, see the [commit history](https://github.com/NyerahMT/ReflexRecomp/commits/main) and [GitHub Actions](https://github.com/NyerahMT/ReflexRecomp/actions). These are a better source for day-to-day changes than a running development log in this README.

## Can I play it?

**Not yet.** This repository is an engineering project, not a downloadable Reflex IPA. It does not currently provide a ready-to-install version of the game.

When there is a meaningful on-device build to test, that milestone will be made clear here. Until then, the focus is getting the original game to initialize and operate correctly.

## Repository and game files

This public repository contains the work needed to analyze, translate, build, and test the port's code and compatibility layer. **It does not distribute the retail game, its executable, DLLs, or copyrighted assets.**

Developer-owned game inputs are kept separately and supplied privately to the relevant build workflows. Public automation and source code can be inspected without shipping the original game's content.

<details>
<summary><strong>Technical reference: source executable and toolchain</strong></summary>

The pipeline is built around a specific Windows executable so that analysis and translation remain reproducible.

```text
Executable:  MXReflex.exe
SHA-256:     917d14e7ef7ce492b665fea7d0c87c9a39b549e2a43b09883d2a786988e7c02c
Image base:  0x00400000
Entry point: 0x009006a7
```

The original scaffold pins `recomp-kit` at commit `eb32cc42623e0e9e868b9d27423a57d5a5cba56b` for reproducible translation. Check the current workflows for the authoritative build configuration.

</details>

## About this project

ReflexRecomp is an **unofficial fan-led technical project**. It is not affiliated with, endorsed by, or sponsored by the rights holders of *MX vs. ATV Reflex*. All game names, trademarks, and original game content belong to their respective owners.

**The destination is Reflex running on iPhone and iPad. The point is getting there without losing what made Reflex special.**
