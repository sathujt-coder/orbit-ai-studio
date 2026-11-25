/** Real Chromium browser E2E for the ORBIT Web-first MVP. No AI-generated code executed. */
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const {login,headers,ORIGIN}=require('./auth-helper.cjs');

test('Web-first UI boots, project form excludes Mobile and creates a Web project', async () => {
  const browser = await chromium.launch({headless: true, args: ['--disable-gpu', '--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1365, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await login(page);
    for(const [path,mime] of [['/studio-line.js',/javascript/],['/studio-line.css',/text\/css/]]){
      const asset=await page.request.get(ORIGIN+path);
      assert.equal(asset.status(),200,path+' must be served by static allowlist');
      assert.match(asset.headers()['content-type'],mime);
    }
    assert.equal((await page.request.get(ORIGIN+'/not-allowlisted.js')).status(),404);
    const response = await page.goto(ORIGIN + '/', {waitUntil: 'domcontentloaded'});
    assert.equal(response.status(), 200);
    await page.locator('#projectSide .project-item').first().waitFor({timeout: 15000});
    await page.waitForFunction(() => document.querySelectorAll('#agentMembers .agent-card').length === 2, null, {timeout: 15000});
    assert.equal(await page.locator('#agentMembers .agent-card').count(), 2);
    assert.equal(await page.locator('#pipelineTrack').isVisible(), true);
    await page.locator('#studioLine[data-ready="true"]').waitFor({state:'visible'});
    const initialId=await page.locator('#studioLine').getAttribute('data-project-id');
    assert.ok(initialId);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.roleId)),['po','research','ba','pm','design','techlead','dev','qa','qc','security','devops','marketing']);
    await page.locator('[data-role-id="pm"] .line-select').click();
    assert.equal(await page.locator('#officeDetails').evaluate(e=>e.open),true);
    assert.equal(await page.locator('#deptName').textContent(),'Project Manager');
    assert.equal(await page.locator('#roleWorkspace').getAttribute('data-role'),'pm');
    assert.equal(await page.locator('#roleWorkspace').getAttribute('data-project-id'),initialId);
    const roleIds=['po','research','ba','pm','design','techlead','dev','qa','qc','security','devops','marketing'];
    const titles=new Set();
    for(const role of roleIds){
      await page.locator('[data-role-id="'+role+'"] .line-select').click();
      assert.equal(await page.locator('#roleWorkspace').getAttribute('data-role'),role);
      titles.add(await page.locator('#roleWorkspace h2').textContent());
      assert.equal(await page.locator('#roleWorkspace .role-workspace-panel').count(),7);
    }
    assert.equal(titles.size,12);
    await page.locator('[data-role-id="pm"] .line-select').click();
    assert.equal(await page.locator('#roleWorkspace [data-focus-key="workspace-link"]').getAttribute('href'),'/planning.html');
    assert.equal(await page.locator('[data-role-id="pm"] .line-link').getAttribute('href'),'/planning.html');
    await page.locator('#newProjectBtn').click();
    await page.locator('#createModal:not(.hidden)').waitFor();
    const options = await page.locator('#newProjectForm select[name=platform] option').allTextContents();
    assert.deepEqual(options, ['Web app', 'SaaS + API']);
    const name = 'Web E2E ' + Date.now();
    await page.locator('#newProjectForm input[name=name]').fill(name);
    await page.locator('#newProjectForm textarea[name=idea]').fill('Test web application end to end with real Chromium and backend persistence');
    await page.locator('#newProjectForm button[type=submit]').click();
    await page.locator('#createModal').waitFor({state: 'hidden', timeout: 15000});
    await page.getByText(name, {exact: true}).first().waitFor({timeout: 15000});
    const state = await page.evaluate(async () => {
      const projects = (await (await fetch('/api/bootstrap')).json()).projects;
      const target = projects.find(p => p.name===document.querySelector('#projectSide .project-item.active strong').textContent);
      return {platform: target.platform, id: target.id};
    });
    assert.equal(state.platform, 'Web app');
    const detail = await (await page.request.get(ORIGIN + '/api/projects/' + state.id + '/state')).json();
    assert.equal(detail.tasks.length, 12);
    assert.equal(detail.project.platform, 'Web app');
    assert.equal(detail.handoff.project_id,state.id);
    assert.equal(detail.handoff.roles.length,12);
    assert.equal(detail.handoff.roles[0].input_status,'project_idea');
    assert.ok(detail.handoff.roles.every(r=>r.output.status==='blocked'&&r.consumption_status==='NOT_RECORDED'));
    assert.equal(detail.handoff.production_release_authorized,false);
    assert.notEqual(state.id,initialId);
    await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',state.id);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.status)),detail.tasks.map(t=>t.status));
    // Hold a real state response in the page, not a Playwright Route.
    // This also observes JSON consumption, rather than merely network arrival.
    await page.evaluate(pid=>{
      const original=window.fetch;
      const gate={held:false,released:false,consumed:false,failed:false};
      let release;
      const pending=new Promise(resolve=>{release=resolve});
      gate.release=()=>{gate.released=true;release()};
      window.__studioTestGate=gate;
      window.fetch=async function(input,...args){
        const response=await original.call(this,input,...args);
        const path=new URL(typeof input==='string'?input:input.url,location.href).pathname;
        if(path!=='/api/projects/'+pid+'/state'||gate.held)return response;
        const originalJson=response.json.bind(response);
        response.json=async()=>{
          const data=await originalJson();
          gate.held=true;
          await pending;
          // The next browser task runs after the application's await continuation.
          setTimeout(()=>{gate.consumed=true},0);
          return data;
        };
        return response;
      };
      gate.restore=()=>{gate.release();window.fetch=original};
    },state.id);
    try{
      await page.waitForFunction(()=>window.__studioTestGate.held,null,{timeout:10000});
      await page.locator('#projectSide [data-pid="'+initialId+'"]').click();
      await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',initialId,{timeout:10000});
      // Record any transient repaint too, not only the final polling state.
      await page.evaluate(()=>{
        const holder=document.querySelector('#studioLine'),gate=window.__studioTestGate;
        gate.observed=[];
        gate.observer=new MutationObserver(()=>gate.observed.push(holder.dataset.projectId||null));
        gate.observer.observe(holder,{attributes:true,attributeFilter:['data-project-id']});
        gate.release();
      });
      await page.waitForFunction(()=>window.__studioTestGate.consumed,null,{timeout:10000});
      const isolation=await page.evaluate(()=>{
        const gate=window.__studioTestGate,holder=document.querySelector('#studioLine');
        gate.observer.disconnect();
        return {project:holder.dataset.projectId,ready:holder.dataset.ready,observed:gate.observed,
          roles:holder.querySelectorAll('[data-role-id]').length,agents:holder.querySelectorAll('.line-lane').length};
      });
      assert.equal(isolation.project,initialId);
      assert.equal(isolation.ready,'true');
      assert.ok(isolation.observed.every(pid=>pid===initialId),'Obsolete response repainted the selected project');
      assert.equal(isolation.roles,12);
      assert.equal(isolation.agents,24);
      assert.equal(await page.locator('#roleWorkspace').getAttribute('data-project-id'),initialId);
    }finally{
      await page.evaluate(()=>{const gate=window.__studioTestGate;gate.observer?.disconnect();gate.restore();delete window.__studioTestGate});
    }
    await page.locator('#projectSide [data-pid="'+state.id+'"]').click();
    await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',state.id,{timeout:10000});
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.status)),detail.tasks.map(t=>t.status));
    assert.equal(await page.locator('#roleWorkspace').getAttribute('data-project-id'),state.id);
    assert.equal(await page.locator('#roleWorkspace .role-handoff').getAttribute('data-output-status'),'blocked');
    assert.match(await page.locator('#roleWorkspace .role-handoff').textContent(),/NOT_RECORDED/);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.locator('#roleWorkspace .role-workspace-grid').first().evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),1);
    assert.equal(await page.locator('#studioLine .line-row').first().evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),1);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(errors, [], 'Unexpected browser JavaScript errors: ' + errors.join('; '));
  } finally {
    await browser.close();
  }
});

