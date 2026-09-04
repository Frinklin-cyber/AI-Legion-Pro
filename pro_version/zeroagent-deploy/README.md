# ZEROagent · 企业知识大脑 + 多 Agent 编排

基于 Zero Daemon 本地 AI Agent 能力升级的企业级产品，已完成前两个阶段：

- **第一阶段 · 企业知识大脑**：本地 RAG 系统。客户上传 PDF / Word / Excel → 本地模型提取并向量化 → 用户提问 → 返回**带引用来源**的答案。
- **第二阶段 · 业务流程自动化 Agent**：多 Agent 编排。路由 Agent 接收任务 → 分发给专项 Agent（合同审核 / 日报生成 / 客服回复）→ 质检 Agent 审核输出 → 返回最终结果，全程审计可回溯。

## 设计原则（本产品的硬约束）

| 原则 | 落地方式 |
|------|----------|
| ✅ 数据不出域 | 所有处理在本地完成：向量化、检索、生成全部走**本地 Ollama**，不调用任何公网 AI API |
| ✅ 企业自主管控 | 内容安全策略由客户配置（见「配置」），不依赖第三方通用审核规则 |
| ✅ 全链路审计 | 上传 / 问答 / Agent 执行全过程写入审计日志（JSON 行），可回溯 |
| ✅ 自进化能力保留 | 后续阶段可在本 PoC 之上接入 ZD 的自进化引擎，让 Agent 随业务变化自我调整 |
| ❌ 不做 SaaS | 纯本地部署（Docker 或裸机），交付物不包含任何云端服务 |

## 架构

```
浏览器 (Web UI: 知识问答 + Agent 工作台)
   │  /upload /ask /documents(DELETE) /feedback        /agents /agents/run /agents/notify
   ▼
FastAPI (main.py)
   │
   ├─ 知识大脑 ─────────────────────────────────────────────
   │  ├─ extractor.py     PDF(PyMuPDF) / Word(docx) / Excel(pandas) / MD/TXT → 统一文本流
   │  ├─ chunker.py       章节优先切分，chunk_size=500, overlap=50，保留页码元数据
   │  ├─ vector_store.py  ChromaDB 持久化到 ./data/vectordb/，增量更新（同文件重传不重建全量）
   │  └─ rag.py           top-k=5 检索 + RAG prompt（要求标注引用）+ 生成；
   │                     兜底澄清：空结果/弱相关/无关 → status=clarify（推荐相关文档/概念）
   │                     或 status=not_found（共情回复 + 建议补充上传），不返回低分引用
   │
   ├─ 多 Agent 编排 ────────────────────────────────────────
   │  ├─ agent_registry.py    加载 agents/*.json → 注册表（每个 Agent 是一个"工具"，有 schema）
   │  ├─ agent_orchestrator.py 路由 Agent(规则+LLM) → 分发专项 Agent → 质检 → 重试 → 聚合
   │  ├─ quality_gate.py      质检 Agent：格式/必需字段/引用完整(防幻觉)/敏感词
   │  └─ webhook_sender.py    企微 / 钉钉 / 飞书 群机器人通知
   │
   └─ ollama_client.py  本地 Ollama：embedding (/api/embed) + 生成 (/api/generate)
                            └─ 模型：nomic-embed-text + qwen2.5:7b（均本地，数据不出域）
```

## 快速启动（本地）

前置条件：已安装 Ollama 且正在运行（`ollama serve`）。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 拉取本地模型（数据不出域，模型存放在本地）
ollama pull nomic-embed-text   # 向量模型 (~274MB)
ollama pull qwen2.5:7b         # 问答模型 (~4.7GB)，也可用 qwen2.5-coder:7b

# 3. 启动服务
python main.py                 # → http://localhost:8000

# 4.（可选）生成测试用示例文档并跑端到端验证
python scripts/make_sample_pdf.py
python scripts/e2e_test.py
```

## Docker 一键部署

```bash
docker compose up --build
# 首次启动：拉取本地模型（模型同样运行在本地容器内，不触网）
docker compose exec app python scripts/pull_models.py
# 访问 http://localhost:8000
```

所有运行时数据（向量库、上传文件、审计日志）持久化在 `./data/`，删除容器不丢失。

## 多 Agent 编排

在知识大脑之上增加"业务流程自动化"能力：**路由 Agent → 专项 Agent → 质检 Agent** 的完整流水线。

```
用户任务
   │
   ▼
路由 Agent ──── ① 用户显式指定 Agent
   │           ② 关键词规则（位置加权，越靠前越优先）
   │           ③ LLM 兜底（把任务与 Agent 描述交给本地模型判断）
   ▼
