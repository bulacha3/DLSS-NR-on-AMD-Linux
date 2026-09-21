// Included inside Network. Only the invariant tail is captured. The prefix
// stays a regular dispatch, so seed/history/features are fresh on every frame.
// Capture records on a private nonblocking stream; ALL execution, including
// the graph replay, remains on the original borrowed stream (which may be 0).
struct GamePrefixBinding {
 void *ffn{},*attention{},*main{},*down{};
 U windows{},mode{},width{},height{};
 bool valid{};
} game_prefix_binding;
struct GameHeadBinding {
 void *low{},*skip{},*scales{},*ffn{},*attention{},*head{};
 U windows{},width{},height{},sx{},sy{};
 float scale{};
 bool valid{};
} game_head_binding;
void*game_frame_output{}; // Borrowed only until the original frame drains.
Handle game_capture_stream{};
bool game_warmed{},game_disabled{},game_recording{};
uint64_t game_direct{},game_replays{},game_builds{},game_nodes{};
std::string game_reason;

void GamePrefix(void*rgba,void*history,void*ffn,void*attention,void*main,void*down,
                U windows,U mode,U width,U height,U seed,U temporal) {
 if(game_recording) {
  if(game_prefix_binding.valid)throw std::runtime_error("multiple game prefixes");
  game_prefix_binding={ffn,attention,main,down,windows,mode,width,height,true};
  return; // No execution or capture of frame-dependent arguments.
 }
 Run(opt.game_rgb_io?"c32_game_io":"c32_game_prefix",opt.game_rgb_io?"lmxxf_game_prefix_rgb":"lmxxf_game_prefix",windows,rgba,history,ffn,attention,
     main,down,windows,mode,U(1),width,height,seed,temporal,opt.prefix_parameters);
}

void GameHead(void*low,void*skip,void*scales,void*ffn,void*attention,
              void*color,void*head,void*output,U windows,U width,U height,
              U sx,U sy,float scale) {
 if(game_recording){
  if(game_head_binding.valid)throw std::runtime_error("multiple game heads");
  game_head_binding={low,skip,scales,ffn,attention,head,windows,width,height,sx,sy,scale,true};
  return; // Never capture an external game input/output address.
 }
 Run("c32_game_io","lmxxf_game_head_rgba",windows,low,skip,scales,ffn,attention,
     color,head,output,windows,width,height,sx,sy,scale);
}

void DisableGameGraph(const char*reason) {
 game_disabled=true;game_reason=reason;
 // None of these graph objects has been launched on the fallback path.
 ClearGraph();game_prefix_binding={};game_head_binding={};game_nodes=0;
}

void BuildGameGraph(void*rgba,void*history,void*rgb_output,U seed) {
 const Handle original=stream;
 bool active=false;
 try {
  api.EnableGameGraphs();
  if(!game_capture_stream)api.Check(api.hipStreamCreateWithFlags(&game_capture_stream,1),"graph capture stream");
  if(!game_capture_stream||game_capture_stream==original)
   throw std::runtime_error("graph capture needs a separate nonblocking stream");
  api.Check(api.hipStreamBeginCapture(game_capture_stream,1),"game graph begin");
  active=true;stream=game_capture_stream;graph_capturing=true;game_recording=true;
  game_prefix_binding={};game_head_binding={};
  EnqueueRaw(rgba,history,rgb_output,seed);
  game_recording=false;graph_capturing=false;stream=original;
  const int result=api.hipStreamEndCapture(game_capture_stream,&captured_graph);
  active=false;api.Check(result,"game graph end");
  if(!game_prefix_binding.valid||!captured_graph||(opt.game_rgb_io&&!game_head_binding.valid))
   throw std::runtime_error("game graph missing prefix or tail");
  size_t nodes=0;
  api.Check(api.hipGraphGetNodes(captured_graph,nullptr,&nodes),"game graph nodes");
  if(!nodes)throw std::runtime_error("empty game graph");
  api.Check(api.hipGraphInstantiate(&graph_exec,captured_graph,nullptr,nullptr,0),"game graph instantiate");
  game_nodes=nodes;++game_builds;
 }catch(const std::exception&e) {
  game_recording=false;graph_capturing=false;stream=original;
  // A failed record/instantiate submitted no neural work. End the private
  // capture before falling back once to the already working direct path.
  if(active){Handle abandoned{};api.hipStreamEndCapture(game_capture_stream,&abandoned);if(abandoned)api.hipGraphDestroy(abandoned);}
  inline_prefix=false;inline_rgba.reset();inline_hist.reset();
  if(profile_capture){ClearGraph();throw;}
  DisableGameGraph(e.what());
 }
}

void EnqueueGameGraph(void*rgba,void*history,void*rgb_output,U seed) {
 if(!game_warmed) {
  EnqueueRaw(rgba,history,rgb_output,seed);
  graph_input=opt.game_rgb_io?nullptr:rgba;graph_output=opt.game_rgb_io?nullptr:rgb_output;game_warmed=true;++game_direct;
  return;
 }
 // The resident buffers are stable. Do not replay stale external addresses if
 // a different caller breaks that contract. No seed/history cache key exists.
 if(!opt.game_rgb_io&&!game_disabled&&(rgba!=graph_input||rgb_output!=graph_output)) {
  Synchronize();DisableGameGraph("resident input/output address changed");
 }
 if(!game_disabled&&!graph_exec)BuildGameGraph(rgba,history,rgb_output,seed);
 if(game_disabled) {
  if(opt.game_profile&&!profile_done)ProfileAbort("game_graph_unavailable");
  EnqueueRaw(rgba,history,rgb_output,seed);++game_direct;return;
 }
 ProfileBeforeFrame(rgba,history,rgb_output,seed);
 const auto&p=game_prefix_binding;
 GamePrefix(rgba,history?history:rgba,p.ffn,p.attention,p.main,p.down,
            p.windows,p.mode,p.width,p.height,seed,U(history!=nullptr));
 // Any failure from here is fatal to the frame: never rerun after a possibly
 // partial launch, never destroy buffers before the borrowed stream drains.
 api.Check(api.hipGraphLaunch(graph_exec,stream),"game graph replay");
 if(opt.game_rgb_io){
  const auto&h=game_head_binding;
  GameHead(h.low,h.skip,h.scales,h.ffn,h.attention,rgba,h.head,rgb_output,
           h.windows,h.width,h.height,h.sx,h.sy,h.scale);
 }
 ProfileAfterEnqueue();
 ++game_replays;
}
