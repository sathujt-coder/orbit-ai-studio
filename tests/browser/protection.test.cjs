const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('operator budget dashboard and persistent emergency stop',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage();const csrf=await login(owner);const vc=await login(viewer,'ci-viewer');const path=ORIGIN+'/api/provider/protection';
 assert.equal((await viewer.request.get(path)).status(),403);
 assert.equal((await viewer.request.get(ORIGIN+'/protection.html')).status(),403);
 assert.equal((await viewer.request.post(path+'/stop',{headers:headers(vc),data:{revision:0,stopped:true,confirmation:'STOP NEW INFERENCE'}})).status(),403);
 await owner.goto(ORIGIN+'/protection.html');await owner.locator('#report').waitFor({state:'visible'});
 owner.on('dialog',d=>d.accept());await owner.getByRole('button',{name:'Stop new inference',exact:true}).click();await owner.getByText('STOPPED — admission blocked').waitFor();
 const d=await (await owner.request.get(path)).json();assert.equal(d.stopped,true);
 assert.equal((await owner.request.post(path+'/stop',{headers:headers(csrf),data:{revision:d.control.revision-1,stopped:false,confirmation:'RESUME INFERENCE'}})).status(),400);
 await owner.getByRole('button',{name:'Resume inference',exact:true}).click();await owner.getByText('RUNNING — admission enabled').waitFor();
 }finally{await browser.close()}
});
