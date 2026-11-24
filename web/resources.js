(function(){
'use strict';
const $=id=>document.getElementById(id);
let csrf='';
const mib=n=>n==null?'—':(n/1048576).toLocaleString('vi-VN',{maximumFractionDigits:1})+' MiB';
const percent=n=>n==null?'—':n.toLocaleString('vi-VN',{maximumFractionDigits:1})+'%';
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-ORBIT-UI':'1','X-ORBIT-CSRF':csrf},...(body?{body:JSON.stringify(body)}:{})});if(r.status===401){location.replace('/account.html');throw Error('Phiên đã hết hạn')}const d=await r.json();if(!r.ok)throw Error(d.error||'Không tải được dữ liệu');return d}
function row(values){const tr=document.createElement('tr');for(const v of values){const td=document.createElement('td');td.textContent=String(v);tr.append(td)}return tr}
function render(d){const m=d.metrics,c=m.cgroup,p=d.policy,a=d.admission;
 $('kpis').replaceChildren(...[['CPU backend',percent(m.process_cpu_percent)],['RAM khả dụng hiệu dụng',mib(m.effective_memory_available_bytes)],['RAM backend RSS',mib(m.process_rss_bytes)],['CPU cores hiệu dụng',m.effective_cpu_cores??'—']].map(([k,v])=>{const b=document.createElement('div'),l=document.createElement('span'),n=document.createElement('strong');l.textContent=k;n.textContent=v;b.append(l,n);return b}));
 $('policy').textContent=p.mode.toUpperCase()+' · RAM trống tối thiểu '+p.min_free_mib+' MiB · Ngưỡng áp lực '+p.max_memory_percent+'%';
 $('pressure').textContent='Áp lực hiện tại: '+(d.pressure_reason||'Không phát hiện theo chỉ số hiện có');
 $('admission').textContent='Lượt cho phép: '+a.allowed+' · Bị chặn: '+a.blocked+' · Cảnh báo trong observe: '+a.would_block+' (từ lúc backend khởi động)';
 const cc=d.concurrency,qp=d.queue_workers;if(cc){const p=cc.policy;$('concurrency').textContent='Inference active '+cc.active+'/'+p.global_limit+' · Waiting '+cc.waiting+'/'+p.max_waiters+' · Peak '+cc.peak_active+' · Endpoint '+p.endpoint_limit+' · Model '+p.model_limit+' · Project '+p.project_limit+' · Timeout '+p.wait_seconds+'s · Workers '+qp.alive+'/'+qp.configured+' · Refused '+(cc.counts.busy+cc.counts.wait_queue_full+cc.counts.wait_timeout+cc.counts.closed)}
 $('memory').textContent='Platform: '+m.platform+'\nHost RAM total: '+mib(m.host_memory_total_bytes)+'\nHost RAM available: '+mib(m.host_memory_available_bytes)+'\nCgroup: '+c.scope+'\nMemory limit: '+mib(c.memory_limit_bytes)+'\nMemory current: '+mib(c.memory_current_bytes)+'\nHeadroom: '+mib(c.memory_headroom_bytes)+'\nCPU quota: '+(c.cpu_quota_cores??'—');
 const g=d.gpu;$('gpus').replaceChildren(...(g?.devices||[]).map(v=>row([v.index,mib(v.vram_total_bytes),mib(v.vram_used_bytes),percent(v.utilization_percent)])));$('gpu-status').textContent=g?.status==='available'?'NVIDIA telemetry khả dụng':'GPU telemetry chưa khả dụng; không suy ra GPU bằng 0.';
 $('report').hidden=false;$('status').textContent='Cập nhật: '+new Date(d.sampled_at*1000).toLocaleString('vi-VN');
}
async function refresh(){const b=$('refresh');b.disabled=true;try{render(await api('/api/provider/resources'))}catch(e){$('status').textContent=e.message;$('report').hidden=true}finally{b.disabled=false}}
window.addEventListener('DOMContentLoaded',async()=>{try{csrf=(await api('/api/auth/session')).csrf_token;$('refresh').addEventListener('click',refresh);
 $('models').addEventListener('click',async()=>{const b=$('models');b.disabled=true;try{const data=await api('/api/provider/resources/models',{confirmation:'READ LOCAL MODEL STATUS'});$('model-status').textContent=Object.entries(data.lanes).map(([k,v])=>'Lane '+k+': '+v.status+'\n'+(v.models||[]).map(m=>m.model+' · loaded '+mib(m.size_bytes)+' · VRAM '+mib(m.size_vram_bytes)+' · context '+(m.context_length??'—')).join('\n')).join('\n\n')}catch(e){$('model-status').textContent=e.message}finally{b.disabled=false}});
 await refresh()}catch(e){$('status').textContent=e.message}});
})();