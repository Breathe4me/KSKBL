/* Invisible real frontend -> concurrent Python Bridge -> actual SQLite. No mock state writes. */
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const readline=require('node:readline');const {spawn}=require('node:child_process');
const {chromium}=require(process.env.CDA_PLAYWRIGHT);
const output=path.resolve(process.argv[2]);const stamp=String(Date.now());
const result={mode:'real UI/service/SQLite; concurrent RPC threads; barriers only; invisible browser, no VM',cases:[]};
let browser;
async function run(baseline){
  const child=spawn(process.env.CDA_TEST_PYTHON,['-B',path.join(__dirname,'assignment_test_host.py'),path.join(output,`mutation-${stamp}-${baseline?'baseline':'fixed'}`),baseline?'baseline':'fixed'],{cwd:path.resolve(__dirname,'..'),env:{...process.env,PYTHONIOENCODING:'utf-8'},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let stderr='',seq=0;const pending=new Map();child.stderr.on('data',data=>stderr+=data);
  readline.createInterface({input:child.stdout}).on('line',line=>{const packet=JSON.parse(line);pending.get(packet.id)?.(packet);pending.delete(packet.id);});
  const call=packet=>new Promise((resolve,reject)=>{const id=String(++seq);const timer=setTimeout(()=>reject(new Error('host deadline '+stderr)),20000);pending.set(id,response=>{clearTimeout(timer);response.host_error?reject(new Error(response.host_error)):resolve(response.result);});child.stdin.write(JSON.stringify({...packet,id})+'\n');});
  const rpc=(method,params={})=>call({method,params});const control=(control,params={})=>call({control,...params});
  const context=await browser.newContext();
  try{
    const {html}=await control('setup');const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.exposeFunction('actualBackend',rpc);
    await context.route('**/*',route=>route.request().url()==='https://cda-ui.invalid/index.html'?route.fulfill({body:html,contentType:'text/html'}):route.abort());
    const load=async()=>{await page.goto('https://cda-ui.invalid/index.html');await page.evaluate(()=>{window.pywebview={api:{invoke:window.actualBackend}};window.dispatchEvent(new Event('pywebviewready'));});await page.waitForFunction(()=>CDAStartup.state.ready);};
    await load();const key='1:assignment:1';const before=Number(await page.locator('#pending-count').textContent());
    const open=async(state)=>{await page.locator('[data-nav="assignments"]').first().click();await page.waitForFunction(()=>!ui.busy);await page.locator('[data-filter="all"]').click();await page.locator(`[data-open="${key}"]`).first().click();await page.locator(`[data-state="${state}"]`).click();};
    await open('ignored');await control('hold',{method:'workspace'});await page.locator('[data-action="confirmstate"]').click();
    await assertEventually(async()=>(await control('entered')).entered);
    if(baseline){
      await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('busy'));
      const database=await control('database');assert.equal(database.local.find(t=>t.task_key===key).state,'ignored');
      assert.equal(await page.evaluate(()=>ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state),'tracking');
      result.cases.push({case:'archived_original_UI_and_Bridge_reproduce_busy_after_commit',passed:true,sqlite:'ignored',ui:'tracking'});
      await control('release');return;
    }
    assert.equal(await page.evaluate(()=>ui.busy),true);
    // Double click cannot dispatch another write while confirmation is pending.
    await page.evaluate(()=>{document.querySelector('[data-action="confirmstate"]')?.click();});
    await control('release');await page.waitForFunction(()=>!ui.busy&&ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state==='ignored');
    assert.equal(Number(await page.locator('#pending-count').textContent()),before-1);
    let database=await control('database');assert.equal(database.local.find(t=>t.task_key===key).state,'ignored');
    assert.equal(database.history.filter(t=>t.task_key===key).length,1);
    assert.equal(database.tasks.find(t=>t.key===key).status,'Confirmed Not Submitted');
    await load();assert.equal(await page.evaluate(()=>ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state),'ignored');
    assert.equal((await control('restart')).data.tasks.find(t=>t.key===key).local.state,'ignored');
    result.cases.push({case:'ignore_commits_once_refresh_and_restart_preserve_state_dashboard_decreases',passed:true});
    for(const state of ['tracking','completed']){
      await open(state);await page.locator('[data-action="confirmstate"]').click();
      await page.waitForFunction(state=>!ui.busy&&ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state===state,state);
      database=await control('database');assert.equal(database.local.find(t=>t.task_key===key).state,state);
      assert.equal(database.tasks.find(t=>t.key===key).status,'Confirmed Not Submitted');
      assert.equal(Number(await page.locator('#pending-count').textContent()),state==='tracking'?before:before-1);
    }
    result.cases.push({case:'restore_and_complete_use_real_SQLite_Canvas_unchanged',passed:true});
    // Genuine SQL exception, not a mocked mutation function; retry only after removing test trigger.
    await open('ignored');await control('fail_writes');await page.locator('[data-action="confirmstate"]').click();
    await page.waitForFunction(()=>!ui.busy&&document.getElementById('toast').textContent.includes('operation_failed'));
    assert.equal(await page.locator('[data-action="confirmstate"]').isEnabled(),true);
    assert.equal((await control('database')).local.find(t=>t.task_key===key).state,'completed');
    await control('allow_writes');await page.locator('[data-action="confirmstate"]').click();
    await page.waitForFunction(()=>!ui.busy&&ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state==='ignored');
    result.cases.push({case:'SQL_failure_rolls_back_buttons_recover_retry_succeeds',passed:true});
    // Sync and state requests enter native Bridge on different real Python threads.
    await control('hold',{method:'sync'});const syncing=rpc('sync');await assertEventually(async()=>(await control('entered')).entered);
    await open('tracking');await page.locator('[data-action="confirmstate"]').click();
    await page.waitForFunction(()=>!ui.busy&&document.getElementById('toast').textContent.includes('bridge_operation_in_progress'));
    assert.match(await page.locator('#toast').textContent(),/sync/);await control('release');assert.equal((await syncing).ok,true);
    await page.locator('[data-action="confirmstate"]').click();await page.waitForFunction(()=>!ui.busy&&ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state==='tracking');
    result.cases.push({case:'concurrent_sync_returns_classified_busy_then_real_retry_succeeds',passed:true});
    // Deadline does not release transport queue or replay an in-flight mutation.
    await page.clock.install();await control('hold',{method:'workspace'});
    const revoke=page.evaluate(()=>rpc('workspace',{operation:'revoke',key:'1:assignment:1',account_scope:ui.data.account_scope}).catch(e=>e.code));
    await assertEventually(async()=>(await control('entered')).entered);
    const queued=page.evaluate(()=>action(()=>rpc('set_tracking',{key:'1:assignment:1',account_scope:ui.data.account_scope,state:'completed'})));
    await page.waitForFunction(()=>ui.busy);await page.clock.fastForward(60001);await revoke;await queued;
    assert.equal(await page.evaluate(()=>ui.busy),false);
    assert.equal((await control('database')).local.find(t=>t.task_key===key).state,'tracking');
    await control('release');await page.evaluate(()=>rpcTail); // expired queued write must never reach Python
    assert.equal((await control('database')).local.find(t=>t.task_key===key).state,'tracking');
    result.cases.push({case:'timeout_restores_UI_expired_queued_write_never_executes',passed:true});
    await control('hold',{method:'set_tracking'});
    const active=page.evaluate(()=>action(()=>rpc('set_tracking',{key:'1:assignment:1',account_scope:ui.data.account_scope,state:'completed'})));
    await assertEventually(async()=>(await control('entered')).entered);
    await page.clock.fastForward(60001);await active;assert.equal(await page.evaluate(()=>ui.busy),false);
    const historyBefore=(await control('database')).history.filter(t=>t.task_key===key).length;
    await page.evaluate(()=>action(()=>rpc('set_tracking',{key:'1:assignment:1',account_scope:ui.data.account_scope,state:'completed'})));
    assert.match(await page.locator('#toast').textContent(),/busy.*outcome_pending/);
    await control('release');await page.evaluate(()=>rpcTail);await page.evaluate(()=>refresh());
    database=await control('database');assert.equal(database.local.find(t=>t.task_key===key).state,'completed');
    assert.equal(database.history.filter(t=>t.task_key===key).length,historyBefore+1);
    assert.equal(database.tasks.find(t=>t.key===key).status,'Confirmed Not Submitted');
    result.cases.push({case:'active_timeout_retains_queue_and_pending_key_no_duplicate_write_reconcile_real_state',passed:true});
    assert.deepEqual(errors,[]);assert.equal(stderr,'');
  }finally{await control('release').catch(()=>{});await context.close();child.stdin.end();child.kill();}
}
async function assertEventually(check){for(let i=0;i<500;i++){if(await check())return;await new Promise(resolve=>setTimeout(resolve,5));}throw new Error('Barrier not entered');}
(async()=>{browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-background-networking','--no-first-run']});await run(true);await run(false);result.status='passed';})()
.catch(error=>{result.status='failed';result.error=error.stack;process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();fs.writeFileSync(path.join(output,'ASSIGNMENT_MUTATION_DOM.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));});
