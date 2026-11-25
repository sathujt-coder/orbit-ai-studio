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
