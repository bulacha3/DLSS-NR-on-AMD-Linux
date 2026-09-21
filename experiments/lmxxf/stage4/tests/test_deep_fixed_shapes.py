#!/usr/bin/env python3
"""Prove helper arithmetic identity and execute dispatch wrappers on the CPU."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if not (HERE / "build_deep_candidate.py").is_file():
    sys.path.insert(0, str(HERE.parent / "experiments/lmxxf"))
from build_deep_candidate import generate, SPECS, source_function
from build_vit_streaming import generate as generate_streaming


def verify(baseline: Path, upstream: Path) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, streaming = root / "candidate.hip", root / "streaming.hip"
        generate(baseline, upstream, candidate)
        generate_streaming(baseline, upstream, streaming)
        old, new = streaming.read_text(), candidate.read_text()
        reconstructed = new
        declarations, wrappers, calls = [], [], []
        for name, spec in SPECS.items():
            old_function = source_function(old, name)
            old_signature = old_function[:old_function.index("{")]
            helper = "lmxxf_fixed_" + name
            helper_start = new.index("DEV void " + helper + "(")
            wrapper_start = new.index("WAVE void " + name + "(", helper_start)
            helper_source = new[helper_start:wrapper_start].rstrip("\n")
            assert helper_source == old_function.replace("WAVE void " + name,
                                                        "DEV void " + helper, 1)
            wrapper_end = new.index("\n", wrapper_start)
            wrapper = new[wrapper_start:wrapper_end]
            assert wrapper[:wrapper.index("{")] == old_signature
            assert wrapper.endswith(f"else {helper}({spec['arguments']});" + "}")
            reconstructed = reconstructed.replace(helper_source + "\n" + wrapper,
                                                   old_function, 1)
            # Actual generated wrapper executes against an instrumented helper.
            # The helper captures every argument; pointer identity and all
            # runtime dimensions must remain the ones supplied by this test.
            scalar_args = spec["arguments"].split(",")[3 if name.startswith("vit_expand") else 4:]
            signature = old_signature.replace("WAVE void " + name, "void " + helper)
            capture = ",".join(scalar_args)
            pointer_count = 3 if name.startswith("vit_expand") else 4
            pointers = ["in", "w", "out"] if pointer_count == 3 else ["in", "w", "skip", "out"]
            pointer_check = ";".join(f"assert({p}==&slots[{i}])" for i, p in enumerate(pointers))
            declarations.append(signature + "{" + pointer_check + "; seen={" + capture + "};}")
            wrappers.append(wrapper.replace("WAVE void", "void", 1))
            scalar_setup = ("uint tokens=shape;" if "tokens" in scalar_args
                            else "uint iw=shape,ih=7,ow=2*shape-1,oh=13;")
            pointer_values = ",".join(f"&slots[{i}]" for i in range(pointer_count))
            all_scalars = ",".join(scalar_args)
            calls.append("for(uint shape: {1u,15u,16u,17u,400u,448u,640u})"
                         "for(uint inputs: {64u,128u,256u,512u,768u,1024u,4096u})"
                         "for(uint outputs: {32u,64u,128u,256u,512u,1024u,4096u}){"
                         + scalar_setup + name + "(" + pointer_values + "," + all_scalars + ");"
                         + "assert(seen==std::vector<uint>({" + all_scalars + "}));++checks;}")
        assert reconstructed == old, "unrelated source or arithmetic changed"
        harness = "#include <cassert>\n#include <vector>\n#include <cstdio>\nusing uint=unsigned;\n"
        harness += "float slots[4];std::vector<uint>seen;\n" + "\n".join(declarations + wrappers)
        harness += "\nint main(){unsigned checks=0;" + "".join(calls)
        harness += 'std::printf("PASS: %u fixed-shape/fallback dispatches; all helper bodies identical\\n",checks);}\n'
        source, binary = root / "dispatch.cpp", root / "dispatch"
        source.write_text(harness)
        subprocess.run(["g++", "-std=c++17", "-O2", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("upstream", type=Path)
    args = parser.parse_args()
    verify(args.baseline, args.upstream)
