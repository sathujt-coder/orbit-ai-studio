(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='',current=null,busy=false,sequence=0,baseline='',wbsEditVersion=null,graphSnapshot=null,estimateBinding=null,scheduleBinding=null;
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
 const e=w?.resource_estimates;
 $('estimate-save').disabled=busy||!d?.can_write||!w?.current||w.stale||!e?.draft||estimateBinding!==estimateKey(w);
 $('estimate-document').readOnly=$('estimate-save').disabled;
 $('schedule-save').disabled=busy||!d?.can_write||!w?.sprint_schedule?.draft||scheduleBinding!==scheduleKey(w);
 $('schedule-document').readOnly=$('schedule-save').disabled;
 $('review-run').disabled=busy||!d?.can_write||!w?.cross_review?.input_ready||['queued','running','paused','waiting_approval'].includes(w?.cross_review?.latest?.status);
 $('adopt-bundle').disabled=busy||!d?.can_approve||!w?.adoption?.can_adopt;
 const blank=w?.current?.document.deliverables.every(d=>d.packages.every(p=>['action','output','evidence'].every(k=>p[k]===null)));
 $('wbs-decompose').disabled=busy||!d?.can_write||!blank||w?.stale||w.current.version!==wbsEditVersion||['queued','running','paused','waiting_approval'].includes(d?.decomposition?.status);
}
function renderGraph(){
 const d=graphSnapshot,kind=$('graph-source').value;
 const g=kind==='wbs'?d?.wbs?.dependency_graph:d?.analysis?.dependency_graph;
 const rev=kind==='wbs'?d?.wbs?.current:d?.current;
 const stale=kind==='wbs'?d?.wbs?.stale:d?.stale;
 const label=kind==='wbs'?'WBS':'Plan';
 const status=!g?(stale?'STALE · Nguồn không còn hợp lệ':'Chưa có đồ thị đã lưu'):
   label+' v'+rev.version+' · '+g.node_count+' nodes · '+g.edge_count+' edges · '+(g.timing_ready?'CPM READY · '+g.critical_path_minutes+' phút':'STRUCTURE ONLY · '+g.unestimated_nodes.length+' chưa ước tính');
 $('graph-status').textContent=status;
 $('graph-path').textContent=g?.timing_ready?'Đường găng đại diện: '+g.critical_path.join(' → ')+' · '+g.critical_nodes.length+' task găng (gồm các nhánh đồng hạng)':'Chưa tính đường găng khi thiếu thời lượng.';
 const item=text=>{const li=document.createElement('li');li.textContent=text;return li};
 $('graph-layers').replaceChildren(...(g?.layers||[]).map(ids=>item(ids.join(' · '))));
 $('graph-edges').replaceChildren(...(g?.critical_edges||[]).map(e=>item(e.source+' → '+e.target)));
 $('graph-nodes').replaceChildren(...(g?.nodes||[]).map(n=>{
  const tr=document.createElement('tr');
  for(const v of [n.id,n.depends_on.join(', ')||'—',n.effort_minutes,n.earliest_start_minutes,n.earliest_finish_minutes,
    n.latest_start_minutes,n.latest_finish_minutes,n.total_float_minutes,n.critical===null?null:n.critical?'Có':'Không']){
   const td=document.createElement('td');td.textContent=String(v??'—');tr.append(td)
  }return tr
 }));
}
function render(d){
 current=d;graphSnapshot=d;$('panel').hidden=false;
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
 renderDiscovery(d);renderWbs(d.wbs,true);renderDecomposition(d.decomposition);renderGraph();
 $('status').textContent='Đã tải kế hoạch';buttons();
}
function renderDiscovery(d){
 const x=d.discovery;
 $('discovery-status').textContent=x?x.status+' · '+x.reason+(x.stale?' · STALE':x.status==='succeeded'&&!x.ready?' · QUALITY BLOCKED':''):'Chưa có đề xuất AI';
 $('discovery-evidence').textContent=x?.evidence?JSON.stringify({models:x.models,...x.evidence},null,2):'';
}
function estimateKey(w){return w?.current?JSON.stringify([w.current.version,w.current.digest,w.resource_estimates?.current?.version||0]):null}
function renderEstimates(w,reset){
 const e=w?.resource_estimates,key=estimateKey(w);
 if(reset){estimateBinding=key;$('estimate-document').value=e?.draft?JSON.stringify(e.current&&!e.stale?e.current.document:e.draft,null,2):''}
 $('estimate-state').textContent=!e?.draft?'BLOCKED · Cần WBS hiện tại':key!==estimateBinding?'VERSION CHANGED · Tải lại trước khi sửa':e.stale?'STALE · Nhập ước lượng mới':e.analysis?.ready?'ESTIMATES READY':e.current?'PARTIAL · Còn thiếu dữ liệu':'Chưa ước lượng';
 $('estimate-analysis').textContent=e?JSON.stringify({analysis:e.analysis,history:e.history},null,2):'';
}
async function saveEstimates(){
 if(busy||$('estimate-save').disabled||!current)return;
 const d=current,w=d.wbs,p=w.current,e=w.resource_estimates;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{
  d.wbs=await api(base(d.project_id)+'/wbs/estimates',{expected_version:e.current?.version||0,wbs_version:p.version,wbs_digest:p.digest,document:JSON.parse($('estimate-document').value),confirmation:'SAVE RESOURCE ESTIMATES'});
  renderWbs(d.wbs,true);graphSnapshot={...graphSnapshot,wbs:d.wbs};renderGraph();
 }catch(err){$('status').textContent=err.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
function scheduleKey(w){const s=w?.sprint_schedule;return s?.source?JSON.stringify([s.source,s.current?.version||0]):null}
function renderSchedule(w,reset){
 const s=w?.sprint_schedule,key=scheduleKey(w);
 if(reset){scheduleBinding=key;$('schedule-document').value=s?.draft?JSON.stringify(s.current&&!s.stale?s.current.document:s.draft,null,2):''}
 $('schedule-state').textContent=!s?.draft?'BLOCKED · Cần estimate hiện tại đầy đủ':key!==scheduleBinding?'VERSION CHANGED · Tải lại trước khi sửa':s.stale?'STALE · Lập lịch mới':s.analysis?.ready?'SCHEDULE CHECKS PASS · DRAFT':s.current?'DRAFT · Có findings':'Chưa lập lịch';
 $('schedule-analysis').textContent=s?JSON.stringify({analysis:s.analysis,history:s.history},null,2):'';
}
async function saveSchedule(){
 if(busy||$('schedule-save').disabled||!current)return;
 const d=current,s=d.wbs.sprint_schedule;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{
  d.wbs=await api(base(d.project_id)+'/wbs/schedule',{...s.source,expected_version:s.current?.version||0,document:JSON.parse($('schedule-document').value),confirmation:'SAVE SPRINT SCHEDULE'});
  renderWbs(d.wbs,true);graphSnapshot={...graphSnapshot,wbs:d.wbs};renderGraph();
 }catch(err){$('status').textContent=err.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
function renderReview(w){
 const r=w?.cross_review,x=r?.latest;
 $('review-state').textContent=x?.stale?'STALE · Review lại nguồn mới':!r?.input_ready?'BLOCKED · Cần WBS, estimates và schedule hợp lệ':r.quality_ready?'CROSS REVIEW PASS · Chưa tiếp nhận':x?x.status+' · '+x.reason:'Chưa review';
 $('review-evidence').textContent=x?.evidence?JSON.stringify(x.evidence,null,2):'';
}
async function runReview(){
 if(busy||$('review-run').disabled||!current)return;
 if(!confirm('Chạy hai lượt review Ollama local?'))return;
 const d=current;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{
  await api(base(d.project_id)+'/wbs/review',{bundle_digest:d.wbs.cross_review.bundle_digest,confirmation:'RUN PM CROSS REVIEW'});
  const fresh=await api(base(d.project_id));d.wbs=fresh.wbs;renderReview(d.wbs);
 }catch(err){$('status').textContent=err.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
function renderAdoption(w){
 const a=w?.adoption;
 $('adoption-state').textContent=a?.status==='adopted'?'ADOPTED · v'+a.current.version:a?.stale?'STALE · Snapshot lịch sử':a?.can_adopt?'READY FOR HUMAN APPROVAL':'BLOCKED · Chưa đủ điều kiện';
 $('adoption-evidence').textContent=a?JSON.stringify(a,null,2):'';
}
async function adoptBundle(){
 if(busy||$('adopt-bundle').disabled||!current)return;
 if(!confirm('Phê duyệt và tiếp nhận đúng bundle hiện tại? Không tự thực thi.'))return;
 const d=current,a=d.wbs.adoption;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{
  d.wbs=await api(base(d.project_id)+'/wbs/adopt',{...a.binding,expected_version:a.current?.version||0,confirmation:'APPROVE AND ADOPT PLANNING BUNDLE'});
  renderWbs(d.wbs,true);
 }catch(err){$('status').textContent=err.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
function renderWbs(w,reset=false){
 renderAdoption(w);
 renderReview(w);
 renderSchedule(w,reset);
 renderEstimates(w,reset);
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
  d.wbs=await api(base(d.project_id)+'/wbs'+(seed?'/seed':''),body);renderWbs(d.wbs,true);if(graphSnapshot){graphSnapshot={...graphSnapshot,wbs:d.wbs};renderGraph()}
 }catch(e){$('status').textContent=e.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
function renderDecomposition(x){
 const guidance=x?.workflow;
 const messages={refresh_source:'Nguồn đã thay đổi; tạo WBS mới từ nguồn hiện tại.',human_review:'Cần người có thẩm quyền review; chưa phê duyệt hay thực thi.',operator_review:'Cần người vận hành kiểm tra lỗi. '+(guidance?.operator_retry_available?'Có thể cấu hình model local khác và Retry trong Agent Queue.':'Không thể Retry trạng thái này.'),wait_for_queue:''};
 const hint=messages[guidance?.next_action]||'';
 $('decomposition-status').textContent=x?x.status+' · '+x.reason+(x.stale?' · STALE':x.ready?' · READY FOR REVIEW':'')+(hint?' · '+hint:''):'Chưa có đề xuất decomposition';
 $('decomposition-evidence').textContent=x?.evidence?JSON.stringify({model:x.model,...x.evidence},null,2):'';
}
async function decompose(){
 if(busy||!current||$('wbs-decompose').disabled)return;
 const d=current,p=d.wbs.current;
 if(!confirm('Chạy model Ollama local để phân rã WBS? Không tự ghi đè WBS.'))return;
 busy=true;buttons();$('project').disabled=true;$('reload').disabled=true;
 try{
  await api(base(d.project_id)+'/wbs/decompose',{wbs_version:p.version,wbs_digest:p.digest,confirmation:'RUN AI DECOMPOSITION'});
  const fresh=await api(base(d.project_id));d.decomposition=fresh.decomposition;renderDecomposition(d.decomposition);
 }catch(e){$('status').textContent=e.message}
 finally{busy=false;$('project').disabled=false;$('reload').disabled=false;buttons()}
}
async function refreshDiscovery(){
 if(busy||!current||document.hidden)return;
 const d=current;
 try{const fresh=await api(base(d.project_id));if(!busy&&current===d){d.discovery=fresh.discovery;d.wbs=fresh.wbs;d.decomposition=fresh.decomposition;graphSnapshot=fresh;renderGraph();renderDiscovery(d);renderWbs(d.wbs);renderDecomposition(d.decomposition);buttons()}}catch(e){if(current===d)$('discovery-status').textContent=e.message}
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
 const seq=++sequence,pid=$('project').value;current=null;graphSnapshot=null;renderGraph();$('panel').hidden=true;buttons();
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
  $('estimate-save').addEventListener('click',saveEstimates);
  $('schedule-save').addEventListener('click',saveSchedule);
  $('review-run').addEventListener('click',runReview);
  $('adopt-bundle').addEventListener('click',adoptBundle);
 $('graph-source').addEventListener('change',renderGraph);$('discover').addEventListener('click',discover);setInterval(refreshDiscovery,2000);
  $('wbs-lane').addEventListener('change',buttons);$('wbs-seed').addEventListener('click',()=>mutateWbs(true));$('wbs-save').addEventListener('click',()=>mutateWbs(false));$('wbs-decompose').addEventListener('click',decompose);
  for(const kind of ['seed','save','approve'])$(kind).addEventListener('click',()=>mutate(kind));await reload();
 }catch(e){$('status').textContent=e.message}
});
})();