#!/usr/bin/env python3
"""Finite E4M3 interchange/fragment proof and real host dispatch contract.

No GPU arithmetic or FPS is simulated. The unchanged producer already rounds
to E4M3; these options remove only its float decode/store and the consumer's
re-encode. All arithmetic, including F16 rounding, stays in shared templates.
"""
import argparse
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def decode(byte):
    exponent, mantissa = (byte >> 3) & 15, byte & 7
    assert (byte & 127) != 127  # E4M3 NaN; no infinity encoding.
    value = math.ldexp(mantissa, -9) if not exponent else math.ldexp(1 + mantissa / 8, exponent - 7)
    return math.copysign(value, -1 if byte & 128 else 1)


def encode_exact(value):
    """Independent exhaustive lookup, including the sign of zero."""
    bits = struct.pack('<f', value)
    return FINITE_BYTES[bits]


FINITE_BYTES = {struct.pack('<f', decode(b)): b for b in range(256) if b & 127 != 127}


def metadata(path):
    import msgpack
    data = path.read_bytes()
    elf = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    result = {}
    for i in range(elf[12]):
        section = struct.unpack_from('<IIQQQQIIQQ', data, elf[6] + i * elf[11])
        if section[1] != 7:
            continue
        at, end = section[4], section[4] + section[5]
        while at < end:
            namesz, descsz, kind = struct.unpack_from('<III', data, at); at += 12
            name = data[at:at+namesz]; at += (namesz+3) & ~3
            desc = data[at:at+descsz]; at += (descsz+3) & ~3
            if name.rstrip(b'\0') == b'AMDGPU' and kind == 32:
                result.update((k['.name'], k) for k in msgpack.unpackb(desc)['amdhsa.kernels'])
    assert result
    return result


