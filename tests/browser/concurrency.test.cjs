const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,ORIGIN}=require('./auth-helper.cjs');
test('operator resource concurrency limits and worker pool are visible',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const owner=await browser.newPage(),viewer=await browser.newPage();await login(owner);await login(viewer,'ci-viewer');
  const r=await owner.request.get(ORIGIN+'/api/provider/resources');assert.equal(r.status(),200);const d=await r.json();
  assert.equal(d.concurrency.policy.global_limit,1);assert.equal(d.queue_workers.configured,2);assert.equal(d.queue_workers.alive,2);
  assert.equal((await viewer.request.get(ORIGIN+'/api/provider/resources')).status(),403);
  await owner.goto(ORIGIN+'/resources.html');await owner.locator('#report').waitFor({state:'visible'});
  assert.match(await owner.locator('#concurrency').textContent(),/Workers 2\/2/);
 }finally{await browser.close()}
});
