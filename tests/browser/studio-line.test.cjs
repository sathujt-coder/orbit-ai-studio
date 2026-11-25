'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {model}=require('../../web/studio-line.js');
test('role line preserves actual backend status and never infers handoff completion',()=>{
 const stages=[{id:'po',short:'PO'},{id:'pm',short:'PM'},{id:'dev',short:'DEV'}];
 const rows=model(stages,[{stage_id:'po',status:'awaiting_approval',artifact_count:2,review_count:2},{stage_id:'pm',status:'queued',artifact_count:0,review_count:0}]);
 assert.equal(rows[0].tone,'blocked');assert.equal(rows[1].input,'Chờ PO');
 assert.equal(rows[2].status,'unknown');assert.equal(rows[2].artifacts,null);
 assert.equal(model(stages,[{stage_id:'po',status:'approved'},{stage_id:'pm',status:'drafting'}])[1].input,'Giai đoạn trước hoàn thành');
 assert.equal(model(stages,[{stage_id:'pm',status:'needs_revision'}])[1].tone,'blocked');
});

test('workspace scopes evidence to selected role and project snapshot',()=>{
 const {workspaceModel}=require('../../web/studio-line.js');
 const stages=[{id:'pm',name:'Project Manager',short:'PM',deliverable:'Plan',approval:false},{id:'security',name:'Security',short:'SEC',approval:true}];
 const state={project:{id:'p',name:'P'},tasks:[{stage_id:'pm',status:'queued'}],artifacts:[{id:'a',stage_id:'pm'},{id:'b',stage_id:'security'}],reviews:[{stage_id:'security'}],events:[{stage_id:'pm'}]};
 const m=workspaceModel(stages,state,'pm');
 assert.equal(m.projectId,'p');assert.deepEqual(m.artifacts.map(a=>a.id),['a']);assert.equal(m.reviews.length,0);assert.equal(m.events.length,1);
 assert.equal(workspaceModel(stages,state,'security').approval,true);
 assert.equal(workspaceModel(stages,state,'unknown'),null);
 assert.equal(workspaceModel(stages,null,'pm'),null);
});

test('handoff evidence is bound to current project',()=>{const {workspaceModel}=require('../../web/studio-line.js');const stages=[{id:'pm'}],state={project:{id:'p'},tasks:[],handoff:{project_id:'q',roles:[{stage_id:'pm',output:{status:'reviewed_output'}}]}};assert.equal(workspaceModel(stages,state,'pm').handoff,null);state.handoff.project_id='p';assert.equal(workspaceModel(stages,state,'pm').handoff.output.status,'reviewed_output')});
