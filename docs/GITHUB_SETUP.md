# GitHub-only bring-up

The project is designed to be developed entirely through GitHub Actions.

## One-time setup

1. In the private `NyerahMT/ReflexBuildInput` repository, create `game/` and upload the pinned `MXReflex.exe` there. The expected path is:

   `game/MXReflex.exe`

2. Create a fine-grained GitHub personal access token restricted to **only** `NyerahMT/ReflexBuildInput` with repository permission **Contents: Read-only**.

3. In the public `NyerahMT/ReflexRecomp` repository, open:

   `Settings -> Secrets and variables -> Actions -> New repository secret`

   Create a secret named exactly:

   `REFLEX_INPUT_TOKEN`

   Paste the fine-grained token as its value. Never commit the token or put it in workflow YAML.

## First real run

Open `Actions -> Analyze + Translate Reflex -> Run workflow`.

The workflow will:

1. check out this public repository;
2. privately check out `ReflexBuildInput`;
3. verify `MXReflex.exe` against SHA-256 `917d14e7ef7ce492b665fea7d0c87c9a39b549e2a43b09883d2a786988e7c02c`;
4. fetch the pinned `recomp-kit` revision;
5. download and SHA-256 verify Ghidra 12.1.3;
6. perform Ghidra default analysis and export the function listing;
7. run the first static translation/generator build;
8. upload only bring-up logs and small metadata artifacts.

The private executable and original game files are never uploaded as workflow artifacts.

## What failure means

A failure before Ghidra indicates infrastructure/input configuration.

A failure during Ghidra indicates analysis/export trouble.

A failure during `Attempt first static translation` is expected during early bring-up and is useful: `translate.log` becomes the next concrete compatibility work queue.
