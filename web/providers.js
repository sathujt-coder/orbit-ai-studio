(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='',state=null,busy=false;
const panels={};
async function api(path,body){
 const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-ORBIT-UI':'1','X-ORBIT-CSRF':csrf},...(body?{body:JSON.stringify(body)}:{})});
 if(r.status===401){location.replace('/account.html');throw Error('Phiên đã hết hạn')}
 const data=await r.json();if(!r.ok)throw Error(data.error||'Access denied');return data;
}
function field(l,k){return panels[l].querySelector('[data-key="'+k+'"]')}
function options(l,preferred){
 const kind=field(l,'provider').value,u=field(l,'url');
 const allowed=state.allowed_endpoints.filter(e=>e.provider===kind);
 u.replaceChildren(...(kind==='demo'?[new Option('Không sử dụng','')]:allowed.map(e=>new Option(e.url,e.url))));
 if([...u.options].some(o=>o.value===preferred))u.value=preferred;
 u.required=kind!=='demo';
 const entry=allowed.find(e=>e.url===u.value);
 panels[l].querySelector('[data-key-status]').textContent=kind==='demo'?'Không cần API Key':entry?.key_configured?'API Key: đã cấu hình phía server':'API Key: không cấu hình';
 panels[l].querySelector('datalist').replaceChildren();
 updateMode();
}
function updateMode(){const a=field('A','provider').value,b=field('B','provider').value;$('mode').textContent='Chế độ dự kiến: '+(a===b?a==='demo'?'Demo':a==='ollama'?'Ollama':'API':'Hybrid / split')+' · Revision '+state.revision}
function read(){const lanes={};for(const l of ['A','B']){lanes[l]={};for(const k of ['provider','url','model','timeout','temperature','context_window','max_tokens'])lanes[l][k]=['timeout','temperature','context_window','max_tokens'].includes(k)?Number(field(l,k).value):field(l,k).value}return lanes}
function render(data){state=data;for(const l of ['A','B']){const v=data.lanes[l];field(l,'provider').value=v.provider;for(const k of ['model','timeout','temperature','context_window','max_tokens'])field(l,k).value=v[k];options(l,v.url)}$('settings').hidden=false;updateMode()}
async function action(fn){if(busy)return;busy=true;for(const b of $('settings').querySelectorAll('button'))b.disabled=true;try{await fn()}catch(e){$('status').textContent=e.message}finally{busy=false;for(const b of $('settings').querySelectorAll('button'))b.disabled=false}}
async function load(){render(await api('/api/provider/settings'));$('status').textContent='Cấu hình hiện tại đã tải.';$('result').textContent=''}
async function network(which){if(!$('settings').reportValidity())return;await action(async()=>{if(!window.confirm('Thực hiện kết nối thật? Provider API có thể tính phí.'))return;$('status').textContent='Đang kiểm tra…';const data=await api('/api/provider/'+which,{lanes:read(),confirmation:'TEST AI CONNECTION'});$('result').textContent=JSON.stringify(data,null,2);if(which==='models')for(const l of ['A','B'])panels[l].querySelector('datalist').replaceChildren(...(data.lanes[l].models||[]).map(x=>new Option(x,x)));$('status').textContent='Đã nhận kết quả kiểm tra; xem trạng thái từng lane.'})}
window.addEventListener('DOMContentLoaded',async()=>{try{
 for(const l of ['A','B']){const node=$('lane-template').content.cloneNode(true);const panel=node.querySelector('fieldset');panels[l]=panel;panel.querySelector('legend').textContent='DEV-'+l;panel.querySelector('datalist').id='models-'+l;field(l,'model').setAttribute('list','models-'+l);$('lanes').append(node);field(l,'provider').addEventListener('change',()=>options(l,''));field(l,'url').addEventListener('change',()=>options(l,field(l,'url').value))}
 csrf=(await api('/api/auth/session')).csrf_token;await load();
 $('settings').addEventListener('submit',e=>{e.preventDefault();action(async()=>{if(!window.confirm('Áp dụng cấu hình AI toàn hệ thống cho các tác vụ mới?'))return;render(await api('/api/provider/settings',{revision:state.revision,lanes:read(),confirmation:'APPLY AI SETTINGS'}));$('status').textContent='Đã lưu và áp dụng cho tác vụ mới.';$('result').textContent=''})});
 $('probe').addEventListener('click',()=>network('probe'));$('models').addEventListener('click',()=>network('models'));$('reload').addEventListener('click',()=>action(load));
 }catch(e){$('status').textContent=e.message}});
})();
