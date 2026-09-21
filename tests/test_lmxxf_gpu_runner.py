import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lmxxf_gpu_runner", ROOT / "experiments/lmxxf/run_gpu_test.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GpuSelection(unittest.TestCase):
    def test_integrated_gpu_is_not_selected(self):
        devices = [{"index": 0, "arch": "gfx1036", "name": "integrated"},
                   {"index": 1, "arch": "gfx1201", "name": "Supported GPU"}]
        self.assertEqual(runner.select_gpu(devices)["index"], 1)

    def test_other_architectures_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "gfx1201"):
            runner.select_gpu([{"index": 0, "arch": "gfx1100"}])

    def test_filters_removed_only_from_child_environment(self):
        original = {"HIP_VISIBLE_DEVICES": "1", "ROCR_VISIBLE_DEVICES": "0", "CUDA_VISIBLE_DEVICES": "2",
                    "LD_PRELOAD": "/unrelated/library.so", "RTC_EXTRA_OPTS": "-ffast-math", "PATH": "/usr/bin"}
        clean = runner.clean_environment(original)
        self.assertEqual(clean, {"PATH": "/usr/bin"})
        self.assertEqual(original["HIP_VISIBLE_DEVICES"], "1")

    def test_report_redacts_home_and_checkout(self):
        text = str(Path.home() / "private") + " " + str(ROOT / "build")
        safe = runner.redact(text)
        self.assertNotIn(str(Path.home()), safe)
        self.assertNotIn(str(ROOT), safe)


class BatchValidation(unittest.TestCase):
    GOOD = ("RESULT cases=79 failures=0 fp8_f16_bitdiff=0 signed_zero_diff=0 "
            "half_diff=0 max_cpu_abs_error=0.001 max_fp8_f16_abs_diff=0\n")
    UPSTREAM = ("RESULT cases=79 failures=0 fp8_f16_bitdiff=2054 signed_zero_diff=0 "
                "half_diff=2 max_cpu_abs_error=6.07849884 max_fp8_f16_abs_diff=4\n")

    def test_wmma_summary_requires_complete_cases_and_numerical_agreement(self):
        self.assertEqual(runner.validate_wmma_result(self.GOOD), "fp8_f16_parity")
        # Upstream counts signed-zero differences separately, without failing.
        runner.validate_wmma_result(self.GOOD.replace("signed_zero_diff=0", "signed_zero_diff=2"))
        for original, replacement in (("cases=79", "cases=1"), ("failures=0", "failures=1"),
                                      ("fp8_f16_bitdiff=0", "fp8_f16_bitdiff=1"),
                                      ("half_diff=0", "half_diff=1")):
            with self.subTest(field=original), self.assertRaises(RuntimeError):
                runner.validate_wmma_result(self.GOOD.replace(original, replacement))
        with self.assertRaises(RuntimeError):
            runner.validate_wmma_result("Compilation succeeded; no validation output")

    def test_upstream_documented_exit_three_is_classified_without_changing_math(self):
        self.assertEqual(runner.validate_wmma_result(self.UPSTREAM, 3), "documented_operand_difference")
        result = subprocess.CompletedProcess(["wmma"], 3, self.UPSTREAM, "")
        lines = []
        with patch.object(runner.subprocess, "run", return_value=result):
            status = runner.run_logged(["wmma"], {}, lines.append, result_check=runner.validate_wmma_result)
        self.assertEqual(status, "documented_operand_difference")
        self.assertEqual(lines, [self.UPSTREAM.strip()])

    def test_only_documented_complete_difference_is_accepted(self):
        for old, new in (("cases=79", "cases=78"), ("failures=0", "failures=1"),
                         ("bitdiff=2054", "bitdiff=2055"), ("half_diff=2", "half_diff=3"),
                         ("signed_zero_diff=0", "signed_zero_diff=1"),
                         ("max_fp8_f16_abs_diff=4", "max_fp8_f16_abs_diff=5"),
                         ("max_cpu_abs_error=6.07849884", "max_cpu_abs_error=nan")):
            with self.subTest(field=old), self.assertRaises(RuntimeError):
                runner.validate_wmma_result(self.UPSTREAM.replace(old, new), 3)
        for code in (0, 1, -11):
            with self.subTest(code=code), self.assertRaises(RuntimeError):
                runner.validate_wmma_result(self.UPSTREAM, code)
        for summary in (self.GOOD, "", self.UPSTREAM + self.UPSTREAM):
            with self.assertRaises(RuntimeError):
                runner.validate_wmma_result(summary, 3)

    def test_process_failure_preserves_diagnostics_and_stops(self):
        output = []
        result = subprocess.CompletedProcess(["probe"], -11, "Starting matrix probe\n", "driver failure\n")
        with patch.object(runner.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "code -11"):
                runner.run_logged(["probe"], {}, output.append)
        self.assertEqual(output, ["Starting matrix probe", "driver failure"])

    def test_timeout_preserves_partial_output(self):
        output = []
        error = subprocess.TimeoutExpired(["probe"], 2, output=b"Loading module\n", stderr=b"partial error\n")
        with patch.object(runner.subprocess, "run", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "2-second limit"):
                runner.run_logged(["probe"], {}, output.append, timeout=2)
        self.assertEqual(output, ["Loading module", "partial error"])


if __name__ == "__main__":
    unittest.main()
