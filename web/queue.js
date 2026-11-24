(function(){
'use strict';
const $=id=>document.getElementById(id);let csrf='',report=null,sequence=0,busy=0;
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-ORBIT-UI':'1','X-ORBIT-CSRF':csrf},...(body?{body:JSON.stringify(body)}:{})});if(r.status===401){location.replace('/account.html');throw Error('Phiên hết hạn')}const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
const base=pid=>'/api/projects/'+encodeURIComponent(pid)+'/queue';
function cell(tr,x){const td=document.createElement('td');td.textContent=String(x);tr.append(td);return td}
function button(td,label,fn){const b=document.createElement('button');b.type='button';b.className='btn outline';b.textContent=label;b.addEventListener('click',async()=>{b.disabled=true;busy++;try{await fn()}catch(e){$('status').textContent=e.message}finally{busy--;b.disabled=false}});td.append(b)}
function render(d){report=d;const c=d.counts;const groups=[['Queued',c.queued||0],['Running',c.running||0],['Paused / approval',(c.paused||0)+(c.waiting_approval||0)],['Dead / interrupted',(c.dead||0)+(c.interrupted||0)]];
 $('kpis').replaceChildren(...groups.map(([k,v])=>{const b=document.createElement('div'),l=document.createElement('span'),n=document.createElement('strong');l.textContent=k;n.textContent=v;b.append(l,n);return b}));
 $('submit-panel').hidden=!d.can_write;const prev=$('dependency').value;$('dependency').replaceChildren(new Option('Không có',''),...d.tasks.filter(t=>!['dead','interrupted','cancelled'].includes(t.status)).map(t=>new Option(t.id.slice(0,12)+' · '+t.kind+' · '+t.status,t.id)));if([...$('dependency').options].some(o=>o.value===prev))$('dependency').value=prev;
 $('tasks').replaceChildren(...d.tasks.map(t=>{const tr=document.createElement('tr');cell(tr,t.id.slice(0,12)+' · '+t.kind+(t.mode?' / '+t.mode:''));cell(tr,t.priority);cell(tr,t.dependency_id?.slice(0,12)||'—');cell(tr,t.status+' · '+t.reason+(t.control?' · '+t.control:''));cell(tr,t.attempts+' / '+t.deferrals);const td=cell(tr,'');
 const action=async(a,b={})=>{await api(base(d.project_id)+'/'+t.id+'/'+a,b);await refresh()};
 button(td,'History',async()=>{const data=await api(base(d.project_id)+'/'+t.id);if($('project').value===d.project_id)$('history').textContent=data.events.map(e=>new Date(e.created_at*1000).toLocaleString('vi-VN')+' · '+e.status+' · '+e.reason).join('\n')});
 if(d.can_write){if(t.status==='queued'||(t.status==='running'&&t.kind==='pipeline'))button(td,'Pause',()=>action('pause'));
 if(['paused','waiting_approval'].includes(t.status))button(td,'Resume',()=>action('resume'));
 if(['queued','paused','waiting_approval'].includes(t.status)||(t.status==='running'&&t.kind==='pipeline'))button(td,'Cancel',async()=>{if(confirm('Hủy tác vụ tại ranh giới an toàn?'))await action('cancel')});
 if(['queued','paused','waiting_approval'].includes(t.status))button(td,'Priority',async()=>{const p=prompt('Ưu tiên 0–9',String(t.priority));if(p!==null&&/^[0-9]$/.test(p))await action('priority',{priority:Number(p)})});
 if(['dead','interrupted','cancelled'].includes(t.status))button(td,'Retry',async()=>{if(confirm('Tạo tác vụ mới; có thể phát sinh chi phí AI?'))await action('retry',{confirmation:'RETRY QUEUE TASK'})})}return tr}));
 $('report').hidden=false;$('status').textContent=!d.dispatcher_running?'Dispatcher đã dừng; cần kiểm tra backend.':d.truncated?'Đã cập nhật 100 tác vụ gần nhất.':'Đã cập nhật.';
}
async function refresh(){const id=++sequence;const pid=$('project').value;if(!pid){$('status').textContent='Chưa có dự án';return}try{const d=await api(base(pid));if(id===sequence)render(d)}catch(e){if(id===sequence){report=null;$('report').hidden=true;$('status').textContent=e.message}}}
window.addEventListener('DOMContentLoaded',async()=>{try{csrf=(await api('/api/auth/session')).csrf_token;const data=await api('/api/bootstrap');$('project').replaceChildren(...data.projects.map(p=>new Option(p.name,p.id)));const saved=localStorage.getItem('orbit-project');if(data.projects.some(p=>p.id===saved))$('project').value=saved;$('filters').hidden=false;
 $('filters').addEventListener('submit',e=>{e.preventDefault();refresh()});$('project').addEventListener('change',()=>{report=null;$('report').hidden=true;$('history').textContent='';refresh()});$('kind').addEventListener('change',()=>{$('spec-label').hidden=$('kind').value!=='coding'});
 $('submit').addEventListener('submit',async e=>{e.preventDefault();if(!report?.can_write)return;const b=e.currentTarget.querySelector('button');b.disabled=true;try{const pid=report.project_id,kind=$('kind').value,body={priority:Number($('priority').value),dependency_id:$('dependency').value||null};if(kind==='coding')await api('/api/coding/start',{...body,project_id:pid,spec:$('spec').value});else await api('/api/projects/'+encodeURIComponent(pid)+'/run',{...body,mode:kind});await refresh()}catch(err){$('status').textContent=err.message}finally{b.disabled=false}});
 await refresh();setInterval(()=>{if(!document.hidden&&!busy&&!$('submit').contains(document.activeElement))refresh()},3000);
 }catch(e){$('status').textContent=e.message}});
})();