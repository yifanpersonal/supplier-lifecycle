// 无浏览器依赖的前端纯逻辑测试；不替代浏览器布局与端到端验收。
import test from 'node:test';
import assert from 'node:assert/strict';
import {escapeHTML, statusOf, table, yearText} from '../frontend/js/utils.js';
import {lineChart, stackedCosts} from '../frontend/js/charts.js';

test('外部文本转义，避免注入页面',()=>{
  assert.equal(escapeHTML('<script>"&\''),'&lt;script&gt;&quot;&amp;&#39;');
  assert.ok(!table(['名称'],[['<img onerror=alert(1)>']]).includes('<img'));
});
test('阈值边界与月份标签',()=>{
  const settings={warning:70,failure:45};
  assert.equal(statusOf(70,settings).type,'warning');
  assert.equal(statusOf(45,settings).type,'failure');
  assert.equal(statusOf(71,settings).type,'normal');
  assert.equal(yearText(13),'第 1 年 1 个月');
});
test('SVG 曲线包含阈值、时间标记且无 NaN',()=>{
  const element={innerHTML:'',style:{}};
  lineChart(element,{series:[{name:'测试',color:'#4169e1',values:[100,90,80],bold:true}],years:1,maxY:100,thresholds:[{value:70,color:'#888',label:'预警线'}],selectedYear:1/12});
  assert.ok(element.innerHTML.includes('预警线 70'));
  assert.ok(element.innerHTML.includes('hover-marker'));
  assert.ok(!element.innerHTML.includes('NaN'));
});
test('图表点击按真实坐标换算月份',()=>{
  let month=-1;
  const element={innerHTML:'',style:{},querySelector:()=>({getBoundingClientRect:()=>({left:0,width:820})})};
  lineChart(element,{series:[{name:'测试',color:'#4169e1',values:Array(241).fill(100)}],years:20,onSelect:value=>month=value});
  element.onclick({clientX:426});
  assert.equal(month,120);
});
test('零成本场景不产生除零图形',()=>{
  const element={innerHTML:''};
  stackedCosts(element,[{name:'零成本',total:0,breakdown:{purchase:0,installation:0,inspection:0,replacement:0,labor:0,downtime:0}}]);
  assert.ok(!element.innerHTML.includes('NaN'));
  assert.ok(element.innerHTML.includes('width:0%'));
});
