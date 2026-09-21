#!/usr/bin/env python3
"""Inspect user-local assets. Raw archive records are NOT inference-ready weights.

Archive framing and the structural index come from lmxxf (MIT); see
LICENSE.upstream and WEIGHTS.md. Nothing here executes or downloads a DLL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import tempfile

HERE = Path(__file__).resolve().parent
RECORDS = json.loads((HERE / "weight-records.json").read_text())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_archive(data: bytes) -> list[dict]:
    """Bounds-checked version of upstream parse_archive, retaining mixed storage."""
    def read(fmt, offset, limit):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > limit:
            raise ValueError("Truncated archive field")
        return struct.unpack_from(fmt, data, offset)

    if read("<Q", 0, len(data))[0] != len(data):
        raise ValueError("Archive length mismatch")
    result, names, cursor = [], set(), 8
    while cursor < len(data):
        n = read("<Q", cursor, len(data))[0]
        cursor += 8
        if not 1 <= n <= 4096 or cursor + n > len(data):
            raise ValueError("Invalid record name length")
        try:
            name = data[cursor:cursor + n].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid record name encoding") from error
        if not re.fullmatch(r"block\d+\.layer\d+\.(?:layer|blend_scale)", name) or name in names:
            raise ValueError("Invalid/duplicate record name")
        names.add(name)
        cursor += n
        span = read("<Q", cursor, len(data))[0]
        body = cursor + 8
        end = body + span
        if span < 40 or end > len(data):
            raise ValueError("Record outside archive")
        inner, size, dtype = read("<QQI", body, end)
        if inner != span or size + 40 != span:
            raise ValueError("Record payload/trailer framing mismatch")
        trailer = read("<5I", body + 20 + size, end)
        if size != trailer[4] * 2:
            raise ValueError("Serialized element count mismatch")
        # The container's two-byte slots can include packed FP8 and FP32.
        # Do not reinterpret the entire payload as FP16.
        result.append({"name": name, "payload_offset": body + 20,
                       "payload_size": size, "dtype_code": dtype,
                       "element_count": trailer[4]})
        cursor = end
    if not result:
        raise ValueError("Empty archive")
    return result


def extract_raw(dll: Path, output: Path) -> dict:
    """Export exact records of the pinned DLL to a new local directory only."""
    if output.exists():
        raise ValueError("Choose a new output directory; existing files are never replaced")
    if sha256(dll) != RECORDS["dll_sha256"]:
        raise ValueError("DLL differs from the verified 310.8.0.0 source; no fixed offsets used")
    with dll.open("rb") as stream:
        stream.seek(RECORDS["archive_offset"])
        data = stream.read(RECORDS["archive_size"])
    records = parse_archive(data)
    if records != RECORDS["records"]:
        raise ValueError("Archive index differs from the pinned source")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".raw-weights-", dir=output.parent))
    try:
        manifest = {"format": "lmxxf-raw-records-v1", "ready_for_inference": False,
                    "upstream_commit": RECORDS["upstream_commit"], "files": {}}
        for record in records:
            start, size = record["payload_offset"], record["payload_size"]
            payload = data[start:start + size]
            name = record["name"] + ".weights"
            (staging / name).write_bytes(payload)
            manifest["files"][name] = {"bytes": size,
                                       "sha256": hashlib.sha256(payload).hexdigest()}
        (staging / "raw-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # mkdir is exclusive even if another process created output during hashing.
        output.mkdir()
        try:
            for path in staging.iterdir():
                path.replace(output / path.name)
        except BaseException:
            shutil.rmtree(output)
            raise
        return {"records": len(records), "bytes": sum(r["payload_size"] for r in records),
                "ready_for_inference": False}
    finally:
        shutil.rmtree(staging)


def required_assets() -> dict[str, int]:
    """Float counts from the pinned Network::WeightElements + RunGraph contract."""
    result = {}
    for block in range(70):
        if block == 39:
            result["decoder39-weights"] = 524800
            continue
        if 31 <= block <= 38:
            for kind, count in (("expand", 4194304), ("contract", 4195328),
                                ("qkv", 3145760), ("projection", 1049600)):
                result[f"block{block}-{kind}"] = count
            continue
        c = (32 if block <= 4 else 64 if block <= 8 else 128 if block <= 14
             else 256 if block <= 22 else 512 if block <= 47 else 256 if block <= 55
             else 128 if block <= 61 else 64 if block <= 65 else 32)
        if c == 512:
            result[f"block{block}-ffwd"] = 524288
            result[f"block{block}-ffwd-projection"] = 262656
        else:
            result[f"block{block}-ffn"] = 8736 if c == 32 else 9 * c * c + c
        result[f"block{block}-attention"] = 8225 if c == 32 else 4*c*c + (c//32)*4096 + c//32 + c
        if block in (4, 8, 14, 22):
            result[f"block{block}-ds"] = 2*c*c
        if block in (48, 56, 62, 66):
            result[f"block{block}-weights"] = 2*c*c + c
    result.update({"head-matrix": 524288, "post70-scales": 64,
                   "post70-head": 96, "post70-ffn": 8736, "post70-attention": 8225})
    return result


def inspect_assets(folder: Path, *, contract=None) -> dict:
    """Collect ALL missing/corrupt files before GPU initialization; stdlib only."""
    contract = required_assets() if contract is None else contract
    errors, files = [], {}
    for stem, count in contract.items():
        full, half = folder / (stem + ".f32"), folder / (stem + ".f16")
        candidates = [p for p in (full, half) if p.exists() or p.is_symlink()]
        if len(candidates) != 1:
            errors.append(stem + (": missing .f32/.f16" if not candidates else ": ambiguous .f32 AND .f16"))
            continue
        p = candidates[0]
        if p.is_symlink() or not p.is_file():
            errors.append(p.name + ": expected a regular local file")
            continue
        size = 4 if p.suffix == ".f32" else 2
        if p.stat().st_size != count * size:
            errors.append(p.name + f": expected {count * size} bytes")
            continue
        h, finite, seen = hashlib.sha256(), True, 0
        try:
            with p.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    h.update(chunk)
                    seen += len(chunk)
                    if len(chunk) % size or not all(math.isfinite(x[0]) for x in struct.iter_unpack("<f" if size == 4 else "<e", chunk)):
                        finite = False
            if not finite or seen != count * size:
                errors.append(p.name + ": nonfinite, unaligned, or changed while reading")
                continue
            files[p.name] = {"bytes": seen, "sha256": h.hexdigest()}
        except OSError:
            errors.append(p.name + ": could not read")
    return {"format": "lmxxf-prepared-assets-check-v1", "expected_files": len(contract),
            "valid_files": len(files), "errors": errors, "files": files,
            "structurally_ready": not errors, "weight_layout_parity_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    raw = sub.add_parser("extract-raw", help="Extract records only; no layout conversion or inference")
    raw.add_argument("dll", type=Path)
    raw.add_argument("output", type=Path)
    check = sub.add_parser("check", help="Check already prepared upstream .f32/.f16 files")
    check.add_argument("assets", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "extract-raw":
            print(json.dumps(extract_raw(args.dll, args.output), indent=2))
            print("Raw records extracted. Conversion is blocked on the layout data documented in WEIGHTS.md.")
            return 0
        result = inspect_assets(args.assets)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
        return 0 if result["structurally_ready"] else 2
    except (OSError, ValueError) as error:
        print(f"Asset preparation stopped: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
