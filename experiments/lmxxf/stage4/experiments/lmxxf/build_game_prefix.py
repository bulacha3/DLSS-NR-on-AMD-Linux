#!/usr/bin/env python3
"""Generate the one stage-4 v2 kernel from the pinned stage-3 upstream source.

Usage: python3 build_game_prefix.py UPSTREAM/hip/c32_fused_ffn_attention.hip OUTPUT.hip
Compile with the stage-3 Linux COMGR driver (no GPU required).
"""
import argparse, hashlib, re
from pathlib import Path
SOURCE_SHA = '4e54ded35834d6ef0579340871317a01b7d6a4f224f23ff62577fd47843fee64'
COMMIT = '90abf6a2d3e3b08136ab56de0c658d830b327865'
def once(text, old, new):
    if text.count(old) != 1: raise RuntimeError('Unexpected upstream anchor: '+old[:80])
    return text.replace(old, new)
def generate(source, output):
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA: raise RuntimeError('Upstream source hash mismatch')
    root=Path(__file__).resolve().parent
    text=raw.decode().split('\nKERNEL ',1)[0]
    text=once(text,'DEV void fused_prefix_values(', (root/'prefix_features.inc').read_text()+'\nDEV void fused_prefix_values(')
    text=once(text,'uint seed,uint temporal,float*f){','uint seed,uint temporal,float*f,lmxxf_prefix_parameters controls){')
    start=text.index('DEV void fused_prefix_values('); end=text.index('\ntemplate<bool Raw=false',start)
    body=text[start:end]
    pattern=r'Hrtz\(Hrtz\(Hrtz\((rgba\[rgbp\*4(?:\+[12])?\]|history\[q(?:\+[12])?\])\)-\.5f\)\*\.125f\)'
    body,count=re.subn(pattern,r'lmxxf_condition_color(\1,controls)',body)
    if count!=6: raise RuntimeError('Expected six current/history color features')
    body=once(body,' for(uint i=0;i<16;i++)f[i]=values[i];',' lmxxf_condition_features(values,controls);\n for(uint i=0;i<16;i++)f[i]=values[i];')
    text=text[:start]+body+text[end:]
    text=once(text,'uint seed=0,uint temporal=0){','uint seed=0,uint temporal=0,lmxxf_prefix_parameters prefix_parameters={}){')
    text=once(text,'fused_prefix_values(rgba,hist,base+first+l,sourcew,seed,temporal,f);','fused_prefix_values(rgba,hist,base+first+l,sourcew,seed,temporal,f,prefix_parameters);')
    wrapper='''
KERNEL __attribute__((amdgpu_flat_work_group_size(128,128))) C32_OCC
void lmxxf_game_prefix(const float*rgba,const float*hist,const float*fw,const float*w,float*main8,float*down,
 uint windows,uint mode,uint raw,uint width,uint height,uint seed,uint temporal,lmxxf_prefix_parameters controls){
 c32_fused_body<true,false,false,false,false,true,true,false,true>(nullptr,fw,w,nullptr,windows,mode,raw,width,height,0,0,0,0,0,
 nullptr,nullptr,nullptr,nullptr,nullptr,0.f,main8,down,rgba,hist,seed,temporal,controls);
}
'''
    output.write_text('// Stage 4 v2, upstream '+COMMIT+'\n#define HIP_PREPACKED_WEIGHTS 1\n'+(root/'prefix_parameters.h').read_text()+'\n'+text+wrapper)
    print('Generated',output)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('source',type=Path); p.add_argument('output',type=Path)
    a=p.parse_args(); generate(a.source,a.output)
