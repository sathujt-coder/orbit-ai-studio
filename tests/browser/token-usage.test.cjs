const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('token usage dashboard is scoped and demo does not generate fake tokens',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage(),anon=await browser.newPage();
 const csrf=await login(owner);await login(viewer,'ci-viewer');
 const created=await owner.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Token usage fixture',idea:'Scoped token tracking test project',platform:'Web app'}});
 assert.equal(created.status(),201);const pid=(await created.json()).project_id;
 assert.equal((await viewer.request.get(ORIGIN+'/api/projects/'+pid+'/usage')).status(),403);
 assert.equal((await viewer.request.get(ORIGIN+'/api/provider/usage')).status(),403);
 assert.equal((await anon.request.get(ORIGIN+'/api/provider/usage')).status(),401);
 await owner.goto(ORIGIN+'/usage.html');await owner.locator('#filters').waitFor({state:'visible'});
 await owner.locator('#project').selectOption(pid);
 await owner.getByText('Chưa có dữ liệu inference; Demo không ghi token.',{exact:false}).waitFor();
 assert.equal(await owner.locator('#kpis strong').count(),4);
 const d=await (await owner.request.get(ORIGIN+'/api/projects/'+pid+'/usage?days=7')).json();
 assert.equal(d.totals.requests,0);assert.equal(d.totals.total_tokens,null);
 }finally{await browser.close()}
});