test('API rejects cross-origin and unsafe project creation', async () => {
  const browser = await chromium.launch({headless: true, args: ['--disable-gpu', '--no-sandbox']});
  const page = await browser.newPage();
  try {
    const csrf=await login(page);
    const bootstrap = await page.request.get(ORIGIN + '/api/bootstrap');
    assert.equal(bootstrap.status(), 200);
    const data = await bootstrap.json();
    assert.equal(data.version, '0.6.0-web-first');
    assert.equal(data.agents.length, 24);
    const forbidden = await page.request.post(ORIGIN + '/api/projects', {
      headers: {'Content-Type':'application/json', 'X-ORBIT-UI':'1', 'Origin':'https://attacker.invalid'},
      data: {name:'Bad', idea:'Must not create this project'}
    });
    assert.equal(forbidden.status(), 403);
    const invalid = await page.request.post(ORIGIN + '/api/projects', {
      headers: headers(csrf),
      data: {name:'A', idea:'short'}
    });
    assert.equal(invalid.status(), 400);
  } finally {
    await browser.close();
  }
});

test('Quality dashboard shows unverified state for a real demo coding job', async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();
  const csrf=await login(page);
  await page.goto(ORIGIN+'/');
  await page.locator('#projectSide .project-item').first().waitFor();
  const b=await (await page.request.get(ORIGIN+'/api/bootstrap')).json();
  const pid=b.projects[0].id;
  const res=await page.request.post(ORIGIN+'/api/coding/start',{headers:headers(csrf),data:{project_id:pid,spec:'Quality dashboard browser test for a demo web feature'}});
  assert.equal(res.status(),202);
  const {job_id}=await res.json();
  await page.evaluate(id=>localStorage.setItem('orbit-project',id),pid);
  await page.reload();
  await page.locator('[data-job="'+job_id+'"]').click({timeout:20000});
  await page.waitForFunction(()=>document.querySelector('#codingQuality').textContent.includes('NOT VERIFIED'),null,{timeout:20000});
  const q=await (await page.request.get(ORIGIN+'/api/coding/'+job_id+'/quality')).json();
  assert.equal(q.selection_ready,false);
  assert.equal(q.production_approved,false);
  assert.match(await page.locator('#codingQuality').textContent(),/CHƯA NGHIỆM THU/);
 }finally{await browser.close()}
});

