(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='',current=null,busy=false,sequence=0,baseline='',wbsEditVersion=null;
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
 $('scope-contract').readOnly=busy||!d?.input_ready||!d?.can_write;
 const w=d?.wbs, lane=$('wbs-lane').value;
 $('wbs-seed').disabled=busy||!d?.can_write||!w?.sources?.[lane];
 $('wbs-save').disabled=busy||!d?.can_write||!w?.current||w.stale||w.current.version!==wbsEditVersion||!w.sources?.[w.current.lane];
 $('wbs-document').readOnly=$('wbs-save').disabled;
 $('wbs-lane').disabled=busy;
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
 $('scope-contract').value='';
 renderDiscovery(d);renderWbs(d.wbs,true);
 $('status').textContent='Đã tải kế hoạch';buttons();
}
function renderDiscovery(d){
 const x=d.discovery;
 $('discovery-status').textContent=x?x.status+' · '+x.reason+(x.stale?' · STALE':x.status==='succeeded'&&!x.ready?' · QUALITY BLOCKED':''):'Chưa có đề xuất AI';
 $('discovery-evidence').textContent=x?.evidence?JSON.stringify({models:x.models,...x.evidence},null,2):'';
}
function renderWbs(w,reset=false){
 if(reset){wbsEditVersion=w?.current?.version??null;$('wbs-document').value=w?.current?JSON.stringify(w.current.document,null,2):''}
 const a=w?.analysis;
 $('wbs-status').textContent=!w?.current?'Chưa có WBS phân cấp':w.stale?'STALE · WBS v'+w.current.version :w.current.version!==wbsEditVersion?'VERSION CHANGED · Tải lại trước khi sửa':(w.decomposition_ready?'DETAIL READY · ':'DRAFT · Cần chi tiết · ')+'WBS v'+w.current.version;
 $('wbs-findings').textContent=a?JSON.stringify(a,null,2):'';
 $('wbs-tree').replaceChildren(...(w?.current?.document.deliverables||[]).map(d=>{
   const box=document.createElement('details');box.open=true;const summary=document.createElement('summary');
   summary.textContent=d.id+' · '+d.requirement+' · '+d.outcome;box.append(summary);
   const list=document.createElement('ul');
   for(const p of d.packages){const li=document.createElement('li');li.textContent=p.id+' · '+p.kind+' · '+(p.action||'Chưa có action')+' · '+p.criteria.join(', ');list.append(li)}
   box.append(list);return box
 }));
}
async function mutateWbs(seed){
 if(busy||!current?.can_write)return;
 const d=current,w=d.wbs,lane=seed?$('wbs-lane').value:w.current?.lane,source=w?.sources?.[lane];
 if(!source||(!seed&&w.current.version!==wbsEditVersion))return;
 if(seed&&!confirm('Tạo WBS nháp mới từ PM-'+lane+'?'))return;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{
  const body={...source,expected_version:w.current?.version||0,...(seed?{confirmation:'CREATE WBS DRAFT'}:{document:JSON.parse($('wbs-document').value)})};
  d.wbs=await api(base(d.project_id)+'/wbs'+(seed?'/seed':''),body);renderWbs(d.wbs,true);
 }catch(e){$('status').textContent=e.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
async function refreshDiscovery(){
 if(busy||!current||document.hidden)return;
 const d=current;
 try{const fresh=await api(base(d.project_id));if(!busy&&current===d){d.discovery=fresh.discovery;d.wbs=fresh.wbs;renderDiscovery(d);renderWbs(d.wbs);buttons()}}catch(e){if(current===d)$('discovery-status').textContent=e.message}
}
async function discover(){
 if(busy||!current?.input_ready||!current.can_write)return;
 const d=current,src=d.requirements_input;
 if(!confirm('Chạy hai model AI độc lập? Có thể phát sinh chi phí theo cấu hình provider.'))return;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{const raw=$('scope-contract').value.trim();const scope=raw?JSON.parse(raw):null;
  await api(base(d.project_id)+'/discover',{requirements_version:src.version,requirements_digest:src.digest,confirmation:'RUN AI PLANNING',...(raw?{scope_contract:scope}:{})});
  const fresh=await api(base(d.project_id));d.discovery=fresh.discovery;d.wbs=fresh.wbs;renderDiscovery(d);renderWbs(d.wbs);
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
  $('wbs-lane').addEventListener('change',buttons);$('wbs-seed').addEventListener('click',()=>mutateWbs(true));$('wbs-save').addEventListener('click',()=>mutateWbs(false));
  for(const kind of ['seed','save','approve'])$(kind).addEventListener('click',()=>mutate(kind));await reload();
 }catch(e){$('status').textContent=e.message}
});
})();