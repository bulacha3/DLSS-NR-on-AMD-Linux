#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "../native/lmxxf_timing.h"
int main(void) {
 struct lm4_timing t={0};uint64_t wall;
 lm4_timing_begin(&t,1000000000);
 assert(lm4_timing_complete(&t,1500000000,1,&wall)==0);
 assert(wall==500000000 && t.anomalies==0);
 lm4_timing_begin(&t,1501000000);
 assert(t.idle_ns==1000000);
 assert(lm4_timing_complete(&t,1521000000,4,&wall)==0);
 uint64_t now=1522000000;
 for (uint64_t frame=5;frame<9;++frame) {
  lm4_timing_begin(&t,now);now+=120000000;
  assert(lm4_timing_complete(&t,now,frame,&wall)==1);
  ++now;
 }
 assert(t.reports==4 && t.anomalies==4);
 lm4_timing_begin(&t,now);now+=120000000;
 assert(lm4_timing_complete(&t,now,9,&wall)==0);
 assert(t.reports==4 && t.anomalies==5);
 assert(lm4_timing_slow_mask(&t,wall,9)==1);
 now+=1500000000;lm4_timing_begin(&t,now);
 assert(t.acquire_ns==0 && t.enqueue_ns==0);
 assert(lm4_timing_complete(&t,now+20000000,10,&wall)==2);
 assert(t.reports==5 && t.anomalies==6);
 /* Quiet gameplay does not produce reports, even after the rate limit expires. */
 for(uint64_t frame=11;frame<100011;++frame) {
  now=t.previous_completed+1000000;lm4_timing_begin(&t,now);
  assert(lm4_timing_complete(&t,now+20000000,frame,&wall)==0);
 }
 assert(t.reports==5 && t.anomalies==6);
 puts("TIMING: startup exclusion, worker/idle distinction, bounded output and 100000 quiet frames passed");
}
