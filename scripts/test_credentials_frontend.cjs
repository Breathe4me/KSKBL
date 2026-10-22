/* Actual frontend / installed pywebview worker / real DPAPI; fabricated keys, no external clients. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),readline=require('node:readline');const {chromium}=require(process.env.CDA_PLAYWRIGHT);
const output=path.resolve(process.argv[2]),bootstrap=JSON.parse(fs.readFileSync(path.join(output,'pywebview-bootstrap.json'),'utf8'));
const report={mode:'actual clicks + real installed pywebview dispatch + Windows DPAPI; synthetic profiles only; no external service',cases:[]};let browser;
async function run(live){
  let page,seq=0,stderr='';const pending=new Map(),evaluations=[];
  const child=spawn(process.env.CDA_TEST_PYTHON,['-B',path.join(__dirname,'operation_trace_test_host.py'),path.join(output,'credentials-'+Date.now()),live?'synthetic-live':'qa'],{cwd:path.resolve(__dirname,'..'),env:{...process.env,PYTHONIOENCODING:'utf-8'},windowsHide:true,stdio:['pipe','pipe','pipe']});
  child.stderr.on('data',data=>stderr+=data);readline.createInterface({input:child.stdout}).on('line',line=>{const packet=JSON.parse(line);if(packet.evaluate_js){evaluations.push(page.evaluate(packet.evaluate_js));return;}pending.get(packet.id)?.(packet.result);pending.delete(packet.id);});
  const call=packet=>new Promise((resolve,reject)=>{const id=String(++seq),timer=setTimeout(()=>reject(new Error('host timeout '+stderr)),15000);pending.set(id,value=>{clearTimeout(timer);resolve(value);});child.stdin.write(JSON.stringify({...packet,id})+'\n');});
  const context=await browser.newContext();
  try{
    const {html}=await call({control:'setup'});page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.exposeFunction('nativePacket',packet=>call({packet}));await page.addInitScript(()=>{window.chrome=window.chrome||{};window.chrome.webview={postMessage:packet=>{window.nativePacket(packet);}};});
    await context.route('**/*',route=>route.request().url()==='https://cda-ui.invalid/index.html'?route.fulfill({body:html,contentType:'text/html'}):route.abort());
    await page.goto('https://cda-ui.invalid/index.html');await page.evaluate(bootstrap.prelude);await page.evaluate(bootstrap.finish);await page.waitForFunction(()=>CDAStartup.state.ready);
    await page.locator('[data-nav="settings"]').first().click();await page.locator('.tab[data-settings-tab="canvas"]').click();
    await page.locator('[data-setting="canvas_url"]').fill('https://canvas.example');await page.locator('#canvas-token').fill('SYNTHETIC-CANVAS-UI-CANARY');
    await page.locator('[data-action="savecanvas"]').click();await page.waitForFunction(()=>!ui.busy);
    assert.equal(await page.locator('#canvas-token').inputValue(),'');
    if(live){
      assert.equal(await page.evaluate(()=>ui.data.credentials.canvas),'saved');
      await page.locator('[data-remove-secret="canvas"]').click();await page.locator('[data-remove-confirmed="canvas"]').click();await page.waitForFunction(()=>!ui.busy&&ui.data.credentials.canvas==='missing');
    }else{assert.match(await page.locator('#toast').textContent(),/qa_credentials_disabled/);assert.equal(await page.evaluate(()=>ui.data.credentials.canvas),'missing');}
    await page.locator('[data-settings-tab="ai"]').click();await page.locator('#ai-token').fill('SYNTHETIC-DEEPSEEK-UI-CANARY');await page.locator('[data-save-secret="ai"]').click();await page.waitForFunction(()=>!ui.busy);
    if(live){
      assert.equal(await page.evaluate(()=>ui.data.credentials.ai),'saved');
      await page.locator('[data-setting="ai_provider"]').selectOption('OpenAI');
      assert.equal(await page.locator('[data-setting="ai_url"]').inputValue(),'https://api.openai.com/v1');
      await page.locator('#ai-token').fill('SYNTHETIC-OPENAI-UI-CANARY');await page.locator('[data-save-secret="ai"]').click();await page.waitForFunction(()=>!ui.busy&&ui.data.settings.ai_provider==='OpenAI');
      assert.equal(await page.evaluate(()=>ui.data.credentials.ai),'saved');
      const files=(await call({control:'snapshot'})).credential_files;assert.equal(files.filter(name=>name.startsWith('ai-')).length,2);
      await page.locator('[data-setting="ai_provider"]').selectOption('DeepSeek');await page.locator('.primary[data-action="savesettings"]').click();await page.waitForFunction(()=>!ui.busy&&ui.data.settings.ai_provider==='DeepSeek');assert.equal(await page.evaluate(()=>ui.data.credentials.ai),'saved');
      await page.locator('[data-remove-secret="ai"]').click();await page.locator('[data-remove-confirmed="ai"]').click();await page.waitForFunction(()=>!ui.busy&&ui.data.credentials.ai==='missing');
      await page.locator('[data-setting="ai_provider"]').selectOption('OpenAI');await page.locator('.primary[data-action="savesettings"]').click();await page.waitForFunction(()=>!ui.busy&&ui.data.settings.ai_provider==='OpenAI');assert.equal(await page.evaluate(()=>ui.data.credentials.ai),'saved');
    }else{assert.match(await page.locator('#toast').textContent(),/qa_credentials_disabled/);assert.equal((await call({control:'snapshot'})).credential_files.length,0);}
    const snapshot=await call({control:'snapshot'});assert.equal(JSON.stringify(snapshot.records).includes('UI-CANARY'),false);
    assert.equal(await page.locator('#ai-token').inputValue(),'');assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
    assert.deepEqual(errors,[]);assert.deepEqual(snapshot.errors,[]);assert.equal(stderr,'');await Promise.all(evaluations);
    report.cases.push({case:live?'Live_service_DPAPI_UI_add_delete_provider_switch_isolation':'QA_UI_explicit_denial_no_DPAPI',passed:true});
  }finally{await context.close();child.stdin.end();child.kill();}
}
(async()=>{browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-background-networking','--no-first-run']});await run(false);await run(true);report.status='passed';})()
.catch(error=>{report.status='failed';report.error=error.stack;process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();fs.writeFileSync(path.join(output,'CREDENTIAL_FRONTEND_TEST.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));});
