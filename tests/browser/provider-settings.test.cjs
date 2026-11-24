const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');
test('provider settings operator access and persisted demo settings',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const ctx=await browser.newContext();const page=await ctx.newPage();
 const base='http://127.0.0.1:8787';
 const login=await ctx.request.post(base+'/api/auth/login',{headers:{'Origin':base,'X-ORBIT-UI':'1'},data:{user:'ci-browser-user',password:'local-ci-fixture-password'}});
 assert.equal(login.status(),200);
 await page.goto(base+'/providers.html');
 await page.locator('#settings').waitFor({state:'visible'});
 assert.equal(await page.locator('fieldset').count(),2);
 const response=await ctx.request.get(base+'/api/provider/settings');assert.equal(response.status(),200);
 const data=await response.json();assert.equal(data.credential_storage,'deployment_environment_only');
 // Save unchanged demo config; must not trigger inference or affect other browser tests.
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Lưu & áp dụng'}).click();
 await page.getByText('Đã lưu và áp dụng cho tác vụ mới.').waitFor();
 const after=await (await ctx.request.get(base+'/api/provider/settings')).json();assert.equal(after.revision,data.revision+1);
 const viewer=await browser.newContext();
 const v=await viewer.request.post(base+'/api/auth/login',{headers:{Origin:base,'X-ORBIT-UI':'1'},data:{user:'ci-viewer',password:'local-ci-fixture-password'}});
 assert.equal(v.status(),200);assert.equal((await viewer.request.get(base+'/api/provider/settings')).status(),403);
 }finally{await browser.close()}
});
