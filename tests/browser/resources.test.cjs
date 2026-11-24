const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('resource status operator dashboard and local model read authorization',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage(),anon=await browser.newPage();const csrf=await login(owner);const vc=await login(viewer,'ci-viewer');
 assert.equal((await anon.request.get(ORIGIN+'/api/provider/resources')).status(),401);
 assert.equal((await viewer.request.get(ORIGIN+'/api/provider/resources')).status(),403);
 assert.equal((await viewer.request.post(ORIGIN+'/api/provider/resources/models',{headers:headers(vc),data:{confirmation:'READ LOCAL MODEL STATUS'}})).status(),403);
 await owner.goto(ORIGIN+'/resources.html');await owner.locator('#report').waitFor({state:'visible'});
 assert.equal(await owner.locator('#kpis strong').count(),4);
 const data=await (await owner.request.get(ORIGIN+'/api/provider/resources')).json();assert.equal(data.schema,'orbit.resources.v1');assert.equal(data.policy.mode,'observe');
 assert.equal((await owner.request.post(ORIGIN+'/api/provider/resources/models',{headers:headers(csrf),data:{}})).status(),400);
 await owner.getByRole('button',{name:'Đọc trạng thái model local'}).click();await owner.getByText('Lane A: not_local_ollama',{exact:false}).waitFor();
 }finally{await browser.close()}
});
