#!/usr/bin/env python3
"""Compare v8/v9: remove RGB/RGBA adapters; preserve all neural arguments.

Real resident/weights/modules, HIP command model in CPU. Does not execute
GPU arithmetic or measure FPS. Fresh addresses alternate every frame.
"""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path


def compare(old,new,pixels):
    assert len(old)==len(new)==6
    for a,b in zip(old,new,strict=True):
        before=[line.split(':') for line in a['trace'].splitlines()]
        after=[line.split(':') for line in b['trace'].splitlines()]
        prefix_at=next(i for i,row in enumerate(before) if row[0]=='lmxxf_game_prefix')
        incoming=[row for row in before[:prefix_at] if row[0]=='lmxxf_rgb_to_rgba']
        outgoing=[row for row in before[prefix_at:] if row[0]=='lmxxf_rgb_to_rgba']
        assert len(incoming) in (1,2) and len(outgoing)==1
        for row in incoming+outgoing:
            assert int.from_bytes(bytes.fromhex(row[5]),'little')==pixels
        adapters={row[4]:row[3] for row in incoming}
        old_prefix=before[prefix_at];old_prefix[0]='lmxxf_game_prefix_rgb'
        old_prefix[3]=adapters[old_prefix[3]];old_prefix[4]=adapters[old_prefix[4]]
        old_head=next(row for row in before if row[0]=='c32_post_merge_head_half')
        old_head[0]='lmxxf_game_head_rgba';old_head[8]=adapters[old_head[8]]
        assert old_head[10]==outgoing[0][3]
        old_head[10]=outgoing[0][4]
        before=[row for row in before if row[0]!='lmxxf_rgb_to_rgba']
        assert all(row[0]!='lmxxf_rgb_to_rgba' for row in after)
        assert b['nodes']==a['nodes']-1 if a['mode']==2 else b['nodes']==0
        assert b['builds']==a['builds'] and b['replays']==a['replays']
        uploads=[]
        for record in (a,b):
            uploads.append({v[0]:v[1:] for line in record['uploads'].splitlines() if (v:=line.split(':'))})
        forward,reverse={},{}
        for left,right in zip(before,after,strict=True):
            for x,y in zip(left,right,strict=True):
                if '+' not in x: assert x==y,(left,right)
                else:
                    oi,oo=x.split('+');ni,no=y.split('+')
                    assert oo==no and forward.setdefault(oi,ni)==ni and reverse.setdefault(ni,oi)==oi,(left,right)
                    if oi in uploads[0]:assert uploads[0][oi]==uploads[1][ni],'weight/map bytes differ'


def main():
    p=argparse.ArgumentParser();p.add_argument('mock');p.add_argument('v8');p.add_argument('v9');p.add_argument('assets');p.add_argument('modules');a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='lmxxf-game-io-') as temp:
        for width,height in ((2176,896),(2432,1024),(2304,1024),(2048,896),(64,64)):
            for stream in (0,0x5550):
                result=[]
                for name in ('v8','v9'):
                    out=Path(temp)/(name+'.json')
                    cmd=[sys.executable,str(Path(__file__).with_name('lmxxf_graph_resident.py')),a.mock,getattr(a,name),a.assets,a.modules,'--child','--width',str(width),'--height',str(height),'--stream',str(stream),'--output',str(out)]
                    if name=='v8':cmd+=['--legacy-io']
                    subprocess.run(cmd,check=True);result.append(json.loads(out.read_text()))
                compare(*result,width*height)
                print(f'GAME_IO_PARITY shape={width}x{height} stream={stream} frames=6 core_commands_arguments=equivalent uploaded_weights=identical converters_removed=2_or_3 fresh_external_buffers=passed',flush=True)


if __name__=='__main__':main()
