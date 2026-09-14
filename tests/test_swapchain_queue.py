"""Compile the real before/after GetDevice implementation with COM mocks."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PIN = '35bdee1435c94f8c3548725fcb046595b263bd7e'
RELATIVE = 'libs/vkd3d/swapchain.c'


def query_body(source):
    start = source.index('static HRESULT STDMETHODCALLTYPE dxgi_vk_swap_chain_GetDevice(')
    end = source.index('\n}\n', start) + 3
    return source[start:end]


class SwapchainQueueContract(unittest.TestCase):
    def test_actual_before_and_after_query(self):
        source = Path(os.environ.get('DLSSNR_TEST_VKD3D_SOURCE', ROOT / 'build/vkd3d-source'))
        if not (source / RELATIVE).is_file():
            self.skipTest('Set DLSSNR_TEST_VKD3D_SOURCE to the reconstructed vkd3d checkout.')
        self.assertIsNotNone(shutil.which('gcc'), 'GCC is required for the CPU contract.')
        self.assertEqual(subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(), PIN)
        original = subprocess.check_output(['git', '-C', str(source), 'show', f'{PIN}:{RELATIVE}'], text=True)
        patched = (source / RELATIVE).read_text()
        self.assertNotEqual(query_body(original), query_body(patched))
        env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
        with tempfile.TemporaryDirectory(prefix='dlssnr-swapchain-contract-') as directory:
            temp = Path(directory)
            for label, code in [('before', original), ('after', patched)]:
                (temp / 'swapchain_query_body.h').write_text(query_body(code))
                binary = temp / label
                subprocess.run(['gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                                '-I', str(temp), str(ROOT / 'tests/swapchain_queue_contract.c'),
                                '-o', str(binary)], check=True, capture_output=True, text=True)
                result = subprocess.run([str(binary), label], env=env, check=True, capture_output=True, text=True)
                self.assertIn('reproduced' if label == 'before' else 'passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
