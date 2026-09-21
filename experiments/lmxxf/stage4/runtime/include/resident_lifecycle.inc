// Public Network methods, used only by the resident ABI after a proved drain.
// No network kernel, packed weight, rounding or geometry formula is changed.
void ConfirmExternalDrain() { external_drain=true;ProfileAfterDrain();if(opt.game_rgb_io){game_frame_output=nullptr;borrowed_output=nullptr;graph_input=graph_history=graph_output=nullptr;} }

void MarkScratchDrained() {
 for(auto&t:pool)t->drained=true;
 for(auto&m:gather_maps)for(auto&t:m)t.second->drained=true;
 if(device_noise)device_noise->drained=true;
 if(vit_in8)vit_in8->drained=true;
}

void MarkAllDrained() {
 MarkScratchDrained();
 for(auto&t:weights)t.second->drained=true;
}

void ResizeAfterDrain(U width,U height) {
 struct lmxxf_geometry geometry;
 if(!external_drain||!opt.use_shared_stream||!opt.game_prefix||
    !lmxxf_geometry(width,height,&geometry))
  throw std::runtime_error("resident resize requires drained game geometry");
 if(width==W&&height==H)return;
 if(opt.game_profile&&!profile_done)ProfileAbort("geometry_changed_during_collection");
 ClearGraph();
 if(game_capture_stream){api.Check(api.hipStreamDestroy(game_capture_stream),"resize capture stream");game_capture_stream=nullptr;}
 graph_input=graph_history=graph_output=nullptr;graph_warmed=false;
 game_prefix_binding={};game_head_binding={};game_frame_output=nullptr;game_warmed=false;game_nodes=0;
 // Keep a diagnosed graph-API fallback disabled. Never retry it every resize.
 inline_prefix=false;inline_rgba.reset();inline_hist.reset();
 MarkScratchDrained();vit_in8.reset();device_noise.reset();
 gather_maps[0].clear();gather_maps[1].clear();pool.clear();
 borrowed_output=nullptr;
 W=opt.width=width;H=opt.height=height;
}

void ResidencyUsage(uint64_t&weight_bytes,uint64_t&scratch_bytes)const {
 weight_bytes=scratch_bytes=0;
 for(const auto&t:weights)weight_bytes+=t.second->capacity;
 for(const auto&t:pool)scratch_bytes+=t->capacity;
 for(const auto&m:gather_maps)for(const auto&t:m)scratch_bytes+=t.second->capacity;
 if(device_noise)scratch_bytes+=device_noise->capacity;
}
