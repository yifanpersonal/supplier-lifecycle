# Qwen 接入说明

## 接口映射

| 能力 | 调用方式 | 默认模型 |
|---|---|---|
| 分析与工具调用 | OpenAI 兼容 `POST /chat/completions`，messages + tools | qwen-plus |
| 图像文字与外观观察 | 同一兼容接口，image_url 传入服务端编码的图像 | qwen-vl-plus |
| 文本向量 | 兼容接口 `POST /embeddings`，1024 维 float | text-embedding-v4 |
| 重排序 | `POST /compatible-api/v1/reranks` | qwen3-rerank |
| 备用重排序 | 原生 `/api/v1/services/rerank/text-rerank/text-rerank` | gte-rerank-v2 |
| 联网检索 | 原生 `/api/v1/services/aigc/text-generation/generation`，enable_search + search_options | qwen-plus |

API Key、可用模型与服务地址应以账号控制台为准。对话、视觉、向量、重排和搜索是不同能力；“检查模型连接”只验证对话，不代表其他服务均可用。

## 配置方式

`.env.example` 提供全部配置项。支持传统 DashScope 网关和工作空间网关。国际地域必须替换对应地址或使用正确的工作空间与地域。密钥只在后端加载，不通过网页表单传递，不写入静态资源或模型提示词。

联网采用 Qwen 内置搜索，程序只接受接口返回的 `search_info.search_results` 来源，不从生成文字猜测来源 URL。价格和寿命检索使用固定公开技术关键词，不将内部报价、批号或用户文档原文拼入公网查询。搜索结果缓存 24 小时。

## RAG 链路

文档解析 → 保留位置的文本分块 → SQLite 存储 → Qwen 向量化 → 产品/资料类别过滤 → BM25 与稠密向量召回 → RRF 融合 → Qwen 重排序 → 相邻片段扩展 → 带来源的分析输出。

文本块默认 1000 字符，重叠 120 字符。向量每批 10 个；已有相同模型向量不会重复生成。模型变更会重建对应语义索引。检索输出包含原文位置、片段 ID、相邻片段 ID 和实际采用的检索方式。向量或重排序服务不可用时明确显示降级。

当前 SQLite 与内存余弦排序适合研发样本规模；数据量增大时，可保持检索契约并替换为专用向量数据库。工程不依赖单一智能体框架。

## 工具及输出边界

智能体最多执行 6 轮、16 次工具调用，每阶段最多 3 次联网搜索。工具名与参数校验由服务端控制。文件读取限于当前产品入库资料，写入限于报告目录，禁止覆盖已有文件、路径穿越和符号链接。没有任意代码执行工具。

输出按 JSON 格式检查。未在本次检索、计算或工具记录中出现的来源 ID 会被移除；无有效来源支撑的“符合/不符合”降为证据不足。该检查只验证引用存在，不声称自动证明文献适用性或报告真实性。

候选模型保留公式、参数、条件和来源，不自动更改确定性计算引擎。当前可编辑的指数衰减参数仍作为人工假设；新的物理模型需要工程实现与校准。

## 官方参考

- 工具调用：https://help.aliyun.com/zh/model-studio/qwen-function-calling
- 联网搜索：https://help.aliyun.com/zh/model-studio/web-search
- 文本向量：https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api
- 重排序：https://help.aliyun.com/zh/model-studio/text-rerank-api
- 视觉理解：https://help.aliyun.com/zh/model-studio/vision
- 知识库工程：https://help.aliyun.com/zh/model-studio/rag-knowledge-base

接口文档核对日期：2026-09-15。模型权限和地域可用性以实际调用结果为准。
