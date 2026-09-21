#!/usr/bin/env python3
"""Generate RGB game prefix and RGBA game head from the pinned upstream body.

Only load/store addressing and shared-memory V layout change. All neural
operations, feature controls, roundings and dot-product order remain unchanged.
"""
import argparse
from pathlib import Path
from build_game_prefix import generate, once


def transpose_c32_v(text):
    """Reuse the existing V plane for contiguous AV matrix fragments.

    A transposed 32x68-byte plane fits inside the existing 64x36-byte V
    allocation. Its stores cross the old wave ownership boundaries, so all
    waves must finish reading the aliased FFN plane before those stores.
    """
    text = once(text,
        '#define HIP_C32_VT 0 /* 1: V stored transposed in its own LDS array so the AV B fragments load as 8 contiguous bytes; same bytes */',
        '#define HIP_C32_VT 1 /* In-place V transpose: contiguous AV B fragments, same bytes and LDS size. */')
    text = once(text, '#ifndef HIP_C32_LOCAL_FFN_SYNC',
        '#if HIP_C32_VT && HIP_C32_LOCAL_ATTN_SYNC\n'
        '#error "In-place C32 V transpose requires group-wide probability rows"\n'
        '#endif\n'
        '#ifndef HIP_C32_LOCAL_FFN_SYNC')
    text = once(text,
        ' __attribute__((shared)) unsigned char vt[32*68]; // V transposed [col][key]: the AV B fragment is 8 contiguous bytes (the [key][col] rows needed 8 byte gathers per fragment)',
        ' unsigned char*vt=packed+128*36; // 32x68 transposed bytes fit the existing 64x36 V plane; no added LDS')
    text = once(text, '  sync_owned_rows();f8 sum{};',
        '  // Transposed V stores can overwrite another wave\'s aliased FFN bytes.\n'
        '  // Every wave has finished its V matrix reads at this barrier.\n'
        '  if(part==2)sync_window();else sync_owned_rows();f8 sum{};')
    text = once(text, ' C32_LOOP for(uint part=0;part<3;part++){',
        ' // Keep the three Q/K/V phases specialized across the V publication barrier.\n'
        '#if !HIP_C32_NO_UNROLL\n'
        '#pragma unroll\n'
        '#endif\n'
        ' C32_LOOP for(uint part=0;part<3;part++){')
    return text


def generate_io(source, output):
    generate(source, output)
    text = output.read_text()
    text = once(text, 'void lmxxf_game_prefix(', 'void lmxxf_game_prefix_rgb(')
    for channel in ('', '+1', '+2'):
        text = once(text, 'rgba[rgbp*4'+channel+']', 'rgba[rgbp*3'+channel+']')
    text = once(text, 'uint q=(y*width+x)*4;', 'uint q=(y*width+x)*3;')
    text = once(text, 'color[p*4+row]', 'color[p*3+row]')
    text = once(text, 'rgb[p*3+row]=clampf(v,0.f,1.f);',
                'rgb[p*4+row]=clampf(v,0.f,1.f);if(row==0)rgb[p*4+3]=1.f;')
    text += '''
KERNEL __attribute__((amdgpu_flat_work_group_size(128,128))) C32_OCC
void lmxxf_game_head_rgba(const float*low,const float*skip,const float*scales,const float*fw,const float*w,const float*color,const float*headw,float*rgb,uint windows,uint width,uint height,uint sx,uint sy,float scale){c32_fused_body<true,true,false,true,true>(low,fw,w,nullptr,windows,0,1,width,height,sx,sy,0,0,0,skip,scales,color,headw,rgb,scale);}
'''
    output.write_text('// Stage 4: direct RGB input / RGBA output; in-place transposed C32 V.\n'+transpose_c32_v(text))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();generate_io(a.source,a.output)