专项 Agent ──── 合同审核 contract_review（use_kb=false）
   │           日报生成 daily_report（use_kb=false）
   │           客服回复 customer_service（use_kb=true，自动检索知识库）
   ▼
质检 Agent ──── 格式正确(JSON) / 必需字段齐全 / 引用完整(防幻觉) / 敏感词
   │           未通过 → 携带质检失败原因重试 1 次
   ▼
审计 + 通知 ─── 全程写入 data/audit_log.jsonl（可回溯）
               可选推送企微/钉钉/飞书群机器人
   ▼
返回最终结果
```

### 示例 Agent 配置

每个 Agent 是一个 JSON 配置文件（`agents/` 目录），schema 复用 Zero Daemon `tool_router.py` 的 function-calling 风格：

```json
{
  "name": "contract_review",
  "title": "合同审核 Agent",
  "description": "审核合同文本，识别付款、违约责任、知识产权、保密等风险条款",
  "use_kb": false,
  "parameters": {
    "type": "object",
    "properties": {
      "contract_text": {"type": "string", "description": "待审核的合同全文"}
    },
    "required": ["contract_text"]
  },
  "output_schema": {
    "summary": "string - 合同总体评估",
    "risk_level": "string - 低 / 中 / 高",
    "issues": "array - 风险项列表",
    "conclusion": "string - 是否建议签署及理由"
  },
  "system_prompt": "你是资深企业法务顾问……"
}
```

**新增自定义 Agent 三步**：写一个 JSON 放到 `agents/` → 重启服务自动注册 → 前端 /agents 下拉框即可选择。无需改代码。

内置 3 个示例 Agent：

| Agent | 输入 | 输出 | 说明 |
|-------|------|------|------|
| 合同审核 | 合同全文（`contract_text`） | 风险等级 + 逐条风险（附原文引用） | 检查付款/违约/知产/保密/争议条款 |
| 日报生成 | 工作要点（`work_points`） | 结构化日报（完成/计划/风险） | 不虚构未提及内容 |
| 客服回复 | 客户问题（`customer_question`） | 回复正文 + 语气 + 是否转人工 | `use_kb=true` 自动检索知识库并核对数值区间 |

### Agent 编排 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agents` | 列出已注册 Agent 及其 schema（工具自描述） |
| POST | `/agents/run` | 执行 Agent 任务（可指定 agent 或自动路由） |
| POST | `/agents/notify` | 测试 Webhook 通知 |

```bash
# 自动路由（推荐）：系统判断任务类型并分发
curl -X POST http://localhost:8000/agents/run \
  -H "Content-Type: application/json" \
  -d '{"task": "帮我写日报：上午完成合同审核模块，下午修了3个bug"}'

# 显式指定 Agent
curl -X POST http://localhost:8000/agents/run \
  -H "Content-Type: application/json" \
  -d '{"task": "客户问：入职满两年能休几天年假？", "agent": "customer_service"}'

# 携带业务参数（不传时自动把 task 填入 Agent 的第一个必填参数）
curl -X POST http://localhost:8000/agents/run \
  -H "Content-Type: application/json" \
  -d '{"task": "略", "agent": "daily_report", "params": {"work_points": "完成了X", "date": "2026-08-21"}}'
```

返回结构：

```json
{
  "task_id": "agent_20260821_130000_ab12",
  "ok": true,
  "agent": "contract_review",
  "agent_title": "合同审核 Agent",
  "result": { "summary": "...", "risk_level": "中", "issues": [...] },
  "quality": {
    "passed": true, "score": 100,
    "checks": [{ "name": "引用完整(无幻觉)", "level": "error", "passed": true, "detail": "..." }]
  },
  "routing": { "agent": "contract_review", "method": "explicit", "reasoning": "..." },
  "attempts": 1,
  "notify": null,
  "elapsed_ms": 4200
}
```

### Webhook 对接（企微 / 钉钉 / 飞书）

复制 `config/webhooks.example.json` 为 `data/webhooks.json` 并填入机器人地址：

```json
{
  "wecom":    {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"},
  "dingtalk": {"url": "https://oapi.dingtalk.com/robot/send?access_token=xxx", "secret": "可选加签密钥"},
  "feishu":   {"url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"}
}
```

- 任务完成通知：`POST /agents/run` 时传 `"webhook_channel": "wecom"`（或 dingtalk / feishu）
- 手动测试：`POST /agents/notify` `{"channel": "wecom", "message": "测试"}`
- **未配置时自动跳过**（返回友好提示），不影响主流程

### 审计日志（可回溯）

每个 Agent 任务的完整执行链写入 `data/audit_log.jsonl`：

