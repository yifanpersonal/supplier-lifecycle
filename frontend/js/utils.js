export const $ = id => document.getElementById(id);
// 表格和文件名属于外部输入，插入 HTML 之前统一转义。
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money = value => new Intl.NumberFormat('zh-CN', {style:'currency', currency:'CNY', maximumFractionDigits:0}).format(value);
export const number = value => new Intl.NumberFormat('zh-CN', {maximumFractionDigits:1}).format(value);
export const yearText = month => `第 ${Math.floor(month / 12)} 年${month % 12 ? ` ${month % 12} 个月` : ''}`;
export const statusOf = (health, settings) => health <= settings.failure ? {name:'达到失效阈值', type:'failure'} : health <= settings.warning ? {name:'进入预警区', type:'warning'} : {name:'阈值以上', type:'normal'};
export function table(headers, rows) {
  return `<table><thead><tr>${headers.map(h=>`<th>${escapeHTML(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${escapeHTML(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
