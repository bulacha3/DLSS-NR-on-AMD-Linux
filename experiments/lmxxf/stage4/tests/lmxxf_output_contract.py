#!/usr/bin/env python3
"""Compare v4/v5 commands: remove only the RGB copy, rebind its consumer.

Normalizes allocation identities bijectively; checks every other scalar,
offset, kernel and grid. Does not simulate neural arithmetic or measure FPS.
"""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path

def compare(old,new,pixels):
    forward={};reverse={}
    for a,b in zip(old,new,strict=True):
        assert a['nodes']==255 if a['mode']==2 else a['nodes']==0
        assert b['nodes']==254 if b['mode']==2 else b['nodes']==0
        before=[line.split(':') for line in a['trace'].splitlines()]
        after=[line.split(':') for line in b['trace'].splitlines()]
        indices=[i for i,line in enumerate(before) if line[0]=='copy']
        assert len(indices)==1 and all(line[0]!='copy' for line in after)
        at=indices[0];copy=before.pop(at)
        assert int(copy[3])==pixels*12
        assert before[at][0]=='lmxxf_rgb_to_rgba' and before[at][3]==copy[1]
        before[at][3]=copy[2] # read the same computed tensor without a copy
        assert len(before)==len(after)
        for x,y in zip(before,after,strict=True):
            assert len(x)==len(y)
            for v,w in zip(x,y,strict=True):
                if '+' not in v:assert v==w,(v,w)
                else:
                    old_id,old_offset=v.split('+');new_id,new_offset=w.split('+')
                    assert old_offset==new_offset
                    assert forward.setdefault(old_id,new_id)==new_id
                    assert reverse.setdefault(new_id,old_id)==old_id

def main():
    p=argparse.ArgumentParser();p.add_argument('mock');p.add_argument('v4');p.add_argument('v5');p.add_argument('assets');p.add_argument('modules');a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='lmxxf-output-') as temp:
        for width,height in ((2176,896),(2432,1024)):
            for stream in (0,0x5550):
                results=[]
                for name in ('v4','v5'):
                    out=Path(temp)/f'{name}.json'
                    subprocess.run([sys.executable,str(Path(__file__).with_name('lmxxf_graph_resident.py')),a.mock,getattr(a,name),a.assets,a.modules,'--child','--width',str(width),'--height',str(height),'--stream',str(stream),'--output',str(out)],check=True)
                    results.append(json.loads(out.read_text()))
                compare(*results,width*height)
                print(f'OUTPUT_COPY_REMOVED shape={width}x{height} stream={stream} six_frames_all_other_commands=identical copy_bytes_saved={width*height*12}',flush=True)
if __name__=='__main__':main()
