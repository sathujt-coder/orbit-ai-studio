(function(){
'use strict';const $=id=>document.getElementById(id);let busy=false,timer=null,delay=10000,ended=false,refreshPending=false;
const number=x=>x==null?'—':Number(x).toLocaleString('vi-VN',{maximumFractionDigits:2});
const mib=x=>x==null?'—':number(x/1048576)+' MiB';
const money=x=>x==null?'—':'$'+x;
const date=x=>x==null?'—':new Date(x*1000).toLocaleString('vi-VN');
const pairs=o=>Object.entries(o).map(([k,v])=>k+': '+v).join(' · ');
async function api(path){const r=await fetch(path,{cache:'no-store'});if(r.status===401){ended=true;location.replace('/account.html');throw Error('Phiên hết hạn')}if(r.status===403){ended=true;throw Error('Operator required')}if(!r.ok)throw Error('HTTP '+r.status);return r.json()}
function row(values){const tr=document.createElement('tr');for(const v of values){const td=document.createElement('td');td.textContent=String(v??'—');tr.append(td)}return tr}
function svg(tag,attrs){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));return e}
function chart(title,points,key,scale=1){
 const box=document.createElement('div');box.className='monitor-chart';const h=document.createElement('h3');h.textContent=title;box.append(h);
 const values=points.map(p=>p[key]==null?null:Number(p[key])/scale),known=values.filter(Number.isFinite);const info=document.createElement('p');
 if(!known.length){info.textContent='Chưa có dữ liệu';box.append(info);return box}
 const max=Math.max(1e-9,...known),min=0,w=320,hh=112;
 const graph=svg('svg',{viewBox:'0 0 320 112',role:'img','aria-label':title+' · min '+number(Math.min(...known))+' · max '+number(max)});
 for(let i=0;i<3;i++)graph.append(svg('line',{x1:8,x2:312,y1:8+i*48,y2:8+i*48,stroke:'#34445d','stroke-width':1}));
 let path='',prev=null;const first=points[0].sampled_at,last=points[points.length-1].sampled_at,span=Math.max(1,last-first);
 values.forEach((v,i)=>{if(!Number.isFinite(v)){prev=null;return}const x=8+304*(points[i].sampled_at-first)/span,y=104-96*(v-min)/(max-min);
 if(prev!==null&&points[prev].boot_id===points[i].boot_id)path+=' L '+x+' '+y;else path+=' M '+x+' '+y;
 graph.append(svg('circle',{cx:x,cy:y,r:1.8,fill:'#78cfff'}));prev=i});
 graph.append(svg('path',{d:path,fill:'none',stroke:'#78cfff','stroke-width':1.8}));box.append(graph);
 info.textContent='Min '+number(Math.min(...known))+' · Max '+number(max)+' · Mới nhất '+number(values[values.length-1]);box.append(info);return box
}
function render(d,h){
 $('control').textContent=d.control.stopped?'Emergency control: STOPPED — new inference blocked':'Emergency control: RUNNING';
 delay=Math.max(5000,d.policy.interval_seconds*1000);const s=d.snapshot;
 $('status').textContent=d.sampler.status.toUpperCase()+' · '+(s?date(s.sampled_at):'Chưa có mẫu')+' · Age '+number(d.sampler.age_seconds)+'s · Sampler failures '+d.sampler.failures;
 if(!s){$('report').hidden=true;return}
 const r=s.resources,m=r.metrics,b=s.protection,t=b.totals,u=s.usage_24h,c=s.cost_24h,q=s.queue,cc=s.concurrency;
 $('report').hidden=false;$('kpis').replaceChildren(...[['System',s.health],['Projects',s.projects],['CPU backend',m.process_cpu_percent==null?'—':number(m.process_cpu_percent)+'%'],['RAM khả dụng',mib(m.effective_memory_available_bytes)],['Inference slots',cc.active+'/'+cc.policy.global_limit],['Queued tasks',q.counts.queued],['Tokens 24h',number(u.total_tokens)],['Known cost 24h',money(c.total_usd)]].map(([k,v])=>{const div=document.createElement('div'),l=document.createElement('span'),n=document.createElement('strong');l.textContent=k;n.textContent=v;div.append(l,n);return div}));
 $('health').textContent='Sampled health: '+s.health+' · '+s.alerts.length+' alerts';
 $('alerts').replaceChildren(...s.alerts.map(a=>{const e=document.createElement('p');e.className='monitor-alert';e.dataset.severity=a.severity;e.textContent=a.severity.toUpperCase()+' · '+a.code+' · '+a.message;return e}));
 $('alert-events').replaceChildren(...h.events.map(e=>row([date(e.created_at),e.code,e.transition,e.severity])));
 $('resources').textContent='Backend RSS '+mib(m.process_rss_bytes)+' · Host RAM '+mib(m.host_memory_available_bytes)+' / '+mib(m.host_memory_total_bytes)+' available · Cgroup used '+mib(m.cgroup.memory_current_bytes)+' / '+mib(m.cgroup.memory_limit_bytes)+' · Effective CPU cores '+number(m.effective_cpu_cores)+' · '+r.policy.mode+' · Pressure '+(r.pressure_reason||'none detected');
 $('gpus').replaceChildren(...r.gpu.devices.map(g=>row([g.index,mib(g.vram_used_bytes)+' / '+mib(g.vram_total_bytes),number(g.utilization_percent)+'%'])));$('gpu-status').textContent=r.gpu.status==='available'?'NVIDIA telemetry available':'GPU telemetry unavailable — không phải 0';
 $('history-note').textContent=h.points.length+'/'+h.stored_points+' mẫu · '+h.hours+'h'+(h.downsampled?' · lấy mẫu đều theo index':'')+' · retention '+d.policy.retention_hours+'h / '+d.policy.max_samples+' samples';
 $('charts').replaceChildren(...[['CPU backend (%)','cpu_percent',1],['RAM khả dụng (MiB)','available_bytes',1048576],['RSS backend (MiB)','rss_bytes',1048576],['GPU max utilization (%)','gpu_max_utilization_percent',1],['Inference active','active',1],['Queued tasks','queued',1],['Tokens rolling 24h','tokens_24h',1],['Known USD rolling 24h','cost_24h_usd',1]].map(([title,key,scale])=>chart(title,h.points,key,scale)));
 $('workers').textContent='Workers '+s.workers.alive+'/'+s.workers.configured+' · Active '+cc.active+'/'+cc.policy.global_limit+' · Waiting '+cc.waiting+' · Peak '+cc.peak_active+' · Pending ledger '+s.pending_ledger;
 $('queue').textContent=pairs(q.counts)+' · Oldest eligible age '+number(q.eligible_oldest_age_seconds)+'s';$('stages').textContent=pairs(s.stage_counts);
 $('agents').replaceChildren(...s.agents.map(a=>row([a.id,a.requests,a.successful,a.failed,a.pending_ledger,number(a.known_tokens),date(a.last_request_at)])));
 $('configured').textContent='Configured defaults ('+s.routing_mode+'): '+Object.entries(s.configured_models).map(([k,v])=>k+' '+v.model).join(' · ');
 $('models').replaceChildren(...s.models_24h.map(m=>row([m.provider+' / '+m.model,m.requests,m.pending,number(m.known_tokens)])));
 $('routes').replaceChildren(...s.latest_routes.map(x=>row([x.decision.task.department+' / '+x.decision.task.kind,Object.entries(x.decision.selected).map(([k,v])=>k+' '+v.model).join(' · ')||'—',x.decision.status])));
 $('coverage').textContent='Requests 24h '+u.requests+' · Complete '+u.complete_calls+' · Known cost '+c.known_calls+'/'+c.requests+' · Unknown cost '+c.unknown_calls;
 $('budget').textContent=b.month_utc+' · '+b.policy.mode+' · Accounted '+money(t.accounted_usd)+' / '+money(b.policy.global_cost_usd)+' · Held '+money(t.held_usd)+' · Held tokens '+number(t.held_tokens)+' · Overruns '+t.reservation_overruns+' · Denials 15m '+s.recent_denials;
 $('breaker-counts').textContent=pairs(s.breaker_counts);$('breakers').replaceChildren(...b.breakers.map(x=>row([x.provider+' / '+x.model,x.state,x.failures])));
}
function schedule(){clearTimeout(timer);if(!ended&&$('auto').checked&&!document.hidden)timer=setTimeout(refresh,delay)}
async function refresh(){if(ended)return;if(busy){refreshPending=true;return}busy=true;clearTimeout(timer);$('refresh').disabled=true;try{const [d,h]=await Promise.all([api('/api/provider/monitoring'),api('/api/provider/monitoring/history?hours='+$('hours').value+'&limit=240')]);render(d,h)}catch(e){$('status').textContent='STALE / '+e.message;$('control').textContent='Emergency control: unknown';if(ended)$('report').hidden=true}finally{busy=false;$('refresh').disabled=false;if(refreshPending&&!ended){refreshPending=false;refresh()}else schedule()}}
window.addEventListener('DOMContentLoaded',()=>{$('refresh').addEventListener('click',refresh);$('hours').addEventListener('change',refresh);$('auto').addEventListener('change',schedule);document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else if($('auto').checked)refresh()});refresh()});
})();