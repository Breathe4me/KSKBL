/* Real frontend + installed pywebview JS AND Python decoder + QA Bridge/config/SQLite.
   Only WebView2's transport is simulated; invisible browser, no native GUI. */
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const readline=require('node:readline');const {spawn}=require('node:child_process');
const {chromium}=require(process.env.CDA_PLAYWRIGHT);
const output=path.resolve(process.argv[2]);const stamp=String(Date.now());
const bootstrap=JSON.parse(fs.readFileSync(path.join(output,'pywebview-bootstrap.json'),'utf8'));
const report={mode:'genuine JS API + installed Python decoder + actual config/QA Bridge; simulated native transport; no Windows GUI',cases:[]};
let browser;
async function run(kind){
  const child=spawn(process.env.CDA_TEST_PYTHON,['-B',path.join(__dirname,'protocol_test_host.py'),path.join(output,'protocol-'+stamp+'-'+kind),kind],{cwd:path.resolve(__dirname,'..'),env:{...process.env,PYTHONIOENCODING:'utf-8'},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let stderr='';child.stderr.on('data',data=>stderr+=data);
  const queue=[];readline.createInterface({input:child.stdout}).on('line',line=>queue.shift()?.(JSON.parse(line)));
  const call=packet=>new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Protocol host timeout: '+stderr)),15000);
    queue.push(value=>{clearTimeout(timer);resolve(value);});child.stdin.write(JSON.stringify(packet)+'\n');
  });
  const context=await browser.newContext();
  try{
    const {html}=await call('setup');
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.exposeFunction('nativePacket',call);
    await page.addInitScript(()=>{
      window.chrome=window.chrome||{};
      window.chrome.webview={postMessage:packet=>{
        window.nativePacket(packet).then(reply=>{
          if(reply)window.pywebview._returnValuesCallbacks[reply.name][reply.id]({value:JSON.stringify(reply.value)});
        });
      }};
    });
    await context.route('**/*',route=>route.request().url()==='https://cda-ui.invalid/index.html'?route.fulfill({body:html,contentType:'text/html'}):route.abort());
    await page.goto('https://cda-ui.invalid/index.html');
    await page.evaluate(bootstrap.prelude);await page.evaluate(bootstrap.finish);
    await page.waitForFunction(()=>CDAStartup.state.ready||CDAStartup.state.failed);
    const success=kind==='legacy';
    assert.equal(await page.evaluate(()=>CDAStartup.state.ready),success);
    assert.equal(await page.locator('#startup-status').isVisible(),!success);
    const snapshot=await call('snapshot');
    assert.deepEqual(snapshot.errors,[]);assert.deepEqual(errors,[]);
    assert.equal(snapshot.stages.includes('backend_state_ready'),success);
    assert.equal(snapshot.stages.includes('ui_ready'),success);
    assert.equal(snapshot.stages.includes('bridge_ready'),true);
    assert.equal(snapshot.stages.includes('dom_ready'),true);
    assert.notEqual(snapshot.status,'ready'); // native navigation was deliberately NOT simulated as evidence
    report.cases.push({kind,passed:true,...snapshot});
    assert.equal(stderr,'');
  }finally{await context.close();child.stdin.end();child.kill();}
}
(async()=>{
  browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-background-networking','--no-first-run']});
  await run('legacy');await run('invalid');report.status='passed';
})().catch(error=>{report.status='failed';report.error=error.stack;process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();fs.writeFileSync(path.join(output,'BOOTSTRAP_PROTOCOL_TEST.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
});
