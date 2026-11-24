(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='';
async function api(path,method='GET',body){
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-ORBIT-UI':'1','X-ORBIT-CSRF':csrf},...(body?{body:JSON.stringify(body)}:{})});
 if(r.status===401){location.replace('/account.html');throw Error('Phiên đã hết hạn')}
 const data=await r.json();if(!r.ok)throw Error(data.error||'Access denied');return data;
}
function route(s){return '/api/projects/'+encodeURIComponent($('project').value)+'/'+s}
async function refresh(){
 if(!$('project').value)return;
 for(const key of ['members','audit','acceptance'])try{
  const data=await api(route(key));
  if(key==='acceptance'){
   $('acceptance').textContent=JSON.stringify(data.state,null,2);
   $('requirement').replaceChildren(...data.requirements.map(r=>new Option(r,r)));
  }else $(key).textContent=JSON.stringify(data[key],null,2);
 }catch(e){$(key).textContent=e.message}
}
async function submit(e,path,body){
 e.preventDefault();const btn=e.currentTarget.querySelector('button');btn.disabled=true;
 try{await api(route(path),'POST',body);$('message').textContent='Đã lưu';await refresh()}
 catch(err){$('message').textContent=err.message}finally{btn.disabled=false}
}
window.addEventListener('DOMContentLoaded',async()=>{
 try{
  csrf=(await api('/api/auth/session')).csrf_token;
  const data=await api('/api/bootstrap');
  $('project').replaceChildren(...data.projects.map(p=>new Option(p.name,p.id)));
  $('project').addEventListener('change',refresh);$('refresh').addEventListener('click',refresh);
  $('membership').addEventListener('submit',e=>submit(e,'members',{user:$('member').value,role:$('role').value}));
  $('evidence').addEventListener('submit',e=>submit(e,'acceptance/evidence',{requirement:$('requirement').value,reference:$('reference').value,passed:$('passed').checked}));
  $('signoff').addEventListener('submit',e=>submit(e,'acceptance/signoff',{confirmation:$('confirmation').value}));
  await refresh();
 }catch(e){$('message').textContent=e.message}
});
})();
