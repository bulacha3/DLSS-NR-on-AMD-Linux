#!/usr/bin/env python3
"""Real resident/weights, modeled HIP: ownership, reuse, resize and command parity.

No GPU arithmetic, images, FPS or GPU timing is simulated. Every uploaded
weight's bytes are fingerprinted and compared at its actual kernel arguments.
"""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from lmxxf_prefix_resident import Config, Frame, Prefix
from lmxxf_graph_resident import Stats


class Residency(c.Structure):
    _fields_ = [('bytes', c.c_uint), ('reused', c.c_uint), ('resized', c.c_uint), ('device', c.c_uint)] + [
        (name, c.c_uint64) for name in ('resident_id', 'creations', 'reuses', 'resizes', 'evictions', 'cached', 'weight_bytes', 'scratch_bytes')]


def load(a):
    os.environ['DLSSNR_RESEARCH_HIP_LIBRARY'] = a.mock
    hip, lib = c.CDLL(a.mock), c.CDLL(a.resident)
    hip.mock_stream.argtypes = [c.c_void_p]; hip.mock_stream(None)
    hip.mock_expect.argtypes = [c.c_uint, c.c_uint, c.c_uint, c.c_uint, c.POINTER(c.c_float)]
    hip.hipMalloc.argtypes = [c.POINTER(c.c_void_p), c.c_size_t]
    hip.hipFree.argtypes = [c.c_void_p]; hip.hipStreamSynchronize.argtypes = [c.c_void_p]
    hip.mock_trace.restype = hip.mock_uploaded.restype = c.c_char_p
    for name in ('allocations', 'live', 'live_bytes', 'peak_bytes', 'uploads', 'upload_bytes', 'module_loads', 'device_syncs', 'graphs'):
        getattr(hip, 'mock_' + name).restype = c.c_size_t
    lib.lmxxf_create.argtypes = [c.POINTER(Config), c.POINTER(c.c_void_p), c.c_char_p, c.c_size_t]
    lib.lmxxf_enqueue.argtypes = [c.c_void_p, c.POINTER(Frame), c.c_char_p, c.c_size_t]
    lib.lmxxf_destroy.argtypes = [c.POINTER(c.c_void_p), c.c_char_p, c.c_size_t]
    lib.lmxxf_get_submission_stats.argtypes = [c.c_void_p, c.POINTER(Stats)]
    if a.mode != 'fresh':
        lib.lmxxf_acquire_resident.argtypes = [c.POINTER(Config), c.POINTER(c.c_void_p), c.POINTER(Residency), c.c_char_p, c.c_size_t]
        lib.lmxxf_return_after_sync.argtypes = [c.POINTER(c.c_void_p), c.c_void_p, c.c_int, c.POINTER(Residency), c.c_char_p, c.c_size_t]
        lib.lmxxf_trim_resident.argtypes = [c.c_char_p, c.c_size_t]
    return hip, lib


def thread_call(fn):
    failures = []
    def wrapped():
        try: fn()
        except BaseException as e: failures.append(e)
    t = threading.Thread(target=wrapped); t.start(); t.join()
    if failures: raise failures[0]


