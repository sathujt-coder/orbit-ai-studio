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
function render(holder,stages,tasks,selected,onSelect){
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
   article.append(el('p','line-handoff',card.next?'Bàn giao dự kiến → '+card.next:'Cuối dây chuyền · không tự release'));
   row.append(article);
  }
  section.append(row);holder.append(section);
 }
 if(hadFocus&&focusId){const target=Array.from(holder.querySelectorAll('[data-role-id]')).find(n=>n.dataset.roleId===focusId);target?.querySelector('button')?.focus({preventScroll:true})}
}
root.StudioLine={model,render};
if(typeof module!=='undefined')module.exports={model};
})(typeof window!=='undefined'?window:globalThis);
