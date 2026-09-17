# 产品全周期分析可信可视平台

第二版工程。在第一版真实供应商数据、确定性仿真和成本图表基础上，增加五模块界面、Qwen 工具调用、持久化 RAG、产品可视化与决策报告。

## 启动

需要 Python 3.10 或以上。在本项目目录运行：

```bash
python -m pip install -r requirements.txt
```

将 `.env.example` 复制为 `.env`，填写阿里云百炼的 API 密钥：

```dotenv
DASHSCOPE_API_KEY=你的密钥
QWEN_MODEL=qwen-plus
QWEN_VISION_MODEL=qwen-vl-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_RERANK_MODEL=qwen3-rerank
QWEN_SEARCH_MODEL=qwen-plus
```

按百炼控制台实际配置选择地域和网关。传统北京网关可保持默认；采用工作空间网关时，填写 `QWEN_WORKSPACE_ID`、`QWEN_REGION`。也可分别设置 `QWEN_BASE_URL`、`QWEN_NATIVE_URL` 和 `QWEN_RERANK_URL`。密钥、模型和网关须属于可兼容的地域；模型名称可根据账号权限调整。

```bash
python -m backend.server --port 8000
```

浏览器打开 http://127.0.0.1:8000 。不要直接打开 HTML。macOS/Linux 可使用 `python3`。Windows 可在依赖安装完成后双击 `start.bat`；macOS/Linux 可运行 `sh start.sh`。

运行日志写入 `log/app.log`，单文件上限 5 MB，保留 5 份轮转。日志只记录请求方法、路径、状态码、耗时和异常堆栈，不记录查询串、请求正文、用户文档正文和密钥，与 `docs/ACCEPTANCE.md` 第 15 项一致。用 `--log_level DEBUG` 或环境变量 `APP_LOG_LEVEL=DEBUG` 可查看静态资源访问；用 `APP_LOG_DIR` 可更换日志目录。任务失败时页面只显示一行错误，完整堆栈在日志中。

没有配置 API 时，产品档案、场景仿真、费用图表、文本型资料上传、关键词检索、结构示意和照片/全景浏览仍可使用。Qwen、扫描件 OCR、语义向量、重排序和联网分析会明确提示未配置，不生成虚构的 AI 结果。

## 建议演示顺序

1. 在侧栏点击“检查模型连接”，验证对话模型配置。
2. 查看“产品信息”。目前加载一个真实鑫豪斯产品，可查看部件资料与检验记录。
3. 点击“资料与知识库”，上传该产品的质量报告、采购要求、报价或参考资料。采购要求只有在勾选“由采购方确认且适用于当前产品”后，才计入已确认要求。
4. 点击“构建语义索引”。系统将新增片段向量化；之后使用 BM25 与向量混合召回、RRF 融合及 Qwen 重排序。未构建索引或服务异常时，页面会说明降级方式。
5. 在“产品生命周期仿真”设置部署场景，运行仿真。查看曲线、时间轴、预警和维护节点。
6. 分别运行质量、寿命和费用分析。寿命/费用模块会调用 Qwen 联网检索，展示返回的参考来源。模型建议不会自动改写当前曲线或费用。
7. 在“产品可视化”旋转部件示意、展开部件，或上传真实照片、2:1 等距柱状全景图。普通照片按原图展示，全景图可拖动环视。
8. 在“决策报告”运行分析。系统依次分析前四个模块，再根据同一计算快照生成报告，支持 Markdown 下载。

全文报告运行会产生多次模型、检索和视觉调用；服务端最多同时处理两个任务，前端显示阶段进度。索引与报告存入 `var/`，刷新或重启后保留。启动阶段只建立本地关键词库，不自动发起付费调用。

## 功能与边界

- 五个模块按指定顺序排列，侧栏横向收起/展开，记忆收起状态，窄屏默认收起。
- 工具可读取当前产品的入库文档、分析 Excel、识别图片文字、查询计算结果、联网检索及写入新报告。文件工具没有系统目录、Shell 或 `.env` 访问权限。
- 上传的通用 Excel 是当前产品的补充资料；不会自动替换整机目录或切换到新的供应商。新增产品需扩展目录注册与对应模板解析。
- 首版保留的五组健康指数和费用仍为可编辑假设。文献检索提高解释依据，不代表已完成寿命标定。
- 质量分析输出辅助审核意见。已确认 JSON 规则可以执行明确的数值核验；普通文档通过 RAG 辅助审核。缺少要求、单位、适用条件或完整覆盖时不直接宣布整机通过准入。
- 扫描 PDF 使用 Qwen 逐页 OCR；图片识别保留“待复核”状态。工作簿内嵌的 PDF/图片不自动解包解析，请单独上传原件。
- 当前旋转模型为功能示意。原始老师 Demo 的全景区域也是占位 UI，工程没有实物 CAD、真实尺寸、VR 头显支持或自动交付合格认证。
- 多场景和维护策略可以比较；当前只有一个真实整机，不生成虚构的多供应商排名。
- 本工程面向本机研发演示，没有账号与多租户权限系统；正式部署需补充身份验证、授权、网关与审计。

## 工程结构

```text
backend/
  server.py        网页和 API
  runtime.py       异步任务与分析快照
  qwen.py          Qwen 对话、工具协议、视觉、向量、重排、联网
  knowledge.py     SQLite 持久化与混合检索
  documents.py     受控文件读写与文档解析
  agent.py         五模块分析、工具调用、引用校验
  workbook.py      第一版产品目录解析
  simulation.py    确定性生命周期与成本计算
  analysis.py      本地解释
frontend/
  index.html       五模块页面
  styles.css       页面与收起侧栏
  js/
    app.js         基础仿真交互
    intelligence.js 资料管理、任务进度、分析与报告
    viewer.js      旋转示意与真实全景投影
    api.js charts.js tree.js utils.js
config/
  buyer-rules.example.json  数值规则格式示例
  supplier-evidence.example.txt  演示用上传文本
  RAG评测问题.json           基于真实样本的检索核验问题
data/xinhaosi.xlsx 原始真实样本
var/              首次运行创建；资料、索引、任务与报告
log/              首次运行创建；运行日志 app.log，按 5 MB 轮转保留 5 份
reports/已实现功能报告.md  本次功能交付说明
docs/             API、模型边界、验收记录与接入文档
```

## 验证

```bash
python -m unittest discover -s tests -v
node --test tests/frontend.test.mjs
```

Python 测试覆盖真实样本、计算账本、上传、检索、OCR 协议、工具边界、来源检查、全链路报告和 HTTP 接口。AI 测试使用明确标记的模拟客户端；不等于已使用真实 API Key 完成线上联调。验收状态见 `docs/ACCEPTANCE.md`。

## 接口参考

按阿里云官方文档实现，可在 `docs/QWEN.md` 查看接口映射与地址配置。
