/* Read-only role-oriented production line. No dispatch or approval authority. */
(function(root){
'use strict';
const GROUPS=[
 {name:'01 · Khám phá sản phẩm',ids:['po','research','ba']},
 {name:'02 · Lập kế hoạch & thiết kế',ids:['pm','design','techlead']},
 {name:'03 · Xây dựng & kiểm chứng',ids:['dev','qa','qc']},
 {name:'04 · Kiểm soát & bàn giao',ids:['security','devops','marketing']}
];
const LABELS={queued:'Chờ đến lượt',drafting:'Đang tạo bản nháp',reviewing:'Đang review chéo',synthesizing:'Đang hợp nhất',done:'Hoàn thành',approved:'Đã phê duyệt',awaiting_approval:'Chờ người duyệt',needs_revision:'Cần sửa'};
const COMPLETE=new Set(['done','approved']);
const ACTIVE=new Set(['drafting','reviewing','synthesizing']);
const BLOCKED=new Set(['awaiting_approval','needs_revision']);
const LINKS={po:['PRD','/requirements.html'],research:['PRD','/requirements.html'],ba:['PRD','/requirements.html'],pm:['Planning','/planning.html'],dev:['Coding Factory','#codingSection'],devops:['GitHub Delivery','#githubSection']};
// Role-specific work areas: descriptions are design intent, never acceptance evidence.
const WORKSPACES={
 po:{title:'Product Strategy',focus:['Product vision','Mục tiêu & KPI','Phạm vi MVP'],inputs:['Ý tưởng dự án','Nhu cầu người dùng']},
 research:{title:'Research Lab',focus:['Nghiên cứu thị trường','Phân tích đối thủ','Bằng chứng & giả định'],inputs:['Product vision','Câu hỏi nghiên cứu']},
 ba:{title:'Business Analysis',focus:['User stories','Use cases','Acceptance criteria'],inputs:['Product vision','Research findings']},
 pm:{title:'Planning & Delivery',focus:['WBS & dependencies','Resource estimates','Sprint schedule & cross-review'],inputs:['Approved PRD','PM proposals']},
 design:{title:'Design Studio',focus:['User journey','Wireframes & design system','Accessibility'],inputs:['Requirements','Planning constraints']},
 techlead:{title:'Architecture Lab',focus:['Architecture & ADR','API contracts','Data model & risks'],inputs:['Requirements','Design specification']},
 dev:{title:'Engineering Factory',focus:['Phương án A/B','Code & review evidence','Sandbox verification'],inputs:['Architecture','Work specification']},
 qa:{title:'Quality Assurance',focus:['Test strategy','Quality process','Acceptance coverage'],inputs:['Requirements','Implementation specification']},
 qc:{title:'Quality Control',focus:['Test cases','Defect report','Release evidence'],inputs:['Test strategy','Build & test evidence']},
 security:{title:'Security Review',focus:['Threat model','Authorization & data protection','Human security review'],inputs:['Architecture','Verification evidence']},
 devops:{title:'Delivery Operations',focus:['CI/CD checklist','GitHub draft delivery','Human release review'],inputs:['Quality & security evidence','Release candidate']},
 marketing:{title:'Growth Studio',focus:['SEO & onboarding','Growth hypotheses','Human campaign approval'],inputs:['Product strategy','Release readiness']}
};
function workspaceModel(stages,state,id){
 const stage=stages.find(s=>s.id===id),config=WORKSPACES[id];
 if(!stage||!config||!state?.project?.id)return null;
 const task=state.tasks.find(t=>t.stage_id===id);
 return {id,projectId:state.project.id,projectName:state.project.name,name:stage.name,short:stage.short,
  title:config.title,focus:config.focus,inputs:config.inputs,deliverable:stage.deliverable,
  status:task?.status||'unknown',label:LABELS[task?.status]||'Chưa xác minh',
  approval:stage.approval===true,link:LINKS[id]||null,
  handoff:state.handoff?.project_id===state.project.id?state.handoff.roles?.find(r=>r.stage_id===id)||null:null,
  activity:state.activity?.project_id===state.project.id?state.activity.roles?.find(r=>r.stage_id===id)||null:null,
  quality:state.quality?.project_id===state.project.id?state.quality.roles?.find(r=>r.stage_id===id)||null:null,
  artifacts:(state.artifacts||[]).filter(a=>a.stage_id===id),
  reviews:(state.reviews||[]).filter(a=>a.stage_id===id),
  events:(state.events||[]).filter(a=>a.stage_id===id)};
}
function renderWorkspace(holder,stages,state,id,actions){
 const m=workspaceModel(stages,state,id);
 if(!m){holder.replaceChildren(el('p','line-notice','Chưa có workspace cho dự án hiện tại.'));delete holder.dataset.projectId;delete holder.dataset.role;return}
 // Preserve focus and avoid replacing unchanged interactive nodes during polling.
 const signature=JSON.stringify(m);
 if(holder.dataset.signature===signature)return;
 const focused=holder.contains(document.activeElement)?document.activeElement.dataset.focusKey:null;
 holder.replaceChildren();holder.dataset.signature=signature;holder.dataset.projectId=m.projectId;holder.dataset.role=m.id;
 const head=el('div','role-workspace-heading');
 head.append(el('p','section-label',m.short+' / ROLE WORKSPACE'),el('h2','',m.title),el('p','line-notice',m.name+' · '+m.projectName+' · '+m.label));holder.append(head);
 const columns=el('div','role-workspace-grid');
 function panel(title,values){
  const section=el('section','role-workspace-panel');section.append(el('h3','',title));
  const ul=el('ul','');for(const v of values)ul.append(el('li','',v));section.append(ul);columns.append(section);return section;
 }
 panel('Đầu vào dự kiến',m.inputs);panel('Phạm vi công việc',m.focus);panel('Đầu ra & kiểm soát',[m.deliverable,'Hai đề xuất độc lập và review chéo',m.approval?'Yêu cầu phê duyệt của con người':'Quality gate nội bộ']);
 holder.append(columns);
 const controls=el('div','role-workspace-actions');
 function button(label,key,fn){const b=el('button','btn outline',label);b.type='button';b.dataset.focusKey=key;b.addEventListener('click',fn);controls.append(b)}
 if(m.link){const link=el('a','btn outline','Mở '+m.link[0]+' ↗');link.href=m.link[1];link.dataset.focusKey='workspace-link';controls.append(link)}
 for(const lane of ['A','B'])button('Trao đổi '+m.short+'-'+lane,'chat-'+lane,()=>actions.chat(m.id,lane,m.projectId));
 button('Chi tiết phòng ban','inspector',()=>actions.inspect(m.id,m.projectId));
 holder.append(controls);
 const handoff=el('section','role-workspace-panel role-handoff');
 handoff.dataset.inputStatus=m.handoff?.input_status||'unknown';
 handoff.dataset.outputStatus=m.handoff?.output?.status||'unknown';
 handoff.append(el('h3','','Bằng chứng đầu vào / đầu ra · Legacy pipeline'));
 const describe=record=>{
  if(!record)return 'Chưa xác minh';
  return record.status==='reviewed_output'?'Final đã qua review nội bộ · v'+record.version+' · SHA256 '+record.content_digest:'BLOCK · '+record.reason;
 };
 const output=m.handoff?.output;
 handoff.append(el('p','line-notice','Đầu ra: '+describe(output)));
 function sourceButton(record,label){
  if(!record?.artifact_id||record.status!=='reviewed_output')return;
  const b=el('button','role-evidence-item',label+' · '+record.artifact_id);b.type='button';b.dataset.focusKey='handoff-'+record.artifact_id;
  b.addEventListener('click',()=>actions.artifact(record.artifact_id,m.projectId));handoff.append(b);
 }
 sourceButton(output,'Xem final');
 if(m.handoff?.input_status==='project_idea')handoff.append(el('p','line-notice','Đầu vào: ý tưởng dự án'));
 for(const record of m.handoff?.inputs||[]){
  handoff.append(el('p','line-notice',record.stage_id+' → '+m.short+': '+describe(record)));
  sourceButton(record,'Xem nguồn '+record.stage_id);
 }
 const receipt=m.handoff?.receipt;
 handoff.dataset.consumptionStatus=m.handoff?.consumption_status||'NOT_RECORDED';
 handoff.append(el('p','line-notice','Biên nhận đầu vào: '+handoff.dataset.consumptionStatus));
 if(receipt){
  handoff.append(el('p','role-evidence-item','Run '+receipt.run_id+' · '+receipt.mode+' · lanes '+receipt.lanes.join(', ')+' · Context SHA256 '+(receipt.context_digest||'INVALID')));
  for(const source of receipt.sources)handoff.append(el('p','role-evidence-item','Nguồn đã ghi nhận: '+source.stage_id+' · '+source.artifact_id+' · v'+source.version+' · '+source.content_digest));
 }
 handoff.append(el('p','line-notice','Biên nhận ghi nhận context đã chuẩn bị và draft trả về; DEMO không phải inference thật. STALE hoặc INVALID không chứng minh bàn giao hiện hành. Không cấp quyền thực thi hoặc release.'));
 holder.append(handoff);
 const activity=el('section','role-agent-activity');
 activity.append(el('h3','','Hoạt động agent · evidence thực tế'));
 const q=m.activity?.queue;
 activity.append(el('p','line-notice',q?'Queue '+q.id+' · '+q.status+' · attempts '+q.attempts+' · '+q.reason:'Chưa có queue liên kết với run này'));
 for(const a of m.activity?.agents||[]){
  const node=el('div','role-evidence-item');node.dataset.activityAgent=a.agent_id;node.dataset.activityState=a.state;
  node.append(el('strong','',a.agent_id+' · '+a.state));
  const attempt=a.stage_attempt;
  if(attempt)node.append(el('p','line-notice',attempt.purpose+' · '+attempt.provider+' / '+attempt.model+' · '+attempt.status+' · '+(attempt.elapsed_ms??'unknown')+' ms · tokens '+(attempt.total_tokens??'unknown')+' · '+attempt.coverage));
  if(a.latest_attempt&&a.latest_attempt.id!==attempt?.id)node.append(el('p','line-notice','Lần gọi khác gần nhất: '+a.latest_attempt.purpose+' · '+a.latest_attempt.provider+' / '+a.latest_attempt.model+' · '+a.latest_attempt.status+' · run '+(a.latest_attempt.run_id||'unknown')));
  if(a.denial)node.append(el('p','line-notice','Inference denied: '+a.denial.reason));
  activity.append(node);
 }
 activity.append(el('p','line-notice','Pending không xác nhận kết nối model đang chạy; DEMO không có token ledger. Queue là trạng thái công việc, không phải trạng thái từng agent.'));
 holder.append(activity);
 const quality=el('section','role-quality');const gate=m.quality;
 quality.dataset.qualityState=gate?.state||'PENDING';
 quality.append(el('h3','','Quality Gates · Legacy pipeline'));
 quality.append(el('p','line-notice',(gate?.state||'PENDING')+' · Run '+(gate?.run_id||'unknown')+' · '+(gate?.mode==='demo'?'DEMO — không phải real AI':gate?.mode||'Mode chưa xác minh')));
 for(const check of gate?.checks||[]){const line=el('p','quality-check',check.key+' · '+check.status);line.dataset.check=check.key;line.dataset.checkStatus=check.status;quality.append(line)}
 for(const review of gate?.reviews||[]){const line=el('p','role-evidence-item',review.reviewer_id+' → '+review.author_id+' · '+review.verdict+' · '+review.score+'/100 · Review '+review.id+' · '+review.feedback);line.dataset.reviewId=review.id;quality.append(line)}
 for(const artifact of [...(gate?.drafts||[]),...(gate?.final?[gate.final]:[])]){const b=el('button','role-evidence-item','Xem bằng chứng '+artifact.id);b.type='button';b.dataset.focusKey='quality-'+artifact.id;b.addEventListener('click',()=>actions.artifact(artifact.id,m.projectId));quality.append(b)}
 if(gate?.approved_at)quality.append(el('p','line-notice','Human approval: '+gate.approved_at));
 if(gate?.output_reason)quality.append(el('p','line-notice','Handoff: '+gate.output_reason));
 quality.append(el('p','line-notice','Ngưỡng từng reviewer ≥80, không lấy trung bình. System/Real AI/Model Qualification không được nghiệm thu tại đây. Không cấp quyền thực thi hoặc release.'));
 holder.append(quality);
 const evidence=el('div','role-workspace-grid');
 const docs=el('section','role-workspace-panel');docs.append(el('h3','','Tài liệu gần đây · '+m.artifacts.length));
 if(!m.artifacts.length)docs.append(el('p','line-notice','Chưa có tài liệu cho vai trò này.'));
 for(const a of m.artifacts.slice(0,8)){const b=el('button','role-evidence-item',a.kind+' · '+a.agent_id+' · '+(a.preview||''));b.type='button';b.dataset.focusKey='artifact-'+a.id;b.addEventListener('click',()=>actions.artifact(a.id,m.projectId));docs.append(b)}
 const reviews=el('section','role-workspace-panel');reviews.append(el('h3','','Review gần đây · '+m.reviews.length));
 if(!m.reviews.length)reviews.append(el('p','line-notice','Chưa có review cho vai trò này.'));
 for(const r of m.reviews.slice(0,8))reviews.append(el('p','role-evidence-item',r.reviewer_id+' → '+r.author_id+' · '+r.verdict+' · '+r.score+' · '+r.feedback));
 const events=el('section','role-workspace-panel');events.append(el('h3','','Hoạt động gần đây'));
 if(!m.events.length)events.append(el('p','line-notice','Chưa có sự kiện cho vai trò này.'));
 for(const event of m.events.slice(0,8))events.append(el('p','role-evidence-item',event.message));
 evidence.append(docs,reviews,events);holder.append(evidence);
 holder.append(el('p','line-notice','Phạm vi và đầu vào là mô tả vai trò, không phải xác nhận bàn giao. Evidence thuộc legacy pipeline; workspace chuyên biệt có quality gates riêng. Không cấp quyền thực thi hoặc release.'));
 if(focused)Array.from(holder.querySelectorAll('[data-focus-key]')).find(n=>n.dataset.focusKey===focused)?.focus({preventScroll:true});
}
function model(stages,tasks){
 const byId=new Map(tasks.map(t=>[t.stage_id,t]));
 return stages.map((stage,index)=>{
  const task=byId.get(stage.id),prior=stages[index-1],previous=prior&&byId.get(prior.id);
  const status=task?.status||'unknown';
  const tone=COMPLETE.has(status)?'complete':ACTIVE.has(status)?'working':BLOCKED.has(status)?'blocked':'waiting';
  const input=!task?'Chưa có dữ liệu':!prior?'Ý tưởng dự án':COMPLETE.has(previous?.status)?'Giai đoạn trước hoàn thành':'Chờ '+prior.short;
  return {id:stage.id,short:stage.short,name:stage.name,deliverable:stage.deliverable,approval:stage.approval,
   status,tone,label:LABELS[status]||'Chưa xác minh',input,previous:prior?.id||null,
   next:stages[index+1]?.short||null,artifacts:task?.artifact_count??null,reviews:task?.review_count??null,link:LINKS[stage.id]||null};
 });
}
function el(tag,cls,text){
 const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;
}
function render(holder,stages,tasks,selected,onSelect,handoff,activity,quality){
 const cards=model(stages,tasks);const active=document.activeElement;
 const focusId=holder.contains(active)?active.closest('[data-role-id]')?.dataset.roleId:null;
 const hadFocus=active?.classList.contains('line-select');
 holder.replaceChildren();
 for(const group of GROUPS){
  const section=el('section','line-group');section.append(el('h3','line-group-title',group.name));
  const row=el('div','line-row');
  for(const id of group.ids){
   const card=cards.find(c=>c.id===id);if(!card)continue;
   const article=el('article','line-role '+card.tone+(selected===id?' selected':''));article.dataset.roleId=id;article.dataset.status=card.status;
   const button=el('button','line-select');button.type='button';button.setAttribute('aria-pressed',String(selected===id));
   button.append(el('span','line-role-code',card.short),el('strong','line-role-name',card.name),el('span','line-status',card.label));
   button.addEventListener('click',()=>onSelect(id));article.append(button);
   article.append(el('p','line-input','← '+card.input));
   const lanes=el('div','line-lanes');
   for(const lane of ['A','B']){const agent=activity?.roles?.find(r=>r.stage_id===id)?.agents?.find(a=>a.lane===lane);const node=el('span','line-lane',card.short+'-'+lane+' · '+(agent?.state||'NO_EVIDENCE'));node.dataset.agentId=id+'-'+lane;node.dataset.activityState=agent?.state||'NO_EVIDENCE';lanes.append(node)}
   article.append(lanes,el('p','line-output','Đầu ra: '+card.deliverable));
   article.append(el('p','line-evidence',card.artifacts===null?'Chưa có dữ liệu evidence':card.artifacts+' tài liệu · '+card.reviews+' review (gần đây)'));
   const gate=quality?.roles?.find(r=>r.stage_id===id);const gateNode=el('p','line-gate',(card.approval?'Quality gate + người duyệt':'Quality gate nội bộ')+' · '+(gate?.state||'PENDING'));gateNode.dataset.qualityState=gate?.state||'PENDING';article.append(gateNode);
   if(card.link){const a=el('a','line-link',card.link[0]+' ↗');a.href=card.link[1];article.append(a)}
   const actual=handoff?.roles?.find(r=>r.stage_id===id);article.append(el('p','line-handoff',card.next?(actual?.output?.status==='reviewed_output'?'Final đã review · nguồn cho '+card.next:'Chưa đủ bằng chứng bàn giao → '+card.next):'Cuối dây chuyền · không tự release'));
   row.append(article);
  }
  section.append(row);holder.append(section);
 }
 if(hadFocus&&focusId){const target=Array.from(holder.querySelectorAll('[data-role-id]')).find(n=>n.dataset.roleId===focusId);target?.querySelector('button')?.focus({preventScroll:true})}
}
function workflowControls(state){
 const w=state?.workflow,p=state?.workflow_permissions;
 if(!w||w.project_id!==state.project?.id||p?.project_id!==w.project_id)return {write:false,approve:false};
 return {write:p.can_write===true,approve:p.can_approve===true};
}
function renderWorkflow(holder,state,submit){
 const w=state.workflow;
 const rights=workflowControls(state),signature=JSON.stringify([w,rights,state.engineering,state.dependency_completion]);
 if(holder.dataset.projectId===state.project?.id&&holder.dataset.signature===signature)return;
 holder.replaceChildren();delete holder.dataset.projectId;delete holder.dataset.signature;
 if(!w||w.project_id!==state.project?.id){holder.append(el('p','line-notice','Unified workflow chưa xác minh'));return}
 holder.dataset.projectId=w.project_id;holder.dataset.signature=signature;
 holder.append(el('h2','','Unified Workflow · Artifact Contracts'));
 const panel=(title,status,lines,href)=>{const p=el('section','role-workspace-panel');p.append(el('h3','',title),el('p','line-notice',status));for(const line of lines)p.append(el('p','role-evidence-item',line));if(href){const a=el('a','line-link','Mở workflow ↗');a.href=href;p.append(a)}holder.append(p);return p};
 const revision=w.requirements.revision;
 const p=panel('Product Requirements',w.requirements.state,revision?['PRD v'+revision.version+' · '+revision.digest]:[], '/requirements.html');p.dataset.workflowStage='requirements';
 const a=w.planning.adoption;
 const lines=a?['Adoption v'+a.version+' · '+a.digest,'Bundle '+a.bundle_digest,'Review '+a.review_id+' · '+a.evidence_digest]:[];
 if(w.planning.wbs)lines.push('WBS v'+w.planning.wbs.version+' · '+w.planning.wbs.digest);
 if(w.planning.reason)lines.push(w.planning.reason);
 panel('Planning Adoption',w.planning.state,lines,'/planning.html').dataset.workflowStage='planning';
 const packages=w.work_packages;
 const wp=panel('Work Package Contracts',packages?packages.bindings.length+' recorded bindings':'NOT_RECORDED',[]);wp.dataset.workflowStage='work-packages';
 const action=(parent,kind,token,build)=>{
  const form=el('form','studio-action');form.dataset.studioAction=kind;
  const label=el('label','','Nhập chính xác: '+token);
  const confirm=el('input','');confirm.required=true;confirm.autocomplete='off';confirm.name='confirmation';label.append(confirm);
  const button=el('button','btn primary','Xác nhận '+kind);button.type='submit';
  const status=el('p','line-notice');status.setAttribute('role','status');
  form.append(label,button,status);
  form.addEventListener('submit',async ev=>{
   ev.preventDefault();
   if(confirm.value!==token){status.textContent='Xác nhận không khớp.';return}
   if(!form.isConnected||holder.dataset.signature!==signature||holder.dataset.projectId!==w.project_id){status.textContent='Nguồn đã thay đổi.';return}
   button.disabled=true;
   try{await submit(w.project_id,kind,{...build(),confirmation:token},signature);status.textContent='Đã gửi yêu cầu.'}
   catch(err){status.textContent=err.message;button.disabled=false}
  });
  parent.append(form);return form;
 };
 for(const p of packages?.available||[]){
  const card=el('article','studio-contract');card.dataset.packageId=p.id;card.append(el('h4','',p.id+' · '+p.kind));
  const bound=packages.bindings.find(b=>b.package_id===p.id&&b.adoption_version===a?.version);
  card.append(el('p','line-notice',bound?bound.state+' · '+bound.digest:'NOT_BOUND'));
  if(rights.write&&submit&&w.planning.state==='adopted'&&!w.planning.stale&&a&&!bound)
   action(card,'bind','BIND ADOPTED WORK PACKAGE',()=>({adoption_version:a.version,bundle_digest:a.bundle_digest,package_id:p.id}));
  if(rights.write&&submit&&bound?.state==='BOUND'&&w.planning.state==='adopted'&&!w.planning.stale&&p.kind==='implement'&&Array.isArray(p.depends_on)&&p.depends_on.length===0&&!w.coding_jobs.some(j=>j.source_binding?.package_id===p.id&&j.source_binding?.adoption_version===a.version))
   action(card,'coding','QUEUE ADOPTED WORK PACKAGE',()=>({adoption_version:a.version,package_id:p.id,binding_digest:bound.digest}));
  if(p.kind!=='implement'||p.depends_on?.length)card.append(el('p','line-notice','Coding bị chặn: loại package hoặc dependency chưa đủ điều kiện.'));
  wp.append(card);
 }
 for(const b of packages?.bindings||[])wp.append(el('p','role-evidence-item',b.package_id+' · v'+b.adoption_version+' · '+b.state+' · '+b.digest));
 if(!rights.write)wp.append(el('p','line-notice','Chỉ đọc: cần quyền write.'));

 const eng=state.engineering;
 if(eng?.project_id===w.project_id){
  const section=panel('Engineering Execution Contracts','Development only · không cấp quyền thực thi',[]);
  section.dataset.workflowStage='engineering';
  for(const item of eng.contracts){
   section.append(el('p','role-evidence-item',item.package_id+' · '+item.state+' · v'+item.latest_version+' · '+(item.source_digest||'unavailable')));
   if(item.source)section.append(el('p','line-notice','Graph '+item.source.graph_digest+' · prerequisites '+(item.source.predecessors.join(', ')||'none')+' · '+item.source.reasons.join(', ')));
  }
 }
 const completion=state.dependency_completion;
 if(completion?.project_id===w.project_id){
  const section=panel('Dependency Completion Evidence','Development evidence only · không tự mở khóa dependency',[]);
  section.dataset.workflowStage='dependency-completion';
  for(const item of completion.items)section.append(el('p','role-evidence-item',item.package_id+' · '+item.state+' · v'+item.latest_version+' · '+(item.receipt?.selected?'DEV-'+item.receipt.selected+' · ':'')+(item.source_digest||'unavailable')));
 }
 const jobs=w.coding_jobs.flatMap(j=>['Job '+j.job_id+' · '+j.status+' · '+j.planning_binding+(j.source_binding?' · '+j.source_binding.package_id+' · '+j.source_binding.binding_digest:''),'Queue '+(j.queue?.id||'unlinked')+' · '+(j.queue?.status||'unknown'), 'Manifest '+(j.manifest_digest||'unknown'), 'Verification '+(j.verification?j.verification.id+' · '+j.verification.state+' · '+j.verification.digest:'NOT_RECORDED'), 'QA '+(j.qa?j.qa.state+' · '+(j.qa.source_digest||'unavailable'):'NOT_RECORDED')]);
 const coding=panel('Coding & Verification',w.coding_jobs.length+' recent jobs',jobs,'#codingSection');coding.dataset.workflowStage='coding';
 const qaPanel=panel('QA/QC · Criterion Attestation',rights.approve?'Human approval required':'Chỉ đọc: cần quyền approve',[]);qaPanel.dataset.workflowStage='qa';
 for(const j of w.coding_jobs){
  if(j.verification?.candidates)for(const lane of ['A','B']){const v=j.verification.candidates[lane];if(v)coding.append(el('p','role-evidence-item','DEV-'+lane+' · '+v.digest+' · tests '+v.test_count))}
  const qa=j.qa;if(!qa)continue;
  const card=el('article','studio-contract');card.dataset.qaJob=j.job_id;card.append(el('h4','',j.job_id+' · '+qa.state));
  if(qa.receipt)card.append(el('p','line-notice','Receipt v'+qa.receipt.version+' · '+qa.receipt.digest));
  const fields=[];
  for(const criterion of qa.source?.acceptance||[]){
   const section=el('section','studio-criterion');section.append(el('p','',criterion.id+' · '+criterion.text));
   const saved=qa.receipt?.criteria?.find(x=>x.id===criterion.id);if(saved)section.append(el('p','line-notice',saved.verdict+' · '+saved.rationale));
   if(rights.approve&&submit&&qa.source_digest){
    const select=el('select','');select.setAttribute('aria-label','Verdict '+criterion.id);
    for(const value of ['', 'PASS','BLOCK']){const opt=el('option','',value||'Chọn verdict');opt.value=value;select.append(opt)}select.required=true;
    const rationale=el('textarea','');rationale.setAttribute('aria-label','Rationale '+criterion.id);rationale.required=true;rationale.minLength=20;rationale.maxLength=1200;
    section.append(select,rationale);fields.push({id:criterion.id,select,rationale});
   }
   card.append(section);
  }
  if(fields.length&&j.planning_binding==='BOUND'&&qa.source_digest){
   const form=action(card,'qa','ATTEST WORK PACKAGE QA',()=>({job_id:j.job_id,source_digest:qa.source_digest,expected_version:qa.latest_version,criteria:fields.map(x=>({id:x.id,verdict:x.select.value,rationale:x.rationale.value}))}));
   for(const x of fields){x.select.closest('section').remove();const section=el('section','studio-criterion');section.append(el('p','',x.id+' · '+qa.source.acceptance.find(c=>c.id===x.id).text),x.select,x.rationale);form.prepend(section)}
  }
  qaPanel.append(card);
 }

 panel('Agent Queue',w.queue.truncated?'Recent 100 · truncated':'Recent jobs',w.queue.tasks.map(q=>q.kind+' · '+q.id+' · '+q.status+' · dependency '+(q.dependency_id||'none'))).dataset.workflowStage='queue';
 holder.append(el('p','line-notice','Next checkpoint: '+w.next_checkpoint+' · Execution NOT AUTHORIZED. Không tự dispatch hoặc release.'));
}
root.StudioLine={model,render,workspaceModel,renderWorkspace,renderWorkflow};
if(typeof module!=='undefined')module.exports={model,workspaceModel,workflowControls};
})(typeof window!=='undefined'?window:globalThis);
