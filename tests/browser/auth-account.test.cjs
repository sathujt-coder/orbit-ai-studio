'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8787';
test('Account UI rejects wrong credentials, restores session and logs out',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext();
  const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/account.html');
  await page.locator('#authLogin').waitFor({state:'visible'});
  await page.locator('#authUser').fill('ci-browser-user');
  await page.locator('#authPassword').fill('incorrect-test-password');
  await page.getByRole('button',{name:'Đăng nhập',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#authError').textContent==='Đăng nhập thất bại');
  assert.equal(await page.locator('#authPassword').inputValue(),'');
  await page.locator('#authPassword').fill('local-ci-fixture-password');
  await page.getByRole('button',{name:'Đăng nhập',exact:true}).click();
  await page.locator('#authSession').waitFor({state:'visible'});
  assert.equal(await page.locator('#authIdentity').textContent(),'ci-browser-user');
  const cookies=await context.cookies();
  const session=cookies.find(c=>c.name==='orbit_session');
  assert.ok(session&&session.httpOnly&&session.sameSite==='Strict');
  assert.equal(await page.evaluate(()=>document.cookie.includes('orbit_session')),false);
  await page.reload();
  await page.locator('#authSession').waitFor({state:'visible'});
  await page.locator('#authLogout').click();
  await page.locator('#authLogin').waitFor({state:'visible'});
  assert.equal((await page.request.get(origin+'/api/auth/session')).status(),401);
  assert.deepEqual(errors,[]);
 }finally{await browser.close()}
});
