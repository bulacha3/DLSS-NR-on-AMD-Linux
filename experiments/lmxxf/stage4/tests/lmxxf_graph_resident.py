#!/usr/bin/env python3
"""Real resident + weights/modules, CPU HIP contract model; no GPU/FPS claim."""
import argparse, ctypes as c, json, os, subprocess, sys, tempfile
from pathlib import Path
from lmxxf_prefix_resident import Config, Frame, Prefix

class Stats(c.Structure):
    _fields_=[('bytes',c.c_uint),('mode',c.c_uint),('builds',c.c_uint64),('replays',c.c_uint64),('direct',c.c_uint64),('nodes',c.c_uint64),('reason',c.c_char*192)]

def child(a):
    os.environ['DLSSNR_RESEARCH_HIP_LIBRARY']=a.mock
    os.environ['DLSSNR_LMXXF_GRAPH']='0' if a.mode=='direct' else '1'
    hip=c.CDLL(a.mock);lib=c.CDLL(a.resident)
    hip.mock_stream.argtypes=[c.c_void_p];hip.mock_stream(a.stream)
    hip.hipMalloc.argtypes=[c.POINTER(c.c_void_p),c.c_size_t];hip.hipFree.argtypes=[c.c_void_p]
    hip.mock_expect.argtypes=[c.c_uint,c.c_uint,c.c_uint,c.c_uint,c.POINTER(c.c_float)]
    hip.mock_trace.restype=hip.mock_uploaded.restype=c.c_char_p
    for key in ('allocations','live','prefix_calls','launches','host_calls','replays','captures','graphs'):
        getattr(hip,'mock_'+key).restype=c.c_size_t
    lib.lmxxf_create.argtypes=[c.POINTER(Config),c.POINTER(c.c_void_p),c.c_char_p,c.c_size_t]
    lib.lmxxf_enqueue.argtypes=[c.c_void_p,c.POINTER(Frame),c.c_char_p,c.c_size_t]
    lib.lmxxf_finish.argtypes=[c.c_void_p,c.c_char_p,c.c_size_t]
    lib.lmxxf_destroy.argtypes=[c.POINTER(c.c_void_p),c.c_char_p,c.c_size_t]
    lib.lmxxf_get_submission_stats.argtypes=[c.c_void_p,c.POINTER(Stats)]
    w,h=a.width,a.height;n=w*h
    buffers=[c.c_void_p() for _ in range(5)]
    for ptr,size in zip(buffers,(n*12,n*12,n*12,n*16,n*16)):
        assert hip.hipMalloc(c.byref(ptr),size)==0
    cfg=Config(3,40,w,h,a.assets.encode(),a.modules.encode(),a.stream)
    ctx=c.c_void_p();err=c.create_string_buffer(384)
    assert lib.lmxxf_create(c.byref(cfg),c.byref(ctx),err,len(err))==0,err.value
    profiles=((.0625,0,0,0,1,1),(.0625,1,1,.0078125,1,1),(.0625,0,0,0,1.2,1.3))
    records=[]
    hip.mock_graph_failure(a.failure if a.failure!=6 else 0)
    for i,(seed,history) in enumerate(zip((0,1,0xffffffff,123,900001,0),(0,1,1,0,1,0))):
        prefix=Prefix((c.c_float*6)(*profiles[i%3]))
        frame=Frame(3,96,w,h,buffers[i%2],buffers[2] if history else None,buffers[3+i%2],n*12,n*12 if history else 0,n*16,seed,0,prefix)
        hip.mock_expect(w,h,seed,history,prefix.values)
        before=hip.mock_prefix_calls();calls=hip.mock_host_calls()
        if a.failure==6 and i==2:
            hip.mock_graph_failure(6)
            assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==2
            assert b'game graph replay' in err.value and hip.mock_prefix_calls()==before+1
            break
        assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==0,err.value
        assert hip.mock_prefix_calls()==before+1
        assert lib.lmxxf_finish(ctx,err,len(err))==0,err.value
        stats=Stats();stats.bytes=c.sizeof(stats)
        assert lib.lmxxf_get_submission_stats(ctx,c.byref(stats))==0
        records.append(dict(trace=hip.mock_trace().decode(),uploads=hip.mock_uploaded().decode(),mode=stats.mode,builds=stats.builds,replays=stats.replays,direct=stats.direct,nodes=stats.nodes,host_calls=hip.mock_host_calls()-calls))
        if i==0:warm=hip.mock_allocations()
        else:assert hip.mock_allocations()==warm
    if a.mode=='graph' and not a.failure:
        assert records[0]['mode']==1 and all(r['mode']==2 for r in records[1:])
        assert stats.builds==1 and stats.replays==5 and stats.direct==1 and stats.nodes>100
        assert hip.mock_captures()==1
        assert all(r['host_calls'] in ((3,4) if a.legacy_io else (2,)) for r in records[2:])
    if a.mode=='noapi' or a.failure not in (0,6):
        assert stats.mode==3 and stats.builds==0 and stats.replays==0 and stats.direct==6 and stats.reason
        assert hip.mock_captures()<=1
    if a.mode=='direct':assert stats.mode==0 and stats.direct==6 and hip.mock_captures()==0
    # A failed prefix OR a partially launched graph poisons the context.
    if a.failure!=6:
        # Head failure reaches the core, so start a fresh frame in the model
        # rather than carrying over the previous frame's gather-map oracle.
        hip.mock_expect(w,h,seed,history,prefix.values)
        hip.mock_failure(2 if a.head_failure else 1,0)
        assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==2
    calls=hip.mock_host_calls();assert lib.lmxxf_enqueue(ctx,c.byref(frame),err,len(err))==2
    assert hip.mock_host_calls()==calls
    live=hip.mock_live();graphs=hip.mock_graphs();hip.mock_failure(0,1)
    assert lib.lmxxf_destroy(c.byref(ctx),err,len(err))==3 and ctx.value
    assert hip.mock_live()==live and hip.mock_graphs()==graphs
    hip.mock_failure(0,0);hip.mock_graph_failure(0)
    assert lib.lmxxf_destroy(c.byref(ctx),err,len(err))==0 and not ctx.value
    assert hip.mock_live()==len(buffers) and hip.mock_graphs()==0
    for ptr in buffers:assert hip.hipFree(ptr)==0
    assert hip.mock_live()==0
    Path(a.output).write_text(json.dumps(records))

