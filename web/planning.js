(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='',current=null,busy=false,sequence=0,baseline='';
const base=pid=>'/api/projects/'+encodeURIComponent(pid)+'/planning';
async function api(path,body){
 const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-ORBIT-UI':'1','X-ORBIT-CSRF':csrf},...(body?{body:JSON.stringify(body)}:{})});
 if(response.status===401){location.replace('/account.html');throw Error('Phiên hết hạn')}
 const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data;
}
function buttons(){
 const d=current,canEdit=!!(d?.input_ready&&d?.can_write&&!d.stale);
 $('seed').disabled=busy||!d?.input_ready||!d?.can_write;
 $('discover').disabled=busy||!d?.input_ready||!d?.can_write||['queued','running','paused','waiting_approval'].includes(d?.discovery?.status);
 $('save').disabled=busy||!canEdit||!d?.current;
 $('approve').disabled=busy||!d?.input_ready||!d?.can_approve||!d?.current||d.stale||!!d.current.approved_at||!d.analysis||d.analysis.unestimated_tasks.length>0;
 $('document').readOnly=busy||!canEdit||!d?.current;
}
function render(d){
 current=d;$('panel').hidden=false;
 const src=d.requirements_input,plan=d.current;
 $('input-state').textContent=src?'PRD đã duyệt · v'+src.version+' · '+src.digest:'BLOCKED · Cần PRD hiện tại được phê duyệt';
 $('source').textContent=src?JSON.stringify(src.document,null,2):'Chưa có PRD đầu vào hợp lệ';
 $('plan-state').textContent=!plan?'Chưa có kế hoạch':d.stale?'STALE · Plan v'+plan.version+' không còn khớp PRD':(d.execution_ready?'READY · Đã duyệt':'DRAFT · Chưa duyệt')+' · Plan v'+plan.version;
 baseline=plan?JSON.stringify(plan.document,null,2):'';$('document').value=baseline;
 $('tasks').replaceChildren(...(plan?.document.tasks||[]).map(t=>{
   const row=document.createElement('tr');
   for(const value of [t.id,t.title,t.kind,t.requirements.join(', '),t.depends_on.join(', ')||'—',t.effort_minutes??'Chưa ước tính']){
     const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);
   }return row;
 }));
 $('analysis').textContent=d.analysis?JSON.stringify(d.analysis,null,2):'Chưa có phân tích cho PRD hiện tại';
 $('history').textContent=d.history.map(v=>'v'+v.version+' · PRD v'+v.requirements_version+' · '+v.author+' · '+(v.approved_by?'Approved: '+v.approved_by:'Draft')).join('\n');
 renderDiscovery(d);
 $('status').textContent='Đã tải kế hoạch';buttons();
}
function renderDiscovery(d){
 const x=d.discovery;
 $('discovery-status').textContent=x?x.status+' · '+x.reason+(x.stale?' · STALE':''):'Chưa có đề xuất AI';
 $('discovery-evidence').textContent=x?.evidence?JSON.stringify({models:x.models,...x.evidence},null,2):'';
}
async function refreshDiscovery(){
 if(busy||!current||document.hidden)return;
 const d=current;
 try{const fresh=await api(base(d.project_id));if(!busy&&current===d){d.discovery=fresh.discovery;renderDiscovery(d);buttons()}}catch(e){if(current===d)$('discovery-status').textContent=e.message}
}
async function discover(){
 if(busy||!current?.input_ready||!current.can_write)return;
 const d=current,src=d.requirements_input;
 if(!confirm('Chạy hai model AI độc lập? Có thể phát sinh chi phí theo cấu hình provider.'))return;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{await api(base(d.project_id)+'/discover',{requirements_version:src.version,requirements_digest:src.digest,confirmation:'RUN AI PLANNING'});
  const fresh=await api(base(d.project_id));d.discovery=fresh.discovery;renderDiscovery(d);
 }catch(e){$('status').textContent=e.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
async function reload(){
 const seq=++sequence,pid=$('project').value;current=null;$('panel').hidden=true;buttons();
 if(!pid)return;
 try{const d=await api(base(pid));if(seq===sequence)render(d)}catch(e){if(seq===sequence)$('status').textContent=e.message}
}
async function mutate(kind){
 if(busy||!current)return;
 const d=current,src=d.requirements_input,p=d.current;
 if(!src)return;
 if(kind==='approve'&&$('document').value!==baseline){$('status').textContent='Có chỉnh sửa chưa lưu; lưu phiên bản trước khi duyệt.';return}
 if(kind==='seed'&&!confirm('Tạo phiên bản WBS nháp mới từ PRD hiện tại? Nội dung chưa lưu sẽ mất.'))return;
 if(kind==='approve'&&!confirm('Phê duyệt đúng phiên bản kế hoạch đã lưu?'))return;
 busy=true;$('project').disabled=true;$('reload').disabled=true;buttons();
 try{
  const source={requirements_version:src.version,requirements_digest:src.digest};
  const payload=kind==='approve'?{...source,version:p.version,digest:p.digest,confirmation:'APPROVE PROJECT PLAN'}:
    {...source,expected_version:p?.version||0,...(kind==='seed'?{confirmation:'CREATE PLAN DRAFT'}:{document:JSON.parse($('document').value)})};
  await api(base(d.project_id)+(kind==='save'?'':'/'+kind),payload);await reload();
 }catch(e){$('status').textContent=e.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
window.addEventListener('DOMContentLoaded',async()=>{
 try{
  csrf=(await api('/api/auth/session')).csrf_token;
  const d=await api('/api/bootstrap');$('project').replaceChildren(...d.projects.map(p=>new Option(p.name,p.id)));
  const saved=localStorage.getItem('orbit-project');if(d.projects.some(p=>p.id===saved))$('project').value=saved;
  $('project').addEventListener('change',reload);$('reload').addEventListener('click',reload);
  $('discover').addEventListener('click',discover);setInterval(refreshDiscovery,2000);
  for(const kind of ['seed','save','approve'])$(kind).addEventListener('click',()=>mutate(kind));await reload();
 }catch(e){$('status').textContent=e.message}
});
})();