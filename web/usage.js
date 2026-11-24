(function(){
'use strict';
const $=id=>document.getElementById(id);
let projectNames={},sequence=0;
const number=n=>n==null?'—':new Intl.NumberFormat('vi-VN').format(n);
async function api(path){const r=await fetch(path);if(r.status===401){location.replace('/account.html');throw Error('Phiên đã hết hạn')}const d=await r.json();if(!r.ok)throw Error(d.error||'Không tải được dữ liệu');return d}
function cellRow(values){const tr=document.createElement('tr');for(const v of values){const td=document.createElement('td');td.textContent=String(v);tr.append(td)}return tr}
function counts(v){return [number(v.requests),number(v.input_tokens),number(v.output_tokens),number(v.total_tokens),v.complete_calls+'/'+v.requests]}
function render(d){const t=d.totals;$('kpis').replaceChildren(...[['Input tokens (đã biết)',t.input_tokens],['Output tokens (đã biết)',t.output_tokens],['Total tokens (đã biết)',t.total_tokens],['Lượt gọi model',t.requests]].map(([label,n])=>{const b=document.createElement('div'),l=document.createElement('span'),v=document.createElement('strong');l.textContent=label;v.textContent=number(n);b.append(l,v);return b}));
 $('coverage').textContent='Đủ số liệu: '+t.complete_calls+'/'+t.requests+' · Thiếu: '+t.unknown_calls+' · Một phần: '+t.partial_calls+' · Không nhất quán: '+t.inconsistent_calls+' · Lỗi gọi model: '+t.failed_calls+' · Đang chờ hoặc gián đoạn: '+t.pending_calls+'. Tổng đã biết có thể thấp hơn tiêu thụ thật.';
 const max=Math.max(1,...d.daily.map(v=>v.total_tokens||0));
 $('daily').replaceChildren(...d.daily.map(v=>{const row=document.createElement('div');row.className='day-row';const l=document.createElement('span');l.textContent=v.day;const bar=document.createElement('progress');bar.max=max;bar.value=v.total_tokens||0;bar.setAttribute('aria-label','Known tokens '+v.day);const n=document.createElement('span');n.textContent=number(v.total_tokens);row.append(l,bar,n);return row}));
 if(!d.daily.length)$('daily').textContent='Chưa có lượt gọi model thực trong khoảng thời gian.';
 $('groups').replaceChildren(...d.by_agent_model.map(v=>cellRow([v.agent_id,v.provider+' / '+v.model,v.purpose,...counts(v)])));
 $('project-section').hidden=d.scope!=='all';$('projects').replaceChildren(...d.by_project.map(v=>cellRow([v.project_id?(projectNames[v.project_id]||v.project_id):'System / Probe',...counts(v)])));
 $('report').hidden=false;
 $('status').textContent=(d.groups_truncated||d.projects_truncated?'Hiển thị tối đa 200 nhóm; tổng vẫn tính toàn bộ. ':'')+'Đã cập nhật. '+(t.requests?'':'Chưa có dữ liệu inference; Demo không ghi token.');
}
async function refresh(){const id=++sequence;$('status').textContent='Đang tải…';$('report').hidden=true;try{const p=$('project').value;if(!p)throw Error('Chưa có dự án được cấp quyền');const path=p==='__all__'?'/api/provider/usage':'/api/projects/'+encodeURIComponent(p)+'/usage';const d=await api(path+'?days='+$('days').value);if(id===sequence)render(d)}catch(e){if(id===sequence)$('status').textContent=e.message}}
window.addEventListener('DOMContentLoaded',async()=>{try{const data=await api('/api/bootstrap');projectNames=Object.fromEntries(data.projects.map(p=>[p.id,p.name]));const options=data.projects.map(p=>new Option(p.name,p.id));if(data.provider_admin)options.unshift(new Option('Toàn hệ thống (Admin)','__all__'));$('project').replaceChildren(...options);$('filters').hidden=false;$('filters').addEventListener('submit',e=>{e.preventDefault();refresh()});$('project').addEventListener('change',refresh);$('days').addEventListener('change',refresh);await refresh()}catch(e){$('status').textContent=e.message}});
})();