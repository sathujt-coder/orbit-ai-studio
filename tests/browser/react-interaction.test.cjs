/** Trusted fixture only: actual browser interaction, not generated proposals. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const esbuild=require('esbuild');
test('React component renders and handles keyboard and pointer interaction offline',async()=>{
 const bundle=await esbuild.build({stdin:{contents:`
 import React,{useState} from 'react';
 import {createRoot} from 'react-dom/client';
 function App(){const [n,setN]=useState(0);return <main><h1>ORBIT</h1><button onClick={()=>setN(v=>v+1)}>Increment</button><output aria-live="polite">{n}</output></main>}
 createRoot(document.getElementById('root')).render(<App/>);
 `,loader:'tsx',resolveDir:process.cwd()},bundle:true,write:false,platform:'browser',jsx:'automatic'});
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>route.abort());
  await page.setContent('<main id="root"></main>');
  await page.addScriptTag({content:bundle.outputFiles[0].text});
  const button=page.getByRole('button',{name:'Increment'});
  await button.waitFor();
  await button.click();
  await page.waitForFunction(()=>document.querySelector('output').textContent==='1');
  await button.focus();await button.press('Enter');
  await page.waitForFunction(()=>document.querySelector('output').textContent==='2');
  assert.deepEqual(errors,[]);
 }finally{await browser.close()}
});
