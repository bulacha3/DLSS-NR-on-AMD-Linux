"""Cross-calling-convention tests for the actual PE wrapper bodies; no Wine/HIP."""
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class Bridge040(unittest.TestCase):
    def test_table_layout_matches_trampoline(self):
        self.assertEqual((ROOT/'native/hip_bridge.h').read_bytes(),
                         (ROOT/'sources/trampoline/hip_bridge.h').read_bytes())

    @unittest.skipUnless(shutil.which('gcc'), 'native compiler required')
    def test_ms_abi_to_sysv_parameters_errors_and_old_table_rejection(self):
        source=(ROOT/'sources/trampoline/amdhip64_7_pe.c').read_text()
        # Only declaration attributes differ for native GCC. Wrapper bodies
        # and table layout are compiled directly from the production source.
        source=source.replace('#define EXPORT __declspec(dllexport)', '#define EXPORT __attribute__((ms_abi))')
        source='#define __declspec(x)\n#define __stdcall __attribute__((ms_abi))\n'+source
        source+='''
#include <assert.h>
static int SYSV get_device(int *out) { *out=9; return 17; }
static int SYSV occupancy(int *out, const void *fn, int size, u64 shared) {
 assert(fn==(const void *)0x12345678 && size==256 && shared==0x123456789ULL);
 *out=3;return 21;
}
int main(void) {
 DlssnrHipBridge table={0}; g=&table; int value=-1;
 table.magic=0x324849504E524C44ULL;
 table.p_hipGetDevice=get_device;
 assert(hipGetDevice(&value)==HIP_ERROR_NOT_INITIALIZED && value==-1);
 table.magic=DLSSNR_HIP_MAGIC;
 assert(hipGetDevice(&value)==17 && value==9);
 table.p_hipOccupancyMaxActiveBlocksPerMultiprocessor=occupancy;
 assert(hipOccupancyMaxActiveBlocksPerMultiprocessor(&value,(void *)0x12345678,256,0x123456789ULL)==21 && value==3);
 table.p_hipOccupancyMaxActiveBlocksPerMultiprocessor=0;
 assert(hipOccupancyMaxActiveBlocksPerMultiprocessor(&value,0,0,0)==HIP_ERROR_NOT_INITIALIZED && value==3);
 g=0;assert(hipGetDevice(&value)==HIP_ERROR_NOT_INITIALIZED);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);p=d/'test.c';p.write_text(source);exe=d/'test'
            subprocess.run(['gcc','-std=gnu11','-O1','-ffunction-sections','-fdata-sections',
                '-Werror=incompatible-pointer-types','-fsanitize=address,undefined',
                '-I',str(ROOT/'sources/trampoline'),str(p),'-Wl,--gc-sections','-o',str(exe)],
                check=True,capture_output=True,timeout=30)
            subprocess.run([str(exe)],check=True,capture_output=True,timeout=15)

if __name__=='__main__':unittest.main()
