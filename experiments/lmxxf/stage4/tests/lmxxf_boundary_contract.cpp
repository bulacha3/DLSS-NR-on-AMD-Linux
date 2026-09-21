// Exact boundary kernel body on CPU; layout/bounds only, no HIP execution.
#include <cassert>
#include <cstring>
#include <cstdio>
#include <vector>
static unsigned group_id,item_id;
#define __builtin_amdgcn_workgroup_id_x() group_id
#define __builtin_amdgcn_workitem_id_x() item_id
#include "../experiments/lmxxf/stage4_boundary.hip"
int main(){
 for(unsigned n:{0u,1u,255u,256u,257u,2176u*896u,2432u*1024u,1792u*768u,2048u*896u,2304u*1024u}){
  std::vector<float> input(n*3),out(n*4+16,-7.f);
  for(unsigned i=0;i<n*3;i++)input[i]=float(int(i%2048)-1024)*.03125f;
  for(group_id=0;group_id<(n+255)/256+1;group_id++)for(item_id=0;item_id<256;item_id++)lmxxf_rgb_to_rgba(input.data(),out.data()+8,n);
  for(unsigned i=0;i<n;i++){assert(!std::memcmp(&input[i*3],&out[8+i*4],12));assert(out[8+i*4+3]==1.f);}
  for(unsigned i=0;i<8;i++)assert(out[i]==-7.f&&out[8+n*4+i]==-7.f);
 }
 std::puts("BOUNDARY_LAYOUT_BOUNDS passed (CPU only)");
}
