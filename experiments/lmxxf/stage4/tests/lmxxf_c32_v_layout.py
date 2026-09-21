#!/usr/bin/env python3
"""Verify every AV matrix fragment and the lifetime of in-place C32 V bytes.

This is a CPU address/byte proof. It does not execute GPU matrix arithmetic or
measure runtime performance. The source delta audit separately preserves the
complete neural arithmetic and WMMA accumulation order.
"""
from pathlib import Path
import hashlib
import re
import subprocess


def check_layout(source_path):
    source = source_path.read_text()
    assert '#define HIP_C32_VT 1' in source
    assert '#define HIP_C32_LOCAL_ATTN_SYNC 0' in source
    assert '#if HIP_C32_VT && HIP_C32_LOCAL_ATTN_SYNC\n#error "In-place C32 V transpose requires group-wide probability rows"\n#endif' in source
    assert '#define HIP_C32_ALIAS_FFN_V 1' in source
    assert '#define HIP_C32_REGISTER_FFN 1' in source
    assert 'unsigned char*vt=packed+128*36;' in source
    assert 'unsigned char vt[32*68]' not in source
    assert 'if(part==2)sync_window();else sync_owned_rows();f8 sum{};' in source
    assert 'sync_window(); // Attention reads K/V rows owned by all four waves.' in source
    for local_sync in (0, 1):
        result = subprocess.run(['c++', '-E', '-x', 'c++',
                                 f'-DHIP_C32_LOCAL_ATTN_SYNC={local_sync}', str(source_path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if local_sync:
            assert result.returncode != 0
            assert 'In-place C32 V transpose requires group-wide probability rows' in result.stderr
        else:
            assert result.returncode == 0, result.stderr

    # Extract the actual producer/consumer address formulas from production.
    producer = re.search(r'if\(part==2\)vt\[(.*?)\]=', source).group(1)
    consumer = re.search(r'__builtin_memcpy\(&b,vt\+(.*?),8\);', source).group(1)
    probability = re.search(r'__builtin_memcpy\(&a,prob\+(.*?),8\);', source).group(1)
    producer = producer.replace('rc()', 'rc')
    consumer = consumer.replace('rc()', 'rc').replace('gr()', 'gr')
    probability = probability.replace('rc()', 'rc').replace('gr()', 'gr')
    assert producer == '(col+rc)*68+row'
    assert consumer == '(col+rc)*68+kt*16+gr*8'
    assert probability == '(first+rc)*68+kt*16+gr*8'

    v_bytes = 64 * 36
    transposed_bytes = 32 * 68
    assert transposed_bytes <= v_bytes
    addresses = set()
    cross_wave_overwrites = 0
    for wave in range(4):
        for col in (0, 16):
            for lane in range(32):
                rc, gr = lane % 16, lane // 16
                for e in range(8):
                    row = wave * 16 + gr * 8 + e
                    address = eval(producer, {'__builtins__': {}},
                                   dict(col=col, rc=rc, row=row))
                    assert 0 <= address < v_bytes
                    assert address not in addresses
                    addresses.add(address)
                    # The old FFN plane has 36-byte rows, owned 16 per wave.
                    if (address // 36) // 16 != wave:
                        cross_wave_overwrites += 1
    assert len(addresses) == 64 * 32
    assert cross_wave_overwrites > 0  # A wave-local fence would be insufficient.

    fragments = 0
    for salt in (0, 1, 17, 127, 255):
        old = bytearray(v_bytes)
        new = bytearray([0xA5] * v_bytes)
        probs = bytes((i * 47 + salt) & 255 for i in range(64 * 68))
        for wave in range(4):
            for col in (0, 16):
                for lane in range(32):
                    rc, gr = lane % 16, lane // 16
                    for e in range(8):
                        row = wave * 16 + gr * 8 + e
                        value = (row * 37 + (col + rc) * 53 + salt) & 255
                        old[row * 36 + col + rc] = value
                        address = eval(producer, {'__builtins__': {}},
                                       dict(col=col, rc=rc, row=row))
                        new[address] = value
        # Check all waves, output fragments, K tiles, lanes and eight byte slots.
        for wave in range(4):
            for col in (0, 16):
                for kt in range(4):
                    for lane in range(32):
                        rc, gr = lane % 16, lane // 16
                        address = eval(consumer, {'__builtins__': {}},
                                       dict(col=col, rc=rc, kt=kt, gr=gr))
                        expected = bytes(old[(kt*16+gr*8+e)*36+col+rc]
                                         for e in range(8))
                        assert bytes(new[address:address+8]) == expected
                        a_address = eval(probability, {'__builtins__': {}},
                                         dict(first=wave*16, rc=rc, kt=kt, gr=gr))
                        a_expected = bytes(probs[(wave*16+rc)*68+kt*16+gr*8+e]
                                           for e in range(8))
                        assert probs[a_address:a_address+8] == a_expected
                        fragments += 1
        assert all(new[i] == 0xA5 for i in range(v_bytes) if i not in addresses)

    # Publication is after all FFN reads for part 2 and before all V writes.
    qkv = source[source.index('C32_LOOP for(uint part=0;part<3;part++){'):
                 source.index('// Q/K packed rows:')]
    assert (qkv.index('a=load8(ffn8+') <
            qkv.index('if(part==2)sync_window();') <
            qkv.index('if(part==2)vt[') <
            qkv.index('sync_window(); // Attention reads K/V'))
    print(f'C32_V_LAYOUT source={source_path.name} fragments={fragments} identical_bytes=1 '
          f'cross_wave_aliases={cross_wave_overwrites} added_lds_bytes=0 '
          'global_publication_barriers=verified')


def main():
    exp = Path(__file__).resolve().parents[1] / 'experiments/lmxxf'
    packed = exp / 'stage3-fixed-sources/c32_fused_ffn_attention-packed.generated.hip'
    for source_path in (exp / 'game-io.generated.hip', packed):
        check_layout(source_path)

    # Removing only the declared layout/barrier edits must recover the complete
    # pinned upstream file, including every wrapper and arithmetic expression.
    source = packed.read_text()
    header = ('// Packed C32 attention: in-place transposed V, unchanged neural arithmetic.\n'
              '#define HIP_ISA_HALF 1\n#define HIP_PREPACKED_WEIGHTS 1\n'
              '#define HIP_C32_DIAG_WEIGHTS 1\n')
    assert source.startswith(header) and source.endswith('\n')
    original = source[len(header):-1]
    original = original.replace(
        '#define HIP_C32_VT 1 /* In-place V transpose: contiguous AV B fragments, same bytes and LDS size. */',
        '#define HIP_C32_VT 0 /* 1: V stored transposed in its own LDS array so the AV B fragments load as 8 contiguous bytes; same bytes */')
    original = original.replace(
        '#if HIP_C32_VT && HIP_C32_LOCAL_ATTN_SYNC\n#error "In-place C32 V transpose requires group-wide probability rows"\n#endif\n', '')
    original = original.replace(
        ' // Keep the three Q/K/V phases specialized across the V publication barrier.\n#if !HIP_C32_NO_UNROLL\n#pragma unroll\n#endif\n', '')
    original = original.replace(
        ' unsigned char*vt=packed+128*36; // 32x68 transposed bytes fit the existing 64x36 V plane; no added LDS',
        ' __attribute__((shared)) unsigned char vt[32*68]; // V transposed [col][key]: the AV B fragment is 8 contiguous bytes (the [key][col] rows needed 8 byte gathers per fragment)')
    original = original.replace(
        '  // Transposed V stores can overwrite another wave\'s aliased FFN bytes.\n  // Every wave has finished its V matrix reads at this barrier.\n  if(part==2)sync_window();else sync_owned_rows();f8 sum{};',
        '  sync_owned_rows();f8 sum{};')
    assert hashlib.sha256(original.encode()).hexdigest() == '4e54ded35834d6ef0579340871317a01b7d6a4f224f23ff62577fd47843fee64'
    print('C32_PACKED_SOURCE_AUDIT pinned_upstream_restored=1 neural_arithmetic_unchanged=1')


if __name__ == '__main__':
    main()
