#!/usr/bin/env python3
"""
Copy the game-derived test data listed in data_manifest.json into place.

The files are never committed. Extract them from your own game install first
(see DATA.md), then:

    python3 fetch_data.py --from /path/to/extracted/chr     # copy + verify
    python3 fetch_data.py --from /path/to/extracted/chr --dry-run
    python3 fetch_data.py --check                           # verify what is in place

Every file is checked against the manifest's size and SHA-256; a mismatch is an
error and nothing is written for that file.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "data_manifest.json"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def hexdump(data):
    """Offset, 16 space-separated hex bytes, then the printable-ASCII column."""
    lines = []
    for off in range(0, len(data), 16):
        row = data[off:off + 16]
        hexes = " ".join(f"{b:02x}" for b in row).ljust(47)
        text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in row)
        lines.append(f"{off:08x}  {hexes}   |{text}|\n")
    return "".join(lines).encode("ascii")


def verify(name, data, spec):
    if len(data) != spec["size"] or sha256(data) != spec["sha256"]:
        hint = ""
        if data[:4] == b"DCX\0":
            hint = " (still DCX-compressed; decompress it first, see DATA.md)"
        raise ValueError(f"{name}: size {len(data)} / sha256 {sha256(data)[:12]}… "
                         f"does not match the manifest{hint}")


def find_source(src_dir, spec):
    for candidate in spec["accepted_names"]:
        path = src_dir / candidate
        if path.is_file():
            return path
    raise FileNotFoundError(f"none of {spec['accepted_names']} found in {src_dir}")


def build_derived(spec, contents):
    if spec["kind"] != "hexdump":
        raise ValueError(f"unknown derived kind {spec['kind']!r}")
    return hexdump(contents[spec["from"]][:spec["length"]])


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--from", dest="src", type=Path,
                    help="directory holding the extracted, decompressed binders")
    ap.add_argument("--dry-run", action="store_true",
                    help="verify the sources but write nothing")
    ap.add_argument("--check", action="store_true",
                    help="only verify the files already in place")
    args = ap.parse_args()
    if not args.check and args.src is None:
        ap.error("--from is required unless --check is given")

    manifest = json.loads(MANIFEST.read_text())
    contents, failures = {}, []

    for spec in manifest["files"]:
        dest = ROOT / spec["dest"]
        try:
            path = dest if args.check else find_source(args.src, spec)
            data = path.read_bytes()
            verify(spec["dest"], data, spec)
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
            continue
        contents[spec["dest"]] = data
        if not (args.check or args.dry_run):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        print(f"ok  {spec['dest']}")

    for spec in manifest["derived"]:
        if spec["from"] not in contents:
            failures.append(f"{spec['dest']}: needs {spec['from']}")
            continue
        try:
            data = build_derived(spec, contents)
            verify(spec["dest"], data, spec)
            if args.check:
                verify(spec["dest"], (ROOT / spec["dest"]).read_bytes(), spec)
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
            continue
        if not (args.check or args.dry_run):
            (ROOT / spec["dest"]).write_bytes(data)
        print(f"ok  {spec['dest']}")

    for msg in failures:
        print(f"FAIL {msg}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
