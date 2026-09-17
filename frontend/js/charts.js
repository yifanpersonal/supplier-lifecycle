import {escapeHTML as e, number} from './utils.js';

// 本地 SVG 图表无 CDN 依赖；坐标点来自服务端计算，页面不重复计算模型。
export function lineChart(container, {series, years, maxY=100, thresholds=[], selectedYear=null, onSelect, currency=false}) {
  const W=820, H=300, p={l:54,r:22,t:18,b:35}, width=W-p.l-p.r, height=H-p.t-p.b;
  const x = year=>p.l+year/years*width;
  const y = value=>p.t+height-value/maxY*height;
  let body='';
  for(let tick=0; tick<=5; tick++) {
    const value=maxY*tick/5;
    body+=`<line x1="${p.l}" y1="${y(value)}" x2="${W-p.r}" y2="${y(value)}" stroke="#e9edf4" stroke-dasharray="3 5"/><text x="${p.l-10}" y="${y(value)+4}" text-anchor="end">${currency && value>=10000 ? number(value/10000)+'万' : number(value)}</text>`;
  }
  const step = years<=5 ? 1 : Math.ceil(years/5);
  const ticks = [...new Set([0,...Array.from({length:Math.floor(years/step)},(_,i)=>(i+1)*step),years])];
  for(const tick of ticks) body+=`<text x="${x(tick)}" y="${H-10}" text-anchor="middle">${tick}年</text>`;
  for(const item of thresholds) body+=`<line x1="${p.l}" y1="${y(item.value)}" x2="${W-p.r}" y2="${y(item.value)}" stroke="${item.color}" stroke-width="1.2" stroke-dasharray="6 5"/><text x="${W-p.r}" y="${y(item.value)-6}" text-anchor="end" style="fill:${item.color}">${e(item.label)} ${item.value}</text>`;
  for(const item of series) {
    const path=item.values.map((v,i)=>`${i?'L':'M'}${x(i/12).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
    body+=`<path d="${path}" fill="none" stroke="${item.color}" stroke-width="${item.bold?2.8:1.9}" stroke-linejoin="round" stroke-linecap="round" opacity="${item.bold?1:.86}"><title>${e(item.name)}</title></path>`;
  }
  if(selectedYear!==null) {
    const at=Math.max(0,Math.min(Math.round(selectedYear*12),series[0].values.length-1));
    body+=`<g class="hover-marker"><line x1="${x(selectedYear)}" y1="${p.t}" x2="${x(selectedYear)}" y2="${H-p.b}" stroke="#6b7fa2" stroke-dasharray="3 3"/>`;
    for(const item of series) body+=`<circle cx="${x(selectedYear)}" cy="${y(item.values[at])}" r="${item.bold?4:3}" fill="${item.color}" stroke="white" stroke-width="1.5"/>`;
    body+='</g>';
  }
  container.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${currency?'累计成本':'健康指数'}随时间变化曲线"><title>${series.map(s=>e(s.name)).join('、')}</title>${body}</svg>`;
  if(onSelect) {
    container.style.cursor='crosshair';
    container.onclick=event=>{
      const rect=container.querySelector('svg').getBoundingClientRect();
      const year=Math.max(0,Math.min(years,((event.clientX-rect.left)*W/rect.width-p.l)/width*years));
      onSelect(Math.round(year*12));
    };
  }
}

export const COST_CATEGORIES = [
  ['purchase','采购','#4169e1'],['installation','安装','#8da6ed'],['inspection','巡检','#13a49a'],
  ['replacement','更换包','#9b72da'],['labor','更换人工','#d5a352'],['downtime','停用处置','#d87987'],
];
export function stackedCosts(container, policies) {
  const max=Math.max(1,...policies.map(p=>p.total));
  container.innerHTML=policies.map(p=>`<div class="bar-row"><div class="bar-label"><span>${e(p.name)}</span><strong>¥${number(p.total)}</strong></div><div class="bar-track">${COST_CATEGORIES.map(([id,name,color])=>`<div class="bar-segment" style="width:${p.breakdown[id]/max*100}%;background:${color}" title="${name}：¥${number(p.breakdown[id])}"></div>`).join('')}</div></div>`).join('')+`<div class="bar-key">${COST_CATEGORIES.map(([,name,color])=>`<span><i style="background:${color}"></i>${name}</span>`).join('')}</div>`;
}
