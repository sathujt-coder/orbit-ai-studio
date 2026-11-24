(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='',current=null,sequence=0,busy=false;
const example={problem:'',goals:[],users:[],scope:[],out_of_scope:[],assumptions:[],open_questions:[],requirements:[{id:'REQ-1',kind:'functional',description:'',priority:'must',acceptance:['']},{id:'REQ-2',kind:'nonfunctional',description:'',priority:'must',acceptance:['']}],stories:[{id:'US-1',actor:'',goal:'',benefit:'',requirements:['REQ-1','REQ-2']}]};
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-ORBIT-UI':'1','X-ORBIT-CSRF':csrf},...(body?{body:JSON.stringify(body)}:{})});if(r.status===401){location.replace('/account.html');throw Error('Phiên hết hạn')}const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
const base=pid=>'/api/projects/'+encodeURIComponent(pid)+'/requirements';
function render(d){current=d;$('panel').hidden=false;$('document').value=JSON.stringify(d.current?.document||example,null,2);$('version').textContent='Version '+(d.current?.version||0)+' · '+(d.planning_ready?'Đã duyệt':'Chưa duyệt')+' · '+(d.current?.source==='ai_adopted'?'AI draft adopted':'Human input');$('history').textContent=d.history.map(v=>'v'+v.version+' · '+v.author+' · '+(v.approved_by?'Approved: '+v.approved_by:'Draft')).join('\n');$('save').disabled=!d.can_write;$('approve').disabled=!d.can_approve||!d.current||d.planning_ready;$('document').readOnly=!d.can_write;$('scope-idea').textContent=d.idea||'';$('scope-contract').readOnly=!d.can_write;$('scope-contract').value=d.discovery?.scope_contract?JSON.stringify(d.discovery.scope_contract,null,2):'';$('status').textContent='Đã tải yêu cầu';renderDiscovery(d);}
function renderDiscovery(d){
 const x=d.discovery;const active=x&&['queued','running','paused','waiting_approval'].includes(x.status);
 $('discover').disabled=busy||!d.can_write||!!active;
 $('adopt').disabled=busy||!d.can_write||!x?.can_adopt;
 $('discovery-status').textContent=x?x.status+' · '+x.reason+(x.adopted_version?' · Đã tiếp nhận v'+x.adopted_version:''):'Chưa có đề xuất AI';
 $('discovery-evidence').textContent=x?.evidence?JSON.stringify({models:x.models,...x.evidence},null,2):'';
}
async function discoveryAction(adopt){
 if(busy||!current?.can_write)return;
 const d=current,pid=d.project_id;
 if(adopt&&!d.discovery?.can_adopt)return;
 if(adopt&&$('document').value!==JSON.stringify(d.current?.document||example,null,2)){ $('status').textContent='Có chỉnh sửa chưa lưu; hãy lưu hoặc tải lại trước khi tiếp nhận.';return; }
 let scopeContract=null;
 if(!adopt){try{scopeContract=JSON.parse($('scope-contract').value)}catch(e){$('status').textContent='Hãy nhập Scope Contract JSON hợp lệ trước khi chạy AI.';return;}}
 if(!confirm(adopt?'Tiếp nhận bản AI thành phiên bản mới chưa phê duyệt?':'Chạy hai model AI; có thể phát sinh chi phí theo provider?'))return;
 busy=true;$('project').disabled=true;$('reload').disabled=true;$('save').disabled=true;$('approve').disabled=true;renderDiscovery(d);
 try{
  await api(base(pid)+(adopt?'/adopt':'/discover'),adopt?{queue_id:d.discovery.queue_id,digest:d.discovery.digest,expected_version:d.discovery.base_version,confirmation:'ADOPT AI REQUIREMENTS'}:{confirmation:'RUN AI REQUIREMENTS',scope_contract:scopeContract});
  if(adopt)await reload();else await refreshDiscoveryAfterSubmit(d);
 }catch(e){$('status').textContent=e.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;if(current){renderDiscovery(current);$('save').disabled=!current.can_write;$('approve').disabled=!current.can_approve||!current.current||current.planning_ready;}}
}
async function refreshDiscoveryAfterSubmit(d){const fresh=await api(base(d.project_id));if(current===d){d.discovery=fresh.discovery;renderDiscovery(d)}}
async function refreshDiscovery(){
 if(busy||!current||document.hidden)return;
 const d=current;
 try{const fresh=await api(base(d.project_id));if(!busy&&current===d){d.discovery=fresh.discovery;renderDiscovery(d)}}catch(e){if(current===d)$('discovery-status').textContent=e.message}
}
async function reload(){const seq=++sequence;current=null;$('panel').hidden=true;const pid=$('project').value;if(!pid)return;try{const d=await api(base(pid));if(seq===sequence)render(d)}catch(e){if(seq===sequence)$('status').textContent=e.message}}
async function mutate(approve){if(busy||!current)return;const d=current,pid=d.project_id;busy=true;$('project').disabled=true;$('reload').disabled=true;$('save').disabled=true;$('approve').disabled=true;try{if(approve){if($('document').value!==JSON.stringify(d.current.document,null,2))throw Error('Có chỉnh sửa chưa lưu; hãy lưu và tải lại trước khi duyệt');if(!confirm('Phê duyệt phiên bản '+d.current.version+'?'))return;await api(base(pid)+'/approve',{version:d.current.version,digest:d.current.digest,confirmation:'APPROVE PRODUCT REQUIREMENTS'})}else await api(base(pid),{expected_version:d.current?.version||0,document:JSON.parse($('document').value)});await reload()}catch(e){$('status').textContent=e.message}finally{busy=false;$('project').disabled=false;$('reload').disabled=false;$('save').disabled=!current?.can_write;$('approve').disabled=!current?.can_approve||!current?.current||current.planning_ready;if(current)renderDiscovery(current)}}
window.addEventListener('DOMContentLoaded',async()=>{try{csrf=(await api('/api/auth/session')).csrf_token;const d=await api('/api/bootstrap');$('project').replaceChildren(...d.projects.map(p=>new Option(p.name,p.id)));const saved=localStorage.getItem('orbit-project');if(d.projects.some(p=>p.id===saved))$('project').value=saved;$('project').addEventListener('change',reload);$('reload').addEventListener('click',reload);$('save').addEventListener('click',()=>mutate(false));$('approve').addEventListener('click',()=>mutate(true));$('discover').addEventListener('click',()=>discoveryAction(false));$('adopt').addEventListener('click',()=>discoveryAction(true));await reload();setInterval(refreshDiscovery,3000)}catch(e){$('status').textContent=e.message}});
})();