```json
{"ts": "2026-08-21T14:27:22", "audit_id": "agent_20260821_142722_d8cf", "agent": "customer_service",
 "stage": "route", "status": "OK", "detail": "explicit 路由 → customer_service", "reasoning": "..."}
{"ts": "2026-08-21T14:27:23", "audit_id": "agent_20260821_142722_d8cf", "agent": "customer_service",
 "stage": "execute", "status": "OK", "detail": "尝试1: 质检得分 100"}
{"ts": "2026-08-21T14:27:23", "audit_id": "agent_20260821_142722_d8cf", "agent": "customer_service",
 "stage": "done", "status": "OK", "detail": "完成，共 1 次尝试", "elapsed_ms": 1282}
```

stage 覆盖 `route / execute / quality / retry / notify / done`，一次任务可完整还原"谁在何时做了什么、质检是否通过"。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/upload` | 上传文件（multipart，字段名 `file`），触发 ingestion |
| POST | `/ask` | `{"question": "..."}` → `{"status", "message", "answer", "references"}`（人格驱动，模型自主决定如何回答） |
| GET | `/documents` | 已索引文档列表 `{"documents": [{"source_file", "chunk_count"}]}` |
| DELETE | `/documents/{filename}` | 删除指定文档：移除向量索引（`delete_by_source`）+ 删除上传原文件，返回 `{"status","source_file","vectors_deleted","file_removed"}` |
| POST | `/feedback` | 收集"回答不准"负面反馈 → 追加写入 `data/feedback/feedback.jsonl`（JSONL，含 ts/question/answer/references） |
| GET | `/agents` | 列出已注册专项 Agent 及 schema（工具自描述） |
| POST | `/agents/run` | 执行 Agent 任务（自动路由或指定 Agent，详见「多 Agent 编排」） |
| POST | `/agents/notify` | 测试 Webhook 通知（企微/钉钉/飞书） |
| GET | `/health` | 健康检查（含 Ollama 状态） |

`/ask` 返回结构：

```json
{
  "status": "ok",
  "message": "AI 的完整回答（引用 / 说明不确定 / 坦诚无资料并给方向，由模型依据人格自主决定）",
  "answer": "同 message（兼容字段）",
  "references": []
}
```

- `status`：统一为 `ok`。不再区分 `success / clarify / not_found`——回复方式由 `app/persona.py` 定义的 ZEROagent 人格（system prompt）驱动，代码不做状态判定、不做关键词匹配。
- `references`：检索到资料时非空（每条含 `source_file` / `page_number` / `text` / `score`）；资料不足或完全没有时为空数组，此时 AI 依据人格坦诚说明并给出有用方向（如建议补充哪类文档）。
- 无 `suggestions` / `data` 字段——引导、澄清、上传修补逻辑已移除，交互责任全部交给 AI 的回复本身。

`references` 每条结构：

```json
{
  "source_file": "员工手册.pdf",
  "page_number": 2,
  "text": "原文片段（该 chunk 全文）",
  "score": 0.82
}
```

### 使用示例

```bash
# 上传
curl -F "file=@员工手册.pdf" http://localhost:8000/upload
# → {"source_file": "员工手册.pdf", "chunks_indexed": 18}

# 提问（命中知识库 → status=ok，AI 引用来源）
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "公司年假是怎么规定的？"}'
# → {"status": "ok", "message": "根据公司员工手册，员工入职满一年后可休 5 天年假。[1]",
#     "answer": "…同 message…",
#     "references": [{"source_file": "员工手册.pdf", "page_number": 3, ...}]}

# 提问完全无关（无参考 → AI 依据人格坦诚说明并给方向）
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "量子纠缠对量子计算机有什么影响？"}'
# → {"status": "ok",
#     "message": "根据目前资料，我的知识库主要覆盖公司内部文档，暂时没有量子计算相关内容。"
#                 "建议补充技术类文档，或者你可以问我：员工手册、考勤制度等。",
#     "references": []}

# 删除文档（向量 + 原文件）
curl -X DELETE http://localhost:8000/documents/员工手册.pdf
# → {"status": "ok", "source_file": "员工手册.pdf", "vectors_deleted": 12, "file_removed": true}

