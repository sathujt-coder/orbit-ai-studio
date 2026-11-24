/* Local account UI: CSRF remains in memory; session cookie is HttpOnly. */
(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='',busy=false;
async function request(path,method='GET',body){
 const headers={'Content-Type':'application/json','X-ORBIT-UI':'1'};
 if(csrf&&method!=='GET')headers['X-ORBIT-CSRF']=csrf;
 const response=await fetch(path,{method,headers,credentials:'same-origin',cache:'no-store',...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data=await response.json();
 return {status:response.status,data};
}
function render(user){
 $('authLogin').hidden=!!user;
 $('authSession').hidden=!user;
 $('authIdentity').textContent=user||'';
 $('authStatus').textContent=user?'Phiên đăng nhập đang hoạt động':'Chưa đăng nhập';
 if(!user)csrf='';
}
async function refresh(){
 try{
  const r=await request('/api/auth/session');
  if(r.status===200){csrf=r.data.csrf_token;render(r.data.user)}
  else if(r.status===401)render('');
  else throw Error('Không thể kiểm tra phiên');
 }catch(e){$('authError').textContent='Không thể kiểm tra phiên. Hãy tải lại trang.'}
}
async function submit(e){
 e.preventDefault();if(busy)return;busy=true;
 const button=e.currentTarget.querySelector('button');
 button.disabled=true;$('authError').textContent='';
 try{
  const r=await request('/api/auth/login','POST',{user:$('authUser').value.trim(),password:$('authPassword').value});
  if(r.status!==200)throw Error(r.status===429?'Quá nhiều lần thử. Vui lòng thử lại sau.':'Đăng nhập thất bại');
  csrf=r.data.csrf_token;render(r.data.user);
 }catch(err){$('authError').textContent=err.message}
 finally{$('authPassword').value='';button.disabled=false;busy=false}
}
async function logout(){
 if(busy)return;busy=true;$('authLogout').disabled=true;$('authError').textContent='';
 try{
  const r=await request('/api/auth/logout','POST',{});
  if(r.status===200||r.status===401)render('');
  else throw Error('Không thể đăng xuất. Hãy tải lại trang.');
 }catch(err){$('authError').textContent=err.message}
 finally{$('authLogout').disabled=false;busy=false}
}
window.addEventListener('DOMContentLoaded',async()=>{
 if($('authLogin')){
  $('authLogin').addEventListener('submit',submit);$('authLogout').addEventListener('click',logout);await refresh();
 }else if($('authAccount')){
  try{const r=await request('/api/auth/session');if(r.status===200)$('authAccount').textContent='Tài khoản · '+r.data.user}catch{}
 }
});
})();
