#!/usr/bin/env python3
"""Actual resident ABI validation, without loading HIP or launching a kernel."""
import argparse
import ctypes as c
from pathlib import Path
from lmxxf_prefix_resident import Frame, Prefix

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resident',type=Path)
    args=parser.parse_args()
    lib=c.CDLL(str(args.resident.resolve()))
    lib.lmxxf_validate_frame.argtypes=[c.POINTER(Frame),c.c_char_p,c.c_size_t]
    err=c.create_string_buffer(384)
    for w,h in ((1792,768),(2048,896),(2304,1024)):
        n=w*h
        frame=Frame(3,96,w,h,0x100000000,0x200000000,0x300000000,
                    n*12,n*12,n*16,748,0,Prefix((c.c_float*6)(.0625,0,0,0,1,1)))
        assert lib.lmxxf_validate_frame(c.byref(frame),err,len(err))==0,err.value
        invalid=[('rgb_bytes',n*12-1),('history_bytes',n*12-1),
                 ('out_bytes',n*16-1),('w',w+1),('h',h+1),
                 ('out',frame.rgb),('rgb',frame.rgb+1),
                 ('history',None)]
        for field,value in invalid:
            assert field in {name for name,_ in Frame._fields_}
            altered=Frame.from_buffer_copy(frame)
            setattr(altered,field,value)
            assert lib.lmxxf_validate_frame(c.byref(altered),err,len(err))==1,(field,err.value)
        frame.history=None;frame.history_bytes=0
        assert lib.lmxxf_validate_frame(c.byref(frame),err,len(err))==0,err.value
        frame.prefix.values[0]=.125
        assert lib.lmxxf_validate_frame(c.byref(frame),err,len(err))==1
        print(f'RESIDENT_GEOMETRY {w}x{h} exact_capacity=passed invalid_capacity_alias_alignment_geometry_profile=rejected')

if __name__=='__main__':main()