def sequence(a):
    hip, lib = load(a); records = []; state = Residency(); state.bytes = c.sizeof(state)
    # Exercise sequential contexts, repeated extents and geometry changes.
    shapes = ((1792, 768), (2048, 896), (2048, 896), (2304, 1024), (2048, 896))
    for stage, (w, h) in enumerate(shapes):
        def worker():
            assert hip.hipSetDevice(0) == 0
            cfg = Config(3, 40, w, h, a.assets.encode(), a.modules.encode(), None)
            ctx = c.c_void_p(); err = c.create_string_buffer(384); n = w*h
            buffers = [c.c_void_p() for _ in range(3)]
            for ptr, size in zip(buffers, (n*12, n*12, n*16)):
                assert hip.hipMalloc(c.byref(ptr), size) == 0
            if a.mode == 'fresh': assert lib.lmxxf_create(c.byref(cfg), c.byref(ctx), err, len(err)) == 0, err.value
            # A fourth v7 reference replays frame 0 on its warmed graph. Cache
            # reuse can legitimately begin with that graph rather than the cold
            # allocation layout. Compare equal warm/cold execution states.
            for iteration in range(4 if a.mode == 'fresh' else 3):
                i = iteration % 3
                if a.mode != 'fresh':
                    assert lib.lmxxf_acquire_resident(c.byref(cfg), c.byref(ctx), c.byref(state), err, len(err)) == 0, err.value
                    assert state.resident_id == 1 and state.creations == 1
                seed = (0, 0xffffffff, 900001)[i] + stage if i != 1 else 0xffffffff
                temporal = i % 2
                prefix = Prefix((c.c_float*6)(.0625, i % 2, 0, .0078125 if i == 1 else 0, 1+stage/10, 1+i/10))
                frame = Frame(3, 96, w, h, buffers[0], buffers[1] if temporal else None, buffers[2], n*12, n*12 if temporal else 0, n*16, seed, 0, prefix)
                hip.mock_expect(w, h, seed, temporal, prefix.values)
                assert lib.lmxxf_enqueue(ctx, c.byref(frame), err, len(err)) == 0, err.value
                # Represents the bridge's ORIGINAL successful final stream drain.
                assert hip.hipStreamSynchronize(None) == 0
                stats = Stats(); stats.bytes = c.sizeof(stats)
                assert lib.lmxxf_get_submission_stats(ctx, c.byref(stats)) == 0
                record = dict(stage=stage, frame=i, shape=[w, h], trace=hip.mock_trace().decode(), uploads=hip.mock_uploaded().decode(), graph_mode=stats.mode)
                if a.mode != 'fresh':
                    assert lib.lmxxf_return_after_sync(c.byref(ctx), None, 0, c.byref(state), err, len(err)) == 0, err.value
                    assert not ctx.value and state.cached == 1
                    record['residency'] = {name: getattr(state, name) for name, _ in state._fields_}
                if iteration == 3: records[-3]['warmed_reference'] = record
                else: records.append(record)
            if a.mode == 'fresh':
                assert lib.lmxxf_destroy(c.byref(ctx), err, len(err)) == 0, err.value
            for ptr in buffers: assert hip.hipFree(ptr) == 0
        thread_call(worker)
    totals = {name: getattr(hip, 'mock_' + name)() for name in ('uploads', 'upload_bytes', 'module_loads', 'device_syncs', 'peak_bytes', 'live_bytes')}
    if a.mode != 'fresh':
        assert state.creations == 1 and state.reuses == 14 and state.resizes == 3 and state.evictions == 0
        # A new worker with the same shape immediately reuses the existing graph.
        assert records[6]['graph_mode'] == 2
        err = c.create_string_buffer(384)
        assert lib.lmxxf_trim_resident(err, len(err)) == 0, err.value
        assert hip.mock_device_syncs() == 0
    assert hip.mock_live() == 0 and hip.mock_graphs() == 0
    Path(a.output).write_text(json.dumps(dict(records=records, totals=totals)))


