// Real browser rendering of the Compute picker, with explicit IPC doubles only.
const {createRequire}=require('node:module');
const {readFileSync,writeFileSync,mkdirSync}=require('node:fs');
const {resolve,join}=require('node:path');
const {pathToFileURL}=require('node:url');
const assert=require('node:assert/strict');
const {chromium}=createRequire(resolve(process.env.DPAD_PLAYWRIGHT_PACKAGE))('@playwright/test');
const source=resolve(process.env.DPAD_PICKER_UI_SOURCE||join(__dirname,'../launcher/src'));
const out=resolve(process.argv[2]);mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:720}});const page=await context.newPage();const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
   const states={handlers:{},catalogFail:false,launches:[]};window.pickerFixture=states;
   const names=[['steam','Steam'],['battlenet','Battle.net'],['epic','Epic Games'],['gog','GOG'],['ea','EA App'],['ubisoft','Ubisoft Connect']];
   window.dpad={getStores:async()=>{if(states.catalogFail)throw Error('fixture unavailable');return names.map(([id,name])=>({id,name,available:true,color:'#66c0f4'}))},
    launchStore:async id=>{states.launches.push(id);return {ok:true}},pollGamepads:async()=>[],quit:()=>{}};
   for(const name of ['onStoreVisible','onStoreExited','onStoreLaunchFailed','onStoreInstalling'])window.dpad[name]=fn=>{states.handlers[name]=fn};
  });
  await page.goto(pathToFileURL(join(source,'index.html')).href);await page.locator('.card').last().waitFor();
  assert.equal(await page.locator('.card').count(),6);assert.equal(await page.locator('.status.available',{hasText:'Ready to open'}).count(),6);
  await page.screenshot({path:join(out,'picker-ready.png')});
  await page.locator('.card').filter({hasText:'Epic Games'}).click();await page.locator('#launchOverlay.show').waitFor();
  await page.evaluate(()=>{window.pickerFixture.handlers.onStoreVisible('steam');window.pickerFixture.handlers.onStoreInstalling('epic')});
  assert.equal(await page.locator('#launchOverlay.show').count(),1);assert.match(await page.locator('#launchName').innerText(),/Waiting for Epic Games/);
  await page.keyboard.press('Escape');assert.equal(await page.locator('#launchOverlay.show').count(),0);
  assert.match(await page.locator('.card.focused').innerText(),/Waiting for window/i);
  await page.evaluate(()=>window.pickerFixture.handlers.onStoreLaunchFailed('epic','Startup could not be confirmed. Check the taskbar, then retry.'));
  assert.match(await page.locator('.card.focused').innerText(),/Startup unconfirmed/i);await page.screenshot({path:join(out,'picker-retry.png')});
  await page.evaluate(()=>{window.pickerFixture.catalogFail=true;window.dispatchEvent(new Event('focus'))});await page.locator('#reloadStores:visible').waitFor();
  assert.equal(await page.locator('.card').count(),6);
  await page.evaluate(()=>{window.pickerFixture.catalogFail=false});await page.locator('#reloadStores').click();await page.locator('#reloadStores').waitFor({state:'hidden'});
  assert.match(await page.locator('.card.focused').innerText(),/Epic Games/);
  await page.locator('.card.focused').click();await page.evaluate(()=>window.pickerFixture.handlers.onStoreVisible('epic'));
  assert.equal(await page.locator('#launchOverlay.show').count(),0);assert.match(await page.locator('.card.focused').innerText(),/Window opened/i);
  for(const viewport of [{width:1280,height:720},{width:1920,height:1080},{width:390,height:844}]){
   await page.setViewportSize(viewport);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   for(const card of await page.locator('.card').all()){await card.scrollIntoViewIfNeeded();const box=await card.boundingBox();assert.ok(box&&box.width>0&&box.x>=0&&box.x+box.width<=viewport.width)}
  }
  assert.deepEqual(errors,[]);await context.close();
  writeFileSync(join(out,'qualification.json'),JSON.stringify({status:'compute-picker-ui-qualified-locally',cases:5,viewports:['1280x720','1920x1080','390x844'],pageErrors:0,
   ipc:'explicit test doubles',realStoreOrCompositorQualified:false,productionChanged:false,paidResourcesCreated:0},null,2)+'\n');
  console.log('Compute picker: five real-browser fixture scenarios and three layouts passed.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
