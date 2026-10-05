# ReflexRecomp

Experimental static recompilation target for the Windows PC version of **MX vs. ATV Reflex**.

Goal: translate the original 32-bit x86 game code ahead of time and compile it as a native ARM64 iOS application using `recomp-kit`, with **no JIT and no jailbreak**. Gameplay systems remain translated original code; platform/API compatibility is implemented around them.

## Target executable

```text
MXReflex.exe
SHA-256: 917d14e7ef7ce492b665fea7d0c87c9a39b549e2a43b09883d2a786988e7c02c
Image base: 0x00400000
Entry point: 0x009006a7
```

The retail game executable, DLLs and assets are not tracked in this public repository. CI obtains the developer's build input from a separate private repository.

## Current pipeline

```text
MXReflex.exe (x86)
  -> Ghidra function recovery
  -> recomp-kit static x86 -> C translation
  -> native compiler
  -> Win32 / D3D9 compatibility runtime
  -> Metal
  -> ARM64 iOS app
```

`recomp-kit` is pinned by CI to commit `eb32cc42623e0e9e868b9d27423a57d5a5cba56b` while the Reflex bring-up is stabilized.

## CI

`Checks` exercises the public scaffold without any game files.

`Analyze + Translate Reflex` is manually triggered. It reads `NyerahMT/ReflexBuildInput` using the repository secret `REFLEX_INPUT_TOKEN`, verifies the executable hash, downloads the pinned Ghidra release, performs headless analysis, and attempts the first static translation.

Generated game-code listings and translations are intentionally not committed to this repository.