def failures(a):
    hip, lib = load(a); err = c.create_string_buffer(384)
    def stats():
        s = Residency(); s.bytes = c.sizeof(s); return s
    def acquire(device=0):
        hip.hipSetDevice(device); cfg = Config(3, 40, 512, 512, a.assets.encode(), a.modules.encode(), None)
        p = c.c_void_p(); s = stats()
        assert lib.lmxxf_acquire_resident(c.byref(cfg), c.byref(p), c.byref(s), err, len(err)) == 0, err.value
        return p, s
    def give_back(p, result=0):
        s = stats(); return lib.lmxxf_return_after_sync(c.byref(p), None, result, c.byref(s), err, len(err))
    first, _ = acquire(); live = hip.mock_live()
    # Another owner must not enqueue, return or destroy this active lease.
    def other_owner():
        alias = c.c_void_p(first.value); s = stats(); e = c.create_string_buffer(384)
        assert lib.lmxxf_return_after_sync(c.byref(alias), None, 0, c.byref(s), e, len(e)) == 1
        assert lib.lmxxf_destroy(c.byref(alias), e, len(e)) == 1
    thread_call(other_owner); assert hip.mock_live() == live
    # A failed original drain retains all resources and prevents later reuse.
    assert give_back(first, 719) == 3 and first.value
    assert hip.mock_live() == live and give_back(first) == 2
    hip.mock_failure(0, 1)
    assert lib.lmxxf_destroy(c.byref(first), err, len(err)) == 3 and first.value
    hip.mock_failure(0, 0)
    assert lib.lmxxf_destroy(c.byref(first), err, len(err)) == 0
    # Two overlapping leases have different identities. Returning both retains
    # one idle context, not one per old worker. Trim cannot touch an active one.
    first, one = acquire(); first_value = first.value
    def second_owner():
        second, two = acquire(); assert second.value != first_value and two.resident_id != one.resident_id
        assert give_back(second) == 0
    thread_call(second_owner)
    assert lib.lmxxf_trim_resident(err, len(err)) == 0 and first.value == first_value
    # Device mismatches are rejected, without selecting a GPU for the caller.
    hip.hipSetDevice(1); assert give_back(first) == 1 and first.value
    hip.hipSetDevice(0); assert give_back(first) == 0
    gpu1, s1 = acquire(1); assert s1.device == 1 and s1.resident_id != one.resident_id
    assert give_back(gpu1) == 0
    hip.hipSetDevice(0); same, s0 = acquire(); assert same.value == first_value and s0.device == 0
    assert give_back(same) == 0
    assert lib.lmxxf_trim_resident(err, len(err)) == 0
    hip.hipSetDevice(1)
    retained, retained_state = acquire(1); assert retained_state.reused == 1
    assert give_back(retained) == 0
    assert lib.lmxxf_trim_resident(err, len(err)) == 0 and hip.mock_live() == 0
    # Returning overlapping leases replaces the older idle resident; only the
    # most recently returned one remains available on this device.
    left, _ = acquire(0); right, right_state = acquire(0)
    right_value = right.value; assert give_back(left) == 0
    returned = stats()
    assert lib.lmxxf_return_after_sync(c.byref(right), None, 0, c.byref(returned), err, len(err)) == 0
    assert returned.cached == 1 and returned.evictions == right_state.evictions + 1
    newest, newest_state = acquire(0)
    assert newest.value == right_value and newest_state.reused == 1
    assert give_back(newest) == 0
    # A graph-mode change must not inherit the previously prepared graph.
    os.environ['DLSSNR_LMXXF_GRAPH'] = '0'
    changed, changed_state = acquire(0)
    assert changed_state.reused == 0 and changed_state.evictions == newest_state.evictions + 1
    assert give_back(changed) == 0
    del os.environ['DLSSNR_LMXXF_GRAPH']
    assert lib.lmxxf_trim_resident(err, len(err)) == 0 and hip.mock_live() == 0
    # A partially enqueued shared resident must never re-enter the cache,
    # even after a later successful drain. Its failure is sticky until destroy.
    partial, _ = acquire(0); n = 512*512; buffers = [c.c_void_p(), c.c_void_p()]
    for ptr, size in zip(buffers, (n*12, n*16)): assert hip.hipMalloc(c.byref(ptr), size) == 0
    prefix = Prefix((c.c_float*6)(.0625, 0, 0, 0, 1, 1))
    frame = Frame(3, 96, 512, 512, buffers[0], None, buffers[1], n*12, 0, n*16, 0, 0, prefix)
    hip.mock_expect(512, 512, 0, 0, prefix.values); hip.mock_failure(1, 0)
    assert lib.lmxxf_enqueue(partial, c.byref(frame), err, len(err)) == 2
    live = hip.mock_live(); hip.mock_failure(0, 0)
    assert hip.hipStreamSynchronize(None) == 0 and give_back(partial) == 2
    assert partial.value and hip.mock_live() == live
    assert lib.lmxxf_destroy(c.byref(partial), err, len(err)) == 0
    for ptr in buffers: assert hip.hipFree(ptr) == 0
    assert lib.lmxxf_trim_resident(err, len(err)) == 0 and hip.mock_live() == 0
    print('RESIDENCY_OWNERSHIP wrong_thread=refused failed_drain=retained partial_enqueue=retained active_lease=exclusive device_isolation=passed idle_bound=passed option_change=evicted', flush=True)


