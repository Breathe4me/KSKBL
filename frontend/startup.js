/* First script: explicit boot stages, bounded failure deadline, no sensitive error strings. */
'use strict';
const CDAStartupConfig=__STARTUP_CONFIG__;
window.CDAOperations=(()=>{
  const config=CDAStartupConfig,events=[],clicks=new WeakMap(),pointers=new WeakMap();
  const operations=new Set(['get_state','set_tracking','workspace','sync','confirmstate','state_selection','save_settings','save_credential','remove_credential','verify_submission','assignment_context','test_pushplus','test_identity','open_official','generate_prompt','export_prompt','review_files','backup_data','import_backup','announcements','announcement_summary','test_ai','weekly_preview','runtime_status','confirm_push_received','copy_prompt','emergency_prepare','background_or_other_process','database_transaction','unknown','other','none']);
  const reasons=new Set(['bridge_operation_in_progress','profile_operation_in_progress','database_locked','outcome_pending','outcome_pending_reload_to_verify','expired_before_dispatch','disabled','frontend_busy','window_closed','invalid_trace_context','transport_exception','other']);
  const codes=new Set(['busy','request_timeout','window_closed','invalid_request','operation_failed','configuration_invalid','stale_account','sqlite_integrity','sqlite_busy','service_exception','qa_credentials_disabled','credential_value_required','credential_storage_failed','ai_endpoint_mismatch','other']);
  const stages=new Set(['click_received','frontend_guard_rejected','state_modal_open','action_started','action_failed','action_released','frontend_rpc_prepare','frontend_rpc_dispatch','frontend_rpc_response','frontend_rpc_rejected','frontend_rpc_timeout','frontend_rpc_settled','refresh_started','refresh_succeeded','refresh_failed','operation_cancelled']);
  const valid=id=>typeof id==='string'&&/^[a-f0-9]{32}$/.test(id);
  const newId=()=>{const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return [...bytes].map(n=>n.toString(16).padStart(2,'0')).join('');};
  const context=()=>{try{return window.CDAOperationContext?.()||{};}catch{return {};}};
  function record(stage,id,fields={}){
    if(!config.operations_enabled||!valid(id)||!stages.has(stage))return;
    const row={channel:'cda-operation-v1',run_id:config.run_id,request_id:id,stage};
    for(const key of ['busy','closed','disabled','ok','changed','has_bridge'])if(typeof fields[key]==='boolean')row[key]=fields[key];
    for(const key of ['owner_request_id','queue_request_id'])if(valid(fields[key]))row[key]=fields[key];
    for(const key of ['operation','owner','blocking_operation','queue_owner'])if(typeof fields[key]==='string')row[key]=operations.has(fields[key])?fields[key]:'other';
    for(const [key,allowed] of [['reason',reasons],['code',codes],['state',new Set(['ignored','completed','tracking'])]])if(typeof fields[key]==='string')row[key]=allowed.has(fields[key])?fields[key]:'other';
    events.push({...row,at:new Date().toISOString()});if(events.length>1000)events.shift();
    // Independent native diagnostic channel: never waits for Bridge.invoke or its business lock.
    try{window.chrome?.webview?.postMessage(row);}catch{/* bounded browser evidence remains exportable */}
  }
  function capture(event){
    const button=event.target.closest?.('button');if(!button)return;
    const state=button.dataset.state,confirm=button.dataset.action==='confirmstate';
    if(!['ignored','completed','tracking'].includes(state)&&!confirm)return;
    const ctx=context();let id=confirm&&valid(ctx.pending_request_id)?ctx.pending_request_id:newId();
    if(event.type==='pointerdown')pointers.set(button,id);
    else{if(pointers.has(button))id=pointers.get(button);pointers.delete(button);}
    clicks.set(event,id);
    record('click_received',id,{operation:'set_tracking',state:state||ctx.pending_state,...ctx,disabled:button.disabled});
    if(button.disabled||ctx.busy||ctx.closed)record('frontend_guard_rejected',id,{operation:'set_tracking',...ctx,disabled:button.disabled,reason:button.disabled?'disabled':ctx.closed?'window_closed':'frontend_busy'});
  }
  document.addEventListener('pointerdown',capture,true);document.addEventListener('click',capture,true);
  return {newId,record,forEvent:event=>clicks.get(event)||newId(),context,
    snapshot:()=>({run_id:config.run_id,identity:config.identity,events:[...events]}),
    exportText:()=>JSON.stringify({run_id:config.run_id,identity:config.identity,events:[...events]},null,2)};
})();
window.CDAStartup=(()=>{
  const config=CDAStartupConfig;
  const state={dom:false,bridge:false,ready:false,failed:false,events:[]};
  let resolveDom;const domReady=new Promise(resolve=>{resolveDom=resolve;});
  function send(event,detail={}){
    state.events.push(event);
    const message={channel:'cda-startup-v1',run_id:config.run_id,event,...detail};
    try{window.chrome?.webview?.postMessage(message);}catch{/* Python/native deadline remains authoritative. */}
  }
  function panel(){return document.getElementById('startup-status');}
  function paint(code){
    const box=panel();
    if(box){box.hidden=false;box.querySelector('[data-startup-title]').textContent='P0 · GUI Startup Failure';box.querySelector('[data-startup-code]').textContent=code;box.querySelector('[data-startup-path]').textContent=config.diagnostics;}
  }
  function fail(code,detail={}){
    if(state.failed)return;state.failed=true;state.failure=code;send(code,detail);paint(code);
  }
  function dom(){state.dom=true;send('dom_ready');if(state.failed)paint(state.failure);resolveDom();}
  document.addEventListener('DOMContentLoaded',dom,{once:true});
  window.addEventListener('pywebviewready',()=>{state.bridge=true;send('bridge_ready');});
  window.addEventListener('error',event=>{
    if(event.target!==window){fail('resource_failed');return;}
    fail('javascript_error',{line:event.lineno||0,column:event.colno||0});
  },true);
  window.addEventListener('unhandledrejection',()=>fail('javascript_error'));
  document.addEventListener('securitypolicyviolation',()=>fail('csp_violation'));
  const timer=setTimeout(()=>{if(!state.ready&&!state.failed)fail('backend_bootstrap_failed');},config.deadline_ms);
  return {state,domReady,fail,bridge(){if(!state.bridge){state.bridge=true;send('bridge_ready');}},ready(){
    if(state.failed)return false;
    if(!state.dom||!state.bridge||!document.querySelector('#page')?.childElementCount||document.querySelectorAll('.navitem').length!==5){fail('backend_bootstrap_failed');return false;}
    state.ready=true;clearTimeout(timer);send('ui_ready');if(panel())panel().hidden=true;return true;
  }};
})();