def main():
    p=argparse.ArgumentParser();p.add_argument('mock');p.add_argument('resident');p.add_argument('assets');p.add_argument('modules')
    p.add_argument('--legacy-io',action='store_true');p.add_argument('--head-failure',action='store_true');p.add_argument('--missing-api');p.add_argument('--child',action='store_true');p.add_argument('--mode',default='graph')
    p.add_argument('--sample-shapes',action='store_true',help='Only the new 1792x768/2048x896 geometry cases; no repeat of unrelated failure cases')
    p.add_argument('--sample-large',action='store_true',help='Only 2304x1024; limit execution to this geometry')
    p.add_argument('--automatic-geometries',action='store_true',help='Unlisted geometries, attention padding, minimum and maximum capacity')
    p.add_argument('--width',type=int,default=2176);p.add_argument('--height',type=int,default=896)
    p.add_argument('--stream',type=int,default=0);p.add_argument('--failure',type=int,default=0);p.add_argument('--output')
    a=p.parse_args()
    for k in ('mock','resident','assets','modules'):setattr(a,k,str(Path(getattr(a,k)).resolve()))
    if a.child:return child(a)
    with tempfile.TemporaryDirectory(prefix='lmxxf-graph-') as temp:
        def run(mode,w=2176,h=896,stream=0,failure=0,mock=None):
            out=Path(temp)/f'{mode}-{w}-{h}-{stream}-{failure}.json'
            subprocess.run([sys.executable,__file__,mock or a.mock,a.resident,a.assets,a.modules,'--child','--mode',mode,'--width',str(w),'--height',str(h),'--stream',str(stream),'--failure',str(failure),'--output',str(out)]+(['--legacy-io'] if a.legacy_io else []),check=True)
            return json.loads(out.read_text())
        shapes=((2304,1024),(64,64),(1024,1024),(1088,704),(1920,1088),(40960,64)) if a.automatic_geometries else ((2304,1024),) if a.sample_large else ((1792,768),(2048,896)) if a.sample_shapes else ((2176,896),(2432,1024))
        for w,h in shapes:
            for stream in (0,0x5550):
                direct=run('direct',w,h,stream);graph=run('graph',w,h,stream)
                assert [r['trace'] for r in direct]==[r['trace'] for r in graph], 'command/argument/order mismatch'
                if a.sample_shapes or a.sample_large:assert graph[-1]['nodes']==((250 if w in (1792,2304) else 254)-(0 if a.legacy_io else 1))
                print(f'GRAPH_CONTRACT shape={w}x{h} stream={stream} all_6_frames_exact=passed nodes={graph[-1]["nodes"]} direct_calls={direct[-1]["host_calls"]} replay_calls={graph[-1]["host_calls"]} fresh_seed_history_features=passed',flush=True)
        if a.sample_shapes or a.sample_large or a.automatic_geometries:return
        direct=run('direct')
        for failure in (1,2,3,4,5,7,8):
            fallback=run('graph',failure=failure)
            assert [r['trace'] for r in direct]==[r['trace'] for r in fallback]
            print(f'GRAPH_FAILURE stage={failure} fallback_once=passed all_6_frames_exact=passed',flush=True)
        run('graph',failure=6)
        print('GRAPH_PARTIAL_LAUNCH no_retry_poison_and_failed_drain_lifetime=passed',flush=True)
        if a.missing_api:
            fallback=run('noapi',mock=str(Path(a.missing_api).resolve()))
            assert [r['trace'] for r in direct]==[r['trace'] for r in fallback]
            print('GRAPH_MISSING_API direct_fallback_and_exact_commands=passed',flush=True)
if __name__=='__main__':main()
