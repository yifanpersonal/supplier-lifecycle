import {$, escapeHTML as e, table} from './utils.js';

export function createTree(catalog, onSelect) {
  const nodes=new Map(catalog.nodes.map(n=>[n.id,n]));
  let selected=catalog.product.root_id;
  let expanded=new Set([selected]);
  let filter='';
  function render() {
    const matches=new Set();
    if(filter) for(const node of nodes.values()) {
      if(`${node.name} ${node.code} ${node.batch} ${node.spec}`.toLowerCase().includes(filter)) {
        let current=node;
        while(current) { matches.add(current.id); current=nodes.get(current.parent_id); }
      }
    }
    const html=[];
    function visit(id) {
      const n=nodes.get(id);
      if(!n || filter && !matches.has(id)) return;
      const open=filter ? true : expanded.has(id);
      html.push(`<div class="tree-row ${selected===id?'selected':''}" style="padding-left:${(n.level-1)*13}px" role="treeitem" aria-level="${n.level}" aria-selected="${selected===id}" ${n.children.length?`aria-expanded="${open}"`:''}><button class="tree-toggle" data-toggle="${id}" ${n.children.length?'':'disabled'} aria-label="${open?'收起':'展开'} ${e(n.name)}">${n.children.length?(open?'⌄':'›'):'·'}</button><button class="tree-select" data-node="${id}" title="${e(n.name)} · ${e(n.batch)}">${e(n.name)}<span class="tree-chip">${n.children.length||''}</span></button></div>`);
      if(open) n.children.forEach(visit);
    }
    catalog.nodes.filter(n=>!n.parent_id).forEach(n=>visit(n.id));
    $('product-tree').innerHTML=html.join('') || '<div class="empty">未找到匹配部件</div>';
    $('tree-count').className='muted';
    $('tree-count').textContent=`${catalog.stats.max_level} 层 / ${catalog.stats.bom_rows} 条路径`;
  }
  $('product-tree').addEventListener('click',event=>{
    const toggle=event.target.closest('[data-toggle]');
    if(toggle) {const id=toggle.dataset.toggle; expanded.has(id)?expanded.delete(id):expanded.add(id);render();return;}
    const button=event.target.closest('[data-node]');
    if(button) select(button.dataset.node);
  });
  $('tree-search').addEventListener('input',event=>{filter=event.target.value.trim().toLowerCase();render();});
  $('collapse-tree').onclick=()=>{expanded=new Set([catalog.product.root_id]);filter='';$('tree-search').value='';render();};
  function select(id) {
    selected=id;
    let n=nodes.get(id);
    while(n?.parent_id) {expanded.add(n.parent_id);n=nodes.get(n.parent_id);}
    render();onSelect(nodes.get(id));
  }
  render();select(selected);
  return {select, nodes};
}

export function renderNode(node,catalog) {
  const nodeMap=new Map(catalog.nodes.map(n=>[n.id,n]));
  const parent=nodeMap.get(node.parent_id);
  const records=catalog.inspections.filter(q=>node.inspection_ids.includes(q.id));
  const documents=catalog.documents.filter(d=>node.document_ids.includes(d.id));
  const metas=[['存货编码',node.code],['批号',node.batch],['规格型号',node.spec],['供应商',node.supplier||'原表未填写'],['上级节点',parent?.name||'整机根节点'],['来源位置',`材料构成 · 第 ${node.source_row} 行 / 第 ${node.level} 层`]];
  $('node-detail').innerHTML=`<div class="detail-header"><div><div class="eyebrow">COMPONENT PROFILE</div><h2>${e(node.name)}</h2></div><span class="pill subtle">${node.group?'关键分析部件':'产品档案'}</span></div><dl class="detail-meta">${metas.map(([k,v])=>`<div><dt>${k}</dt><dd>${e(v)}</dd></div>`).join('')}</dl><h3>批次检验 <span class="muted">${records.length} 项 · 编码＋批号关联</span></h3>${records.length?`<div class="table-scroll">${table(['检验项目','要求','检测原文','判定 / 来源'],records.map(q=>[q.project,q.requirement,q.measured_raw||'原始值缺失',`${q.result} · 质量明细第 ${q.source_row} 行`]))}</div>`:'<div class="empty">当前部件批次未匹配到质量明细，不代表未检验。</div>'}<h3>供应商证明文件 <span class="muted">${documents.length} 份索引</span></h3>${documents.length?documents.map(d=>`<div class="document-item"><div><strong>${e(d.name)}</strong><small>来源：材料构成 · ${e(d.refs.find(ref=>ref.endsWith(String(node.source_row)))||d.refs[0])}${d.expires_at?` · 原链接到期 ${e(d.expires_at.slice(0,10))}`:''}</small></div><span class="tag missing">原文未取得</span></div>`).join(''):'<div class="empty">原表未关联证明文件。</div>'}<p class="field-note" style="margin-top:18px">文件索引不是检测结论。相同物料可在多个父路径中出现；当前展示的是所选原始行。</p>`;
}
