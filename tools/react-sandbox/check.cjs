'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const esbuild = require('esbuild');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const path = '/work/Component.tsx';
assert.ok(fs.statSync(path).size <= 18000);
const result = esbuild.buildSync({
  entryPoints:[path], bundle:true, write:false, platform:'node', format:'cjs',
  jsx:'automatic', nodePaths:['/opt/orbit/node_modules'],
  external:['react','react-dom','react/jsx-runtime'],
  logLevel:'silent', outfile:'/tmp/component.cjs'
});
fs.writeFileSync('/tmp/component.cjs',result.outputFiles[0].contents);
const Module = require('node:module');
const compiled = new Module('/tmp/component.cjs',module);
compiled.filename='/tmp/component.cjs';
compiled.paths=['/opt/orbit/node_modules'];
compiled._compile(fs.readFileSync('/tmp/component.cjs','utf8'),compiled.filename);
assert.equal(typeof compiled.exports.default,'function');
const html=renderToStaticMarkup(React.createElement(compiled.exports.default,{name:'ORBIT'}));
assert.match(html,/<h1>Welcome ORBIT<\/h1>/);
console.log('React component bundle and render: PASS');
