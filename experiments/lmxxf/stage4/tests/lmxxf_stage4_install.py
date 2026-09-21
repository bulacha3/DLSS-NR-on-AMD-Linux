#!/usr/bin/env python3
"""Developer contract: real host compilation/DSOs/weights, simulated game only."""
import argparse, importlib.util, json, subprocess, tempfile
from pathlib import Path
def refused(fn, message):
    try: fn()
    except RuntimeError as e: assert message in str(e), str(e)
    else: raise AssertionError('Expected refusal')
def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('package',type=Path); parser.add_argument('weights',type=Path)
    parser.add_argument('--mixed-log',type=Path,help='Optional observed mixed-support log, for classification only; not shipped in the package')
    args=parser.parse_args()
    root=args.package.resolve(); weights=args.weights.resolve()
    spec=importlib.util.spec_from_file_location('stage4_test',root/'experiments/lmxxf/prepare_stage4.py')
    p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
    with tempfile.TemporaryDirectory(prefix='lmxxf-install-contract-') as temporary:
        temp=Path(temporary); game=temp/"Sample Game's [case]"; mod=game/'bin/x64/.dlssnr-linux'; mod.mkdir(parents=True)
        payload=mod.parent/'version.dll'; payload.write_bytes(b'LOCAL TEST FIXTURE; NOT A DANIEL DLL'); expected=p.digest(payload)
        original='\n'.join(['#!/bin/bash','set -e','(( $# > 0 ))',
            'export DLSSNR_HIP_LIBRARY=/test/runtime/libamdhip64.so',
            'export DLSSNR_HIP_LOG='+p.shlex.quote(str(mod/'logs/hip.log')),
            'export KEEP_ORIGINAL_SETTING="HDR with spaces"','export WINEDLLOVERRIDES="version=n,b;other=n"',
            'export LD_PRELOAD=/test/original/bridge.so','exec "$@"',''])
        (mod/'launch.sh').write_text(original)
        base=temp/'experiments/lmxxf-stage4'; entry=temp/'experiments/c32-prepack/launch.sh'; entry.parent.mkdir(parents=True)
        old=b'#!/bin/bash\n# previous experiment\nexec /bin/true "$@"\n'; entry.write_bytes(old); entry.chmod(0o700)
        # Existing v8 activation must upgrade while keeping the pre-stage4 backup.
        base.mkdir(parents=True); backup=base/'before-stage4-fixture.sh'; backup.write_bytes(old); backup.chmod(0o700)
        v8_entry=b'#!/bin/bash\n# already installed stage4 v8\nexec /bin/true "$@"\n'; entry.write_bytes(v8_entry)
        (base/'activation.json').write_text(json.dumps({'format':'lmxxf-stage4-activation-v1','active':True,
            'entry':str(entry),'installed_sha256':p.sha(v8_entry),'backup':backup.name,
            'backup_sha256':p.sha(old),'backup_mode':0o700}))
        refused(lambda:p.prepare(game,weights,root=root,base=base,entry=entry),'version.dll'); assert entry.read_bytes()==v8_entry
        # In-memory test override only; production installer/manifest stay unchanged.
        p.PAYLOAD_SHA=expected
        state=p.prepare(game,weights,root=root,base=base,entry=entry); installed=entry.read_bytes()
        assert installed!=old and (mod/'launch.sh').read_text()==original and p.digest(payload)==expected
        report=Path(state['report']); capture=temp/'args.txt'; env=p.clean_env()
        env.update(CAPTURE=str(capture),DLSSNR_ACTIVE_C32='1',DLSSNR_C32_PREPACK='1',DLSSNR_PROFILE='1')
        shell='''set -e
/bin/true
[[ "$DLSSNR_LMXXF" == 1 ]]
[[ "$DLSSNR_RESEARCH_HIP_LIBRARY" == "$DLSSNR_HIP_LIBRARY" ]]
[[ "$KEEP_ORIGINAL_SETTING" == "HDR with spaces" ]]
[[ "$WINEDLLOVERRIDES" == "version=n,b;other=n" ]]
[[ -z ${DLSSNR_ACTIVE_C32+x} && -z ${DLSSNR_C32_PREPACK+x} && -z ${DLSSNR_PROFILE+x} ]]
[[ "$LD_PRELOAD" == *libdlssnr_hip_bridge.so && "$LD_PRELOAD" != *original* ]]
printf '%s\\n' "$@" > "$CAPTURE"
if [[ -n "$MOCK_LINES" ]]; then printf '%s\\n' "$MOCK_LINES" >> "$DLSSNR_LMXXF_REPORT"; fi
exit "$MOCK_EXIT"
'''
        argv=['alpha beta',"value'quote",'literal $HOME `abc`']
        def run(lines='',rc=0,result='bridge_loaded_no_frames',unsupported=0):
            env.update(MOCK_LINES=lines,MOCK_EXIT=str(rc))
            proc=subprocess.run([str(entry),'/bin/bash','-c',shell,'mock-game',*argv],env=env,capture_output=True,text=True,timeout=40)
            assert proc.returncode==rc,proc.stderr
            assert capture.read_text().splitlines()==argv
            content=report.read_text(); assert 'bridge_loaded=1 build=13 graph_tail=1 output_copy=0 direct_game_io=1 boundary_conversions=0' in content,(content,proc.stderr)
            assert f'\nresult={result}\n' in content,content
            assert f'\nunsupported_seen={unsupported}\n' in content,content
            assert f'launcher_exit={rc}\n' in content
        run()
        run('[lmxxf-stage4] completed=1 backend=original-preflight-or-unsupported next_eligible=0',result='original_only',unsupported=1)
        done='[lmxxf-stage4] completed=2 backend=lmxxf replaced_total=1 skipped_original_neural=154'
        run(done+'\n[lmxxf-stage4] submission=graph graph_builds=1 graph_replays=119 graph_nodes=254',result='lmxxf_ran')
        assert 'submission=graph' in report.read_text()
        preflight='[lmxxf-stage4] completed=1 backend=original-preflight-or-unsupported next_eligible=1 blocked_mask=0x0'
        refused_geometry='[lmxxf-stage4] frame=1 unsupported=import-geometry phase=1'
        late_unsupported='[lmxxf-stage4] completed=120 backend=original-preflight-or-unsupported next_eligible=0 blocked_mask=0x1'
        run(preflight+'\n'+done,result='lmxxf_ran')
        run(done+'\n'+refused_geometry,result='lmxxf_partial',unsupported=1)
        run(late_unsupported+'\n'+done,result='lmxxf_partial',unsupported=1)
        error='[lmxxf-stage4] error=injected-test-failure completed=0'
        run(done+'\n'+error,23,'backend_failed_after_lmxxf_frames'); run(error,24,'backend_failed')
        run(done+'\n'+refused_geometry+'\n'+error,25,'backend_failed_after_lmxxf_frames',1)
        if args.mixed_log:run(args.mixed_log.read_text(),result='lmxxf_partial',unsupported=1)
        assert report.with_name(report.name+'.previous').is_file()

        # Upgrade an already installed per-game v8 entry (nested executable layout).
        # Its state/report remain separate, and its existing weights are shared.
        game2=temp/'Second Game';mod2=game2/'Second/Binaries/Win64/.dlssnr-linux';mod2.mkdir(parents=True)
        original2=original.replace('HDR with spaces','SECOND GAME HDR')
        (mod2/'launch.sh').write_text(original2);(mod2.parent/'version.dll').write_bytes(payload.read_bytes())
        state_base2,expected_entry2=p.installation_paths(mod2/'launch.sh',base)
        state_base2.mkdir(parents=True,mode=0o700)
        before2=('#!/bin/bash\nset -e\nexec '+p.shlex.quote(str(mod2/'launch.sh'))+' "$@"\n').encode()
        backup2=state_base2/'before-stage4-v8-fixture.sh';backup2.write_bytes(before2);backup2.chmod(0o700)
        installed_v8=b'#!/bin/bash\n# existing per-game v8\nexec /bin/true "$@"\n'
        expected_entry2.write_bytes(installed_v8);expected_entry2.chmod(0o700)
        (state_base2/'activation.json').write_text(json.dumps({'format':'lmxxf-stage4-activation-v1','active':True,
            'entry':str(expected_entry2),'installed_sha256':p.sha(installed_v8),'backup':backup2.name,
            'backup_sha256':p.sha(before2),'backup_mode':0o700,'original_launcher':str(mod2/'launch.sh')}))
        legacy_state=(base/'activation.json').read_bytes();first_report=report.read_bytes()
        actual_compile=p.compile_host
        def reuse_verified_dsos(package,output):
            for name in ('liblmxxf_resident.so','libdlssnr_hip_bridge.so'):
                p.shutil.copyfile(Path(state['target'])/name,output/name)
        p.compile_host=reuse_verified_dsos
        try: second=p.prepare(game2,root=root,base=base,profile=True)
        finally:p.compile_host=actual_compile
        entry2=Path(second['entry']);state2=entry2.parent;installed2=entry2.read_bytes();report2=Path(second['report'])
        assert entry2==expected_entry2 and installed2!=installed_v8
        assert entry2!=entry and state2.is_relative_to(base/'games') and report2!=report
        assert entry.read_bytes()==installed and (base/'activation.json').read_bytes()==legacy_state
        assert p.installation_paths(mod/'launch.sh',base)==(base,entry)
        assert p.installation_paths(mod2/'launch.sh',base)==(state2,entry2)
        assert not (state2/'assets').exists() and not (state2/'builds').exists()
        env2=p.clean_env();env2.update(EXPECT_REPORT=str(report2))
        # Exercise an external executable as in the first-game test, not only a shell builtin.
        second_shell='/bin/true && [[ "$KEEP_ORIGINAL_SETTING" == "SECOND GAME HDR" && "$DLSSNR_LMXXF_REPORT" == "$EXPECT_REPORT" && "$DLSSNR_LMXXF_GPU_PROFILE" == 1 ]]'
        proc=subprocess.run([str(entry2),'/bin/bash','-c',second_shell],env=env2,capture_output=True,text=True)
        assert proc.returncode==0,proc.stderr
        assert report.read_bytes()==first_report, ('first report changed', first_report, report.read_bytes())
        assert 'build=13' in report2.read_text(), ('second report', report2.read_text(), proc.stderr)
        profile2=report2.with_name('kernel-profile.txt')
        assert 'profile_status=waiting_for_frames' in profile2.read_text()
        assert 'build='+second['package'] in profile2.read_text()
        assert not report.with_name('kernel-profile.txt').exists()
        assert (mod2/'launch.sh').read_text()==original2

        for modified in (Path(state['target'])/'modules/game-io.hsaco',Path(state['target'])/'modules/game-prefix.hsaco',base/'assets'/p.WEIGHTS_SHA[:16]/'block0-ffn.f32'):
            data=modified.read_bytes(); modified.write_bytes(bytes([data[0]^1])+data[1:])
            proc=subprocess.run([str(entry),'/bin/true'],env=p.clean_env(),capture_output=True,timeout=40)
            assert proc.returncode==1 and b'lmxxf:' in proc.stderr
            modified.write_bytes(data)
        candidate=root/'native/lmxxf_bridge.c'; data=candidate.read_bytes()
        try:
            candidate.write_bytes(data+b'\n/* tamper test */\n')
            refused(lambda:p.prepare(game,weights,root=root,base=base,entry=entry),'modified')
        finally: candidate.write_bytes(data)
        assert entry.read_bytes()==installed
        edited=installed+b'# user edit\n'; entry.write_bytes(edited)
        refused(lambda:p.restore(base,entry),'modified'); assert entry.read_bytes()==edited
        entry.write_bytes(installed); p.restore(base,entry)
        assert entry.read_bytes()==old and entry.stat().st_mode&0o777==0o700
        assert not json.loads((base/'activation.json').read_text())['active']
        assert (mod/'launch.sh').read_text()==original and p.digest(payload)==expected and report.is_file()
        p.restore(base,entry)
        assert entry2.read_bytes()==installed2
        p.restore(state2,entry2)
        assert entry.read_bytes()==old
        assert str(mod2/'launch.sh') in entry2.read_text()
        assert entry2.read_bytes()==before2
        assert not json.loads((state2/'activation.json').read_text())['active']
        assert (mod2/'launch.sh').read_text()==original2
    print('INSTALL_V8_TO_V9_MULTIGAME_BUILD_LOAD_SUMMARY_INTEGRITY_RESTORE passed (CPU; simulated game, real weights and DSOs)')
if __name__=='__main__': main()