def compare(a, b):
    assert len(a) == len(b) == 15
    for old, new in zip(a, b, strict=True):
        if old['graph_mode'] != new['graph_mode']:
            assert old['graph_mode'] == 1 and new['graph_mode'] == 2
            old = old['warmed_reference']
            assert old['graph_mode'] == 2
        assert (old['shape'], old['frame']) == (new['shape'], new['frame'])
        uploads = []
        for record in (old, new):
            uploads.append({parts[0]: parts[1:] for line in record['uploads'].splitlines() if (parts := line.split(':'))})
        forward, reverse = {}, {}
        left, right = old['trace'].splitlines(), new['trace'].splitlines()
        assert len(left) == len(right)
        for x, y in zip(left, right, strict=True):
            for v, w in zip(x.split(':'), y.split(':'), strict=True):
                if '+' not in v: assert v == w, (v, w)
                else:
                    oi, oo = v.split('+'); ni, no = w.split('+')
                    assert oo == no and forward.setdefault(oi, ni) == ni and reverse.setdefault(ni, oi) == oi, (old['stage'], old['frame'], x, y, v, w, forward.get(oi), reverse.get(ni))
                    if oi in uploads[0]: assert uploads[0][oi] == uploads[1][ni], 'uploaded weight/map bytes differ'


def main():
    p = argparse.ArgumentParser(); p.add_argument('mock'); p.add_argument('resident'); p.add_argument('assets'); p.add_argument('modules')
    p.add_argument('--reference'); p.add_argument('--child', action='store_true'); p.add_argument('--mode', default='shared'); p.add_argument('--output')
    a = p.parse_args()
    for name in ('mock', 'resident', 'assets', 'modules'):
        setattr(a, name, str(Path(getattr(a, name)).resolve()))
    if a.child:
        return failures(a) if a.mode == 'failures' else sequence(a)
    a.reference = a.reference or a.resident # Same IO ABI; v8 parity uses lmxxf_game_io_contract.py.
    with tempfile.TemporaryDirectory(prefix='lmxxf-residency-') as directory:
        results = []
        for mode, resident in (('fresh', str(Path(a.reference).resolve())), ('shared', a.resident)):
            out = Path(directory) / (mode + '.json')
            subprocess.run([sys.executable, __file__, a.mock, resident, a.assets, a.modules, '--child', '--mode', mode, '--output', str(out)], check=True)
            results.append(json.loads(out.read_text()))
        compare(results[0]['records'], results[1]['records'])
        old, new = results[0]['totals'], results[1]['totals']
        assert new['module_loads'] * 5 == old['module_loads']
        assert new['upload_bytes'] < old['upload_bytes'] / 4
        assert new['device_syncs'] == 0 and old['device_syncs'] == 0
        print('RESIDENCY_PARITY five_workers=passed 15_frames_all_commands=equivalent uploaded_weight_bytes=identical creations=1 resizes=3', flush=True)
        print('MODELED_HIP_COUNTS ' + json.dumps({'v9_fresh': old, 'v9_shared': new, 'not_GPU_or_FPS_measurements': True}), flush=True)
    subprocess.run([sys.executable, __file__, a.mock, a.resident, a.assets, a.modules, '--child', '--mode', 'failures'], check=True)


if __name__ == '__main__': main()
