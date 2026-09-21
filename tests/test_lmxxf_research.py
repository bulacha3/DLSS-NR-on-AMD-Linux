"""Research-only checks; none of these substitute for GPU numerical validation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "experiments/lmxxf"
spec = importlib.util.spec_from_file_location("lmxxf_lab", LAB / "lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
SOURCE = Path(os.environ.get("LMXXF_SOURCE_DIR", ROOT / "build/lmxxf/upstream"))
BUILD = Path(os.environ.get("LMXXF_BUILD_DIR", ROOT / "build/lmxxf/linux"))


@unittest.skipUnless(SOURCE.is_dir(), "Set LMXXF_SOURCE_DIR to the pinned source fixture")
class SourceContract(unittest.TestCase):
    def test_tampered_kernel_rejected_before_build(self):
        lab.verify(SOURCE)
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            for name in lab.LOCK["files"]:
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SOURCE / name, target)
            with (fixture / "hip/c32_fused_ffn_attention.hip").open("ab") as out:
                out.write(b"\n#define DIFFERENT_KERNEL 1\n")
            with self.assertRaisesRegex(ValueError, "does not match pinned commit"):
                lab.verify(fixture)

    def test_production_packing_and_rounding_defines(self):
        modules = {m["name"]: m for m in lab.parse_recipe(SOURCE)}
        self.assertEqual(len(modules), 24)
        for name, module in modules.items():
            self.assertIn("HIP_ISA_HALF 1", module["defines"])
            self.assertEqual("HIP_PREPACKED_WEIGHTS 1" in module["defines"], name.endswith("-packed"))
        for name, define in {
            "c32_fused_ffn_attention-packed": "HIP_C32_DIAG_WEIGHTS 1",
            "multihead_fused_attention": "HIP_MH_RTZ_ISA 1",
            "deep_fast-packed": "HIP_BRANCHLESS_F 1",
            "multihead-fast-padded-wave-packed": "HIP_FFN_HOIST_RES 2",
        }.items():
            self.assertIn(define, modules[name]["defines"])
        self.assertEqual(modules["c32_fused_attention"]["sources"], ["c32_fused_attention_packed.hip"])

    def test_module_load_probe_entries_exist_in_pinned_sources(self):
        for module in lab.parse_recipe(SOURCE):
            source = (SOURCE / "hip" / module["sources"][-1]).read_text()
            with self.subTest(module=module["name"]):
                self.assertRegex(source, r"\bvoid\s+" + module["probe_entry"] + r"\s*\(")


@unittest.skipUnless((BUILD / "bin/hip_probe").is_file(), "Build the native Linux research tools first")
class NativeHostContract(unittest.TestCase):
    def run_probe(self, library):
        env = {**os.environ, "DLSSNR_RESEARCH_HIP_LIBRARY": str(library)}
        return subprocess.run([str(BUILD / "bin/hip_probe")], env=env, capture_output=True, text=True, timeout=10)

    def test_upstream_packed_weight_numerics(self):
        result = subprocess.run([str(BUILD / "bin/test_packed_weights")], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS finite E4M3 roundtrip", result.stdout)

    def test_missing_runtime_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_probe(Path(tmp) / "missing.so.7")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot load native HIP 7", result.stderr)

    def test_wrong_hip_major_rejected_despite_library_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fake.c"
            source.write_text("int hipRuntimeGetVersion(int *v) {*v=60000000; return 0;}\n")
            library = root / "libamdhip64.so.7"
            subprocess.run(["cc", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
            result = self.run_probe(library)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not HIP 7", result.stderr)

    def test_incomplete_runtime_names_missing_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fake.c"
            source.write_text("int hipRuntimeGetVersion(int *v) {*v=70100000; return 0;}\n")
            library = root / "libamdhip64.so.7"
            subprocess.run(["cc", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
            result = self.run_probe(library)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing HIP export hipEventCreate", result.stderr)


@unittest.skipUnless(os.environ.get("DLSSNR_RESEARCH_COMGR_LIBRARY"),
                     "Set DLSSNR_RESEARCH_COMGR_LIBRARY for GPU-free device compilation")
class DeviceCompileContract(unittest.TestCase):
    def test_all_production_modules_and_probes_compile(self):
        # COMGR compiles gfx1201 code on the CPU; a Radeon/HIP device is not needed.
        # Subtests collect failures across the entire recipe, rather than making
        # an operator discover one missing declaration per GPU test round.
        lab.kernels(SOURCE, BUILD, generate_only=True)
        env = dict(os.environ)
        env.pop("RTC_EXTRA_OPTS", None)
        names = [m["name"] for m in lab.parse_recipe(SOURCE)] + ["fp8_probe", "wmma_probe"]
        for name in names:
            with self.subTest(module=name):
                module = BUILD / "kernels" / (name + ".hsaco")
                result = subprocess.run([str(BUILD / "bin/compile_hip"), str(module),
                                         str(BUILD / "kernels" / (name + ".generated.hip")), "comgr"],
                                        env=env, capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                lab.code_object_record(module)


if __name__ == "__main__":
    unittest.main()
