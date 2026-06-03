#!/usr/bin/env python3
"""Mirror RenderDoc Android APKs from official stable ZIP builds to GitHub Releases."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import urllib.parse
import urllib.request
import zipfile


BUILDS_URL = "https://renderdoc.org/builds?showall=1"
DEFAULT_MIN_VERSION = "1.35"
DEFAULT_REPO = "Axonsin/renderdoc-apk-mirror"
APK_NAMES = {
    "arm32": "org.renderdoc.renderdoccmd.arm32.apk",
    "arm64": "org.renderdoc.renderdoccmd.arm64.apk",
}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def compare_versions(left: str, right: str) -> int:
    left_parts = list(version_key(left))
    right_parts = list(version_key(right))
    length = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (length - len(left_parts)))
    right_parts.extend([0] * (length - len(right_parts)))
    return (left_parts > right_parts) - (left_parts < right_parts)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "renderdoc-apk-mirror/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def download_file(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "renderdoc-apk-mirror/1.0"})
    with urllib.request.urlopen(req, timeout=300) as response:
        with target.open("wb") as out:
            shutil.copyfileobj(response, out)


def parse_stable_builds(page_html: str, minimum_version: str) -> list[dict[str, str]]:
    stable_match = re.search(r'<h2 id="stable">.*?<tbody>(.*?)</tbody>', page_html, re.S | re.I)
    if not stable_match:
        raise RuntimeError("Could not find stable builds table in RenderDoc builds page")

    stable_html = stable_match.group(1)
    builds: dict[str, dict[str, str]] = {}

    for row_match in re.finditer(r"<tr>(.*?)</tr>", stable_html, re.S | re.I):
        row = row_match.group(1)
        version_match = re.search(r"RenderDoc\s+v([0-9]+(?:\.[0-9]+)*)", row)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", row)
        href_match = re.search(r'href="([^"]*RenderDoc_[^"]*_64\.zip)"', row)
        if not (version_match and date_match and href_match):
            continue

        version = version_match.group(1)
        if compare_versions(version, minimum_version) < 0:
            continue

        href = html.unescape(href_match.group(1))
        source_zip = urllib.parse.urljoin("https://renderdoc.org", href)
        builds[version] = {
            "version": version,
            "date": date_match.group(1),
            "sourceZip": source_zip,
        }

    return sorted(builds.values(), key=lambda item: version_key(item["version"]), reverse=True)


def read_manifest(path: Path, minimum_version: str) -> dict[str, Any]:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {}

    manifest.setdefault("schemaVersion", 1)
    manifest["minimumVersion"] = minimum_version
    manifest.setdefault("latest", None)
    manifest.setdefault("lastCheckedAt", None)
    manifest.setdefault("versions", [])
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_apks(zip_path: Path, output_dir: Path) -> dict[str, Path]:
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        for abi, apk_name in APK_NAMES.items():
            matches = [member for member in members if member.endswith("/plugins/android/" + apk_name)]
            if not matches:
                matches = [member for member in members if member.endswith(apk_name)]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one {apk_name} in {zip_path.name}, found {len(matches)}")

            target = output_dir / apk_name
            with zf.open(matches[0]) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted[abi] = target

    return extracted


def run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], check=check, text=True, capture_output=True)


def release_exists(repo: str, tag: str) -> bool:
    result = run_gh(["release", "view", tag, "--repo", repo], check=False)
    return result.returncode == 0


def publish_release(repo: str, build: dict[str, str], apk_paths: dict[str, Path]) -> str:
    version = build["version"]
    tag = f"renderdoc-v{version}"
    release_url = f"https://github.com/{repo}/releases/tag/{tag}"
    assets = [str(apk_paths["arm32"]), str(apk_paths["arm64"])]
    notes = (
        f"RenderDoc v{version} Android APKs extracted from the official stable Windows x64 ZIP.\n\n"
        f"Source ZIP: {build['sourceZip']}\n"
    )

    if release_exists(repo, tag):
        run_gh(["release", "upload", tag, *assets, "--repo", repo, "--clobber"])
    else:
        run_gh(
            [
                "release",
                "create",
                tag,
                *assets,
                "--repo",
                repo,
                "--title",
                f"RenderDoc v{version} Android APKs",
                "--notes",
                notes,
            ]
        )

    return release_url


def mark_latest_release(repo: str, version: str) -> None:
    tag = f"renderdoc-v{version}"
    run_gh(["release", "edit", tag, "--repo", repo, "--latest"])


def build_manifest_entry(repo: str, build: dict[str, str], apk_paths: dict[str, Path]) -> dict[str, Any]:
    version = build["version"]
    tag = f"renderdoc-v{version}"
    entry = {
        "version": version,
        "date": build["date"],
        "tag": tag,
        "sourceZip": build["sourceZip"],
        "releaseUrl": f"https://github.com/{repo}/releases/tag/{tag}",
        "files": {},
    }

    for abi, path in apk_paths.items():
        name = path.name
        entry["files"][abi] = {
            "name": name,
            "downloadUrl": f"https://github.com/{repo}/releases/download/{tag}/{name}",
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }

    return entry


def download_and_extract_build(build: dict[str, str], temp_dir: Path) -> dict[str, Path]:
    zip_path = temp_dir / f"RenderDoc_{build['version']}_64.zip"
    apk_dir = temp_dir / "apks"
    apk_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading RenderDoc v{build['version']} from {build['sourceZip']}", flush=True)
    download_file(build["sourceZip"], zip_path)
    return extract_apks(zip_path, apk_dir)


def print_extract_check(build: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        apk_paths = download_and_extract_build(build, Path(tmp))
        result = {
            "version": build["version"],
            "date": build["date"],
            "sourceZip": build["sourceZip"],
            "files": {
                abi: {
                    "name": path.name,
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
                for abi, path in apk_paths.items()
            },
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))


def sync(args: argparse.Namespace) -> int:
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO
    manifest_path = Path(args.manifest)

    builds = parse_stable_builds(fetch_text(BUILDS_URL), args.min_version)
    if not builds:
        raise RuntimeError(f"No stable RenderDoc builds found at or above v{args.min_version}")

    if args.extract_version:
        matching_build = next((build for build in builds if build["version"] == args.extract_version), None)
        if not matching_build:
            raise RuntimeError(f"Could not find RenderDoc v{args.extract_version} in stable builds")
        print_extract_check(matching_build)
        return 0

    manifest = read_manifest(manifest_path, args.min_version)
    known_versions = {entry["version"] for entry in manifest["versions"]}
    new_builds = [build for build in builds if build["version"] not in known_versions]

    if args.limit is not None:
        new_builds = new_builds[: args.limit]

    print(f"Found {len(builds)} stable builds at or above v{args.min_version}")
    print(f"Manifest already contains {len(known_versions)} versions")
    print(f"New versions to sync: {', '.join('v' + build['version'] for build in new_builds) or 'none'}")

    if args.dry_run:
        return 0

    new_entries: list[dict[str, Any]] = []
    for build in sorted(new_builds, key=lambda item: version_key(item["version"])):
        with tempfile.TemporaryDirectory() as tmp:
            apk_paths = download_and_extract_build(build, Path(tmp))
            publish_release(repo, build, apk_paths)
            new_entries.append(build_manifest_entry(repo, build, apk_paths))

    if new_entries:
        mark_latest_release(repo, builds[0]["version"])

    manifest["latest"] = builds[0]["version"]
    manifest["lastCheckedAt"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest["versions"] = sorted(
        [*manifest["versions"], *new_entries],
        key=lambda item: version_key(item["version"]),
        reverse=True,
    )
    write_manifest(manifest_path, manifest)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mirror RenderDoc Android APKs to GitHub Releases.")
    parser.add_argument("--manifest", default="renderdoc-apks.json")
    parser.add_argument("--repo", default=None, help="GitHub repository in owner/name form.")
    parser.add_argument("--min-version", default=DEFAULT_MIN_VERSION)
    parser.add_argument("--dry-run", action="store_true", help="Parse and compare versions without downloading or publishing.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of new versions processed.")
    parser.add_argument("--extract-version", help="Download one version and print extracted APK metadata without publishing.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(sync(parse_args()))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
