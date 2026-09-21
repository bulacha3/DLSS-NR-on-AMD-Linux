// Layout only. Original Daniel import/export retain HDR/exposure/colorspace.
extern "C" __attribute__((global))
void lmxxf_rgb_to_rgba(const float*rgb,float*rgba,unsigned pixels){
 unsigned p=__builtin_amdgcn_workgroup_id_x()*256+__builtin_amdgcn_workitem_id_x();
 if(p>=pixels)return;
 rgba[4*p]=rgb[3*p];rgba[4*p+1]=rgb[3*p+1];rgba[4*p+2]=rgb[3*p+2];rgba[4*p+3]=1.f;
}
