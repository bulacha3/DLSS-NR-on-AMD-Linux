#!/usr/bin/env python3
"""Bounded profile state machine on the real resident ABI with modeled HIP.

Synthetic event ticks validate accounting, not GPU performance. Every neural
command and argument must match the uninstrumented control for every frame.
"""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from lmxxf_prefix_resident import Config, Frame, Prefix
from lmxxf_residency_contract import Residency, load
from lmxxf_graph_resident import Stats


def child(a):
    os.environ['DLSSNR_LMXXF_GRAPH'] = '1'
    os.environ['DLSSNR_LMXXF_GPU_PROFILE'] = '0' if a.case == 'off' else '1'
    report = Path(a.output).with_suffix('.txt')
    os.environ['DLSSNR_LMXXF_GPU_PROFILE_REPORT'] = str(report)
    a.mode = 'resident'
    hip, lib = load(a)
    for name in ('events', 'event_calls', 'stream_syncs', 'host_calls'):
        getattr(hip, 'mock_' + name).restype = c.c_size_t
    buffers = [c.c_void_p() for _ in range(5)]
    w, h = 512, 512
    n = w*h
    for ptr, size in zip(buffers, (n*12, n*12, n*12, n*16, n*16)):
        assert hip.hipMalloc(c.byref(ptr), size) == 0
    cfg = Config(3, 40, w, h, a.assets.encode(), a.modules.encode(), None)
    ctx = c.c_void_p()
    err = c.create_string_buffer(384)
    state = Residency(); state.bytes = c.sizeof(state)
    records = []
    failure = {'create': 1, 'record': 2, 'capture': 3, 'elapsed': 4, 'negative': 5}.get(a.case, 0)
    hip.mock_event_failure(failure)
    for i in range(165):
        assert lib.lmxxf_acquire_resident(c.byref(cfg), c.byref(ctx), c.byref(state), err, len(err)) == 0, err.value
        prefix = Prefix((c.c_float*6)(.0625, i%2, 1, .0078125, 1+i%3/10, 1))
        seed, temporal = i*101, i%2
        frame = Frame(3, 96, w, h, buffers[i%2], buffers[2] if temporal else None,
                      buffers[3+i%2], n*12, n*12 if temporal else 0, n*16, seed, 0, prefix)
        hip.mock_expect(w, h, seed, temporal, prefix.values)
        if a.case == 'instantiate' and i == 129: hip.mock_graph_failure(5)
        before_sync = hip.mock_stream_syncs()
        assert lib.lmxxf_enqueue(ctx, c.byref(frame), err, len(err)) == 0, err.value
        if i == 129:
            calls = hip.mock_host_calls()
            assert lib.lmxxf_enqueue(ctx, c.byref(frame), err, len(err)) == 1
            assert hip.mock_host_calls() == calls
        # Collection may never add a stream/device synchronization.
        if i > 0: assert hip.mock_stream_syncs() == before_sync
        if a.case == 'drain' and i == 130:
            live_events, live_graphs = hip.mock_events(), hip.mock_graphs()
            assert live_events > 0 and live_graphs == 4
            hip.mock_failure(0, 1)
            assert hip.hipStreamSynchronize(None) != 0
            assert lib.lmxxf_return_after_sync(c.byref(ctx), None, 719, c.byref(state), err, len(err)) == 3
            assert ctx.value and hip.mock_events() == live_events and hip.mock_graphs() == live_graphs
            assert lib.lmxxf_destroy(c.byref(ctx), err, len(err)) == 3
            assert ctx.value and hip.mock_events() == live_events and hip.mock_graphs() == live_graphs
            hip.mock_failure(0, 0)
            assert lib.lmxxf_destroy(c.byref(ctx), err, len(err)) == 0
            assert not ctx.value and hip.mock_events() == 0 and hip.mock_graphs() == 0
            for ptr in buffers: assert hip.hipFree(ptr) == 0
            assert hip.mock_live() == 0
            Path(a.output).write_text(json.dumps(records))
            return
        assert hip.hipStreamSynchronize(None) == 0
        assert lib.lmxxf_return_after_sync(c.byref(ctx), None, 0, c.byref(state), err, len(err)) == 0, err.value
        records.append(hashlib.sha256(hip.mock_trace()).hexdigest())
        if i == 150: settled_events = hip.mock_event_calls()
        if i > 150: assert hip.mock_event_calls() == settled_events
        assert state.creations == 1
    text = report.read_text() if report.exists() else ''
    if a.case == 'off':
        assert not text and hip.mock_event_calls() == 0
    elif a.case == 'ok':
        assert 'profile_status=complete' in text and 'normal_graph_restored=1' in text
        assert 'profile_samples=8\n' in text and 'reference_samples_each=8\n' in text
        assert 'kernel=c32_game_io/lmxxf_game_prefix_rgb' in text
        assert 'kernel=c32_game_io/lmxxf_game_head_rgba' in text
        values = [float(line.split()[0].split('=')[1]) for line in text.splitlines() if line.startswith('kernel_gpu_ms=')]
        assert values == sorted(values, reverse=True) and sum(values) > 0
    else:
        assert 'profile_status=unavailable' in text and 'profile_status=complete' not in text, text
    assert hip.mock_events() == 0 and hip.mock_graphs() == 2
    assert lib.lmxxf_trim_resident(err, len(err)) == 0
    assert hip.mock_graphs() == 0 and hip.mock_events() == 0
    for ptr in buffers: assert hip.hipFree(ptr) == 0
    assert hip.mock_live() == 0
    Path(a.output).write_text(json.dumps(records))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('mock', 'resident', 'assets', 'modules'): p.add_argument(name)
    p.add_argument('--missing-api', required=True)
    p.add_argument('--child', action='store_true')
    p.add_argument('--case', default='ok')
    p.add_argument('--output')
    a = p.parse_args()
    for name in ('mock', 'resident', 'assets', 'modules', 'missing_api'):
        setattr(a, name, str(Path(getattr(a, name)).resolve()))
    if a.child: return child(a)
    with tempfile.TemporaryDirectory(prefix='lmxxf-profile-contract-') as d:
        control = None
        for case in ('off', 'ok', 'create', 'record', 'capture', 'elapsed', 'negative', 'instantiate', 'noapi', 'drain'):
            out = Path(d)/(case+'.json')
            mock = a.missing_api if case == 'noapi' else a.mock
            subprocess.run([sys.executable, __file__, mock, a.resident, a.assets, a.modules,
                            '--missing-api', a.missing_api, '--child', '--case', case, '--output', str(out)], check=True)
            result = json.loads(out.read_text())
            if control is None: control = result
            assert result == control[:len(result)], 'Neural command/argument mismatch: '+case
            print('PROFILE_CONTRACT '+case+' exact_neural_commands=passed bounded_events=passed no_extra_sync=passed', flush=True)


if __name__ == '__main__':
    main()