test('Studio handoff shows actual queued demo source and durable downstream receipt',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:850}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const csrf=await login(page);
  const created=await page.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Handoff E2E '+Date.now(),idea:'Verify real queued demo handoff and durable source binding',platform:'Web app'}});
  assert.equal(created.status(),201);
  const pid=(await created.json()).project_id;
  await page.goto(ORIGIN+'/');
  await page.locator('#projectSide [data-pid="'+pid+'"]').click();
  await page.waitForFunction(id=>document.querySelector('#studioLine').dataset.projectId===id&&document.querySelector('#studioLine').dataset.ready==='true',pid,{timeout:15000});
  const path=ORIGIN+'/api/projects/'+pid;
  async function step(stage){
   const started=await page.request.post(path+'/run',{headers:headers(csrf),data:{mode:'next'}});
   assert.ok([200,202].includes(started.status()),await started.text());
   const deadline=Date.now()+20000;
   while(Date.now()<deadline){
    const response=await page.request.get(path+'/state');
    assert.equal(response.status(),200);
    const data=await response.json();
    if(!data.running&&data.tasks.find(t=>t.stage_id===stage).status==='done')return data;
    await new Promise(resolve=>setTimeout(resolve,150));
   }
   assert.fail('Stage did not complete: '+stage);
  }
  const first=await step('po');
  const source=first.handoff.roles[0].output;
  assert.equal(source.status,'reviewed_output');
  assert.match(source.content_digest,/^[a-f0-9]{64}$/);
  const second=await step('research');
  const target=second.handoff.roles[1];
  assert.equal(target.input_status,'reviewed_sources_available');
  assert.equal(target.output.status,'reviewed_output');
  assert.equal(target.consumption_status,'DEMO_DRAFTS');
  assert.equal(target.receipt.mode,'demo');
  assert.deepEqual(target.receipt.lanes,['A','B']);
  assert.deepEqual(target.receipt.sources,[source]);
  assert.match(target.receipt.context_digest,/^[a-f0-9]{64}$/);
  assert.equal(second.handoff.production_release_authorized,false);
  await page.locator('[data-role-id="research"] .line-select').click();
  await page.locator('#roleWorkspace .role-handoff[data-consumption-status="DEMO_DRAFTS"][data-output-status="reviewed_output"]').waitFor({timeout:15000});
  const panel=page.locator('#roleWorkspace .role-handoff');
  assert.match(await panel.textContent(),new RegExp(source.content_digest));
  assert.match(await panel.textContent(),new RegExp(target.receipt.context_digest));
  await panel.locator('[data-focus-key="handoff-'+source.artifact_id+'"]').click();
  await page.locator('#artifactModal:not(.hidden)').waitFor();
  assert.match(await page.locator('#artifactBody').textContent(),/DEMO/);
  await page.locator('#artifactModal').getByRole('button',{name:'Đóng',exact:true}).click();
  await page.locator('#artifactModal').waitFor({state:'hidden'});
  await page.reload();
  await page.locator('#studioLine[data-ready="true"]').waitFor({timeout:15000});
  await page.locator('[data-role-id="research"] .line-select').click();
  await page.locator('#roleWorkspace .role-handoff[data-consumption-status="DEMO_DRAFTS"]').waitFor({timeout:15000});
  assert.match(await page.locator('#roleWorkspace .role-handoff').textContent(),new RegExp(target.receipt.context_digest));
  assert.deepEqual(errors,[]);
 }finally{await browser.close()}
});
