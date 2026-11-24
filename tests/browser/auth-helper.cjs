const assert=require('node:assert/strict');
const ORIGIN='http://127.0.0.1:8787';
async function login(page,user='ci-browser-user'){
 const r=await page.request.post(ORIGIN+'/api/auth/login',{headers:{Origin:ORIGIN,'X-ORBIT-UI':'1','Content-Type':'application/json'},data:{user,password:'local-ci-fixture-password'}});
 assert.equal(r.status(),200);return (await r.json()).csrf_token;
}
function headers(csrf){return {'Content-Type':'application/json','X-ORBIT-UI':'1',Origin:ORIGIN,'X-ORBIT-CSRF':csrf}}
module.exports={login,headers,ORIGIN};
