import {initIntelligence} from './intelligence.js';
import {api} from './api.js';
import {$,escapeHTML as e,money,number,yearText,statusOf,table} from './utils.js';
import {lineChart,stackedCosts,COST_CATEGORIES} from './charts.js';
import {createTree,renderNode} from './tree.js';

const state={catalog:null,config:null,result:null,month:0,mode:'baseline',policy:'preventive',timer:null,tree:null,comparisons:[],running:false,revision:0};
const pages={structure:['产品信息','产品信息','查看产品结构、关键部件及质量资料。'],overview:['产品生命周期仿真','产品生命周期仿真','基于部署场景，查看性能变化、风险预警和维护节点。'],cost:['成本分析','成本分析','以统一费用口径比较维护策略与部署场景。'],visual:['产品可视化','产品可视化','通过结构示意和真实图像，直观理解目标产品。'],evidence:['决策报告','决策报告','汇总质量、寿命、成本和图像分析，形成有依据的选择建议。']};
function setMessage(text='',error=false){$('global-message').textContent=text;$('global-message').className=`message${error?' error':''}`;}
function changePage(page){
  if(!pages[page]) page='structure';
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${page}`));
  document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});
  [$('page-label').textContent,$('page-title').textContent,$('page-description').textContent]=pages[page];
  stopPlayback();
  window.dispatchEvent(new CustomEvent('platform-page',{detail:page}));
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{location.hash=b.dataset.page;});
window.addEventListener('hashchange',()=>changePage(location.hash.slice(1)));
changePage(location.hash.slice(1));

function inputField(name,label,value,min,max,step=1){return `<label>${label}<input name="${name}" type="number" value="${value}" min="${min}" max="${max}" step="${step}" required></label>`;}
function renderInputs(){
  const {config,catalog}=state;
  $('product-select').innerHTML=`<option value="${e(catalog.product.id)}">鑫豪斯 · ${e(catalog.product.model)}</option>`;
  const costFields=[['purchase','采购单价（元 / 台）'],['installation','安装费（元 / 台）'],['inspection','巡检费（元 / 台 / 次）'],['labor','更换人工（元 / 系统 / 台）'],['downtime','失效停用处置（元 / 次 / 台）']];
  $('assumptions-fields').innerHTML='<p class="field-note" style="margin-top:14px">以下费用与衰减率均不是供应商报价或标定值，可根据后续资料替换。</p>'+costFields.map(([key,label])=>inputField(key,label,config.defaults[key],0,1000000,.01)).join('')+inputField('inspection_interval','巡检间隔（年）',1,1,10)+`<h3>系统参数 · 假设</h3>`+config.groups.map(g=>`<h3>${e(g.name)}</h3><div class="form-grid">${inputField(`rate_${g.id}`,'年衰减率',g.base_rate,0,.5,.001)}${inputField(`replace_${g.id}`,'更换包（元 / 台）',g.replacement,0,1000000,.01)}</div>`).join('');
  $('location').onchange=()=>{
    const preset=config.presets.find(p=>p.name===$('location').value);
    $('custom-location-wrap').hidden=preset.name!=='自定义';
    $('custom-location').required=preset.name==='自定义';
    const form=$('scenario-form');
    form.elements.temperature.value=preset.temperature;form.elements.humidity.value=preset.humidity;
    markDirty();
  };
}
function markDirty(){state.revision++;if(state.result)$('dirty-note').hidden=false;window.dispatchEvent(new Event('platform-dirty'));}
$('scenario-form').addEventListener('input',markDirty);
$('scenario-form').addEventListener('change',markDirty);
// 浏览器发现折叠区域中存在非法输入时，先展开，方便用户定位。
$('scenario-form').addEventListener('invalid',event=>{const details=event.target.closest('details');if(details)details.open=true;},true);

function getSettings(){
  const data=new FormData($('scenario-form'));
  const settings={rates:{},replacements:{}};
  const strings=['product_id','project_name','location','exposure'];
  for(const [key,value] of data){
    if(key.startsWith('rate_')) settings.rates[key.slice(5)]=Number(value);
    else if(key.startsWith('replace_')) settings.replacements[key.slice(8)]=Number(value);
    else settings[key]=strings.includes(key)?value:Number(value);
  }
  if(settings.location==='自定义')settings.location=$('custom-location').value.trim();
  return settings;
}
async function runSimulation(event){
  event?.preventDefault();
  if(state.running || !$('scenario-form').reportValidity())return;
  const settings=getSettings();
  const submittedRevision=state.revision;
  if(settings.warning<=settings.failure){setMessage('预警线必须高于失效阈值。请调整后重新运行。',true);return;}
  stopPlayback();state.running=true;$('run').disabled=true;$('run').textContent='正在计算…';setMessage('正在计算月度衰减、维护事件与费用…');
  try{
    state.result=await api.simulate(settings);
    state.month=Math.min(state.month,settings.years*12);
    $('year-slider').max=settings.years*12;$('year-slider').value=state.month;
    $('dirty-note').hidden=state.revision===submittedRevision;setMessage();renderResults();
  }catch(error){setMessage(`仿真失败：${error.message}。${state.result?'仍显示上一次成功结果。':''}`,true);}
  finally{state.running=false;$('run').disabled=false;$('run').innerHTML='运行生命周期仿真 <span>→</span>';}
}
$('scenario-form').addEventListener('submit',runSimulation);

function renderCatalog(){
  const {product:p,stats:s}=state.catalog;
  $('product-strip').innerHTML=`<div class="product-symbol">▦</div><div class="product-main"><strong>${e(p.name)}</strong><small>鑫豪斯 · 产品编码 ${e(p.code)} · 批号 ${e(p.batch)}</small></div><div class="strip-data"><span>物料编码</span><strong>${s.unique_codes} 种</strong></div><div class="strip-data"><span>批次物料</span><strong>${s.unique_batch_items} 组</strong></div><div class="strip-data"><span>质检记录</span><strong>${s.inspection_count} 项</strong></div><div class="strip-data"><span>数据状态</span><strong style="color:var(--green)">真实 Excel 已读取</strong></div>`;
  state.tree=createTree(state.catalog,node=>renderNode(node,state.catalog));
}
function metric(label,value,foot,unit=''){return `<div class="metric"><div class="metric-label">${e(label)}</div><div class="metric-number">${e(value)}<small>${e(unit)}</small></div><div class="metric-foot">${e(foot)}</div></div>`;}
function currentSeries(){return state.mode==='baseline'?state.result.baseline:state.result.policies.find(p=>p.id===state.mode).series;}
function renderResults(){
  const r=state.result,s=r.settings;
  $('range-end').textContent=`${s.years} 年`;
  $('run-context').textContent=`${s.location} · ${s.temperature}℃ / ${s.humidity}% RH`;
  $('forecast-subtitle').textContent=`${r.systems.length} 个关键系统 · ${s.years} 年 · ${s.quantity} 台`;
  $('chart-legend').innerHTML=[{name:'整体指数',color:'#263f69'},...r.systems].map(g=>`<span class="legend-item"><i class="legend-line" style="background:${g.color}"></i>${e(g.name)}</span>`).join('');
  renderTime();renderMaintenance();renderCosts();renderEvidence();renderComparisons();window.dispatchEvent(new CustomEvent('platform-result',{detail:state.result}));
}
function renderTime(){
  if(!state.result)return;
  const r=state.result,s=r.settings,series=currentSeries(),point=series[state.month];
  const earliest=Math.min(...r.systems.map(g=>g.warning_year??Infinity));
  const event=r.policies[0].events[0];
  $('metrics').innerHTML=metric('当前整体健康指数',point.health.toFixed(1),state.mode==='baseline'?'自然衰减 · 未执行维护':'更换后的当月状态','/ 100')+metric('首次预警（不维护）',earliest<=s.years?number(earliest):`>${s.years}`,'含电池供能 · 演示估算','年')+metric('首次预防性更换',event?number(event.year):'无',event?event.system:'预测期内未触线',event?'年':'')+metric(`${s.years} 年预防维护总支出`,money(r.policies[0].total),`${s.quantity} 台 · 含采购和安装`);
  $('year-label').textContent=yearText(state.month);$('state-year').textContent=yearText(state.month);
  $('system-cards').innerHTML=r.systems.map(g=>{
    const health=point.systems[g.id],status=statusOf(health,s);
    return `<button class="system-card" data-system="${g.id}" title="查看真实部件及检验依据"><span class="name">${e(g.name)}</span><div class="system-score" style="color:${g.color}">${health.toFixed(1)}</div><div class="health-track"><span style="width:${health}%;background:${g.color}"></span></div><div class="status ${status.type}">${status.name}</div></button>`;
  }).join('');
  lineChart($('health-chart'),{years:s.years,series:[{name:'整体指数',color:'#263f69',bold:true,values:series.map(p=>p.health)},...r.systems.map(g=>({name:g.name,color:g.color,values:series.map(p=>p.systems[g.id])}))],thresholds:[{value:s.warning,color:'#c59035',label:'预警线'},{value:s.failure,color:'#d26c77',label:'失效阈值'}],selectedYear:state.month/12,onSelect:setMonth});
}
function setMonth(month){state.month=Math.max(0,Math.min(Number($('year-slider').max),month));$('year-slider').value=state.month;renderTime();}
$('year-slider').addEventListener('input',event=>setMonth(Number(event.target.value)));
$('curve-mode').onchange=()=>{state.mode=$('curve-mode').value;if(state.mode!=='baseline'){state.policy=state.mode;$('maintenance-policy').value=state.policy;renderMaintenance();}renderTime();};
function stopPlayback(){if(state.timer)clearInterval(state.timer);state.timer=null;$('play').textContent='▶';$('play').setAttribute('aria-label','播放时间轴');}
$('play').onclick=()=>{
  if(!state.result)return;
  if(state.timer)return stopPlayback();
  if(state.month>=state.result.settings.years*12)setMonth(0);
  $('play').textContent='Ⅱ';$('play').setAttribute('aria-label','暂停时间轴');
  state.timer=setInterval(()=>{setMonth(Math.min(state.month+3,state.result.settings.years*12));if(state.month>=state.result.settings.years*12)stopPlayback();},220);
};
$('system-cards').addEventListener('click',event=>{const target=event.target.closest('[data-system]');if(!target)return;const group=state.result.systems.find(g=>g.id===target.dataset.system);state.tree.select(group.node_ids[0]);location.hash='structure';});
function renderMaintenance(){
  if(!state.result)return;
  const policy=state.result.policies.find(p=>p.id===state.policy);
  $('maintenance-summary').innerHTML=`<div>策略：<strong>${e(policy.name)}</strong></div><div>系统更换事件：<strong>${policy.events.length}</strong>次</div><div>更换及人工：<strong>${money(policy.breakdown.replacement+policy.breakdown.labor)}</strong></div><div>定期巡检：<strong>${money(policy.breakdown.inspection)}</strong></div>`;
  $('maintenance-summary').className='maintenance-summary';
  $('maintenance-table').innerHTML=policy.events.length?table(['计划时间','分析系统','触发指数','动作','本次总费用（全部设备）'],policy.events.map(item=>[yearText(item.month),item.system,item.trigger_health,item.action,money(item.cost)])):'<div class="empty">预测期内没有触发系统更换；采购、安装及巡检仍按配置计费。</div>';
}
$('maintenance-policy').onchange=()=>{state.policy=$('maintenance-policy').value;renderMaintenance();};

function renderCosts(){
  const r=state.result,s=r.settings;
  $('cost-horizon').className='muted';$('cost-horizon').textContent=`${s.years} 年 · ${s.quantity} 台`;
  stackedCosts($('cost-bars'),r.policies);
  $('cost-breakdown').innerHTML=table(['费用项目',...r.policies.map(p=>p.name)],[...COST_CATEGORIES.map(([id,name])=>[name,...r.policies.map(p=>money(p.breakdown[id]))]),['总计',...r.policies.map(p=>money(p.total))],['单台全周期',...r.policies.map(p=>money(p.per_unit))]]);
  lineChart($('cost-chart'),{years:s.years,currency:true,maxY:Math.max(100,...r.policies.map(p=>p.total))*1.1,series:r.policies.map((p,i)=>({name:p.name,color:i?'#13a49a':'#4169e1',bold:true,values:p.series.map(v=>v.cost)}))});
  $('cost-caption').innerHTML=`<div class="legend"><span class="legend-item"><i class="legend-line" style="background:#4169e1"></i>预防性维护</span><span class="legend-item"><i class="legend-line" style="background:#13a49a"></i>到失效阈值更换</span></div>两种策略均使用同一真实产品与费用配置。成本低不代表安全性更高；失效触线策略仅用于对比，非使用建议。`;
}
function renderComparisons(){
  if(!state.comparisons.length){$('comparison-cards').innerHTML='<div class="empty" style="grid-column:1/-1">运行一个部署场景后，点击“保存当前场景对比”。随后修改地点或参数重新运行，即可保存第二个方案。</div>';return;}
  const base=state.comparisons[0];
  $('comparison-cards').innerHTML=state.comparisons.map((c,i)=>{
    const consistent=c.product===base.product&&c.years===base.years&&c.quantity===base.quantity;
    return `<article class="comparison-card"><div class="panel-heading"><h3>${e(c.location)} · 场景 ${i+1}</h3><button class="text-button" data-remove="${i}" aria-label="删除场景 ${i+1}">删除</button></div><span class="tag ${consistent?'':'assumed'}">${consistent?'同产品 / 年限 / 数量':'口径不同 · 请勿直接排序'}</span><div class="amount">${money(c.total)}</div><p>预防性维护全周期支出</p><p>${c.years} 年 · ${c.quantity} 台 · 单台 ${money(c.perUnit)}</p><p>${e(c.location)} / ${c.temperature}℃ / 湿度 ${c.humidity}%</p><p>年启闭 ${c.cycles} 次 · ${e(c.exposure)}</p><p>采购 ${money(c.purchase)} / 台 · 预警 ${c.warning} / 失效 ${c.failure}</p><div class="health-track" style="margin:16px 0"><span style="width:${Math.min(100,c.total/Math.max(1,...state.comparisons.map(c=>c.total))*100)}%;background:#4169e1"></span></div><p>快照 ${e(c.time)} · 后续编辑不会修改已存快照</p></article>`;
  }).join('');
}
$('save-comparison').onclick=()=>{
  if(!state.result)return;
  if(!$('dirty-note').hidden){setMessage('请先运行已修改的场景，再保存对比快照。',true);return;}
  if(state.comparisons.length>=3){setMessage('最多保存三个场景，请先删除一个快照。',true);return;}
  const r=state.result,s=r.settings,p=r.policies[0];
  state.comparisons.push({...structuredClone(s),product:r.product.id,total:p.total,perUnit:p.per_unit,time:new Date().toLocaleTimeString('zh-CN')});
  setMessage();renderComparisons();
};
$('clear-comparisons').onclick=()=>{state.comparisons=[];renderComparisons();};
$('comparison-cards').onclick=event=>{const button=event.target.closest('[data-remove]');if(button){state.comparisons.splice(Number(button.dataset.remove),1);renderComparisons();}};

function renderEvidence(){
  const c=state.catalog,r=state.result,s=c.stats;
  $('evidence-metrics').innerHTML=metric('原始 BOM 路径',number(s.bom_rows),'保留层级、原行号及重复展开')+metric('检验覆盖',`${s.with_inspections} / ${s.unique_batch_items}`,'按编码＋批号去重')+metric('证明文件索引',s.document_count,'原文未取得，不等于验证通过')+metric('现场寿命数据','未提供','未标定，不输出真实故障概率');
  $('reasoning').innerHTML=r.systems.map(g=>`<article class="reason-card"><div class="reason-title"><strong>${e(g.name)}</strong><span class="tag assumed">参数为演示假设</span></div><p>${e(g.mechanism)}</p><code>H(t) = 100 × exp(−${g.base_rate} × ${g.factor.toFixed(3)} × t)</code><div class="reason-facts"><span>真实 BOM 路径 ${g.node_ids.length} 条</span><span>关联检验 ${g.inspection_ids.length} 项</span><span>报告索引 ${g.document_ids.length} 份</span></div><p>环境载荷系数：温度 ${g.factors.temperature.toFixed(3)} × 湿度 ${g.factors.humidity.toFixed(3)} × 暴露 ${g.factors.exposure.toFixed(3)} × 频次 ${g.factors.cycles.toFixed(3)}。100 为统一起点，并非合格率。</p><button class="text-button" data-evidence-system="${g.id}">查看部件与原始检验 →</button></article>`).join('');
  $('data-warnings').innerHTML=c.warnings.map(w=>`<div class="warning-item">${e(w)}</div>`).join('');
  $('model-limitations').innerHTML=r.limitations.map(w=>`<div class="limit-item">${e(w)}</div>`).join('');
  $('production-table').innerHTML=table(['生产订单','工位','项目','检测数量','合格数量','不合格数量','合格率'],c.production.map(p=>[p.order,p.station,p.project,p.tested,p.qualified,p.unqualified,p.rate]));
}
$('reasoning').onclick=event=>{const button=event.target.closest('[data-evidence-system]');if(button){const g=state.result.systems.find(g=>g.id===button.dataset.evidenceSystem);state.tree.select(g.node_ids[0]);location.hash='structure';}};

async function init(){
  $('run').disabled=true;
  try{
    [state.catalog,state.config]=await Promise.all([api.catalog(),api.config()]);
    renderInputs();renderCatalog();$('run').disabled=false;
    initIntelligence({state,runSimulation,getSettings,selectNode:id=>state.tree.select(id)});
    await runSimulation();
  }catch(error){setMessage(`读取数据失败：${error.message}。请确认后端已启动，并从 http://127.0.0.1:8000 打开页面。`,true);}
}
init();