# 反馈（👍👎）
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{"question": "…", "answer": "…", "status": "ok", "rating": "down", "references": [...]}'
# → {"status": "ok", "message": "感谢反馈，这将帮助我们优化未来的回答。"}
```

## 配置（环境变量，客户可自主管控）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_HOST` | `http://localhost:11434` | 本地 Ollama 地址；容器内为 `http://ollama:11434` |
| `EMBED_MODEL` | `nomic-embed-text` | 向量模型；可换 `bge-m3`（切换后需清空 `data/vectordb/`，维度不同） |
| `LLM_MODEL` | `qwen2.5:7b` | 问答模型；可换 `qwen2.5-coder:7b` 等 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `500` / `50` | 切分参数 |
| `TOP_K` | `5` | 检索返回块数 |
| `TEMPERATURE` | `0.1` | 生成温度（人格驱动问答采用 `0.3` 保持自然） |
| `MAX_UPLOAD_SIZE_MB` | `50` | 单文件上传上限 |
| `ZD_DATA_DIR` | `./data` | 数据目录（向量库/上传/审计） |

> 内容安全策略：企业可在后续阶段为 `/ask` 配置自定义关键词拦截、敏感词审计等，无需依赖任何第三方审核服务。当前 PoC 已内置全量操作审计。

## 验证清单（交付自查）

### 知识大脑

- [x] `pip install -r requirements.txt` 后可直接 `python main.py` 启动
- [x] 上传 PDF 后 `./data/vectordb/` 生成 ChromaDB 文件
- [x] 提问返回 JSON 含 `status=ok` + `message` + `answer` + `references`
- [x] `references` 每条含 `source_file` 和 `page_number`
- [x] 完全无关问题：AI 依据人格坦诚说明无资料并给出有用方向，`references` 为空
- [x] 相近概念问题：AI 依据人格自主决定如何回应（人格驱动，无状态分支）
- [x] `DELETE /documents/{filename}` 删除文档（向量 + 原文件）并刷新文档列表
- [x] `POST /feedback` 将"回答不准"反馈写入 `data/feedback/feedback.jsonl`（JSONL）
- [x] Docker 构建后可启动并访问 UI
- [x] Ollama 未运行时返回友好错误（503 + 提示），不崩溃

### 多 Agent 编排（`python scripts/e2e_agents_test.py`，13 项断言全部通过）

- [x] `GET /agents` 返回 3 个专项 Agent，均含 schema（description + parameters）
- [x] 合同审核：识别风险条款（附原文引用）、输出 risk_level、质检通过
- [x] 日报生成：自动路由到 daily_report（不会被"合同"关键词误路由）
- [x] 客服回复：自动检索知识库，数值区间精确匹配（"满2年 → 5天"）
- [x] 质检报告含 checks（格式 / 必需字段 / 引用完整 / 敏感词）
- [x] 每个 Agent 执行过程写入 `data/audit_log.jsonl`（route/execute/quality/done 全链路）
- [x] Webhook 未配置时友好提示（502 + 配置指引），不崩溃

## 目录结构

```
zeroagent/
├── main.py                 # FastAPI 入口（知识大脑 + Agent 编排 API）
├── app/
│   ├── config.py           # 配置（环境变量可覆盖）
│   ├── ollama_client.py    # 本地 Ollama 客户端（embed + generate）
│   ├── extractor.py        # PDF/Word/Excel/MD 提取
│   ├── chunker.py          # 章节优先切分
│   ├── vector_store.py     # ChromaDB 增量向量库
│   ├── rag.py              # 检索 + 生成编排（含 retrieve 供 Agent 复用）
│   ├── agent_registry.py   # Agent 注册表（复用 tool_router schema 模式）
│   ├── agent_orchestrator.py # 路由 Agent → 专项 Agent → 质检 → 聚合
│   ├── quality_gate.py     # 质检 Agent（格式/引用/幻觉/敏感词）
│   ├── webhook_sender.py   # 企微/钉钉/飞书通知
│   ├── audit.py            # 全链路审计（audit.log + audit_log.jsonl）
│   └── static/             # Web UI（知识问答 + Agent 工作台）
├── agents/                 # 示例 Agent 配置（JSON，可自定义扩展）
│   ├── contract_review.json
│   ├── daily_report.json
│   └── customer_service.json
├── config/
│   └── webhooks.example.json  # Webhook 配置模板
├── scripts/
│   ├── make_sample_pdf.py  # 生成示例「员工手册.pdf」
│   ├── pull_models.py      # 拉取本地模型
│   ├── e2e_test.py         # 知识大脑端到端验证
│   └── e2e_agents_test.py  # 多 Agent 编排端到端验证（13 项断言）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 路线图（后续阶段）

1. ~~**业务流程自动化 Agent（主力款）**~~ ✅ 已完成：路由 Agent + 专项 Agent（合同/日报/客服）+ 质检 Agent + Webhook + 审计。
2. **私有 AI 中台（旗舰款）**：多知识库隔离、权限分级治理、模型管理、内容安全策略中心。
3. **自进化能力接入**：将 ZD 的 `auto_evolve` 引擎接入，让 Agent 能根据客户业务变化自我调整 prompt 与工具。
