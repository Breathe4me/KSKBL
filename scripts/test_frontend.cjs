/* Code-only test: invisible headless browser + real Python bridge over stdio. No desktop actions. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.CDA_PLAYWRIGHT);

const root=path.resolve(__dirname,'..');
const run=path.join(root,'reports','dom-'+new Date().toISOString().replace(/[:.]/g,'-'));
fs.mkdirSync(run,{recursive:true});
const python=spawn(process.env.CDA_TEST_PYTHON,['-B',path.join(root,'scripts/bridge_test_host.py'),path.join(run,'profile')],{cwd:root,env:process.env,windowsHide:true,stdio:['pipe','pipe','pipe']});
const pending=[];
let stderr='';python.stderr.on('data',data=>stderr+=data);
readline.createInterface({input:python.stdout}).on('line',line=>{const wait=pending.shift();if(wait)wait.resolve(JSON.parse(line));});
function rpc(method,params={}){return new Promise((resolve,reject)=>{pending.push({resolve,reject});python.stdin.write(JSON.stringify({method,params})+'\n');});}
const results={mode:'headless DOM + Python stdio; no Windows GUI or host screen capture',cases:[],screenshots:[],requestCount:0};
let browser;
(async()=>{
  browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-background-networking','--no-first-run']});
  const html=fs.readFileSync(path.join(root,'reports/headless-doc.html'),'utf8');
  for(const [width,height] of [[1440,900],[1180,800],[1000,700],[900,700]]){
    for(const scale of [1,1.25,1.5]){
      const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:scale,reducedMotion:'reduce'});
      await context.route('**/*',route=>{results.requestCount++;return route.abort();});
      const page=await context.newPage();
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.exposeFunction('backendCall',rpc);
      await page.setContent(html,{waitUntil:'domcontentloaded'});
      if(process.env.CDA_NATIVE_BOOTSTRAP){
        const bootstrap=JSON.parse(fs.readFileSync(process.env.CDA_NATIVE_BOOTSTRAP,'utf8'));
        await page.evaluate(()=>{window.__nativeStartupMessages=[];window.chrome=window.chrome||{};window.chrome.webview={postMessage:packet=>{
          if(!Array.isArray(packet)){window.__nativeStartupMessages.push(packet);return;}
          const [name,args,id]=packet;if(name!=='invoke')return;
          window.backendCall(...JSON.parse(args)).then(result=>window.pywebview._returnValuesCallbacks[name][id]({value:JSON.stringify(result)}));
        }};});
        await page.evaluate(bootstrap.prelude);await page.evaluate(bootstrap.finish);
        results.transport='installed pywebview JS API + simulated native pipe + real Python stdio (not Windows WebView2)';
      }else await page.evaluate(()=>{window.pywebview={api:{invoke:(method,params)=>window.backendCall(method,params)}};window.dispatchEvent(new Event('pywebviewready'));});
      await page.waitForFunction(()=>!!ui.data&&window.CDAStartup.state.ready);
      assert.equal(await page.locator('#startup-status').isVisible(),false,'Startup overlay must clear only after UI Ready');
      for(const language of ['zh','en'])for(const theme of ['sage','pink']){
        await page.evaluate(()=>{closeDrawer();closeModal();});
        await rpc('save_settings',{settings:{language,theme}});
        await page.evaluate(()=>refresh());
        const checks=[];
        for(const destination of ['today','assignments','records','notifications','settings']){
          await page.evaluate(destination=>{ui.page=destination;ui.settingsTab='appearance';render();},destination);
          await page.waitForTimeout(15);
          const metrics=await page.evaluate(()=>{
            const app=document.querySelector('.app'),sidebar=document.querySelector('.sidebar');
            const invalid=[...document.querySelectorAll('.content button,.content input,.content select,.content textarea')].filter(node=>{const r=node.getBoundingClientRect();return r.width>0&&r.height>0&&(r.left < -1 || r.right > document.documentElement.clientWidth+1);}).map(n=>n.textContent||n.id);
            const cards=[...document.querySelectorAll('.task')].map(node=>node.getBoundingClientRect().toJSON());
            return {rootOverflow:document.documentElement.scrollWidth>innerWidth+1,contentOverflow:app.scrollWidth>app.clientWidth+1,sidebarWidth:sidebar.getBoundingClientRect().width,invalid,cards};
          });
          assert.equal(metrics.rootOverflow,false,JSON.stringify({width,height,scale,language,theme,destination,metrics}));
          assert.equal(metrics.contentOverflow,false,JSON.stringify({width,height,scale,language,theme,destination,metrics}));
          assert.deepEqual(metrics.invalid,[],JSON.stringify({width,height,scale,language,theme,destination,metrics}));
          for(let i=1;i<metrics.cards.length;i++)assert(metrics.cards[i].top>=metrics.cards[i-1].bottom-1,'Task cards overlap');
          checks.push(destination);
          if(destination==='settings')for(const section of ['canvas','reminders','ai','advanced']){
            await page.locator(`[data-settings-tab="${section}"]`).first().click();
            await page.locator('details').evaluateAll(nodes=>nodes.forEach(n=>n.open=true));
            const overflow=await page.evaluate(()=>{const app=document.querySelector('.app');return app.scrollWidth>app.clientWidth+1;});
            assert.equal(overflow,false,`Expanded settings overflow: ${width}/${scale}/${language}/${section}`);
            checks.push('settings/'+section);
          }
        }
        await page.evaluate(()=>{ui.page='assignments';render();drawer(ui.data.tasks[0].key);document.querySelector('.copilotoptions').open=true;});
        assert.equal(await page.locator('#drawer').evaluate(node=>node.scrollWidth>node.clientWidth+1),false,'Expanded drawer overflow');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#drawer').getAttribute('aria-hidden'),'true');
        if(width===1440&&scale===1){
          await page.evaluate(()=>{ui.page='today';render();});
          if(theme==='sage'&&language==='zh'){
            const cdp=await context.newCDPSession(page);await cdp.send('DOM.enable');await cdp.send('CSS.enable');
            const document=await cdp.send('DOM.getDocument');
            const node=await cdp.send('DOM.querySelector',{nodeId:document.root.nodeId,selector:'#pagetitle'});
            results.titleFonts=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId:node.nodeId})).fonts;
            await cdp.detach();
          }
          const file=path.join(run,`offscreen-${theme}-${language}-today.png`);await page.screenshot({path:file});results.screenshots.push(file);
          if(theme==='pink'&&language==='zh'){
            await page.evaluate(()=>{ui.page='settings';ui.settingsTab='appearance';render();});
            const settings=path.join(run,'offscreen-pink-settings.png');await page.screenshot({path:settings});results.screenshots.push(settings);
          }
        }
        if(width===900&&scale===1&&language==='zh'&&theme==='sage'){
          await page.evaluate(()=>{ui.page='assignments';render();drawer(ui.data.tasks[0].key);});
          const file=path.join(run,'offscreen-900x700-drawer.png');await page.screenshot({path:file});results.screenshots.push(file);
        }
        results.cases.push({width,height,deviceScaleFactor:scale,language,theme,pages:checks,passed:true});
      }
      assert.deepEqual(errors,[],'Browser script error');
      // Actual Python SQLite state change through a DOM click and explicit modal confirmation.
      if(width===1440&&scale===1){
        await page.evaluate(()=>{ui.page='assignments';ui.filter='all';render();drawer(ui.data.tasks.find(t=>t.key==='1:assignment:1').key);});
        await page.locator('[data-state="ignored"]').click();
        await page.locator('#localnote').fill('DOM integration note');
        await page.locator('[data-action="confirmstate"]').click();
        await page.waitForFunction(()=>ui.data.tasks.find(t=>t.key==='1:assignment:1').local.state==='ignored');
        const actual=await rpc('get_state');assert.equal(actual.data.tasks[0].local.note,'DOM integration note');
        assert.equal(actual.data.tasks[0].status,'Confirmed Not Submitted');
        await rpc('set_tracking',{key:'1:assignment:1',account_scope:actual.data.account_scope,state:'tracking'});
        await page.evaluate(()=>refresh());
        // Untrusted task strings must render literally, without creating active DOM content.
        await page.evaluate(()=>{ui.data.tasks[0].title='<img src="https://invalid.example/" onerror="window.__xss=true">';ui.page='today';render();});
        assert.equal(await page.locator('.taskTitle img').count(),0);
        assert.equal(await page.evaluate(()=>window.__xss),undefined);
        await page.evaluate(()=>refresh());
        await page.locator('[data-open="1:assignment:1"]').first().click();
        await page.locator('[data-action="prompt"]').click();
        await page.waitForFunction(()=>document.querySelector('#context-body textarea')?.value.includes('Academic assistance request'));
        await page.locator('.copilotoptions summary').click();
        await page.locator('[data-action="wsfiles"]').click();
        assert.equal(await page.locator('[data-action="wsconfirmed"]').count(),1);
        await page.locator('[data-close="modal"]').click();
        await page.locator('[data-action="reviewfiles"]').click();
        assert.equal(await page.locator('#overlay.show').count(),1);
        await page.locator('[data-close="modal"]').click();
        await page.locator('[data-close="drawer"]').click();
        await page.evaluate(()=>{ui.page='settings';ui.settingsTab='ai';render();});
        await page.locator('[data-toggle-setting="ai_enabled"]').click();
        assert.equal(await page.locator('#overlay.show').count(),1);
        await page.locator('[data-close="modal"]').click();
        assert.equal((await rpc('get_state')).data.settings.ai_enabled,false);
        await page.locator('[data-action="announcements"]').click();
        await page.locator('[data-announcement="1:announcement:1"]').click();
        await page.waitForFunction(()=>document.querySelector('#modal').textContent.includes('Synthetic QA announcement'));
        await page.locator('[data-action="summarygenerate"]').click();
        assert.equal(await page.locator('[data-action="confirmedai"]').count(),1);
        await page.locator('[data-close="modal"]').click();
        await page.evaluate(()=>{ui.settingsTab='reminders';render();});
        await page.locator('[data-setting="mode"]').selectOption('exam');
        await page.locator('[data-setting="channels"]').selectOption('windows');
        await page.locator('[data-action="savesettings"]').click();
        await page.waitForFunction(()=>ui.data.settings.mode==='exam');
        await page.evaluate(()=>{ui.settingsTab='appearance';render();});
        await page.locator('button[data-theme="pink"]').click();
        await page.waitForFunction(()=>document.documentElement.dataset.theme==='pink');
        await page.locator('[data-language="zh"]').click();
        await page.waitForFunction(()=>document.documentElement.lang==='zh-CN');
        const persisted=(await rpc('get_state')).data.settings;
        assert.equal(persisted.theme,'pink');assert.equal(persisted.language,'zh');assert.equal(persisted.mode,'exam');
        results.interaction={sqliteLocalState:true,canvasStatePreserved:true,xssEscaped:true,localPrompt:true,nativeConfirmation:true,aiConsentCancel:true,announcementRead:true,aiRequestConfirmation:true,settingsPersisted:true};
      }
      await context.close();
    }
  }
  assert.equal(results.requestCount,0,'The bundled UI attempted a network request');
  results.status='passed';
})().catch(error=>{results.status='failed';results.error=error.stack;process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();python.stdin.end();
  fs.writeFileSync(path.join(run,'results.json'),JSON.stringify(results,null,2));
  fs.writeFileSync(path.join(root,'reports/dom-latest.json'),JSON.stringify({report:path.join(run,'results.json'),...results},null,2));
  console.log(JSON.stringify({status:results.status,cases:results.cases.length,report:path.join(run,'results.json'),error:results.error,backendError:stderr},null,2));
});
