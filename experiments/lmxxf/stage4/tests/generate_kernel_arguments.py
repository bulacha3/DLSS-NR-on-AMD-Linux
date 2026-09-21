#!/usr/bin/env python3
"""Developer-only generator; needs msgpack. Run from the package root."""
import json, struct
from pathlib import Path
import msgpack

def main():
    kernels={}
    for path in sorted(Path('runtime/modules').glob('*.hsaco')):
        data=path.read_bytes()
        elf=struct.unpack_from('<16sHHIQQQIHHHHHH',data)
        assert elf[0][:6]==b'\x7fELF\x02\x01'
        for i in range(elf[12]):
            section=struct.unpack_from('<IIQQQQIIQQ',data,elf[6]+i*elf[11])
            if section[1]!=7:continue
            at=section[4];end=at+section[5]
            while at<end:
                namesz,descsz,kind=struct.unpack_from('<III',data,at);at+=12
                name=data[at:at+namesz];at+=(namesz+3)&~3
                desc=data[at:at+descsz];at+=(descsz+3)&~3
                if name.rstrip(b'\0')!=b'AMDGPU' or kind!=32:continue
                metadata=msgpack.unpackb(desc)
                for kernel in metadata['amdhsa.kernels']:
                    args=[(a['.size'],int(a['.value_kind']=='global_buffer'))
                          for a in kernel.get('.args',[])
                          if not a['.value_kind'].startswith('hidden_')]
                    key=kernel['.name']
                    if key in kernels:assert kernels[key]==args
                    kernels[key]=args
    assert kernels
    text='// Test fixture: explicit argument sizes/pointer flags from shipped ELF AMDGPU metadata.\n'
    text+='static const std::map<std::string,std::vector<std::pair<size_t,bool>>> kernel_arguments={\n'
    for name,args in sorted(kernels.items()):
        text+='{'+json.dumps(name)+', {'+','.join('{%d,%d}'%x for x in args)+'}},\n'
    text+='};\n'
    Path('tests/lmxxf_kernel_arguments.h').write_text(text)
    print(f'{len(kernels)} kernel ABIs extracted')
if __name__=='__main__':main()
