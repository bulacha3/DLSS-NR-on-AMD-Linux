#!/usr/bin/env python3
"""Audit production source delta; run extracted prefix/head addressing in CPU.

CPU math intrinsics are shared stand-ins, NOT GPU arithmetic validation. The
source audit requires the complete neural body to differ only in addressing,
the byte-preserving V layout, and its required publication barrier.
"""
import argparse,subprocess,tempfile
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--sanitize',action='store_true');a=p.parse_args()
    root=Path(__file__).resolve().parents[1];exp=root/'experiments/lmxxf'
    old=(exp/'game-prefix.generated.hip').read_text();new=(exp/'game-io.generated.hip').read_text()
    expected=new.split('\n',1)[1].split('\nKERNEL ',1)[0]
    expected=expected.replace('rgba[rgbp*3','rgba[rgbp*4').replace('uint q=(y*width+x)*3;','uint q=(y*width+x)*4;')
    expected=expected.replace('color[p*3+row]','color[p*4+row]').replace('rgb[p*4+row]=clampf(v,0.f,1.f);if(row==0)rgb[p*4+3]=1.f;','rgb[p*3+row]=clampf(v,0.f,1.f);')
    expected=expected.replace('#define HIP_C32_VT 1 /* In-place V transpose: contiguous AV B fragments, same bytes and LDS size. */',
        '#define HIP_C32_VT 0 /* 1: V stored transposed in its own LDS array so the AV B fragments load as 8 contiguous bytes; same bytes */')
    expected=expected.replace('#if HIP_C32_VT && HIP_C32_LOCAL_ATTN_SYNC\n#error "In-place C32 V transpose requires group-wide probability rows"\n#endif\n', '')
    expected=expected.replace(' // Keep the three Q/K/V phases specialized across the V publication barrier.\n#if !HIP_C32_NO_UNROLL\n#pragma unroll\n#endif\n', '')
    expected=expected.replace(' unsigned char*vt=packed+128*36; // 32x68 transposed bytes fit the existing 64x36 V plane; no added LDS',
        ' __attribute__((shared)) unsigned char vt[32*68]; // V transposed [col][key]: the AV B fragment is 8 contiguous bytes (the [key][col] rows needed 8 byte gathers per fragment)')
    expected=expected.replace('  // Transposed V stores can overwrite another wave\'s aliased FFN bytes.\n  // Every wave has finished its V matrix reads at this barrier.\n  if(part==2)sync_window();else sync_owned_rows();f8 sum{};',
        '  sync_owned_rows();f8 sum{};')
    assert expected==old.split('\nKERNEL ',1)[0], 'unexpected neural arithmetic delta'
    def prefix(s):
        s=s[s.index('DEV uint production_pcg'):s.index('\ntemplate<bool Raw=false')]
        return s.replace('__builtin_amdgcn_sqrtf','std::sqrt').replace('__builtin_amdgcn_logf','std::log2').replace('__builtin_amdgcn_cosf','cpu_cos').replace('__builtin_amdgcn_sinf','cpu_sin')
    def head(s):
        start=s.index('for(uint task=l;task<48;task+=32)');end=s.index('\n }\n}',start)
        return 'void head(const float*color,const float*headw,float*rgb,const Scratch&scratch,uint window,uint tid,uint sourcew,uint sourceh){uint first=(tid/32)*16,l=tid%32,sx=0,sy=0,ww=sourcew;float rgb_scale=.03125f;'+s[start:end]+'}\n'
    hf=(root/'tests/lmxxf_prefix_contract.cpp').read_text();hf=hf[hf.index('static float Hrtz('):hf.index('\n#define DEV')]
    source='''#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
#include <limits>
#include "prefix_parameters.h"
using uint=uint32_t;
#define DEV static inline
struct Scratch{_Float16 ex[64*66];};
float clampf(float x,float lo,float hi){return std::fmin(std::fmax(x,lo),hi);}
float cpu_cos(float x){return std::cos(x*6.283185307179586f);}
float cpu_sin(float x){return std::sin(x*6.283185307179586f);}
'''+hf+'\nnamespace legacy{'+prefix(old)+head(old)+'}\nnamespace direct{'+prefix(new)+head(new)+'}\n'+r'''
int main(){
 const float special[]={-100.f,-0.f,0.f,1e-7f,.125f,.5f,.75f,1.f,2.f,65504.f,1e10f,std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()};
 const lmxxf_prefix_parameters profiles[]={{{.0625f,0,0,0,1,1}},{{.0625f,1,1,.0078125f,1,1}},{{.0625f,.25f,.5f,.75f,1.25f,1.5f}}};
 uint64_t checks=0;
 for(auto shape: {std::pair<uint,uint>{64,64},{128,64},{64,128}}){
  uint w=shape.first,h=shape.second,n=w*h;
  std::vector<float> rgb(n*3),history(n*3),rgba(n*4,1.f),hrgba(n*4,1.f);
  for(uint i=0;i<n*3;i++){rgb[i]=special[i%13];history[i]=special[(i*7)%13];rgba[(i/3)*4+i%3]=rgb[i];hrgba[(i/3)*4+i%3]=history[i];}
  for(uint temporal:{0u,1u})for(uint seed:{0u,900001u,0xffffffffu})for(auto controls:profiles)for(uint i=0;i<n;i++){
   float a[16],b[16];legacy::fused_prefix_values(rgba.data(),hrgba.data(),i,w,seed,temporal,a,controls);
   direct::fused_prefix_values(rgb.data(),history.data(),i,w,seed,temporal,b,controls);
   assert(!std::memcmp(a,b,sizeof(a)));++checks;
  }
  Scratch scratch;for(uint i=0;i<64*66;i++)scratch.ex[i]=_Float16((int(i%31)-15)*.03125f);
  float weights[96];for(uint i=0;i<96;i++)weights[i]=(int(i%13)-6)*.0625f;
  std::vector<float> before(n*3,12345.f),after(n*4,12345.f);
  for(uint win=0;win<n/64;win++)for(uint tid=0;tid<128;tid++){
   legacy::head(rgba.data(),weights,before.data(),scratch,win,tid,w,h);
   direct::head(rgb.data(),weights,after.data(),scratch,win,tid,w,h);
  }
  for(uint i=0;i<n;i++){
   for(uint ch=0;ch<3;ch++)assert(!std::memcmp(&before[i*3+ch],&after[i*4+ch],4));
   assert(after[i*4+3]==1.f);
  }
 }
 std::printf("GAME_IO_SOURCE_AND_CPU_ADDRESSING prefix_vectors=%llu head_rgb_bits=identical alpha=1 neural_body_delta=addressing_and_V_layout\n",(unsigned long long)checks);
}
'''
    with tempfile.TemporaryDirectory(prefix='lmxxf-io-math-') as t:
        d=Path(t);(d/'test.cpp').write_text(source)
        cmd=['g++','-std=c++17','-O1','-g','-fno-fast-math','-ffp-contract=off','-I',str(exp),str(d/'test.cpp'),'-o',str(d/'test')]
        if a.sanitize:cmd+=['-fsanitize=address,undefined','-fno-omit-frame-pointer']
        subprocess.run(cmd,check=True);subprocess.run([str(d/'test')],check=True)


if __name__=='__main__':main()
