/* Native WebGL 3D office — no CDN, external assets or JS packages required. */
(function(){
'use strict';
const V=(x,y,z)=>[x,y,z], sub=(a,b)=>a.map((v,i)=>v-b[i]), cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]], dot=(a,b)=>a.reduce((v,x,i)=>v+x*b[i],0), norm=a=>{let n=Math.hypot(...a)||1;return a.map(v=>v/n)};
const multiply=(a,b)=>{let o=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)o[c*4+r]+=a[k*4+r]*b[c*4+k];return o};
const perspective=(fov,asp,n,f)=>{let q=1/Math.tan(fov/2),o=new Float32Array(16);o[0]=q/asp;o[5]=q;o[10]=(f+n)/(n-f);o[11]=-1;o[14]=(2*f*n)/(n-f);return o};
const lookAt=(eye,target,up)=>{let z=norm(sub(eye,target)),x=norm(cross(up,z)),y=cross(z,x),o=new Float32Array(16);o[0]=x[0];o[1]=y[0];o[2]=z[0];o[4]=x[1];o[5]=y[1];o[6]=z[1];o[8]=x[2];o[9]=y[2];o[10]=z[2];o[12]=-dot(x,eye);o[13]=-dot(y,eye);o[14]=-dot(z,eye);o[15]=1;return o};
const model=(x,y,z,sx,sy,sz)=>new Float32Array([sx,0,0,0,0,sy,0,0,0,0,sz,0,x,y,z,1]);
const rgb=h=>{let a=h.replace('#','');if(a.length!==6)return [0.5,0.6,0.7];return [0,2,4].map(i=>parseInt(a.slice(i,i+2),16)/255)};
const dim=(c,p)=>c.map(v=>v*p);
function cubeGeometry(){let data=[];const f=[
{n:[0,0,1],v:[[-.5,-.5,.5],[.5,-.5,.5],[.5,.5,.5],[-.5,.5,.5]]},
{n:[0,0,-1],v:[[.5,-.5,-.5],[-.5,-.5,-.5],[-.5,.5,-.5],[.5,.5,-.5]]},
{n:[1,0,0],v:[[.5,-.5,.5],[.5,-.5,-.5],[.5,.5,-.5],[.5,.5,.5]]},
{n:[-1,0,0],v:[[-.5,-.5,-.5],[-.5,-.5,.5],[-.5,.5,.5],[-.5,.5,-.5]]},
{n:[0,1,0],v:[[-.5,.5,.5],[.5,.5,.5],[.5,.5,-.5],[-.5,.5,-.5]]},
{n:[0,-1,0],v:[[-.5,-.5,-.5],[.5,-.5,-.5],[.5,-.5,.5],[-.5,-.5,.5]]}];
for(const face of f)for(const i of [0,1,2,0,2,3])data.push(...face.v[i],...face.n);return data;}
function sphereGeometry(){let d=[],rows=9,cols=14;function p(a,b){let y=Math.cos(a),v=Math.sin(a);return [v*Math.cos(b),y,v*Math.sin(b)]}for(let i=0;i<rows;i++){let t=i*Math.PI/rows,t2=(i+1)*Math.PI/rows;for(let j=0;j<cols;j++){let q=j*2*Math.PI/cols,q2=(j+1)*2*Math.PI/cols;let a=p(t,q),b=p(t2,q),c=p(t2,q2),e=p(t,q2);for(let n of [a,b,c,a,c,e])d.push(...n,...n)}}return d}
function cylinderGeometry(){let d=[],count=14;for(let i=0;i<count;i++){let a=i*2*Math.PI/count,b=(i+1)*2*Math.PI/count;let p=[Math.cos(a)*.5,-.5,Math.sin(a)*.5],q=[Math.cos(b)*.5,-.5,Math.sin(b)*.5],r=[Math.cos(b)*.5,.5,Math.sin(b)*.5],s=[Math.cos(a)*.5,.5,Math.sin(a)*.5];for(let pt of [p,q,r,p,r,s]){let n=norm([pt[0],0,pt[2]]);d.push(...pt,...n)}for(let pts of [[[0,.5,0],r,s],[[0,-.5,0],p,q]])for(let pt of pts)d.push(...pt,0,pt[1]>.0?1:-1,0)}return d}
class Office3D{
 constructor(canvas,labels,onSelect){this.canvas=canvas;this.labelsRoot=labels;this.onSelect=onSelect;this.gl=canvas.getContext('webgl',{antialias:true,alpha:true,premultipliedAlpha:false});this.stages=[];this.tasks=[];this.selected='techlead';this.yaw=.53;this.pitch=.91;this.zoom=23.5;this.drag=null;this.startTime=performance.now();this.labels=[];this.ready=!!this.gl;this.fallback=!this.ready;this.ctx=this.fallback?canvas.getContext('2d'):null;if(this.ready)this.setup();this.events();this.frame()}
 setup(){let gl=this.gl,vs=`attribute vec3 aPosition; attribute vec3 aNormal; uniform mat4 uVP; uniform mat4 uModel; varying vec3 vNorm; varying vec3 vWorld; void main(){vec4 w=uModel*vec4(aPosition,1.);vWorld=w.xyz;vNorm=mat3(uModel)*aNormal;gl_Position=uVP*w;}`,fs=`precision mediump float;varying vec3 vNorm;varying vec3 vWorld;uniform vec3 uColor;uniform float uGlow;void main(){vec3 l=normalize(vec3(-.48,1.,.65));vec3 n=normalize(vNorm);float d=max(dot(n,l),0.)*.49+.47;float rim=pow(1.-max(dot(n,normalize(vec3(.2,.72,.5))),0.),2.)*.1;vec3 c=uColor*(d+rim)+uColor*uGlow*.25;float fog=clamp((length(vWorld.xz)-7.)/29.,0.,.25);c=mix(c,vec3(.057,.11,.17),fog);gl_FragColor=vec4(c,1.);}`;
 let compile=(src,type)=>{let sh=gl.createShader(type);gl.shaderSource(sh,src);gl.compileShader(sh);if(!gl.getShaderParameter(sh,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(sh));return sh};let pr=gl.createProgram();gl.attachShader(pr,compile(vs,gl.VERTEX_SHADER));gl.attachShader(pr,compile(fs,gl.FRAGMENT_SHADER));gl.linkProgram(pr);if(!gl.getProgramParameter(pr,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(pr));gl.useProgram(pr);this.pr=pr;this.locations={position:gl.getAttribLocation(pr,'aPosition'),normal:gl.getAttribLocation(pr,'aNormal'),vp:gl.getUniformLocation(pr,'uVP'),model:gl.getUniformLocation(pr,'uModel'),color:gl.getUniformLocation(pr,'uColor'),glow:gl.getUniformLocation(pr,'uGlow')};this.geoms={};for(const [name,fn] of [['box',cubeGeometry],['sphere',sphereGeometry],['cylinder',cylinderGeometry]]){let d=new Float32Array(fn());let buf=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buf);gl.bufferData(gl.ARRAY_BUFFER,d,gl.STATIC_DRAW);this.geoms[name]={buf,count:d.length/6}}gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.clearColor(.035,.074,.13,0);}
 setData(stages,tasks,selected){this.stages=stages;this.tasks=tasks;this.selected=selected;this.makeLabels()}
 setSelected(sid){this.selected=sid;this.labels.forEach(o=>o.el.classList.toggle('selected',o.stage.id===sid))}
 resetCamera(){this.yaw=.53;this.pitch=.91;this.zoom=23.5}
 position(i){let col=i%4,row=Math.floor(i/4);return {x:(col-1.5)*4.83,z:(row-1)*4.66}}
 makeLabels(){this.labelsRoot.innerHTML='';this.labels=[];this.stages.forEach((stage,i)=>{let el=document.createElement('div');el.className='room-label'+(stage.id===this.selected?' selected':'');let t=this.tasks.find(x=>x.stage_id===stage.id);let msg=t?this.labelStatus(t.status):'Chờ việc';let b=document.createElement('b'),s=document.createElement('small');b.textContent=stage.short+' · '+stage.name;s.textContent=msg;el.append(b,s);el.addEventListener('click',e=>{e.stopPropagation();this.onSelect(stage.id)});this.labelsRoot.append(el);this.labels.push({el,stage,index:i,sub:s})})}
 labelStatus(status){return ({queued:'Chờ việc',drafting:'Đang soạn',reviewing:'Review chéo',synthesizing:'Tổng hợp',done:'Hoàn thành',approved:'Đã duyệt',awaiting_approval:'Chờ phê duyệt',needs_revision:'Cần chỉnh sửa'})[status]||status}
 updateTasks(tasks){this.tasks=tasks;this.labels.forEach(l=>{let t=tasks.find(x=>x.stage_id===l.stage.id);l.sub.textContent=this.labelStatus(t?.status||'queued')})}
 events(){let c=this.canvas;c.addEventListener('pointerdown',e=>{c.setPointerCapture(e.pointerId);this.drag={x:e.clientX,y:e.clientY,yaw:this.yaw,pitch:this.pitch,moved:false}});c.addEventListener('pointermove',e=>{if(!this.drag)return;let dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;if(Math.abs(dx)+Math.abs(dy)>4)this.drag.moved=true;this.yaw=this.drag.yaw-dx*.006;this.pitch=Math.max(.3,Math.min(1.4,this.drag.pitch+dy*.004))});c.addEventListener('pointerup',e=>{if(!this.drag)return;let moved=this.drag.moved;this.drag=null;if(!moved)this.pick(e)});c.addEventListener('wheel',e=>{e.preventDefault();this.zoom=Math.max(16,Math.min(44,this.zoom+Math.sign(e.deltaY)*1.2))},{passive:false});window.addEventListener('resize',()=>this.resize())}
 pick(e){let r=this.canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let hit=null,best=100;this.stages.forEach((s,i)=>{let p=this.position(i),v=this.project([p.x,1.1,p.z]);if(!v)return;let d=Math.hypot(x-v.x,y-v.y);if(d<best){best=d;hit=s.id}});if(hit)this.onSelect(hit)}
 resize(){let r=this.canvas.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2),w=Math.max(1,Math.round(r.width*d)),h=Math.max(1,Math.round(r.height*d));if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;if(this.gl)this.gl.viewport(0,0,w,h)}this.width=r.width;this.height=r.height}
 project(p){if(!this.vp)return null;let m=this.vp,w=m[3]*p[0]+m[7]*p[1]+m[11]*p[2]+m[15];if(w<=.01)return null;let x=(m[0]*p[0]+m[4]*p[1]+m[8]*p[2]+m[12])/w;let y=(m[1]*p[0]+m[5]*p[1]+m[9]*p[2]+m[13])/w;return {x:(x+1)*this.width*.5,y:(1-y)*this.height*.5,w}}
 draw(mesh,x,y,z,sx,sy,sz,color,glow=0){let gl=this.gl,g=this.geoms[mesh],l=this.locations;gl.bindBuffer(gl.ARRAY_BUFFER,g.buf);gl.enableVertexAttribArray(l.position);gl.enableVertexAttribArray(l.normal);gl.vertexAttribPointer(l.position,3,gl.FLOAT,false,24,0);gl.vertexAttribPointer(l.normal,3,gl.FLOAT,false,24,12);gl.uniformMatrix4fv(l.model,false,model(x,y,z,sx,sy,sz));gl.uniform3fv(l.color,color);gl.uniform1f(l.glow,glow);gl.drawArrays(gl.TRIANGLES,0,g.count)}
 cube(...args){if(args[0]==='box')args.shift();this.draw('box',...args)}

 // Canvas2D projected-3D renderer: graceful fallback for headless and GPU-blocked browsers.
 renderFallback(t){
  const ctx=this.ctx;if(!ctx)return;
  const w=this.canvas.width,h=this.canvas.height,scale=w/this.width;ctx.setTransform(scale,0,0,scale,0,0);ctx.clearRect(0,0,this.width,this.height);
  let back=ctx.createRadialGradient(this.width*.48,this.height*.38,20,this.width*.5,this.height*.4,this.width*.78);back.addColorStop(0,'#1c3849');back.addColorStop(.65,'#102438');back.addColorStop(1,'#0b1829');ctx.fillStyle=back;ctx.fillRect(0,0,this.width,this.height);
  const eye=[Math.sin(this.yaw)*this.zoom*Math.cos(this.pitch),this.zoom*Math.sin(this.pitch),Math.cos(this.yaw)*this.zoom*Math.cos(this.pitch)];
  this.vp=multiply(perspective(.77,this.width/this.height,.1,130),lookAt(eye,[0,0,0],[0,1,0]));
  const commands=[];
  const faceVerts=[
   {n:[0,1,0],verts:[[-1,1,-1],[1,1,-1],[1,1,1],[-1,1,1]],shade:1.18},
   {n:[0,-1,0],verts:[[-1,-1,1],[1,-1,1],[1,-1,-1],[-1,-1,-1]],shade:.48},
   {n:[0,0,1],verts:[[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],shade:.78},
   {n:[0,0,-1],verts:[[1,-1,-1],[-1,-1,-1],[-1,1,-1],[1,1,-1]],shade:.59},
   {n:[-1,0,0],verts:[[-1,-1,-1],[-1,-1,1],[-1,1,1],[-1,1,-1]],shade:.63},
   {n:[1,0,0],verts:[[1,-1,1],[1,-1,-1],[1,1,-1],[1,1,1]],shade:.92}
  ];
  let box=(x,y,z,sx,sy,sz,col,glow=0)=>{
   if(typeof x==='string')return;
   for(const face of faceVerts){let fc=[x+face.n[0]*sx*.5,y+face.n[1]*sy*.5,z+face.n[2]*sz*.5],toEye=sub(eye,fc);if(dot(face.n,toEye)<=0)continue;
    let projected=face.verts.map(v=>this.project([x+v[0]*sx*.5,y+v[1]*sy*.5,z+v[2]*sz*.5]));if(projected.some(v=>!v))continue;
    commands.push({type:'face',pts:projected,depth:dot(toEye,toEye),col,shade:face.shade+glow*.18,stroke:glow>0?.22:0});
   }
  };
  let sphere=(x,y,z,r,col,glow=0)=>{let p=this.project([x,y,z]),o=this.project([x+r,y,z]);if(!p||!o)return;commands.push({type:'sphere',x:p.x,y:p.y,r:Math.max(1,Math.hypot(p.x-o.x,p.y-o.y)),col,glow,depth:dot(sub(eye,[x,y,z]),sub(eye,[x,y,z]))})};
  let C=box;
  C(0,-.55,0,21.5,.15,16.6,[.08,.17,.25]);
  for(let i=0;i<25;i++){let x=-10.3+i*.86;C(x,-.465,0,.017,.007,16.3,[.13,.26,.36])}
  for(let i=0;i<20;i++){let z=-7.95+i*.82;C(0,-.465,z,20.8,.007,.017,[.13,.26,.36])}
  for(let i=0;i<this.stages.length;i++){
   let s=this.stages[i],pos=this.position(i),task=this.tasks.find(k=>k.stage_id===s.id),status=task?.status||'queued',base=rgb(s.color||'#6cddcd'),selected=s.id===this.selected;
   let active=['drafting','reviewing','synthesizing'].includes(status),done=['done','approved'].includes(status),problem=['awaiting_approval','needs_revision'].includes(status),tone=problem?[.95,.60,.34]:done?[.29,.95,.75]:active?[.39,.73,1]:[.35,.53,.67],pulse=.5+.5*Math.sin(t/500+i),{x,z}=pos;
   C(x,-.32,z,4.27,.22,4.04,selected?[.16,.42,.44]:[.12,.24,.36]);
   C(x,-.18,z+1.96,4.27,.09,.085,selected?[.40,1,.81]:tone,.6);
   C(x,-.18,z-1.95,4.27,.09,.065,dim(tone,.7));C(x-2.1,-.16,z,.09,.1,3.98,dim(tone,.7));C(x+2.1,-.16,z,.09,.1,3.98,dim(tone,.7));
   C(x,.35,z-1.94,4.13,1,.11,[.16,.36,.48]);C(x,.91,z-1.94,4.23,.065,.12,dim(base,.85),.2);
   C(x-2.08,.18,z-.48,.075,.8,2.7,[.16,.30,.41]);
   C(x,1.11,z-1.75,.17,.47,.17,tone,.5);sphere(x,1.48,z-1.75,.17,tone,.7+pulse*.4);
   for(let m=0;m<2;m++){
    let px=x+(m===0?-1.02:1.02),roleColor=m===0?dim(base,.87):[.68,.55,.95],working=active&&(status!=='reviewing'||m===0);
    C(px,.19,z-.59,1.44,.11,.81,[.32,.44,.56]);C(px-.54,-.13,z-.59,.085,.64,.085,[.23,.36,.48]);C(px+.54,-.13,z-.59,.085,.64,.085,[.23,.36,.48]);
    C(px,.6,z-.91,.81,.64,.09,[.09,.18,.26]);C(px,.61,z-.85,.68,.49,.04,working?[.28,.87,.90]:[.28,.46,.61],working?.4:0);
    C(px,.30,z-.22,.6,.03,.2,[.33,.51,.62]);
    C(px,-.04,z+.66,.52,.12,.48,[.25,.39,.53]);C(px,-.30,z+.66,.09,.48,.09,[.25,.39,.53]);
    let bob=active?.04*Math.sin(t/350+i+m):0;
    C(px,.27+bob,z+.63,.50,.73,.49,roleColor,.05);sphere(px,.87+bob,z+.63,.35,m===0?[.76,.84,.92]:[.80,.73,.96]);
    sphere(px-.11,.88+bob,z+.34,.045,[.17,.39,.54],working?.5:0);sphere(px+.11,.88+bob,z+.34,.045,[.17,.39,.54],working?.5:0);
   }
   if(selected)C(x,-.11,z+2.11,2.0,.12,.09,[.50,1,.80],.7);
  }
  commands.sort((a,b)=>b.depth-a.depth);
  for(const cmd of commands){let c=cmd.col.map(v=>Math.max(0,Math.min(255,Math.round(v*(cmd.shade||1)*255))));let color=`rgb(${c.join(',')})`;
   if(cmd.type==='sphere'){
    let rr=Math.max(2,cmd.r),g=ctx.createRadialGradient(cmd.x-rr*.27,cmd.y-rr*.3,0,cmd.x,cmd.y,rr*1.3);g.addColorStop(0,'#e6f5ff');g.addColorStop(.14,color);g.addColorStop(1,'#213448');ctx.fillStyle=g;ctx.beginPath();ctx.ellipse(cmd.x,cmd.y,rr,rr*.85,0,0,Math.PI*2);ctx.fill();if(cmd.glow){ctx.strokeStyle='rgba(146,248,224,.6)';ctx.lineWidth=.8;ctx.stroke()}continue;
   }
   ctx.beginPath();cmd.pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.lineWidth=.6;ctx.strokeStyle=cmd.stroke?'rgba(153,255,230,.33)':'rgba(10,26,41,.37)';ctx.stroke();
  }
  // Labels sit above the real 3D geometry and remain clickable.
  for(const lab of this.labels){let p=this.position(lab.index),v=this.project([p.x,2.02,p.z]);if(!v){lab.el.style.display='none';continue}lab.el.style.display='block';lab.el.style.left=v.x+'px';lab.el.style.top=v.y+'px'}
 }
 render(t){this.resize();if(this.fallback){this.renderFallback(t);return}let gl=this.gl;gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);let eye=[Math.sin(this.yaw)*this.zoom*Math.cos(this.pitch),this.zoom*Math.sin(this.pitch),Math.cos(this.yaw)*this.zoom*Math.cos(this.pitch)];this.vp=multiply(perspective(.77,this.canvas.width/this.canvas.height,.1,130),lookAt(eye,[0,.0,0],[0,1,0]));gl.useProgram(this.pr);gl.uniformMatrix4fv(this.locations.vp,false,this.vp);
 this.cube('box',0,-.55,0,21.5,.15,16.6,[.075,.14,.215]);
 for(let i=0;i<24;i++){let x=-10.3+i*.9;this.cube('box',x,-.465,0,.016,.007,16.3,[.11,.23,.31])}
 for(let i=0;i<19;i++){let z=-7.95+i*.89;this.cube('box',0,-.465,z,20.8,.007,.016,[.11,.23,.31])}
 // Central corridor soft lines & architecture
 this.cube('box',0,-.34,-7.8,20.8,.055,.09,[.19,.43,.47],.25);this.cube('box',0,-.34,7.8,20.8,.055,.09,[.15,.35,.43],.1);
 for(let i=0;i<this.stages.length;i++){
 let s=this.stages[i],pos=this.position(i),task=this.tasks.find(k=>k.stage_id===s.id),status=task?.status||'queued',base=rgb(s.color||'#68ddcc'),selected=s.id===this.selected;
 let active=['drafting','reviewing','synthesizing'].includes(status),done=['done','approved'].includes(status),problem=['awaiting_approval','needs_revision'].includes(status),tone=problem?[.9,.5,.28]:done?[.24,.85,.66]:active?[.33,.73,.95]:[.33,.49,.67],p=(Math.sin(t/420+i)*.5+.5);
 let {x,z}=pos;
 this.cube('box',x,-.32,z,4.27,.22,4.04,selected?[.12,.28,.33]:[.10,.18,.28],selected?.6:0);
 // Edge strips are bright for status and selection
 this.cube('box',x,-.19,z+1.94,4.24,.065,.065,selected?[.38,.95,.76]:tone,active?.3+p*.6:0);
 this.cube('box',x,-.19,z-1.94,4.24,.065,.045,dim(tone,.75));
 this.cube('box',x-2.1,-.16,z,.07,.10,3.98,dim(tone,.7));this.cube('box',x+2.1,-.16,z,.07,.10,3.98,dim(tone,.7));
 // Back glass panel and divider: actual walls in 3D
 this.cube('box',x,.34,z-1.92,4.14,.95,.09,[.12,.26,.34]);this.cube('box',x,.87,z-1.92,4.2,.058,.12,dim(base,.86),.1);
 this.cube('box',x-2.06,.16,z-.5,.07,.8,2.65,[.12,.24,.32]);
 // Status beacon
 this.draw('cylinder',x+.02,1.13,z-1.75,.21,.5,.21,tone,active?.7+p:done?.5:.18);
 this.draw('sphere',x+.02,1.48,z-1.75,.21,.21,.21,tone,.7+p*.35);
 for(let m=0;m<2;m++){
  let px=x+(m===0?-1.03:1.03),roleColor=m===0?dim(base,.78):[.55,.49,.83],working=active&&(status!=='reviewing'||m===0);
  // desk, monitor, monitor screen, keyboard
  this.cube('box',px,.2,z-.55,1.42,.10,.74,[.27,.36,.46]);this.cube('box',px-.54,-.13,z-.55,.08,.62,.08,[.2,.31,.44]);this.cube('box',px+.54,-.13,z-.55,.08,.62,.08,[.2,.31,.44]);
  this.cube('box',px,.57,z-.87,.74,.55,.08,[.09,.16,.22]);this.cube('box',px,.59,z-.81,.64,.43,.04,working?[.20,.64,.7]:[.20,.36,.47],working?.52:0);
  this.cube('box',px,.30,z-.24,.59,.025,.19,[.31,.44,.55]);
  // two stylized people / agents
  let bob=active?Math.sin(t/290+i+m)*.035:0;
  this.cube('box',px,-.03,z+.63,.46,.12,.43,[.20,.28,.42]);this.cube('box',px,-.34,z+.63,.06,.5,.06,[.20,.31,.45]);
  this.draw('cylinder',px,.26+bob,z+.63,.43,.74,.43,roleColor,active?.25:0);
  this.draw('sphere',px,.82+bob,z+.63,.48,.48,.48,m===0?[.69,.78,.86]:[.69,.64,.83],.02);
  this.draw('sphere',px+.17,.82+bob,z+.53,.075,.075,.075,[.14,.34,.46],working?.8:0);
  this.draw('sphere',px-.17,.82+bob,z+.53,.075,.075,.075,[.14,.34,.46],working?.8:0);
  this.cube('box',px,.97+bob,z+.62,.14,.02,.15,active?[.47,.97,.81]:[.34,.55,.7],active?.65:0);
 }
 if(selected){this.cube('box',x,-.14,z+2.05,1.85,.10,.09,[.40,1,.77],.8)}
 }
 for(let lab of this.labels){let p=this.position(lab.index),v=this.project([p.x,1.95,p.z]);if(!v){lab.el.style.display='none';continue}lab.el.style.display='block';lab.el.style.left=v.x+'px';lab.el.style.top=v.y+'px';lab.el.style.opacity=v.w<5?0:1}
 }
 frame(){let tick=t=>{this.render(t);requestAnimationFrame(tick)};requestAnimationFrame(tick)}
}
window.Office3D=Office3D;
})();
