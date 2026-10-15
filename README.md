# ReflexRecomp

An experimental iOS port of **MX vs. ATV Reflex** (the original Windows PC version), using static x86 recompilation.

Reflex is a 32-bit Windows game. This project translates its original x86 code into C ahead of time, compiles it for ARM64, and implements the Windows functionality the game expects. The idea is to run the actual game on iPhone and iPad, not recreate it in another engine or stream it from a PC.

The long-term target is a native iOS build that doesn't need a jailbreak, an x86 emulator, or JIT compilation.

## Status

**Work in progress. Not playable yet.**

The recompilation pipeline and native runtime are far enough along to execute original game code in automated startup tests. The current work is mostly about getting through initialization: Windows/CRT behavior, x86 calling conventions, original resource loading, audio interfaces, and Direct3D 9 compatibility.

The game **does not have a verified working main menu yet**, and there's no public IPA to install. Getting to a properly loaded menu is the next major milestone. Gameplay and on-device testing come after that.

### Progress

- [x] Identify and verify the target PC executable
- [x] Set up the Ghidra / `recomp-kit` translation pipeline
- [x] Execute translated original code with a native test runtime
- [ ] Finish startup and original asset loading
- [ ] Get the main menu loading and rendering correctly
- [ ] Bring up gameplay, controls, sound, and graphics on iOS
- [ ] Produce a playable device build

This is a rough milestone list, not a percentage-complete estimate. A successful CI build doesn't necessarily mean the game boots.

## How it works

```text
MXReflex.exe (32-bit Windows)
            |
     Ghidra analysis
            |
    recomp-kit (x86 -> C)
            |
      Native ARM64 build
            |
    Compatibility runtime
    - Win32 / MSVCR
    - Direct3D 9 -> Metal
    - FMOD / audio
    - Filesystem / input
            |
        iOS / iPadOS
```

Static recompilation avoids having to interpret x86 instructions on the phone. It doesn't automatically solve the rest of the port, though: the translated code still expects the original Windows APIs, x86 ABI details, Direct3D behavior, and game data. Most of the work is making those assumptions hold on another platform.

The goal is to leave the original gameplay code intact wherever possible, including Reflex's bike/rider handling and terrain systems.

## Input target: physical controller

The iOS version is being designed for a **connected game controller**, not an
on-screen virtual gamepad. Xbox and PlayStation controllers are the initial
targets through Apple's Game Controller support (or the SDL gamepad backend
where appropriate). Reflex's separate bike steering and rider body control
should remain independent on two analog sticks, with analog triggers retained.

Controller handling is a **future gameplay milestone**, not an implemented
feature yet. We do not plan virtual thumbsticks or touchscreen throttle and
brake overlays; a supported connected controller will be required for play.

## Building / testing

There's no end-user build process or release package yet. The CI workflows are primarily for translation, compilation, runtime tests, and startup diagnostics.

- [Actions](https://github.com/NyerahMT/ReflexRecomp/actions) — builds and test results
- [Commits](https://github.com/NyerahMT/ReflexRecomp/commits/main) — recent changes

The public repository does **not** contain the game executable, DLLs, or assets. The build input is kept separately and supplied to CI privately; you'll need legitimate game files to reproduce game-dependent work.

The current target executable is:

```text
File:       MXReflex.exe
SHA-256:    917d14e7ef7ce492b665fea7d0c87c9a39b549e2a43b09883d2a786988e7c02c
Image base: 0x00400000
Entry:      0x009006a7
```

The project uses `recomp-kit` for x86-to-C translation. Refer to the workflows for the currently pinned toolchain and build configuration.

## Scope

The priority is getting the PC game running correctly before adding anything new. That means startup, menus, track loading, rendering, input, sound, and actual gameplay in roughly that order.

Mobile-specific UI changes and other enhancements can wait until there's a game worth testing.

## Disclaimer

This is an unofficial project and is not affiliated with the developers or publishers of *MX vs. ATV Reflex*. No copyrighted game binaries or assets are distributed here.
