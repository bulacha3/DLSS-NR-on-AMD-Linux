#!/usr/bin/env python3
"""Convert the pinned NVIDIA archive to the 184 lmxxf host tensors on CPU.

MIT upstream formulas are credited in WEIGHTS.md and LICENSE.upstream. C32
connectivity and multihead residual maps were recovered from the supplied
310.8.0.0 CUBINs; see layout-recovery.json. Static recovery and lossless
coefficient conversion are NOT original-GPU arithmetic or image parity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

import weight_assets


def bits(count, positions):
    source = np.arange(count, dtype=np.int32)
    result = np.zeros(count, dtype=np.int32)
    for target, position in enumerate(positions):
        result |= ((source >> position) & 1) << target
    return result


def fp8(raw):
    """Exact E4M3FN -> binary32, including signed zero; reject NaN codes."""
    raw = np.asarray(raw, dtype=np.uint8)
    if np.any((raw & 127) == 127):
        raise ValueError("Nonfinite E4M3 coefficient")
    exponent = ((raw >> 3) & 15).astype(np.int16)
    mantissa = (raw & 7).astype(np.float32)
    value = np.where(exponent == 0, np.ldexp(mantissa, -9),
                     np.ldexp(1 + mantissa / 8, exponent - 7))
    return np.copysign(value, np.where(raw & 128, -1, 1)).astype(np.float32)


def matrix(raw, shape, row_bits, col_bits, *, sparse=False):
    rows, cols = bits(len(raw), row_bits), bits(len(raw), col_bits)
    indices = rows.astype(np.int64) * shape[1] + cols
    if (rows.max() >= shape[0] or cols.max() >= shape[1]
            or len(np.unique(indices)) != len(raw)
            or (not sparse and len(raw) != shape[0] * shape[1])):
        raise ValueError("Incomplete, overlapping, or out-of-range matrix map")
    # C>=64 W2 is a grouped sparse operator, as in the upstream reference.
    # Its structural zero entries are not missing model coefficients.
    result = np.zeros(shape, dtype=np.float32) if sparse else np.empty(shape, np.float32)
    decoded = fp8(raw)
    result[rows, cols] = decoded
    if not np.array_equal(result[rows, cols].view(np.uint32), decoded.view(np.uint32)):
        raise ValueError("Coefficient assignment did not round-trip")
    return result


def order(channels):
    if channels == 32:
        return np.array([0,1,4,5,8,9,12,13,2,3,6,7,10,11,14,15,
                         16,17,20,21,24,25,28,29,18,19,22,23,26,27,30,31])
    i = np.arange(channels)
    return (i // 16) * 16 + (i % 8) * 2 + (i % 16 // 8)


def half(raw):
    result = np.ascontiguousarray(raw).view('<f2').astype(np.float32)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite half coefficient")
    return result


def skip(raw, channels):
    result = np.empty(channels, np.float32)
    result[order(channels)] = half(raw)
    return result


def bias(raw, channels):
    n = (channels // 32) * 4096
    if len(raw) != 2 * n:
        raise ValueError("Bias length mismatch")
    heads = bits(n, list(range(12, 12 + (channels // 32).bit_length() - 1)))
    query, key = bits(n, [5,6,10,7,1,11]), bits(n, [0,3,8,4,2,9])
    index = heads * 4096 + query * 64 + key
    if len(np.unique(index)) != n:
        raise ValueError("Bias permutation is not bijective")
    result = np.empty((channels // 32, 64, 64), np.float32)
    result[heads, query, key] = half(raw)
    return result


def joined(*arrays):
    result = np.concatenate([np.asarray(x, np.float32).ravel() for x in arrays])
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite prepared coefficient")
    return result.astype('<f4', copy=False)


def c32(raw, mix=None):
    if len(raw) not in (20672, 22720):
        raise ValueError("C32 body length mismatch")
    w1 = matrix(raw[:4096], (128,32), [3,6,7,8,9,10,11], [0,1,4,5,2])
    w2 = matrix(raw[4096:8192], (32,128), [6,3,7,8,9], [1,0,4,5,2,10,11])
    qkv = [matrix(raw[8288+1024*i:9312+1024*i], (32,32),
                  [3,6,7,8,9], [0,1,4,5,2]) for i in range(3)]
    projection = matrix(raw[19568:20592], (32,32), [6,3,7,8,9], [1,0,4,5,2])
    fs, ats = skip(raw[8208:8272],32), skip(raw[20592:20656],32)
    return (joined(np.zeros(512,np.float32) if mix is None else mix, w1, w2, fs),
            joined(*qkv, projection, bias(raw[11360:19552],32),
                   raw[19552:19556].view('<f4'), ats))


CONTRACT = {
    64: (0x7010,0xe0a0,0xe0b0,0xa0a0,0xf0b0,0x70a0),
    128: (0x18010,0x2c120,0x2c130,0x24120,0x30130,0x18120),
    256: (0x58010,0x98220,0x98240,0x88220,0xa8240,0x58220),
}


def multihead(raw, C):
    d = C.bit_length() - 1
    group = list(range(12,d+7))
    b2, b3 = 4*C*C, 4*C*C+C*128
    w1 = matrix(raw[:b2], (4*C,C), [3,6,7,8,9,10,11]+list(range(d+7,2*d+2)), [1,0,4,5,2]+group)
    w2 = matrix(raw[b2:b3], (C,4*C), [3,6,7,8,9]+group, [1,0,4,5,2,10,11]+group, sparse=True)
    ob, ib = [3,6,7,8,9]+list(range(10,d+5)), [1,0,4,5,2]+list(range(d+5,2*d))
    w3 = matrix(raw[b3:b3+C*C], (C,C), ob, ib)
    fs, sc, p, bi, ats, q = CONTRACT[C]
    i = np.arange(C*C)
    qkv = [matrix(raw[q+(i//1024)*3072+j*1024+i%1024], (C,C), ob, ib) for j in range(3)]
    return (joined(w1,w2,w3,skip(raw[fs:fs+2*C],C)),
            joined(*qkv,matrix(raw[p:p+C*C],(C,C),ob,ib),bias(raw[bi:sc],C),
                   raw[sc:sc+4*(C//32)].view('<f4'),skip(raw[ats:ats+2*C],C)))


def split(raws):
    C = 512
    ob, ib = [3,6,7,8,9,10,11,12,13], [1,0,4,5,2,14,15,16,17]
    m = lambda r: matrix(r,(C,C),ob,ib)
    expand, contract = [], []
    for g in range(8):
        expand.append(matrix(raws[0][0x40000+g*16384:0x40000+(g+1)*16384], (256,64),
                             [3,6,7,8,9,10,11,12], [1,0,4,5,2,13]))
        contract.append(matrix(raws[0][0x60000+g*16384:0x60000+(g+1)*16384], (64,256),
                               [3,6,7,8,9,10], [1,0,4,5,2,11,12,13]))
    i = np.arange(C*C)
    qkv = [m(raws[2][(i//1024)*3072+j*1024+i%1024]) for j in range(3)]
    return (joined(m(raws[0][:262144]),expand,contract),
            joined(m(raws[1][:262144]),skip(raws[1][262144:],C)),
            joined(*qkv,m(raws[3][:262144]),bias(raws[2][0xc0000:0xe0000],C),
                   raws[2][0xe0000:].view('<f4'),skip(raws[3][262144:],C)))


def vit_matrix(raw, inputs, outputs):
    ib, ob = inputs.bit_length()-1, outputs.bit_length()-1
    return matrix(raw,(outputs,inputs),[6,3,9,7,8]+list(range(10,ob+5)),
                  [0,1,2,4,5]+list(range(ob+5,ib+ob)))


def vit(raws):
    i = np.arange(1024)
    # Upstream axis_permutation(1024, MATRIX_OUTPUT_TO_RAW): gather, not scatter.
    permutation = (i&~31)|((i&1))|((i&2)<<2)|((i&4)<<2)|((i&8)>>2)|((i&16)>>2)
    result = [vit_matrix(raws[0][:4194304],1024,4096)]
    result.append(joined(vit_matrix(raws[1][:4194304],4096,1024),half(raws[1][4194304:])[permutation]))
    packed = raws[2][128:].reshape(-1,3,1024)
    result.append(joined(*[vit_matrix(packed[:,j,:].ravel(),1024,1024) for j in range(3)],raws[2][:128].view('<f4')))
    result.append(joined(vit_matrix(raws[4][:1048576],1024,1024),half(raws[4][1048576:])[permutation]))
    return result


def upsample(raw, C):
    if C==32:
        ordinary=np.zeros(20672,np.uint8)
        ordinary[:0x2000]=raw[:0x2000]
        ordinary[0x2000:0x2060]=raw[0x2800:0x2860]
        ordinary[0x2060:]=raw[0x28a0:]
        m=matrix(raw[0x2000:0x2800],(32,64),[3,6,7,8,9],[1,0,4,5,2,10])
        i=np.arange(32);other=(i//16)*16+(i%8)*2+(i%16//8)
        reordered=np.empty_like(m);reordered[order(32)]=m[other]
        return joined(reordered,skip(raw[0x2860:0x28a0],32)),c32(ordinary)
    n, begin, ffskip = {64:(61760,0x7000,0x9000),128:(197184,0x18000,0x20000),256:(689232,0x58000,0x78000)}[C]
    ordinary=np.zeros(n,np.uint8)
    ordinary[:begin]=raw[:begin]
    ordinary[begin+16:begin+16+2*C]=raw[ffskip:ffskip+2*C]
    ordinary[CONTRACT[C][5]:]=raw[ffskip+4*C:]
    d=C.bit_length()-1
    m=matrix(raw[begin:ffskip],(C,2*C),[3]+list(range(6,d+5)),[1,0,4,5,2]+list(range(d+5,2*d+1)))
    return joined(m,skip(raw[ffskip+2*C:ffskip+4*C],C)),multihead(ordinary,C)


def convert_dll(dll: Path, output: Path) -> dict:
    """Hash gate, new-directory transaction, full structural check, no HIP calls."""
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new output directory; existing output is preserved")
    data=dll.read_bytes()
    if hashlib.sha256(data).hexdigest()!=weight_assets.RECORDS['dll_sha256']:
        raise ValueError("DLL differs from the pinned 310.8.0.0 source")
    start=weight_assets.RECORDS['archive_offset']
    archive=data[start:start+weight_assets.RECORDS['archive_size']]
    del data
    records=weight_assets.parse_archive(archive)
    if records!=weight_assets.RECORDS['records']:
        raise ValueError("Archive index differs from the pinned source")
    raw_records={r['name']:np.frombuffer(archive,np.uint8,r['payload_size'],r['payload_offset']) for r in records}
    used=set()
    def raw(block,layer=0):
        name=f'block{block}.layer{layer}.layer';used.add(name);return raw_records[name]
    expected=weight_assets.required_assets()
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.convert-weights-',dir=output.parent))
    written={}
    def put(name,value):
        value=joined(value)
        if name not in expected or value.size!=expected[name] or name in written:
            raise ValueError(f"Tensor contract mismatch: {name}")
        path=staging/(name+'.f32');value.tofile(path)
        written[name]={'elements':int(value.size),'bytes':path.stat().st_size,'sha256':weight_assets.sha256(path)}
    def body(block,values):
        for kind,value in zip(('ffn','attention'),values):put(f'block{block}-{kind}',value)
    try:
        for block in range(70):
            if block==0:
                r=raw(0);ordinary=np.zeros(20672,np.uint8)
                ordinary[:8192]=r[:8192];ordinary[8192:]=r[9216:]
                s=np.arange(512);ch=(s//64)*4+(s//32%2)+(s//4%2)*2;feature=(s//8%4)*4+s%4
                mix=np.empty((32,16),np.float32);mix[ch,feature]=half(r[8208:9232])
                body(0,c32(ordinary,mix));continue
            if 31<=block<=38:
                values=vit({i:raw(block,i) for i in (0,1,2,4)})
                for kind,value in zip(('expand','contract','qkv','projection'),values):put(f'block{block}-{kind}',value)
                continue
            if block==39:
                r=raw(39)
                m=matrix(r[:524288],(512,1024),[3,6,7,8,9,10,11,12,13],[1,0,4,5,2,14,15,16,17,18])
                put('decoder39-weights',joined(m,skip(r[524288:],512)));continue
            C=(32 if block<=4 else 64 if block<=8 else 128 if block<=14 else 256 if block<=22
               else 512 if block<=47 else 256 if block<=55 else 128 if block<=61 else 64 if block<=65 else 32)
            if C==512:
                for kind,value in zip(('ffwd','ffwd-projection','attention'),split([raw(block,i) for i in range(4)])):
                    put(f'block{block}-{kind}',value)
                if block==30:
                    put('head-matrix',matrix(raw(30,4)[:524288],(1024,512),[3,6,7,8,9,10,11,12,13,14],[1,0,4,5,2,15,16,17,18]))
                continue
            r=raw(block)
            if block in (48,56,62,66):
                projection,values=upsample(r,C);put(f'block{block}-weights',projection);body(block,values)
            else:body(block,c32(r) if C==32 else multihead(r,C))
            if block in (4,8,14,22):
                d=C.bit_length()-1
                begin={32:20656,64:0xf130,128:0x30230,256:0xa8440}[C]
                ob=[3,6,7,8,9]+list(range(10,d+6))
                ib=([0,1,4,5,2] if C==32 else [1,0,4,5,2])+list(range(d+6,2*d+1))
                put(f'block{block}-ds',matrix(r[begin:begin+2*C*C],(2*C,C),ob,ib))
        r=raw(70);ordinary=np.zeros(20672,np.uint8)
        ordinary[:0x2050]=r[:0x2050];ordinary[0x2060:]=r[0x20d0:0x5130]
        for kind,value in zip(('ffn','attention'),c32(ordinary)):put('post70-'+kind,value)
        put('post70-scales',joined(skip(r[0x2050:0x2090],32),skip(r[0x2090:0x20d0],32)))
        head=np.empty((16,32),np.float32);head[bits(512,[2,5,6,7]),bits(512,[0,1,3,4,8])]=half(r[0x5130:])
        put('post70-head',head[[0,2,4]])
        if set(written)!=set(expected):raise ValueError("Incomplete prepared tensor set")
        check=weight_assets.inspect_assets(staging)
        if not check['structurally_ready']:raise ValueError(str(check['errors']))
        unused=sorted(set(raw_records)-used)
        allowed_unused=[f'block{i}.layer3.layer' for i in range(31,39)]+['block70.layer0.blend_scale']
        if unused!=sorted(allowed_unused):raise ValueError("Unexpected unconsumed model record")
        result={'format':'lmxxf-direct-dll-conversion-v1','dll_sha256':weight_assets.RECORDS['dll_sha256'],
                'upstream_commit':weight_assets.RECORDS['upstream_commit'],'records_extracted':len(records),
                'records_consumed':len(used),'files_prepared':len(written),'structurally_ready':True,
                'weight_layout_parity_verified':False,'gpu_inference_executed':False,
                'records_not_consumed_by_reference':unused,
                'converter_sha256':weight_assets.sha256(Path(__file__)),
                'layout_recovery_sha256':weight_assets.sha256(Path(__file__).with_name('layout-recovery.json')),
                'bytes':sum(x['bytes'] for x in written.values()),'files':written}
        (staging/'conversion-provenance.json').write_text(json.dumps(result,indent=2)+'\n')
        output.mkdir()
        try:
            for path in staging.iterdir():path.replace(output/path.name)
        except BaseException:
            shutil.rmtree(output);raise
        return result
    finally:shutil.rmtree(staging)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dll',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    result=convert_dll(args.dll,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='files'},indent=2))
