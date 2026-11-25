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
 handoff.append(el('p','line-notice','Chưa có biên nhận sử dụng đầu vào (NOT_RECORDED). Phiên bản là thứ tự final hiện có; digest tính từ nội dung hiện tại, không phải chứng nhận bất biến lịch sử. Không cấp quyền thực thi.'));
 holder.append(handoff);
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
function render(holder,stages,tasks,selected,onSelect,handoff){
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
   for(const lane of ['A','B'])lanes.append(el('span','line-lane',card.short+'-'+lane+' · Đề xuất / review'));
   article.append(lanes,el('p','line-output','Đầu ra: '+card.deliverable));
   article.append(el('p','line-evidence',card.artifacts===null?'Chưa có dữ liệu evidence':card.artifacts+' tài liệu · '+card.reviews+' review (gần đây)'));
   article.append(el('p','line-gate',card.approval?'Quality gate + người duyệt':'Quality gate nội bộ'));
   if(card.link){const a=el('a','line-link',card.link[0]+' ↗');a.href=card.link[1];article.append(a)}
   const actual=handoff?.roles?.find(r=>r.stage_id===id);article.append(el('p','line-handoff',card.next?(actual?.output?.status==='reviewed_output'?'Final đã review · nguồn cho '+card.next:'Chưa đủ bằng chứng bàn giao → '+card.next):'Cuối dây chuyền · không tự release'));
   row.append(article);
  }
  section.append(row);holder.append(section);
 }
 if(hadFocus&&focusId){const target=Array.from(holder.querySelectorAll('[data-role-id]')).find(n=>n.dataset.roleId===focusId);target?.querySelector('button')?.focus({preventScroll:true})}
}
root.StudioLine={model,render,workspaceModel,renderWorkspace};
if(typeof module!=='undefined')module.exports={model,workspaceModel};
})(typeof window!=='undefined'?window:globalThis);
