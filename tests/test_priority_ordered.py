"""Regression for 0.4.1's null-marker/priority-inference stream pair."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class OrderedPriorityRegression(unittest.TestCase):
    @unittest.skipUnless(shutil.which('gcc'), 'C compiler required')
    def test_actual_bridge_two_queue_contract(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'priority-ordered'
            subprocess.run(['gcc','-std=gnu11','-O1','-g','-pthread',
                '-Werror=incompatible-pointer-types','-fsanitize=address,undefined',
                '-fno-pie','-no-pie',str(ROOT/'tests/priority_ordered_contract.c'),
                '-ldl','-o',str(exe)],check=True,capture_output=True,timeout=30)
            for scenario in range(16):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(exe),str(scenario)],check=True,
                        capture_output=True,timeout=5,
                        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

if __name__=='__main__': unittest.main()
