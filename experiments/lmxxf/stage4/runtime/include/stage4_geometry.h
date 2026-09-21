#ifndef LMXXF_STAGE4_GEOMETRY_H
#define LMXXF_STAGE4_GEOMETRY_H
#include <stdint.h>
/* Processing buffers come from the original import, never from a game list.
 * Six 2x reductions require 64-aligned processing dimensions. Attention uses
 * complete 16-token tiles and the compiled kernels support at most 640 tokens.
 * Only the attention lattice is zero-padded; the decoder crops to the image. */
struct lmxxf_geometry {uint32_t width,height,token_width,token_height;};
enum lmxxf_geometry_status {
 LMXXF_GEOMETRY_OK, LMXXF_GEOMETRY_SIZE, LMXXF_GEOMETRY_ALIGNMENT,
 LMXXF_GEOMETRY_TOKENS, LMXXF_GEOMETRY_PADDING
};
static inline int lmxxf_plan_geometry(uint32_t w,uint32_t h,struct lmxxf_geometry*g){
 if(!g||!w||!h)return LMXXF_GEOMETRY_SIZE;
 if(w%64||h%64)return LMXXF_GEOMETRY_ALIGNMENT;
 uint32_t tw=w/64,th=h/64;
 /* Widen before multiplication: reject malicious/invalid dimensions without overflow. */
 if((uint64_t)tw*th>640)return LMXXF_GEOMETRY_TOKENS;
 /* Preserve this existing validated layout; it is not an acceptance exception. */
 if(w==1920&&h==1152){tw=32;th=20;}
 else if(tw*th%16){
  uint32_t best=641,bw=0,bh=0;
  /* Find the smallest representable rectangle, allowing either axis to pad.
   * Equal-area candidates keep the smallest width (stable row-first layout). */
  for(uint32_t cw=tw;cw<=640/th;++cw){
   uint32_t a=cw,b=16;while(b){uint32_t r=a%b;a=b;b=r;}
   uint32_t rows=16/a,ch=(th+rows-1)/rows*rows,n=cw*ch;
   if(n<best){best=n;bw=cw;bh=ch;}
  }
  if(best>640)return LMXXF_GEOMETRY_PADDING;
  tw=bw;th=bh;
 }
 g->width=w;g->height=h;g->token_width=tw;g->token_height=th;
 return LMXXF_GEOMETRY_OK;
}
static inline int lmxxf_geometry(uint32_t w,uint32_t h,struct lmxxf_geometry*g){
 return lmxxf_plan_geometry(w,h,g)==LMXXF_GEOMETRY_OK;
}
static inline const char*lmxxf_geometry_reason(int status){
 switch(status){
 case LMXXF_GEOMETRY_OK:return "compatible";
 case LMXXF_GEOMETRY_ALIGNMENT:return "processing-alignment-64";
 case LMXXF_GEOMETRY_TOKENS:return "attention-token-limit-640";
 case LMXXF_GEOMETRY_PADDING:return "attention-padding-limit-640";
 default:return "invalid-processing-size";
 }
}
#endif
