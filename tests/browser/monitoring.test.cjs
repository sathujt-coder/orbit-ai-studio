const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,ORIGIN}=require('./auth-helper.cjs');
test('operator monitoring dashboard, sampled history, roster and access isolation',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage();await login(owner);await login(viewer,'ci-viewer');
 const path=ORIGIN+'/api/provider/monitoring';
 assert.equal((await viewer.request.get(path)).status(),403);
 assert.equal((await viewer.request.get(path+'/history')).status(),403);
 assert.equal((await viewer.request.get(ORIGIN+'/monitoring.html')).status(),403);
 assert.equal((await owner.request.get(path+'/history?hours=2')).status(),400);
 await owner.goto(ORIGIN+'/monitoring.html');
 await owner.locator('#report').waitFor({state:'visible',timeout:30000});
 assert.equal(await owner.locator('#agents tr').count(),24);
 assert.equal(await owner.locator('#charts .monitor-chart').count(),8);
 const d=await (await owner.request.get(path)).json();assert.equal(d.snapshot.agents.length,24);assert.equal(d.sampler.running,true);
 const h=await (await owner.request.get(path+'/history?hours=1&limit=2')).json();assert.ok(h.points.length>=1&&h.points.length<=2);
 await owner.locator('#auto').uncheck();await owner.locator('#hours').selectOption('1');await owner.waitForFunction(()=>document.querySelector('#history-note').textContent.includes('1h'));
 await owner.setViewportSize({width:390,height:844});assert.ok(await owner.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2));
 }finally{await browser.close()}
});