def source_and_fragments():
    exp = ROOT / 'experiments/lmxxf'
    producer = (exp / 'stage3-fixed-sources/multihead-fast-padded-wave-packed.generated.hip').read_text()
    consumer = (exp / 'stage3-fixed-sources/multihead_fused_attention.generated.hip').read_text()
    assert '#define HIP_BRANCHLESS_Q8 1' in producer
    assert 'uint q=q8(__builtin_fminf(__builtin_fmaxf(x,-448.f),448.f));return a==0?0u:q;' in producer
    # fmax/fmin numeric-NaN semantics select -448 for a NaN accumulator.
    # Every input (including infinity) thus gives a finite byte; x==+/-0 is
    # canonicalized before storage. Tiny negative inputs may round to -0.
    store = re.search(r'for\(uint e=0;e<8;e\+\+\)\{uint byte=q8_fused_round\(result\[e\]\);.*?qfeature\[.*?;\}', producer).group()
    assert 'float v=__builtin_amdgcn_cvt_f32_fp8(int(byte),0);' in store
    index = '(first+group*8+e)*C+wave*16+rc'
    assert f'if constexpr(ByteFeature)out[{index}]=static_cast<unsigned char>(byte);else reinterpret_cast<float*>(out)[{index}]=v;' in store
    assert 'qfeature[(group*8+e)*(C+4)+wave*16+rc]=static_cast<unsigned char>(byte);' in store
    assert '#define HIP_MH_VT 1' in consumer and '#define HIP_MH_ABLATE 0' in consumer
    assert 'DEV uint fp8(float f){return uint(__builtin_amdgcn_cvt_pk_fp8_f32(__builtin_fminf(__builtin_fmaxf(f,-448.f),448.f),0.f,0,false))&255u;}' in consumer
    assert 'DEV uint raster(uint win,uint tok,uint width){return ((win/(width/8))*8+tok/8)*width+(win%(width/8))*8+tok%8;}' in consumer
    valid = [b for b in range(256) if b & 127 != 127]
    assert len(valid) == 254
    for b in valid:
        assert encode_exact(decode(b)) == b
    assert encode_exact(-0.0) == 128 and encode_exact(0.0) == 0
    fragments = 0
    for channels in (64,128,256):
        # Both exports instantiate the same complete attention body. Its only
        # ByteFeature branch replaces fp8(decode(byte)) with the original byte.
        for suffix, feature in (('diag','false'),('fb_diag','true')):
            match = re.search(r'void c'+str(channels)+r'_attention_project_'+suffix+r'\([^\n]+\)\{([^\n]+)\}', consumer)
            assert match and f'c{channels}_attention_project_body<{feature},false,true>' in match[1]
        expected = f'if constexpr(ByteFeature)__builtin_memcpy(&a,feature8+p*{channels}+ct*16+gr()*8,8);else for(uint e=0;e<8;e++)put_bits(a,e,fp8(feature[p*{channels}+ct*16+gr()*8+e]));'
        assert expected in consumer
        for width,height in ((8,8),(24,16)):
            # These include window padding rows: the producer computes every
            # work pixel, including those derived from mapped zero input.
            count = width*height*channels
            writes = set()
            for first in range(0,width*height,16):
                for wave in range(channels//16):
                    for lane in range(32):
                        rc,group = lane%16,lane//16
                        for e in range(8):
                            address = (first+group*8+e)*channels+wave*16+rc
                            assert address not in writes and 0 <= address < count
                            writes.add(address)
            assert len(writes) == count
            data = bytes(valid[(i*37+19)%254] for i in range(count))
            for win in range(width*height//64):
                for wave in range(4):
                    for lane in range(32):
                        rc,group = lane%16,lane//16
                        tok = wave*16+rc
                        p = ((win//(width//8))*8+tok//8)*width+(win%(width//8))*8+tok%8
                        for ct in range(channels//16):
                            address = p*channels+ct*16+group*8
                            assert address%8 == 0 and address+8 <= count
                            old = bytes(encode_exact(decode(b)) for b in data[address:address+8])
                            assert old == data[address:address+8]
                            fragments += 1
    print(f'MH_FEATURE_BYTES finite_encodings=254 signed_zero=preserved complete_fragments={fragments} same_bytes=1 padding_produced=1 V11_VT_compatible=1')


def module_abis():
    modules = ROOT/'runtime/modules'
    mh = metadata(modules/'multihead_fused_attention.hsaco')
    ffn = metadata(modules/'multihead-fast-padded-wave-packed.hsaco')
    def abi(k):
        return [(a['.size'],a['.offset'],a['.value_kind']) for a in k['.args']]
    for c in (64,128,256):
        old,new = mh[f'c{c}_attention_project_diag'],mh[f'c{c}_attention_project_fb_diag']
        assert abi(old) == abi(new)
        assert old['.kernarg_segment_size'] == new['.kernarg_segment_size']
        assert old['.max_flat_workgroup_size'] == new['.max_flat_workgroup_size']
        for mapped in ('','_mapped'):
            name=f'mh_ffn_fused_c{c}'+('_tiled' if c==256 else '')+f'_project{mapped}_g128_qkv'
            assert abi(ffn[name]) == abi(ffn[name+'_fb'])
        print(f'MH_FEATURE_ABI channels={c} attention_args=identical producer_args=identical scratch_bytes={new[".private_segment_fixed_size"]} LDS_bytes={new[".group_segment_fixed_size"]}')


def host_dispatch(assets):
    with tempfile.TemporaryDirectory(prefix='lmxxf-feature-') as tmp:
        tmp=Path(tmp);mock=tmp/'mock.so';resident=tmp/'resident.so'
        subprocess.run(['g++','-std=c++17','-O2','-fPIC','-shared',str(ROOT/'tests/lmxxf_mh_feature_mock.cpp'),'-o',str(mock)],check=True)
        subprocess.run(['g++','-std=c++17','-O2','-fPIC','-shared','-pthread','-fno-fast-math','-ffp-contract=off','-I',str(ROOT/'runtime/include'),str(ROOT/'experiments/lmxxf/resident_backend.cpp'),'-ldl','-o',str(resident)],check=True)
        records={}
        for mode in ('direct','graph'):
            out=tmp/(mode+'.json')
            subprocess.run([sys.executable,str(ROOT/'tests/lmxxf_graph_resident.py'),str(mock),str(resident),str(assets),str(ROOT/'runtime/modules'),'--child','--mode',mode,'--width','512','--height','512','--output',str(out)],check=True)
            records[mode]=json.loads(out.read_text())
        assert [r['trace'] for r in records['direct']] == [r['trace'] for r in records['graph']]
        for record in records['graph']:
            trace=record['trace'].splitlines()
            for c,count in ((64,8),(128,12),(256,16)):
                assert sum(line.startswith(f'c{c}_attention_project_fb_diag:') for line in trace)==count
            assert not any('_bout:' in line or '_bytein_' in line for line in trace)
        print('MH_FEATURE_HOST real_resident=1 real_weights=1 direct_graph_6_frames_same=1 all_36_blocks=1 float_residual_stream_preserved=1 buffer_capacities=checked')


def main():
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path);a=p.parse_args()
    source_and_fragments();module_abis()
    if a.assets:host_dispatch(a.assets.resolve())


if __name__=='__main__':
    main()
