#!/usr/bin/env python3
"""Real resident/weights/modules, fake HIP: no GPU image or FPS validation."""
import ctypes as c, os, sys
from pathlib import Path
class Prefix(c.Structure): _fields_=[('values',c.c_float*6)]
class Config(c.Structure):
    _fields_=[('abi',c.c_uint),('bytes',c.c_uint),('w',c.c_uint),('h',c.c_uint),('assets',c.c_char_p),('modules',c.c_char_p),('stream',c.c_void_p)]
class Frame(c.Structure):
    _fields_=[('abi',c.c_uint),('bytes',c.c_uint),('w',c.c_uint),('h',c.c_uint),('rgb',c.c_void_p),('history',c.c_void_p),('out',c.c_void_p),('rgb_bytes',c.c_uint64),('history_bytes',c.c_uint64),('out_bytes',c.c_uint64),('seed',c.c_uint),('reserved',c.c_uint),('prefix',Prefix)]
def main():
    mock,resident,assets,modules=[str(Path(x).resolve()) for x in sys.argv[1:]]
    os.environ['DLSSNR_RESEARCH_HIP_LIBRARY']=mock
    hip=c.CDLL(mock);lib=c.CDLL(resident)
    hip.hipMalloc.argtypes=[c.POINTER(c.c_void_p),c.c_size_t];hip.hipFree.argtypes=[c.c_void_p]
    hip.mock_expect.argtypes=[c.c_uint,c.c_uint,c.c_uint,c.c_uint,c.POINTER(c.c_float)]
    for key in ('allocations','live','prefix_calls','launches'):getattr(hip,'mock_'+key).restype=c.c_size_t
    lib.lmxxf_create.argtypes=[c.POINTER(Config),c.POINTER(c.c_void_p),c.c_char_p,c.c_size_t]
    lib.lmxxf_validate_frame.argtypes=[c.POINTER(Frame),c.c_char_p,c.c_size_t]
    lib.lmxxf_enqueue.argtypes=[c.c_void_p,c.POINTER(Frame),c.c_char_p,c.c_size_t]
    lib.lmxxf_destroy.argtypes=[c.POINTER(c.c_void_p),c.c_char_p,c.c_size_t]
    assert c.sizeof(Config)==40 and c.sizeof(Frame)==96 and Frame.prefix.offset==72
    for w,h in ((2176,896),(2432,1024)):
        n=w*h;rgb=c.c_void_p();hist=c.c_void_p();out=c.c_void_p()
        for ptr,size in ((rgb,n*12),(hist,n*12),(out,n*16)):assert hip.hipMalloc(c.byref(ptr),size)==0
        cfg=Config(3,40,w,h,assets.encode(),modules.encode(),0x5550);ctx=c.c_void_p();err=c.create_string_buffer(384)
        assert lib.lmxxf_create(c.byref(cfg),c.byref(ctx),err,len(err))==0,err.value
        profiles=((.0625,0,0,0,1.1,1.1),(.0625,1,1,.0078125,1,1),(.0625,0,0,0,1.2,1.3))
        for i,values in enumerate(profiles):
            prefix=Prefix((c.c_float*6)(*values));history=i%2
            frame=Frame(3,96,w,h,rgb,hist if history else None,out,n*12,n*12 if history else 0,n*16,i,0,prefix)
            hip.mock_expect(w,h,i,history,prefix.values);before=hip.mock_prefix_calls()
            assert lib.lmxxf_validate_frame(c.byref(frame),err,len(err))==0,err.value
            assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==0,err.value
            assert hip.mock_prefix_calls()==before+1
            if i==0:warm=hip.mock_allocations()
            else:assert hip.mock_allocations()==warm
        hip.mock_failure(1,0)
        assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==2
        count=hip.mock_launches()
        assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==2 and hip.mock_launches()==count
        live=hip.mock_live();hip.mock_failure(0,1)
        assert lib.lmxxf_destroy(c.byref(ctx),err,len(err))==3 and ctx.value and hip.mock_live()==live
        hip.mock_failure(0,0)
        assert lib.lmxxf_destroy(c.byref(ctx),err,len(err))==0 and not ctx.value and hip.mock_live()==3
        for ptr in (rgb,hist,out):assert hip.hipFree(ptr)==0
        assert hip.mock_live()==0
        print(f'RESIDENT_REAL_PREFIX_ARGUMENTS shape={w}x{h} profile_changes=3 warm_allocations=0 failure_lifetime=passed',flush=True)
if __name__=='__main__':main()
