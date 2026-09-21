#!/usr/bin/env python3
"""Prove V-fragment equivalence and shared-memory ownership without a GPU.

Values are distinct logical (head, token, channel) tags, so a misplaced operand
cannot accidentally pass by matching a repeated byte value. This checks layout
and ordering contracts; it does not measure GPU performance or execute WMMA.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if not (HERE / "build_mh_attention.py").is_file():
    sys.path.insert(0, str(HERE.parent / "experiments/lmxxf"))
from build_mh_attention import generate, UPSTREAM_SHA256


def verify_head(head: int, split_queries: bool = False) -> int:
    allocation = 64 * 36
    old, new = {}, {}
    owners = {}
    # The source producer distributes packed groups of four V bytes across the
    # 128 threads belonging to a head, or 256 in the w16 export. Both layouts
    # share the same allocation; w16 distributes each query across two waves.
    threads = 256 if split_queries else 128
    for tid in range(threads):
        for i in range(tid, 64 * 8, threads):
            token, first_column = divmod(i, 8)
            first_column *= 4
            for q in range(4):
                column = first_column + q
                tag = (head, token, column)
                old[token * 36 + column] = tag
                address = column * 68 + token
                assert 0 <= address < allocation
                assert address not in owners, "multiple writers to a V byte"
                owners[address] = tid
                new[address] = tag
    assert len(new) == 64 * 32
    assert max(new) == 2171
    probability = {row * 68 + key: (head, row, key)
                   for row in range(64) for key in range(64)}
    # The initial sync_window happens after every V producer. Subsequent reads
    # have no writes to V until all AV fragments for the head have been consumed.
    fragments = 0
    for wave in range(threads // 32):
        for lane in range(32):
            rc, group = lane & 15, lane >> 4
            columns = ((wave % 2) * 16,) if split_queries else (0, 16)
            for column_tile in columns:
                column = column_tile + rc
                for key_tile in range(4):
                    first_key = key_tile * 16 + group * 8
                    expected = [(head, first_key + e, column) for e in range(8)]
                    old_fragment = [old[(first_key + e) * 36 + column] for e in range(8)]
                    start = column * 68 + first_key
                    contiguous_fragment = [new[start + e] for e in range(8)]
                    assert contiguous_fragment == old_fragment == expected
                    # A changes from an eight-byte gather to memcpy as well;
                    # its layout stays row-major with the same 68-byte stride.
                    query = (wave // 2 if split_queries else wave) * 16 + rc
                    a_start = query * 68 + first_key
                    assert a_start + 7 < 64 * 66 * 2
                    a_fragment = [probability[a_start + e] for e in range(8)]
                    assert a_fragment == [(head, query, first_key + e) for e in range(8)]
                    fragments += 1
    return fragments


def verify_source(source: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "candidate.hip"
        generate(source, output)
        body = source.read_bytes()
        generated = output.read_bytes()
        prefix = generated[: -len(body) - 1]
        assert generated[len(prefix) : -1] == body
        assert hashlib.sha256(body).hexdigest() == UPSTREAM_SHA256
        assert prefix == (b"#define HIP_ISA_HALF 1\n#define HIP_MH_RTZ_ISA 1\n"
                          b"#define HIP_MH_ABLATE 0\n#define HIP_MH_VT 1\n")
        altered = Path(tmp) / "altered.hip"
        altered.write_bytes(body + b" ")
        try:
            generate(altered, output)
        except ValueError:
            pass
        else:
            raise AssertionError("generator accepted an unpinned source")
    # Verify the relevant lifetime boundaries remain in the pinned source:
    # staging -> sync -> attention/AV -> sync -> output. In C256 the two batches
    # reuse the same storage only after the previous AV read and a group barrier.
    text = body.decode("utf-8")
    for channels in (64, 128, 256):
        start = text.index(f"DEV void c{channels}_attention_project_body(")
        end = text.index("\n}", start) + 2
        fn = text[start:end]
        stage = fn.index("packed[(c+q)*68+tok]")
        read = fn.index("__builtin_memcpy(&b,packed+(col+rc())*68+")
        assert "sync_window();" in fn[stage:read]
        assert "sync_window();" in fn[read:]
        if channels == 256:
            assert "for(uint batch=0;batch<2;batch++)" in fn
            assert "sync_window();" in fn[read:fn.index("f8 result", read)]
    start = text.index("void c64_attention_project_w16(")
    end = text.index("\n}", start) + 2
    fn = text[start:end]
    assert "head=alltid/256,t=alltid%256,qr=t/64,side=(t/32)&1,first=qr*16" in fn
    assert "for(uint i=t;i<64*8;i+=256)" in fn
    stage = fn.index("packed[(c+q)*68+tok]")
    read = fn.index("__builtin_memcpy(&b,packed+(col+rc())*68+")
    assert "uint col=side*16" in fn[stage:read]
    assert "sync_window();" in fn[stage:read]
    assert "sync_window();" in fn[read:]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    verify_source(args.source)
    total = 0
    for channels in (64, 128, 256):
        per_case = sum(verify_head(head) for head in range(channels // 32))
        total += per_case
        print(f"C{channels}: {per_case} equivalent lane fragments; unique in-bounds stores")
    w16 = sum(verify_head(head, split_queries=True) for head in range(2))
    total += w16
    print(f"C64 w16: {w16} equivalent lane fragments; unique in-bounds stores")
    print(f"PASS: {total} fragments; pinned source intact; no extra LDS or arithmetic changes")
