const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('routing registry and metadata-only preview operator authorization',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage();const csrf=await login(owner);const vc=await login(viewer,'ci-viewer');
 const path=ORIGIN+'/api/provider/routing';
 assert.equal((await viewer.request.get(path)).status(),403);
 assert.equal((await viewer.request.get(ORIGIN+'/routing.html')).status(),403);
 assert.equal((await viewer.request.post(path+'/preview',{headers:headers(vc),data:{department:'dev',kind:'coding',chars:100}})).status(),403);
 const before=await (await owner.request.get(path)).json();assert.equal(before.mode,'fixed');
 await owner.goto(ORIGIN+'/routing.html');await owner.locator('#report').waitFor({state:'visible'});await owner.locator('#department').selectOption('dev');await owner.locator('#kind').selectOption('coding');
 await owner.getByRole('button',{name:'Preview',exact:true}).click();await owner.waitForFunction(()=>document.querySelector('#decision').textContent.includes('demo_no_inference'));
 const data=await (await owner.request.post(path+'/preview',{headers:headers(csrf),data:{department:'dev',kind:'coding',chars:100,secret:'forbidden'}}));assert.equal(data.status(),400);
 }finally{await browser.close()}
});
