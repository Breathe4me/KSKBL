/* Browser-only Mock Adapter. Production app.js, layout and styles remain unchanged. */
'use strict';
const previewFixture = __QA_FIXTURE__;
const previewState = structuredClone(previewFixture.state);
const mockCopy = value => structuredClone(value);
const mockResponse = data => ({ok:true,data:{...data,mock:true,adapter:'Browser Mock Adapter'}});
const mockFailure = code => ({ok:false,error:'mock_adapter_'+code});
window.CDA_PREVIEW_MODE = 'browser_mock';
window.pywebview = {api:{invoke:async(method,params={})=>{
  if (!params || typeof params!=='object' || Array.isArray(params)) return mockFailure('invalid_parameters');
  if (method==='get_state') return mockResponse(mockCopy(previewState));
  if (method==='save_settings') {
    const changes=params.settings;
    if (!changes || typeof changes!=='object' || Array.isArray(changes)) return mockFailure('invalid_settings');
    if (Object.keys(changes).some(key=>!Object.hasOwn(previewState.settings,key))) return mockFailure('unknown_setting');
    if (changes.monitoring===true) return mockFailure('no_task_scheduler');
    if (changes.theme && !['sage','pink'].includes(changes.theme)) return mockFailure('invalid_theme');
    if (changes.language && !['zh','en'].includes(changes.language)) return mockFailure('invalid_language');
    if (changes.timezone) {try{new Intl.DateTimeFormat('en',{timeZone:changes.timezone});}catch{return mockFailure('invalid_timezone');}}
    Object.assign(previewState.settings,mockCopy(changes));
    return mockResponse({saved:true,persistence:'memory_only_resets_on_reload'});
  }
  if (['set_tracking','verify_submission','assignment_context','generate_prompt'].includes(method)) {
    if (params.account_scope!==previewState.account_scope) return mockFailure('stale_account');
    const task=previewState.tasks.find(task=>task.key===params.key);
    if (!task) return mockFailure('unknown_task');
    if (method==='set_tracking') {
      if (!['tracking','completed','ignored'].includes(params.state)) return mockFailure('invalid_tracking_state');
      task.local={...task.local,state:params.state,reason:params.reason||'',note:String(params.note||'').slice(0,500)};
      return mockResponse({saved:true});
    }
    if (method==='verify_submission') {
      const checked=new Date().toISOString();
      previewState.history.push({key:task.key,checked,status:'Unknown / Unable to Verify',attempt:null,error:'Browser Mock: no Canvas request'});
      return mockResponse({status:'Unknown / Unable to Verify',checked,qa:true,live_request:false});
    }
    if (method==='assignment_context') return mockResponse(mockCopy(previewFixture.contexts[task.key]));
    return mockResponse({text:previewFixture.prompts[task.key],generated_locally:true,precomputed_synthetic_fixture:true});
  }
  if (method==='sync') return mockResponse({status:'mock_only_no_sync',live_request:false});
  if (method==='test_identity') return mockResponse({status:'qa_offline',live_request:false});
  if (method==='announcements') return mockResponse(mockCopy(previewFixture.announcements));
  if (method==='announcement_summary') return mockResponse({status:'disabled',text:'Mock Adapter：不调用 AI；此处不提供真实摘要。 / No AI call or real summary.'});
  if (method==='workspace' && params.operation==='revoke') return mockResponse({status:'revoked'});
  // Never accept secrets, open external pages/native dialogs, send messages or call AI.
  return mockFailure('operation_unavailable_no_python_or_external_service');
}}};
window.addEventListener('DOMContentLoaded',()=>{
  // Keep the transport label independent of production render() and its timing.
  const notice=document.createElement('div');
  notice.id='browser-mock-notice';notice.setAttribute('role','note');
  notice.textContent='Browser Mock Adapter · 离线合成预览 / Offline synthetic preview · No Python/API';
  notice.style.cssText='position:fixed;bottom:8px;left:8px;z-index:90;max-width:calc(100vw - 16px);padding:6px 10px;border-radius:8px;background:#fff;color:#354a40;border:1px solid #bbc9bf;font:12px/1.4 Segoe UI,Microsoft YaHei UI,sans-serif;pointer-events:none';
  document.body.appendChild(notice);
  const appRender=window.render;
  window.render=function(){
    appRender();
    const english=ui.data?.settings.language==='en';
    document.querySelector('.statuschip').textContent=english?'Mock Adapter · Offline preview':'Mock Adapter · 离线预览';
    document.querySelector('.subbrand').textContent='v1.2 · BROWSER MOCK';
    document.querySelector('.sidebarfoot').textContent=english?'Synthetic data · No Python/API':'合成数据 · 无 Python/API';
    document.querySelector('.footer').textContent=english?'Browser Mock Adapter · Real frontend · In-memory changes reset on reload · Do not enter real tokens':'浏览器 Mock Adapter · 当前真实前端 · 刷新后重置 · 请勿输入真实 Token';
  };
  document.title='Canvas Deadline Agent v1.2 · Mock Adapter Offline Preview';
  window.dispatchEvent(new Event('pywebviewready'));
},{once:true});
