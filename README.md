# RenderDoc APK Mirror

This repository mirrors the Android capture/replay APKs bundled inside official RenderDoc stable Windows x64 ZIP builds.

Only RenderDoc `v1.35` and newer stable versions are mirrored.

## Manifest

The frontend-facing manifest is:

```text
https://raw.githubusercontent.com/Axonsin/renderdoc-apk-mirror/main/renderdoc-apks.json
```

Each version is also published as a GitHub Release using tags like `renderdoc-v1.44`.

Each release contains exactly two APK assets:

```text
org.renderdoc.renderdoccmd.arm32.apk
org.renderdoc.renderdoccmd.arm64.apk
```

## Sync

The weekly GitHub Action runs:

```bash
python scripts/sync_renderdoc_apks.py
```

The script parses `https://renderdoc.org/builds?showall=1`, compares the stable versions against `renderdoc-apks.json`, and only downloads versions that are not already present in the manifest.

Useful local checks:

```bash
python scripts/sync_renderdoc_apks.py --dry-run
python scripts/sync_renderdoc_apks.py --extract-version 1.44
```

## Source

RenderDoc is created by Baldur Karlsson and distributed from:

- https://renderdoc.org/
- https://github.com/baldurk/renderdoc

This repository is an unofficial mirror of APK files extracted from official RenderDoc binary packages.

