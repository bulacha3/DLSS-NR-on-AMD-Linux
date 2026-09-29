"""Priority ABI regression: production wrapper bodies on CPU, never a GPU."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from dlssnr import upstream, deploy, assets
ROOT = Path(__file__).resolve().parents[1]

class PriorityContractTests(unittest.TestCase):
    def test_exact_new_import_surface(self):
        from dlssnr import legacy_converter
        self.assertEqual(upstream.HIP_IMPORTS - legacy_converter.HIP_IMPORTS,
            {'hipGetDevice','hipOccupancyMaxActiveBlocksPerMultiprocessor',
             'hipDeviceGetStreamPriorityRange','hipStreamCreateWithPriority','hipStreamDestroy'})
        self.assertEqual(len(upstream.HIP_IMPORTS),38)

    def test_previous_hip_table_rejected_by_package(self):
        manifest = json.loads((ROOT/'assets/manifest.json').read_text())
        manifest['files'] = {name:'0'*64 for name in upstream.COMPONENTS}
        assets.require_deployable(manifest)
        for old in (1,2,3):
            with self.subTest(old=old), self.assertRaises(RuntimeError):
                assets.require_deployable(dict(manifest,hip_bridge_abi=old))

    def test_priority_setting_not_forced_or_dropped(self):
        for value in (0,1):
            prior=f'[DlssNrOnAmd]\nQueuePriority={value}\nToneCurve=aces\nProfile=0\n'.encode()
            out=deploy._ini(prior,0,update=True)
            self.assertIn(f'QueuePriority={value}\n'.encode(),out)
            self.assertIn(b'ToneCurve=aces\n',out)
            self.assertIn(b'Profile=0\n',out)
        self.assertNotIn(b'QueuePriority=',deploy._ini(b'',0))

    @unittest.skipUnless(shutil.which('gcc'),'C compiler required')
    def test_actual_pe_wrappers_forward_signed_priority_and_errors(self):
        src=(ROOT/'sources/trampoline/amdhip64_7_pe.c').read_text().replace(
            '#define EXPORT __declspec(dllexport)','#define EXPORT __attribute__((ms_abi))')
        src='#define __declspec(x)\n#define __stdcall __attribute__((ms_abi))\n'+src
        src+=r'''
#include <assert.h>
static int called, result;
static int SYSV range(int *least,int *greatest) {
    called++; if(!result){if(least)*least=2;if(greatest)*greatest=-3;} return result;
}
static int SYSV create(void **out,unsigned flags,int priority) {
    called++; assert(flags==0x80000001u && priority==-3);
    if(!result && out)*out=(void *)0x123456789ULL;return result;
}
static int SYSV destroy(void *s){called++;assert(s==(void *)0x123456789ULL);return result;}
int main(void){
    DlssnrHipBridge t={0};g=&t;int least=91,greatest=92;void *out=0;
    t.p_hipDeviceGetStreamPriorityRange=range;
    t.p_hipStreamCreateWithPriority=create;t.p_hipStreamDestroy=destroy;
    t.magic=0x334849504E524C44ULL;
    assert(hipDeviceGetStreamPriorityRange(&least,&greatest)==3);
    assert(hipStreamCreateWithPriority(&out,0x80000001u,-3)==3);
    assert(hipStreamDestroy((void *)0x123456789ULL)==3 && !called);
    t.magic=DLSSNR_HIP_MAGIC;
    assert(hipDeviceGetStreamPriorityRange(&least,&greatest)==0 && least==2 && greatest==-3);
    assert(hipDeviceGetStreamPriorityRange(0,0)==0);
    assert(hipStreamCreateWithPriority(&out,0x80000001u,-3)==0 && out==(void *)0x123456789ULL);
    assert(hipStreamDestroy(out)==0);
    result=801;least=91;greatest=92;out=0;
    assert(hipDeviceGetStreamPriorityRange(&least,&greatest)==801 && least==91 && greatest==92);
    assert(hipStreamCreateWithPriority(&out,0x80000001u,-3)==801 && !out);
    assert(hipStreamDestroy((void *)0x123456789ULL)==801);
    t.p_hipDeviceGetStreamPriorityRange=0;t.p_hipStreamCreateWithPriority=0;t.p_hipStreamDestroy=0;
    assert(hipDeviceGetStreamPriorityRange(0,0)==3);
    assert(hipStreamCreateWithPriority(0,0,0)==3);
    assert(hipStreamDestroy(0)==3);
    g=0;assert(hipStreamDestroy(0)==3);return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'test.c').write_text(src)
            subprocess.run(['gcc','-std=gnu11','-O1','-ffunction-sections','-fdata-sections',
                '-Werror=incompatible-pointer-types','-fsanitize=address,undefined','-fno-pie','-no-pie',
                '-I',str(ROOT/'sources/trampoline'),str(d/'test.c'),'-Wl,--gc-sections','-o',str(d/'test')],
                check=True,capture_output=True,timeout=30)
            subprocess.run([str(d/'test')],check=True,capture_output=True,timeout=15)

    @unittest.skipUnless(shutil.which('gcc'),'C compiler required')
    def test_native_priority_forwarding(self):
        src=r'''
#define _GNU_SOURCE
#include "native/hip_bridge.c"
#include <assert.h>
static int result,called;
static int range(int *lo,int *hi){called++;if(!result){if(lo)*lo=1;if(hi)*hi=-1;}return result;}
static int create(void **s,unsigned flags,int priority){called++;assert(flags==1 && priority==-1);if(!result && s)*s=(void *)0x123456789ULL;return result;}
static int destroy(void *s){called++;assert(s==(void *)0x123456789ULL);return result;}
int main(void){
    g_hip_ok=1;real.p_hipDeviceGetStreamPriorityRange=range;
    real.p_hipStreamCreateWithPriority=create;real.p_hipStreamDestroy=destroy;
    int lo=0,hi=0;void *s=0;
    assert(g_bridge.magic==0x344849504E524C44ULL);
    assert(g_bridge.p_hipDeviceGetStreamPriorityRange(&lo,&hi)==0 && lo==1 && hi==-1);
    assert(g_bridge.p_hipStreamCreateWithPriority(&s,1,-1)==0 && s==(void *)0x123456789ULL);
    assert(g_bridge.p_hipStreamDestroy(s)==0);
    result=801;
    assert(stub_priority_range(0,0)==801);
    assert(stub_streamcreate_priority(0,1,-1)==801);
    assert(stub_streamdestroy(s)==801);
    real.p_hipDeviceGetStreamPriorityRange=0;real.p_hipStreamCreateWithPriority=0;real.p_hipStreamDestroy=0;
    assert(stub_priority_range(0,0)==3 && stub_streamcreate_priority(0,1,-1)==3 && stub_streamdestroy(s)==3);
    assert(called==6);return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'test.c').write_text(src)
            subprocess.run(['gcc','-std=gnu11','-O1','-g','-pthread','-Werror=incompatible-pointer-types',
                '-fsanitize=address,undefined','-fno-pie','-no-pie','-I',str(ROOT),str(d/'test.c'),'-ldl','-o',str(d/'test')],
                check=True,capture_output=True,timeout=30)
            subprocess.run([str(d/'test')],check=True,capture_output=True,timeout=15)

if __name__=='__main__':unittest.main()
