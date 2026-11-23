/** Real Chromium browser E2E for the ORBIT Web-first MVP. No AI-generated code executed. */
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const ORIGIN = 'http://127.0.0.1:8787';

test('Web-first UI boots, project form excludes Mobile and creates a Web project', async () => {
  const browser = await chromium.launch({headless: true, args: ['--disable-gpu', '--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1365, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    const response = await page.goto(ORIGIN + '/', {waitUntil: 'domcontentloaded'});
    assert.equal(response.status(), 200);
    await page.locator('#projectSide .project-item').first().waitFor({timeout: 15000});
    assert.equal(await page.locator('#agentMembers .agent-card').count(), 2);
    assert.equal(await page.locator('#pipelineTrack').isVisible(), true);
    await page.locator('#newProjectBtn').click();
    await page.locator('#createModal:not(.hidden)').waitFor();
    const options = await page.locator('#newProjectForm select[name=platform] option').allTextContents();
    assert.deepEqual(options, ['Web app', 'SaaS + API']);
    const name = 'Web E2E ' + Date.now();
    await page.locator('#newProjectForm input[name=name]').fill(name);
    await page.locator('#newProjectForm textarea[name=idea]').fill('Test web application end to end with real Chromium and backend persistence');
    await page.locator('#newProjectForm button[type=submit]').click();
    await page.locator('#createModal.hidden').waitFor({timeout: 15000});
    await page.getByText(name, {exact: true}).first().waitFor({timeout: 15000});
    const state = await page.evaluate(async () => {
      const projects = (await (await fetch('/api/bootstrap')).json()).projects;
      const target = projects.find(p => p.name.startsWith('Web E2E '));
      return {platform: target.platform, id: target.id};
    });
    assert.equal(state.platform, 'Web app');
    const detail = await (await page.request.get(ORIGIN + '/api/projects/' + state.id + '/state')).json();
    assert.equal(detail.tasks.length, 12);
    assert.equal(detail.project.platform, 'Web app');
    assert.deepEqual(errors, [], 'Unexpected browser JavaScript errors: ' + errors.join('; '));
  } finally {
    await browser.close();
  }
});

test('API rejects cross-origin and unsafe project creation', async () => {
  const browser = await chromium.launch({headless: true, args: ['--disable-gpu', '--no-sandbox']});
  const page = await browser.newPage();
  try {
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
      headers: {'Content-Type':'application/json', 'X-ORBIT-UI':'1'},
      data: {name:'A', idea:'short'}
    });
    assert.equal(invalid.status(), 400);
  } finally {
    await browser.close();
  }
});
