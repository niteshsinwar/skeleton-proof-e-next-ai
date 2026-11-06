#!/usr/bin/env python3
"""Install the pinned tool binaries from ops/tools.toml into .tools/bin, each checked against its sha256 (13/V3).

  python3 -I scripts/tools.py            # install what is missing or at the wrong version
  python3 -I scripts/tools.py --check    # exit 1 unless every pinned binary is installed at its version

A download whose checksum differs, a platform with no checksum, or an unknown platform stops the install: a tool
that can't be verified is never run (README #6). Python tools (zizmor, semgrep) run through `uvx` instead.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ops" / "tools.toml"
BIN = ROOT / ".tools" / "bin"


def current_platform() -> str:
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(machine, machine)
    return f"{system}-{arch}"


def load() -> dict[str, dict]:
    with MANIFEST.open("rb") as f:
        return tomllib.load(f)


def stamp(name: str) -> Path:
    return BIN / f".{name}.version"


def extract(name: str, data: bytes, url: str) -> bytes:
    """The tool's executable from a tarball, a zip or a bare binary."""
    if url.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            member = next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name == name)
            handle = tar.extractfile(member)
            assert handle is not None
            return handle.read()
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            member = next(n for n in archive.namelist() if Path(n).name == name)
            return archive.read(member)
    return data


def install(name: str, spec: dict, plat: str) -> str:
    if plat not in spec.get("platforms", {}):
        raise SystemExit(f"tools: {name} has no build listed for {plat} in ops/tools.toml")
    expected = spec.get("sha256", {}).get(plat)
    if not expected:
        raise SystemExit(f"tools: {name} has no sha256 for {plat}; an unverifiable download is never run")
    url = spec["url"].format(version=spec["version"], platform=spec["platforms"][plat])
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310  (a pinned https URL)
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"tools: {name} {spec['version']} checksum mismatch: expected {expected}, got {actual}")
    target = BIN / name
    target.write_bytes(extract(name, data, url))
    target.chmod(0o755)
    stamp(name).write_text(spec["version"], encoding="utf-8")
    return f"installed {name} {spec['version']} (sha256 verified)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only report; exit 1 if anything is missing or stale")
    args = parser.parse_args()
    manifest, plat = load(), current_platform()
    BIN.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, spec in sorted(manifest.get("binary", {}).items()):
        have = stamp(name).read_text(encoding="utf-8").strip() if stamp(name).exists() else None
        if have == spec["version"] and (BIN / name).exists():
            continue
        if args.check:
            stale.append(f"{name} {spec['version']} (have {have or 'nothing'})")
            continue
        print(f"tools: {install(name, spec, plat)}")
    for line in stale:
        print(f"tools: not installed: {line}; run `make tools`")
    print(f"tools: {len(manifest.get('binary', {}))} pinned binaries for {plat}; {len(stale)} missing or stale")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
