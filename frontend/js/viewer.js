// 本地绘制部件空间示意；真实全景采用等距柱状纹理投影，不伪装成实物 CAD。
import {$,escapeHTML as e} from './utils.js';
const parts=[{id:'body',name:'阀体结构',color:'#b8c4d7',description:'阀体和阀盖组成承压结构。当前几何为功能示意，尺寸和位置不是实物测绘。'},
{id:'seal',name:'密封系统',color:'#5387f6',description:'对应真实资料中的 O 型圈与密封垫。示意环帮助定位密封功能，不代表真实装配尺寸。'},
{id:'spring',name:'弹簧机构',color:'#40c4ad',description:'对应密封弹簧。寿命分析需要结合载荷、启闭次数、松弛与疲劳数据。'},
{id:'electric',name:'电气与驱动',color:'#a68ce8',description:'对应线圈、铁芯与电容等。真实接线和内部布局需由供应商模型或图纸补充。'},
{id:'battery',name:'电池供能',color:'#e7b36a',description:'对应供应商资料中的碱性电池。容量与工作电流数据尚需补充。'}];
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
export function createViewer(bridge){
  const holder=$('viewer'),canvas=$('product-canvas'),ctx=canvas.getContext('2d'),pano=$('panorama-canvas');
  let yaw=Math.PI/6,pitch=-.18,zoom=1,explode=0,selected='body',drag=null,auto=false,frame=0,mode='model',assetList=[],polygons=[],result=null;
  let gl=null,program=null,texture=null,panoImage=null;
  function dimensions(){const r=holder.getBoundingClientRect();return {w:Math.max(300,r.width),h:Math.max(330,r.height)};}
  function sizeCanvas(c){const {w,h}=dimensions();const dpr=Math.min(devicePixelRatio||1,2);c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);return {w,h,dpr};}
  function project(p,w,h){
    const x=p[0]*Math.cos(yaw)+p[2]*Math.sin(yaw),z=-p[0]*Math.sin(yaw)+p[2]*Math.cos(yaw);
    const y=p[1]*Math.cos(pitch)-z*Math.sin(pitch),zz=p[1]*Math.sin(pitch)+z*Math.cos(pitch);
    const scale=Math.min(w/7,h/5)*zoom*6/(6-zz);
    return [w/2+x*scale,h*.54-y*scale,zz];
  }
  function boxMesh(id,c,s,color){
    const pts=[];for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1])pts.push([c[0]+x*s[0]/2,c[1]+y*s[1]/2,c[2]+z*s[2]/2]);
    return [[0,1,3,2],[4,6,7,5],[0,4,5,1],[2,3,7,6],[0,2,6,4],[1,5,7,3]].map((f,i)=>({id,points:f.map(j=>pts[j]),color,shade:.72+i*.035}));
  }
  function cylinder(id,c,r,len,color,axis='x',n=28){
    const faces=[],rings=[];
    for(const side of [-1,1]){const ring=[];for(let i=0;i<n;i++){const a=i/n*Math.PI*2;ring.push(axis==='x'?[c[0]+side*len/2,c[1]+r*Math.cos(a),c[2]+r*Math.sin(a)]:[c[0]+r*Math.cos(a),c[1]+side*len/2,c[2]+r*Math.sin(a)]);}rings.push(ring);}
    faces.push({id,points:rings[0],color,shade:.72},{id,points:rings[1],color,shade:.94});
    for(let i=0;i<n;i++)faces.push({id,points:[rings[0][i],rings[1][i],rings[1][(i+1)%n],rings[0][(i+1)%n]],color,shade:.64+.32*(Math.cos(i/n*Math.PI*2)+1)/2});
    return faces;
  }
  function shade(hex,f){return '#'+hex.slice(1).match(/../g).map(h=>Math.round(parseInt(h,16)*f).toString(16).padStart(2,'0')).join('');}
  function drawModel(){
    if(mode!=='model'||!holder.clientWidth)return;
    const {w,h,dpr}=sizeCanvas(canvas);ctx.setTransform(dpr,0,0,dpr,0,0);
    const gradient=ctx.createRadialGradient(w*.5,h*.45,10,w*.5,h*.4,w*.8);gradient.addColorStop(0,'#243449');gradient.addColorStop(1,'#111d2d');ctx.fillStyle=gradient;ctx.fillRect(0,0,w,h);
    ctx.strokeStyle='#52637924';ctx.lineWidth=1;for(let i=-7;i<8;i++){ctx.beginPath();ctx.moveTo(w/2+i*70,h*.68);ctx.lineTo(w/2+i*130,h);ctx.stroke();}for(let y=h*.68;y<h;y+=30){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
    const mesh=[...cylinder('body',[0,-.4,0],.48,3,'#b8c4d7'),...cylinder('body',[-1.65,-.4,0],.65,.22,'#b8c4d7'),...cylinder('body',[1.65,-.4,0],.65,.22,'#b8c4d7'),...cylinder('body',[0,.12,0],.55,.6,'#b8c4d7','y'),...cylinder('seal',[-1.12-explode*.25,-.4,0],.51,.12,'#5387f6'),...cylinder('seal',[1.12+explode*.25,-.4,0],.51,.12,'#5387f6'),...boxMesh('electric',[0,1+explode*.8,0],[1.2,.65,.9],'#a68ce8'),...boxMesh('battery',[1.05+explode*.6,1+explode*.8,0],[.45,.75,.6],'#e7b36a')];
    for(let i=0;i<8;i++)mesh.push(...cylinder('spring',[0,.45+i*.05+explode*.38,0],.24,.028,'#40c4ad','y',18));
    const projected=mesh.map(face=>({...face,p:face.points.map(p=>project(p,w,h))})).sort((a,b)=>a.p.reduce((s,p)=>s+p[2],0)/a.p.length-b.p.reduce((s,p)=>s+p[2],0)/b.p.length);
    polygons=[];
    for(const face of projected){const path=new Path2D();face.p.forEach((p,i)=>i?path.lineTo(p[0],p[1]):path.moveTo(p[0],p[1]));path.closePath();ctx.fillStyle=shade(face.color,face.shade);ctx.fill(path);ctx.strokeStyle=face.id===selected?'#ffffff80':'#13233828';ctx.lineWidth=face.id===selected?.8:.5;ctx.stroke(path);polygons.push({path,id:face.id});}
    ctx.fillStyle='#d6e1f0';ctx.font='12px sans-serif';ctx.fillText('X',w-44,h-33);ctx.fillText('Y',w-66,h-69);ctx.fillText('Z',w-88,h-31);
  }
  function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error('浏览器无法编译全景渲染程序');return s;}
  function initGL(){
    gl=pano.getContext('webgl',{preserveDrawingBuffer:true});if(!gl)throw new Error('浏览器未启用 WebGL，请使用支持 WebGL 的浏览器查看全景。');
    program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec2 p; varying vec2 uv; void main(){uv=p;gl_Position=vec4(p,0.0,1.0);}'));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`precision mediump float; varying vec2 uv; uniform sampler2D tex; uniform float yaw; uniform float pitch; uniform float aspect; uniform float fov;
      void main(){vec3 r=normalize(vec3(uv.x*aspect*fov,uv.y*fov,-1.0));float y=r.y*cos(pitch)-r.z*sin(pitch);float z=r.y*sin(pitch)+r.z*cos(pitch);float x=r.x*cos(yaw)+z*sin(yaw);z=-r.x*sin(yaw)+z*cos(yaw);vec2 t=vec2(fract(atan(x,-z)/6.2831853+0.5),0.5-asin(clamp(y,-1.0,1.0))/3.14159265);gl_FragColor=texture2D(tex,t);}`));
    gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('全景渲染初始化失败');gl.useProgram(program);
    const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
    const loc=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
    texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
  }
  function drawPano(){if(mode!=='panorama'||!gl||!panoImage)return;const {w,h}=sizeCanvas(pano);gl.viewport(0,0,pano.width,pano.height);gl.useProgram(program);for(const [k,v] of Object.entries({yaw,pitch,aspect:w/h,fov:.75/zoom}))gl.uniform1f(gl.getUniformLocation(program,k),v);gl.drawArrays(gl.TRIANGLES,0,6);}
  function draw(){mode==='model'?drawModel():drawPano();}
  function select(id){selected=id;const p=parts.find(p=>p.id===id);$('visual-part-name').textContent=p.name;$('visual-part-description').textContent=p.description;
    $('visual-parts').innerHTML=parts.map(p=>`<button class="part-choice ${p.id===id?'selected':''}" data-part="${p.id}"><i style="background:${p.color}"></i><span>${e(p.name)}</span>${result?`<small>期末指数 ${result.baseline.at(-1).systems[p.id]?.toFixed(1)??'—'}</small>`:''}</button>`).join('');draw();}
  $('visual-parts').onclick=ev=>{const b=ev.target.closest('[data-part]');if(b)select(b.dataset.part);};
  $('visual-open-part').onclick=()=>{const n=bridge.state.catalog.nodes.find(n=>n.group===selected);if(n){bridge.selectNode(n.id);location.hash='structure';}};
  function syncAngle(){$('view-angle').value=((yaw*180/Math.PI)%360+360)%360;}
  holder.onpointerdown=ev=>{if(mode==='photo')return;drag={x:ev.clientX,y:ev.clientY,moved:false};holder.setPointerCapture(ev.pointerId);};
  holder.onpointermove=ev=>{if(!drag)return;const dx=ev.clientX-drag.x,dy=ev.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>2)drag.moved=true;yaw+=dx*.008;pitch=clamp(pitch+dy*.006,-1.1,1.1);drag.x=ev.clientX;drag.y=ev.clientY;syncAngle();draw();};
  holder.onpointerup=ev=>{if(drag&&!drag.moved&&mode==='model'){const r=canvas.getBoundingClientRect();ctx.setTransform(1,0,0,1,0,0);for(const p of [...polygons].reverse())if(ctx.isPointInPath(p.path,ev.clientX-r.left,ev.clientY-r.top)){select(p.id);break;}}drag=null;};
  holder.onpointercancel=()=>drag=null;
  holder.addEventListener('wheel',ev=>{if(mode==='photo')return;ev.preventDefault();zoom=clamp(zoom-ev.deltaY*.001,.65,2.1);draw();},{passive:false});
  holder.onkeydown=ev=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(ev.key)){ev.preventDefault();yaw+=ev.key==='ArrowLeft'?-.12:ev.key==='ArrowRight'?.12:0;pitch=clamp(pitch+(ev.key==='ArrowUp'?-.1:ev.key==='ArrowDown'?.1:0),-1.1,1.1);syncAngle();draw();}};
  $('view-angle').oninput=ev=>{yaw=Number(ev.target.value)*Math.PI/180;draw();};$('view-explode').oninput=ev=>{explode=Number(ev.target.value)/100;draw();};
  function stop(){auto=false;cancelAnimationFrame(frame);$('view-play').textContent='自动旋转';}
  function animate(){if(!auto)return;yaw+=.004;syncAngle();draw();frame=requestAnimationFrame(animate);}
  $('view-play').onclick=()=>{if(auto)return stop();auto=true;$('view-play').textContent='暂停旋转';animate();};
  $('view-reset').onclick=()=>{yaw=Math.PI/6;pitch=-.18;zoom=1;explode=0;$('view-explode').value=0;syncAngle();draw();};
  $('view-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await holder.requestFullscreen();}catch{$('viewer-hint').textContent='此浏览器不支持全屏，请放大窗口查看。';}};
  function setMode(value){mode=value;canvas.hidden=mode!=='model';pano.hidden=mode!=='panorama';$('product-photo').hidden=mode!=='photo';$('view-explode').disabled=mode!=='model';$('view-play').disabled=mode==='photo';$('view-angle').disabled=mode==='photo';stop();}
  $('view-model').onclick=()=>{setMode('model');$('visual-asset').value='';$('visual-caption').textContent='关键系统空间示意，可拖动旋转；不是实物 CAD 模型。';$('viewer-badge').textContent='结构示意 / 非实物模型';$('viewer-hint').textContent='拖动旋转 · 滚轮缩放 · 点击系统查看说明';draw();};
  let imageVersion=0;
  $('visual-asset').onchange=async()=>{
    const doc=assetList.find(d=>d.id===$('visual-asset').value);if(!doc)return $('view-model').click();
    const version=++imageVersion,src='/api/media/'+doc.metadata.file_id;
    try{
      const img=new Image();await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error('图片读取失败'));img.src=src;});if(version!==imageVersion)return;
      if(doc.metadata.panorama){
        if(Math.abs(img.width/img.height-2)>.12)throw new Error('该图片不是约 2:1 的等距柱状全景，请以普通照片重新上传。');
        if(!gl)initGL();const max=gl.getParameter(gl.MAX_TEXTURE_SIZE);let source=img;
        if(img.width>max||img.height>max){const c=document.createElement('canvas');const factor=max/Math.max(img.width,img.height);c.width=img.width*factor;c.height=img.height*factor;c.getContext('2d').drawImage(img,0,0,c.width,c.height);source=c;}
        gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,gl.RGB,gl.UNSIGNED_BYTE,source);panoImage=img;setMode('panorama');$('viewer-hint').textContent='拖动环视 · 滚轮缩放';
      }else{setMode('photo');$('product-photo').src=src;$('viewer-hint').textContent='供应商上传原图';}
      $('visual-caption').textContent=doc.name;$('viewer-badge').textContent=doc.metadata.panorama?'真实全景图':'真实上传图片';draw();
    }catch(err){$('view-model').click();$('viewer-hint').textContent=err.message;}
  };
  new ResizeObserver(()=>draw()).observe(holder);document.addEventListener('fullscreenchange',draw);
  window.addEventListener('platform-page',ev=>{if(ev.detail==='visual')requestAnimationFrame(draw);else stop();});
  select('body');
  return {refresh(r){result=r;select(selected);},assets(docs){assetList=docs;const prior=$('visual-asset').value;$('visual-asset').innerHTML='<option value="">选择真实图片或全景</option>'+docs.map(d=>`<option value="${e(d.id)}">${e(d.name)}${d.metadata.panorama?' · 全景':''}</option>`).join('');if(docs.some(d=>d.id===prior))$('visual-asset').value=prior;}};
}
