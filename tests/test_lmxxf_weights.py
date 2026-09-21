"""Archive/layout boundaries and batch failure gates; no GPU success inferred."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "experiments/lmxxf"
sys.path.insert(0, str(LAB))
import weight_assets as weights
import run_network_test as runner


def archive(records):
    result = bytearray(b"\0" * 8)
    for name, payload in records:
        name = name.encode("ascii")
        span = len(payload) + 40
        result.extend(struct.pack("<Q", len(name)) + name + struct.pack("<Q", span))
        result.extend(struct.pack("<QQI", span, len(payload), 1))
        result.extend(payload)
        result.extend(struct.pack("<5I", 1, 1, 1, 1, len(payload) // 2))
    struct.pack_into("<Q", result, 0, len(result))
    return bytes(result)


class ArchiveBoundaries(unittest.TestCase):
    def test_valid_records_match_upstream_parser(self):
        source = Path(os.environ.get("LMXXF_SOURCE_DIR", ROOT / "build/lmxxf/upstream")) / "Development/parse_weights_archive.py"
        if not source.is_file():
            self.skipTest("Optional upstream archive parser fixture is absent")
        spec = importlib.util.spec_from_file_location("upstream_archive", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = archive([("block0.layer0.layer", bytes(range(32))), ("block70.layer0.blend_scale", b"\0\x3c")])
        ours = weights.parse_archive(data)
        theirs = [{k: r[k] for k in ours[0]} for r in module.parse_archive(data)]
        self.assertEqual(ours, theirs)

    def test_truncated_or_overlapping_records_rejected(self):
        valid = archive([("block0.layer0.layer", bytes(range(32)))])
        r = weights.parse_archive(valid)[0]
        corruptions = [valid[:i] for i in (0, 7, 8, 19, len(valid) - 1)]
        for offset, fmt, value in ((0, "<Q", len(valid) + 1), (8, "<Q", 5000),
                                   (r["payload_offset"] - 12, "<Q", 2**63),
                                   (len(valid) - 4, "<I", 999)):
            bad = bytearray(valid); struct.pack_into(fmt, bad, offset, value); corruptions.append(bad)
        corruptions.append(archive([("block0.layer0.layer", b"\0\0")] * 2))
        corruptions.append(archive([("../../escape", b"\0\0")]))
        for bad in corruptions:
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                weights.parse_archive(bad)

    def test_extraction_is_hash_gated_and_preserves_mixed_bytes(self):
        data = archive([("block0.layer0.layer", b"\x7f\x80\x3f\x00"), ("block70.layer0.blend_scale", b"\0\x3c")])
        dll = b"synthetic PE placeholder" + data
        schema = {"dll_sha256": hashlib.sha256(dll).hexdigest(), "archive_offset": len(dll)-len(data),
                  "archive_size": len(data), "records": weights.parse_archive(data), "upstream_commit": "fixture"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(weights, "RECORDS", schema):
            root = Path(tmp); source = root / "test.dll"; source.write_bytes(dll)
            result = weights.extract_raw(source, root / "raw")
            self.assertFalse(result["ready_for_inference"])
            self.assertEqual((root / "raw/block0.layer0.layer.weights").read_bytes(), b"\x7f\x80\x3f\x00")
            self.assertEqual(source.read_bytes(), dll)
            with self.assertRaisesRegex(ValueError, "new output"):
                weights.extract_raw(source, root / "raw")
            source.write_bytes(dll + b"changed")
            with self.assertRaisesRegex(ValueError, "differs"):
                weights.extract_raw(source, root / "other")
            self.assertFalse((root / "other").exists())

    def test_pinned_record_index_has_153_records_and_closes_at_archive_end(self):
        s = weights.RECORDS
        self.assertEqual(len(s["records"]), 153)
        self.assertEqual(sum(r["payload_size"] for r in s["records"]), 147683778)
        last = s["records"][-1]
        self.assertEqual(last["payload_offset"] + last["payload_size"] + 20, s["archive_size"])


class PreparedWeights(unittest.TestCase):
    def test_collects_every_missing_asset_before_gpu_probe(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "ROOT", Path(tmp)), \
             patch.object(runner, "select_environment", side_effect=AssertionError("GPU must not be initialized")), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--assets", str(Path(tmp) / "absent")]), 2)
            report = (Path(tmp) / "build/lmxxf/network-test-result.txt").read_text()
            self.assertIn("Valid files: 0/184", report)
            self.assertEqual(report.count(": missing .f32/.f16"), 184)
            self.assertIn("No GPU test was started", report)

    def test_mixed_f16_f32_nonfinite_ambiguity_size_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "half.f16").write_bytes(struct.pack("<2e", -0., 1.5))
            (root / "full.f32").write_bytes(struct.pack("<2f", .125, .25))
            (root / "nan.f32").write_bytes(struct.pack("<f", float("nan")))
            (root / "bad.f16").write_bytes(b"\0")
            (root / "both.f16").write_bytes(b"\0\0")
            (root / "both.f32").write_bytes(b"\0" * 4)
            (root / "link.f16").symlink_to(root / "half.f16")
            check = weights.inspect_assets(root, contract={"half":2, "full":2, "nan":1, "bad":1, "both":1, "link":2})
            self.assertEqual(check["valid_files"], 2)
            self.assertEqual(len(check["errors"]), 4)
            self.assertFalse(check["structurally_ready"])
            self.assertFalse(check["weight_layout_parity_verified"])
            self.assertEqual(set(check["files"]), {"half.f16", "full.f32"})

    def test_complete_summary_required(self):
        cases = [(n, 0) for n in ("gradient", "replay", "history", "history-replay", "history-reset", "alternate", "alternate-replay")]
        cases += [("gradient", 123), ("replay", 123)]
        text = "\n".join(f"COMPLETE case={n} seed={s} blocks=71 min=0 max=1 wall_seconds=1" for n,s in cases)
        text += "\nRESULT runs=9 blocks_per_run=71 repeats_exact=yes finite=yes external_parity=not_tested\n"
        runner.verify_suite(text)
        for bad in (text.split("\n",1)[1], text.replace("history-reset", "history"), text.replace("blocks=71", "blocks=70"), text + text):
            with self.assertRaises(RuntimeError):
                runner.verify_suite(bad)

    def test_native_suite_cpu_failure_checks_without_runtime(self):
        binary = Path(os.environ.get("LMXXF_BUILD_DIR", ROOT / "build/lmxxf/linux")) / "bin/network_suite"
        if not binary.exists():
            self.skipTest("Build the native host tools")
        env = {**os.environ, "DLSSNR_RESEARCH_HIP_LIBRARY": "/nonexistent/runtime.so"}
        result = subprocess.run([str(binary), "--self-test"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GPU not initialized", result.stdout)


if __name__ == "__main__":
    unittest.main()
