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
    assert.notEqual(state.id,initialId);
    await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',state.id);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.status)),detail.tasks.map(t=>t.status));
    // Delay a real state request, switch projects while it is in flight, then
    // verify the obsolete response cannot repaint the current project's line.
    let releaseOld,notifyOld;
    const oldHeld=new Promise(resolve=>{notifyOld=resolve});
    const oldRelease=new Promise(resolve=>{releaseOld=resolve});
    const oldPath='**/api/projects/'+state.id+'/state';
    await page.route(oldPath,async route=>{notifyOld();await oldRelease;await route.continue()});
    try{
      await oldHeld;
      await page.locator('#projectSide [data-pid="'+initialId+'"]').click();
      await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',initialId);
      releaseOld();
      await page.unroute(oldPath);
      await page.locator('#projectSide [data-pid="'+state.id+'"]').click();
      await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',state.id);
    }finally{releaseOld();await page.unroute(oldPath)}
    await page.setViewportSize({width:390,height:844});
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
