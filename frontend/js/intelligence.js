// 五模块共享同一计算快照；所有模型结果按分析编号显示，避免旧结果混入新场景。
import {$,escapeHTML as e,table} from './utils.js';
import {request} from './api.js';
import {createViewer} from './viewer.js';

const labels={quality:'质量与标准',lifetime:'寿命依据',cost:'维护费用',visual:'产品图像',report:'决策报告'};
const kinds={product_data:'产品数据',supplier_evidence:'供应商资料',buyer_requirement:'采购要求',quote:'报价',reference:'参考资料',visual:'产品图像'};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const text=value=>typeof value==='string'?value:JSON.stringify(value??'');
const safeURL=value=>{try{const u=new URL(value,location.origin);return ['http:','https:'].includes(u.protocol)?u.href:'';}catch{return '';}};

export function initIntelligence(bridge){
  let activeJob=false,currentKey='',dirty=false,modules={},documents=[];
  const {state}=bridge;
  const viewer=createViewer(bridge);
  const enabled=state.config.llm.enabled;
  $('engine-status').textContent=enabled?`${state.config.llm.model} · 密钥已配置`:'Qwen 未配置 · 基础仿真可用';
  $('check-provider').disabled=!enabled;
  $('build-index').disabled=!enabled;
  document.querySelectorAll('.ai-run').forEach(b=>{b.disabled=!enabled;b.title=enabled?'':'请在项目 .env 中配置 DASHSCOPE_API_KEY 后重启';});
  if(!enabled)document.querySelectorAll('.ai-result').forEach(el=>{el.innerHTML='<p class="field-note">Qwen 尚未配置。请复制项目 .env.example 为 .env，填写 DASHSCOPE_API_KEY 后重启服务。基础仿真和本地资料检索可继续使用。</p>';});
  let collapsed=localStorage.getItem('sidebar-collapsed')===null?matchMedia('(max-width:900px)').matches:localStorage.getItem('sidebar-collapsed')==='true';
  function setSidebar(){document.body.classList.toggle('sidebar-collapsed',collapsed);$('sidebar-toggle').setAttribute('aria-expanded',String(!collapsed));$('sidebar-toggle').setAttribute('aria-label',collapsed?'展开侧边栏':'收起侧边栏');}
  $('sidebar-toggle').onclick=()=>{collapsed=!collapsed;localStorage.setItem('sidebar-collapsed',String(collapsed));setSidebar();};setSidebar();

  function message(content,error=false){$('global-message').textContent=content;$('global-message').className='message'+(error?' error':'');}
  function jobView(job){
    $('job-panel').hidden=false;
    $('job-panel').innerHTML=`<div class="job-head"><span class="job-dot ${job.status==='failed'?'failed':''}"></span><strong>${e(job.label||'分析任务')}</strong><span>${e(job.message||job.status)}</span></div><details><summary>查看处理记录</summary><ol>${(job.events||[]).map(v=>`<li>${e(v.message)}</li>`).join('')}</ol></details>${job.error?`<p class="error-text">${e(job.error)}</p>`:''}`;
  }
  async function job(path,payload,onDone){
    if(activeJob){message('当前任务仍在运行，请等待完成。',true);return;}
    activeJob=true;
    document.querySelectorAll('.ai-run').forEach(b=>b.disabled=true);
    try{
      const started=await request(path,payload);localStorage.setItem('last-analysis-job',started.job_id);
      await poll(started.job_id,onDone);
    }catch(error){message(error.message,true);throw error;}
    finally{activeJob=false;document.querySelectorAll('.ai-run').forEach(b=>b.disabled=!enabled);}
  }
  async function poll(id,onDone){
    let failures=0;
    while(true){
      let data;
      try{data=await request('/api/jobs/'+id);failures=0;}catch(err){if(++failures>=3)throw new Error('任务进度连接中断。后台任务可能仍在运行，刷新页面可恢复查看。');await sleep(2000);continue;}
      jobView(data);
      if(data.status==='completed'){localStorage.removeItem('last-analysis-job');if(onDone)await onDone(data.result);return data.result;}
      if(['failed','interrupted'].includes(data.status)){localStorage.removeItem('last-analysis-job');throw new Error(data.error||'任务未完成');}
      await sleep(1200);
    }
  }
  function sourceButtons(ids){return (ids||[]).map(id=>`<button class="source-ref" data-source="${e(id)}">${e(id)}</button>`).join(' ');}
  function renderStage(stage,data){
    const items=data.findings||[];
    let html=`<div class="analysis-meta"><span class="tag">${e(data.model)}</span><span>${e(new Date(data.created_at).toLocaleString('zh-CN'))}</span><span>辅助分析 · 待复核</span></div><p class="analysis-summary">${e(data.summary)}</p>`;
    if(stage==='quality')html+=`<div class="quality-gate"><strong>规则核验：${e(data.rule_check?.status||'证据不足')}</strong><p>${e(data.rule_check?.note||'')}</p></div>`;
    if(data.rule_check?.checks?.length&&stage==='quality')html+=table(['检验项目','程序判断','依据'],data.rule_check.checks.map(r=>[r.project,r.status,r.reason]));
    html+=items.map(f=>`<article class="finding"><div><strong>${e(f.title||'分析要点')}</strong><span class="tag ${['不符合','证据不足','假设'].includes(f.status)?'assumed':''}">${e(f.status||'参考')}</span></div><p>${e(f.detail||'')}</p><div>${sourceButtons(f.source_ids)}</div></article>`).join('');
    if(data.model_proposals?.length)html+='<h3>候选寿命模型</h3>'+data.model_proposals.map(m=>`<article class="finding"><strong>${e(text(m.model))}</strong><p>${e(text(m.formula))}</p><p>参数：${e(text(m.parameters))}</p><p>适用条件：${e(text(m.applicability))}</p>${sourceButtons(m.source_ids)}${m.evidence_status?`<p class="field-note">${e(m.evidence_status)}</p>`:''}<p class="field-note">尚未校准，未自动应用到当前曲线。可在场景的“费用与模型假设”中手动调整可支持的参数。</p></article>`).join('');
    if(data.cost_references?.length)html+='<h3>费用参考</h3>'+data.cost_references.map(c=>`<article class="finding"><strong>${e(text(c.item))}</strong><p>${e(text(c.range))}</p><p>${e(text(c.basis))}</p>${sourceButtons(c.source_ids)}${c.evidence_status?`<p class="field-note">${e(c.evidence_status)}</p>`:''}</article>`).join('');
    if(data.recommendation)html+=`<h3>建议与理由</h3><p>${e(text(data.recommendation))}</p>`;
    if(data.web_research)html+=`<p class="field-note">联网依据：${data.web_research.verified_search?`${data.web_research.sources.length} 个检索来源${data.web_research.cached?'（24 小时内缓存）':''}`:e(data.web_research.error||'未返回可追溯来源，不能视为已取得外部证据')}</p>`;
    if(data.limitations?.length)html+=`<details class="analysis-details"><summary>数据缺口与适用限制</summary><ul>${data.limitations.map(l=>`<li>${e(text(l))}</li>`).join('')}</ul></details>`;
    html+=`<details class="analysis-details"><summary>来源与工具记录（${data.sources?.length||0} 个来源）</summary><div>${(data.sources||[]).map(s=>`<div class="source-row">${sourceButtons([s.id])}<span>${e(s.title)} · ${e(s.locator||'')}</span></div>`).join('')}</div><p class="field-note">${(data.tool_trace||[]).map(t=>e(t.tool)+' · '+e(t.status)).join('；')||'本阶段使用预设检索与分析流程'}</p></details>`;
    if(data.download)html+=`<a class="button primary report-download" href="${e(data.download)}" download>下载决策报告</a>`;
    $('ai-'+stage).innerHTML=html;
  }
  async function refreshSnapshot(){
    if(!currentKey)return;
    const requested=currentKey;const data=await request('/api/analyses/'+requested);
    if(requested!==currentKey)return;
    modules=data.modules||{};
    for(const stage of Object.keys(labels)){
      if(modules[stage])renderStage(stage,modules[stage]);
      else $('ai-'+stage).innerHTML=`<p class="field-note">${enabled?'当前场景尚未运行此项分析。':'Qwen 未配置。请填写服务端 .env 并重启后运行分析。'}</p>`;
    }
  }
  window.addEventListener('platform-result',event=>{
    currentKey=event.detail.analysis_key;dirty=!$('dirty-note').hidden;
    document.querySelectorAll('.ai-panel').forEach(el=>el.classList.remove('stale'));
    refreshSnapshot().catch(err=>message(err.message,true));viewer.refresh(state.result);
  });
  window.addEventListener('platform-dirty',()=>{dirty=true;document.querySelectorAll('.ai-panel').forEach(el=>el.classList.add('stale'));});
  document.querySelectorAll('.ai-run').forEach(button=>button.onclick=async()=>{
    if(dirty||!state.result){message('请先运行当前部署场景，再启动智能分析。',true);location.hash='overview';return;}
    const sentKey=currentKey;
    try{await job('/api/analysis/run',{stage:button.dataset.stage,settings:state.result.settings},async result=>{
      if(result.analysis_key===currentKey&&sentKey===currentKey&&!dirty){modules=result.modules;await refreshSnapshot();message(result.partial?'报告已生成，部分前置分析未完成，请查看报告限制。':'分析完成，结果与来源已更新。');}
      else message('分析已保存；当前场景已变化，请针对新场景重新分析。');
    });}catch{}
  });
  $('check-provider').onclick=async()=>{try{await job('/api/provider/check',{},result=>message(`Qwen 连接成功：${result.model}`));}catch{}};
  $('upload').onclick=()=>{refreshDocuments();$('upload-dialog').showModal();};
  $('visual-upload').onclick=()=>{$('document-kind').value='visual';updateKind();refreshDocuments();$('upload-dialog').showModal();};
  $('close-dialog').onclick=()=>$('upload-dialog').close();
  $('close-source').onclick=()=>$('source-dialog').close();
  function updateKind(){const kind=$('document-kind').value;$('confirmed-wrap').hidden=kind!=='buyer_requirement';$('panorama-wrap').hidden=kind!=='visual';}
  $('document-kind').onchange=updateKind;
  async function refreshDocuments(){
    const data=await request('/api/documents');documents=data.documents;
    const total=documents.reduce((n,d)=>n+d.chunk_count,0),vectors=documents.reduce((n,d)=>n+d.vector_count,0);
    $('knowledge-stats').textContent=`${documents.length} 份资料 · ${total} 个文本片段 · ${vectors} 个语义向量就绪`;
    $('document-list').innerHTML=`<table><thead><tr><th>资料名称</th><th>类别</th><th>索引</th><th>查看</th></tr></thead><tbody>${documents.map(d=>`<tr><td>${e(d.name)}${d.confirmed?' <span class="tag">要求已确认</span>':''}</td><td>${e(kinds[d.kind]||d.kind)}</td><td>${d.vector_count}/${d.chunk_count}</td><td><button class="text-button" data-document="${e(d.id)}">正文</button></td></tr>`).join('')}</tbody></table>`;
    viewer.assets(documents.filter(d=>d.kind==='visual'));
  }
  $('upload-form').onsubmit=async event=>{
    event.preventDefault();const file=$('document-file').files[0];if(!file)return;
    if(file.size>24*1024*1024){$('import-status').textContent='文件超过 24 MB，请分拆上传。';return;}
    const kind=$('document-kind').value;
    $('submit-upload').disabled=true;$('import-status').textContent='正在上传与解析…';
    try{
      const base64=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});
      await job('/api/supplier-data/import',{name:file.name,content_base64:base64,kind,confirmed:kind==='buyer_requirement'&&$('document-confirmed').checked,panorama:kind==='visual'&&$('document-panorama').checked},async data=>{
        $('import-status').textContent=data.status;await refreshDocuments();await bridge.runSimulation();
      });
    }catch(err){$('import-status').textContent=err.message;}
    finally{$('submit-upload').disabled=false;}
  };
  $('build-index').onclick=async()=>{try{await job('/api/knowledge/index',{},async result=>{await refreshDocuments();$('import-status').textContent=`语义索引完成，本次处理 ${result.indexed} 个片段。`;});}catch(err){$('import-status').textContent=err.message;}};
  $('knowledge-search-form').onsubmit=async event=>{
    event.preventDefault();
    try{await job('/api/knowledge/search',{query:$('knowledge-query').value},data=>{
      $('knowledge-results').innerHTML=`<p class="field-note">检索方式：${e(data.mode)} ${e(data.warnings.join('；'))}</p>`+(data.hits.length?data.hits.map(h=>`<article class="finding"><button class="text-button" data-document="${e(h.doc_id)}">${e(h.name)} · ${e(h.locator)}</button><p>${e(h.text)}</p></article>`).join(''):'<p>未找到匹配资料，请修改问题或补充文档。</p>');
    });}catch(err){$('knowledge-results').textContent=err.message;}
  };
  async function openDocument(id){
    const doc=await request('/api/documents/'+encodeURIComponent(id));$('source-title').textContent=doc.name;
    $('source-content').innerHTML=doc.sections.map(s=>`<h3>${e(s.locator)}</h3><pre>${e(s.text)}</pre>`).join('');
    $('source-dialog').showModal();
  }
  document.addEventListener('click',async event=>{
    const doc=event.target.closest('[data-document]');if(doc){try{await openDocument(doc.dataset.document);}catch(err){message(err.message,true);}return;}
    const btn=event.target.closest('[data-source]');if(!btn)return;
    const source=Object.values(modules).flatMap(m=>m.sources||[]).find(s=>s.id===btn.dataset.source);
    if(!source)return;
    $('source-title').textContent=source.title;
    const url=safeURL(source.url||'');
    $('source-content').innerHTML=`<p>${e(source.locator||'')}</p>${source.excerpt?`<pre>${e(source.excerpt)}</pre>`:''}${source.url&&url?`<p><a href="${e(url)}" target="_blank" rel="noopener noreferrer">打开原始来源</a></p>`:''}${source.doc_id?`<button class="text-button" data-document="${e(source.doc_id)}">查看资料正文</button>`:''}<p class="field-note">来源存在表示可追溯；适用性及检测真实性仍需核对。</p>`;
    $('source-dialog').showModal();
  });
  refreshDocuments().catch(err=>message(err.message,true));
  const last=localStorage.getItem('last-analysis-job');
  if(last){activeJob=true;poll(last,async()=>{await refreshDocuments();await refreshSnapshot();}).catch(err=>message(err.message,true)).finally(()=>activeJob=false);}
}
