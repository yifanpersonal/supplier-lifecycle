# 第二版 API

默认服务地址 `http://127.0.0.1:8000`，同源调用，JSON 编码。服务端不返回 API Key。

| 路径 | 方法 | 作用 |
|---|---|---|
| /api/health | GET | 版本与 Qwen 配置状态 |
| /api/config | GET | 场景默认值和模型名称 |
| /api/catalog | GET | 当前真实产品档案 |
| /api/simulate | POST | 原第一版场景对象，返回曲线、维护账本及 analysis_key |
| /api/analysis/explain | POST | 本地规则解释，保持旧接口兼容 |
| /api/documents | GET | 当前产品资料、片段及向量数量 |
| /api/documents/{id} | GET | 查看资料正文，页面最多展示前 100 块 |
| /api/supplier-data/import | POST | 上传并提交异步解析任务 |
| /api/knowledge/index | POST | 增量构建向量索引 |
| /api/knowledge/search | POST | 提交混合检索任务 |
| /api/analysis/run | POST | 提交模块分析或完整报告任务 |
| /api/jobs/{id} | GET | 状态、阶段记录、结果或错误 |
| /api/analyses/{analysis_key} | GET | 同一场景的模块分析快照 |
| /api/reports/{filename} | GET | 下载报告 |
| /api/media/{file_id} | GET | 查看已入库的产品照片/全景 |
| /api/provider/check | POST | 检查对话模型连接 |

## 上传

```json
{"name":"质量报告.pdf","kind":"supplier_evidence","content_base64":"文件Base64","confirmed":false,"panorama":false}
```

类别可选 `supplier_evidence`、`buyer_requirement`、`quote`、`reference`、`visual`。本版统一归属当前产品；confirmed 仅表示用户确认采购要求的来源与适用对象，不代表系统已经验证真伪。

文件不超过 24 MB；PDF 不超过 60 页；支持 XLSX、PDF、PNG/JPEG/WebP、TXT、MD、JSON、CSV。扫描 PDF 必须配置视觉 API。图片以 visual 上传时可先用于浏览，再单独启动图片分析。

## 检索与分析

```json
{"query":"密封性检验要求","kind":"supplier_evidence"}
```

```json
{"stage":"report","settings":{"years":20,"quantity":100},"question":"关注密封件维护与费用"}
```

stage 为 `quality`、`lifetime`、`cost`、`visual`、`report`。report 顺序运行前四项后汇总，前置项失败会在报告中披露；模型建议不会自动应用到计算公式。

任务接口返回 HTTP 202：

```json
{"job_id":"任务ID","status":"queued"}
```

任务状态为 queued / running / completed / failed / interrupted。刷新可恢复最后一个任务进度；服务重启后未完成任务标记 interrupted，不冒充完成。

当前场景、源数据或知识库版本变化后，analysis_key 会改变，前端不将旧结论展示为新场景结果。
