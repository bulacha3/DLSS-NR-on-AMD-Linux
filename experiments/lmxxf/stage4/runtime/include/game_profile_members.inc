// Optional, bounded GPU diagnostic. Included inside Network.
// Timing markers remain on the original stream. The normal graph is retained
// while a temporary graph records explicit HIP external-event nodes.
struct ProfilePoint { std::string name; Handle begin{},end{}; double sum{}; };
std::vector<ProfilePoint> profile_points;
ProfilePoint profile_span{"network"},profile_prefix{"c32_game_io/lmxxf_game_prefix_rgb"},
             profile_head{"c32_game_io/lmxxf_game_head_rgba"};
Handle profile_saved_graph{},profile_saved_exec{};
uint64_t profile_saved_nodes{},profile_frames{};
unsigned profile_before{},profile_samples{},profile_after{};
double profile_before_ms{},profile_detail_ms{},profile_after_ms{};
bool profile_done{},profile_capture{},profile_pending{},profile_detail{};
const char*profile_error{};
static constexpr unsigned profile_warmup=120,profile_window=8;

void ProfileMessage(const char*status,const char*reason="") noexcept {
 try {
  std::ofstream out(opt.game_profile_report,std::ios::app);
  out<<"profile_status="<<status<<" reason="<<reason<<"\n";
 }catch(...){} // Diagnostics must not fail an otherwise usable frame.
}
void ProfileCreate(ProfilePoint&p) {
 api.Check(api.hipEventCreate(&p.begin),"profile event create");
 api.Check(api.hipEventCreate(&p.end),"profile event create");
}
void ProfileDestroy(ProfilePoint&p) noexcept {
 if(p.begin)api.hipEventDestroy(p.begin);
 if(p.end)api.hipEventDestroy(p.end);
 p.begin=p.end=nullptr;
}
void ProfileRestoreGraph() noexcept {
 if(profile_saved_exec) {
  ClearGraph();captured_graph=profile_saved_graph;graph_exec=profile_saved_exec;
  game_nodes=profile_saved_nodes;
  profile_saved_graph=profile_saved_exec=nullptr;
 }
 profile_detail=false;
}
void ProfileRelease() noexcept {
 // Caller has proved completion of the original stream. Destroy graph nodes
 // before their referenced events, and keep the original graph available.
 ProfileRestoreGraph();
 for(auto&p:profile_points)ProfileDestroy(p);
 ProfileDestroy(profile_span);ProfileDestroy(profile_prefix);ProfileDestroy(profile_head);
}
void ProfileAbort(const char*reason) noexcept {
 profile_done=true;profile_pending=false;profile_capture=false;
 ProfileMessage("unavailable",reason);ProfileRelease();
}
void ProfileRecord(Handle event) noexcept {
 if(api.hipEventRecord(event,stream))profile_error="event_record_failed";
}
ProfilePoint*ProfileKernelBegin(const std::string&module,const std::string&kernel) {
 if(profile_capture) {
  if(profile_points.size()>=1024)throw std::runtime_error("profile kernel limit");
  profile_points.push_back({module+"/"+kernel});auto&p=profile_points.back();
  ProfileCreate(p);
  // hipEventRecordExternal = 0x01 (HIP 7): an actual event node, not only a
  // capture dependency. Plain hipEventRecord is not a graph timing probe.
  api.Check(api.hipEventRecordWithFlags(p.begin,stream,1),"profile capture begin");
  return &p;
 }
 if(!profile_pending||!profile_detail)return nullptr;
 auto*p=kernel=="lmxxf_game_prefix_rgb"?&profile_prefix:
         kernel=="lmxxf_game_head_rgba"?&profile_head:nullptr;
 if(p)ProfileRecord(p->begin);
 return p;
}
void ProfileKernelEnd(ProfilePoint*p) {
 if(!p)return;
 if(profile_capture)api.Check(api.hipEventRecordWithFlags(p->end,stream,1),"profile capture end");
 else ProfileRecord(p->end);
}
bool ProfileElapsed(const ProfilePoint&p,float&ms) noexcept {
 return !api.hipEventElapsedTime(&ms,p.begin,p.end)&&std::isfinite(ms)&&ms>=0;
}
void ProfileBeforeFrame(void*rgba,void*history,void*output,U seed) noexcept {
 if(!opt.game_profile||profile_done)return;
 if(profile_pending) {
  // Never overwrite outstanding events or destroy in-flight graph resources.
  profile_error="missing_frame_drain";return;
 }
 if(++profile_frames<=profile_warmup)return;
 if(!graph_exec||game_disabled||!opt.game_rgb_io) {
  ProfileAbort("requires_direct_io_and_game_graph");return;
 }
 try {
  if(!profile_span.begin) {
   api.Load(api.hipEventRecordWithFlags,"hipEventRecordWithFlags");
   ProfileCreate(profile_span);ProfileCreate(profile_prefix);ProfileCreate(profile_head);
   ProfileMessage("collecting","gpu_events_not_fps");
  }
  if(profile_before==profile_window&&!profile_samples&&!profile_saved_exec) {
   profile_saved_graph=captured_graph;profile_saved_exec=graph_exec;
   profile_saved_nodes=game_nodes;captured_graph=graph_exec=nullptr;
   const auto prefix=game_prefix_binding;const auto head=game_head_binding;
   profile_capture=true;
   try{BuildGameGraph(rgba,history,output,seed);}
   catch(...){game_prefix_binding=prefix;game_head_binding=head;throw;}
   profile_capture=false;
   if(profile_points.empty()||game_nodes!=profile_saved_nodes+profile_points.size()*2)
    throw std::runtime_error("profile event nodes missing");
   profile_detail=true;
  }
  profile_pending=true;ProfileRecord(profile_span.begin);
 }catch(const std::exception&e){ProfileAbort(e.what());}
 catch(...){ProfileAbort("profile_setup_failed");}
}
void ProfileAfterEnqueue() noexcept {
 if(profile_pending)ProfileRecord(profile_span.end);
}
void ProfileAfterDrain() noexcept {
 if(!profile_pending)return;
 profile_pending=false;
 if(profile_error){ProfileAbort(profile_error);return;}
 float total=0;
 if(!ProfileElapsed(profile_span,total)||total<=0){ProfileAbort("invalid_network_interval");return;}
 if(profile_detail) {
  // Commit a sample only if every interval is valid. No partial ranking.
  double sum=0;std::vector<float> values;
  try{values.reserve(profile_points.size()+2);}catch(...){ProfileAbort("profile_memory_failed");return;}
  for(const auto*p:{&profile_prefix,&profile_head}) {
   float ms=0;if(!ProfileElapsed(*p,ms)){ProfileAbort("invalid_kernel_interval");return;}
   sum+=ms;values.push_back(ms);
  }
  for(const auto&p:profile_points) {
   float ms=0;if(!ProfileElapsed(p,ms)){ProfileAbort("invalid_kernel_interval");return;}
   sum+=ms;values.push_back(ms);
  }
  if(sum>total*1.02+0.01){ProfileAbort("inconsistent_event_intervals");return;}
  profile_prefix.sum+=values[0];profile_head.sum+=values[1];
  for(size_t i=0;i<profile_points.size();++i)profile_points[i].sum+=values[i+2];
  profile_detail_ms+=total;
  if(++profile_samples==profile_window)ProfileRestoreGraph();
 }else if(profile_before<profile_window){profile_before_ms+=total;++profile_before;}
 else {
  profile_after_ms+=total;
  if(++profile_after==profile_window) {
   try {
    std::map<std::string,std::pair<double,unsigned>> grouped;
    for(const auto&p:profile_points){auto&v=grouped[p.name];v.first+=p.sum;++v.second;}
    for(const auto*p:{&profile_prefix,&profile_head}){auto&v=grouped[p->name];v.first+=p->sum;++v.second;}
    std::vector<std::pair<std::string,std::pair<double,unsigned>>> ranked(grouped.begin(),grouped.end());
    std::sort(ranked.begin(),ranked.end(),[](const auto&a,const auto&b){return a.second.first>b.second.first;});
    std::ofstream out(opt.game_profile_report,std::ios::app);
    out.exceptions(std::ios::badbit|std::ios::failbit);
    out<<"profile_format=lmxxf-gpu-kernels-v1\nprofile_samples="<<profile_samples
       <<"\nreference_samples_each="<<profile_window
       <<"\nreference_before_gpu_ms="<<profile_before_ms/profile_window
       <<"\nprofiled_network_gpu_ms="<<profile_detail_ms/profile_window
       <<"\nreference_after_gpu_ms="<<profile_after_ms/profile_window
       <<"\nprofile_to_reference_ratio="<<2*profile_detail_ms/(profile_before_ms+profile_after_ms)
       <<"\ninstrumentation_and_scene_variation_affect_intervals=1"
       <<"\ngpu_intervals_are_not_fps=1\nnormal_graph_restored=1\n";
    for(const auto&v:ranked)out<<"kernel_gpu_ms="<<v.second.first/profile_window
       <<" calls_per_frame="<<v.second.second<<" kernel="<<v.first<<"\n";
    out<<"profile_status=complete\n";
   }catch(...){ProfileMessage("unavailable","report_write_failed");}
   profile_done=true;ProfileRelease();
  }
 }
}
