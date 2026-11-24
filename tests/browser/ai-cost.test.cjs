const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('cost UI, advisory budget persistence, operator rate permission',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage(),anon=await browser.newPage();const csrf=await login(owner);const vc=await login(viewer,'ci-viewer');
 const made=await owner.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Cost budget fixture',idea:'Project isolated cost test fixture',platform:'Web app'}});
 assert.equal(made.status(),201);const pid=(await made.json()).project_id;
 assert.equal((await viewer.request.get(ORIGIN+'/api/projects/'+pid+'/cost')).status(),403);
 assert.equal((await viewer.request.get(ORIGIN+'/api/provider/rates')).status(),403);
 assert.equal((await anon.request.get(ORIGIN+'/api/provider/cost')).status(),401);
 await owner.goto(ORIGIN+'/cost.html');await owner.locator('#filters').waitFor({state:'visible'});
 await owner.locator('#project').selectOption(pid);await owner.locator('#budget-form').waitFor({state:'visible'});
 await owner.locator('#budget-limit').fill('12.50');owner.once('dialog',d=>d.accept());await owner.getByRole('button',{name:'Lưu ngân sách'}).click();
 await owner.getByText('Giới hạn $12.5',{exact:false}).waitFor();
 const data=await (await owner.request.get(ORIGIN+'/api/projects/'+pid+'/cost')).json();assert.equal(data.budget.limit_usd,'12.500000000000');assert.equal(data.budget.enforcement,'advisory_only');assert.equal(data.totals.requests,0);
 await owner.locator('#rates-panel').waitFor({state:'visible'});await owner.locator('#model').fill('fixture-cost-model');await owner.locator('#input-rate').fill('1.25');await owner.locator('#output-rate').fill('2.75');
 owner.once('dialog',d=>d.accept());await owner.getByRole('button',{name:'Lưu phiên bản giá'}).click();await owner.getByText('Đã lưu phiên bản giá mới.').waitFor();
 const rates=await (await owner.request.get(ORIGIN+'/api/provider/rates')).json();assert.ok(rates.rates.some(r=>r.model==='fixture-cost-model'&&r.input_usd_per_million==='1.250000000000'));
 assert.equal((await viewer.request.post(ORIGIN+'/api/provider/rates',{headers:headers(vc),data:{}})).status(),403);
 }finally{await browser.close()}
});
