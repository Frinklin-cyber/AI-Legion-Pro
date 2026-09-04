# 🎖️ AI军团 Pro 版（AI 店长）— 让 AI 当员工，老板只做决策

> **一句话定位**：普通版是「AI 工具箱」（老板自己动手），Pro 版是「AI 员工」（老板说话、AI 干活）——新增「主代理 + 编排引擎 + 质检/审批」三层，把"下达指令 → 拆解任务 → 自动执行 → 质检重试 → 人工审批 → 发布交付"全流程交给 AI 店长打理。

---

## 一、产品概述

AI军团 Pro 版在已上线的 v1.0（AI 军团指挥中心）之上，增量叠加一套 **「AI 店长」智能体系统**。

老板不再需要逐个点按钮（诊断一下 / 写一篇 / 发一条），而是像给员工布置工作一样，**一句话下达目标**，例如：

> "策划本周末的引流活动，先诊断店铺现状，再生成一套朋友圈+抖音文案，最后安排定时发布"

AI 店长会把这句话拆解成**有序任务树**（侦察兵查竞品 → 参谋部诊断 → 创作部写文案 → 后勤兵定时发布），生成计划给你确认，确认后自动执行；每步产出经过**质检 Agent** 把关，对外发布前必须**老板点确认**；积分**预扣 + 多退少补**，清清楚楚。

### 产品愿景
| 维度 | 说明 |
|------|------|
| 目标用户 | 中小微企业主 / 个体经营者 / 门店老板（已购买 v1.0 的老客户优先升级） |
| 核心价值 | 老板从"操作员"升级为"管理者"，90% 执行工作由 AI 员工完成 |
| 独特风格 | 延续衡水模式：量化一切 · 直击要害 · 战场隐喻 |
| 交付形态 | 在 v1.0 同仓库内增量交付，**现有五大模块一行不改** |
| 商业模式 | 积分制：充值 → 按任务扣费（多退少补），天然具备付费与续费入口 |

---

## 二、Pro 版核心功能（9 项确认）

### 1. 一句话下达指令 💬
- 聊天式输入框，老板用大白话布置任务
- 上方一排**快捷模板按钮**（周末引流 / 周度计划 / 新品推广 / 店铺诊断），一键预填目标

### 2. 执行前计划确认 📋
- AI 店长生成 **JSON 任务树**：每个步骤含部门、动作、依赖、预估积分、是否需审批
- 老板可**增删改步骤、调整顺序**，确认后才执行（`PUT /plan/{plan_id}`）

### 3. 执行中全程可见 👀
- 步骤列表 + 进度轮询，每步状态实时展示：
  `等待中 → 执行中 → 质检中 → 质检通过 → 已完成`
  （不通过会进入 `质检重试`，失败则标记 `失败`，不影响其他步骤）

### 4. 自动质检重试 ✅
- `quality_agent` 按行业基因库规范评估每步产出（评分 1-10）
- 不通过自动重试（**最多 2 次**），并注入修改意见，无需老板介入

### 5. 产出可编辑 ✏️
- 每一步最终产出（文案 / 报告 / 诊断）都可查看与编辑

### 6. 人工审批发布 🔐
- 高风险动作（发企微、定时发布）默认 `needs_approval=true`
- 老板点确认后由执行手脚自动推送，**不点就不动**

### 7. 预估扣费 + 多退少补 💰
- 生成任务树时预估积分（店铺诊断 12 / 文案生成 5 / 竞品情报 8 / 分析报告 15 / 定时发布 3）
- 执行时预扣，执行完按实际消耗结算，差额自动退/补，全程流水可查

### 8. 周期任务 ⏰
- 老板设置 cron 任务（如"每周一 8:00 生成下周朋友圈计划"）
- 后勤兵按点触发，跑完结果推送到企业微信供老板确认
- **服务重启后自动恢复**已启用任务

### 9. 店铺长期记忆 🧠
- ChromaDB 按 `store_id` 分 collection 持久化店铺历史（诊断报告 / 文案 / 改稿记录）
- AI 店长每次编排前自动注入最近记忆，越用越懂这家店

---

## 三、整体架构（三层增量）

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1   AI 店长（主代理） orchestrator.py               │
│            目标 → JSON 任务树  +  注入店铺长期记忆          │
├──────────────────────────────────────────────────────────┤
│  Layer 2   任务编排引擎 workflow_engine.py                 │
│            依赖分层 · 并行执行 · 积分预扣 · 自动质检重试     │
├──────────────────────────────────────────────────────────┤
│  Layer 3   质检 + 人工审批网关                             │
│            quality_agent.py  →  approval_gate.py → 发布   │
└──────────────────────────────────────────────────────────┘
              │                 │
   ┌──────────▼─────┐   ┌───────▼────────┐
   │ 现有五大模块    │   │  积分/审批/计划  │
   │ 侦察兵·参谋部   │   │  SQLite 新增 5 表 │
   │ 创作部·后勤兵   │   │  balances ...   │
   │ 知识库(只读调用) │   │  schedules ...  │
   └────────────────┘   └────────────────┘
```

| 层级 | 职责 | 核心文件 |
|------|------|----------|
| Layer 1 | 目标理解 → 任务拆解 → 预估费用 → 标记审批 | `orchestrator.py` |
| Layer 2 | 依赖调度、并行执行、积分预扣、质检重试、结算 | `workflow_engine.py` |
| Layer 3 | 产出质检 + 人工审批 + 发布执行 | `quality_agent.py` / `approval_gate.py` / `executor.py` |

---

## 四、新增文件清单

全部位于 `ai_army/src/command/pro/`（`__init__.py` 描述整体架构）：

| 文件 | 角色 | 说明 |
|------|------|------|
| `orchestrator.py` | AI 店长主代理 | 读 `config/prompts/orchestrator.md`，输出 JSON 任务树，含快捷模板 |
| `workflow_engine.py` | 编排引擎 | 依赖分层、并行执行、质检重试（最多 2 次）、多退少补结算 |
| `quality_agent.py` | 质检 Agent | 读 `config/prompts/quality.md`，按行业基因规范评分，输出 approved/score/feedback/must_fix |
| `approval_gate.py` | 人工审批网关 | 高风险动作创建审批单，老板确认后才发布 |
| `executor.py` | 执行手脚 | 动作分发：发企微/生成文案/爬取情报/数据分析/店铺诊断/定时发布/存报告 |
| `billing.py` | 积分计费 | 充值/预扣/退还/结算/流水，含默认单价表 |
| `memory.py` | 店铺长期记忆 | ChromaDB 按 store_id 分 collection 存取 |
| `scheduler_pro.py` | 周期任务调度 | 复用现有 TaskScheduler，重启自动恢复 |
| `runtime.py` | 运行时状态 | 执行单/步骤状态内存存储（供前端轮询） |
| `routes.py` | Pro 版 API | 9 个核心路由 + 3 个辅助路由，`prefix=/api/pro` |

**需修改的现有文件（仅 2 处，均为增量）：**
- `main.py` — ① `app.include_router(pro_router)` ② 调度器绑定 + 周期任务恢复
- `src/db/models.py` — 追加 5 张新表（数据层，非业务模块）

**新增 Prompt：**
- `config/prompts/orchestrator.md` — AI 店长 System Prompt（部门介绍 / 拆解原则 / 输出 Schema）
- `config/prompts/quality.md` — 质检 Agent System Prompt（5 维评分标准 / 打分区间 / 输出 Schema）

---

## 五、数据库新增表（5 张）

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `balances` | 积分余额 | store_id(主键)、balance |
| `transactions` | 积分流水 | store_id、type(recharge/deduct/refund/settle)、amount、plan_id |
| `plans` | 执行计划 | id、store_id、goal、plan_json(任务树)、estimated_cost、status |
| `approvals` | 人工审批队列 | id、store_id、plan_id、action、payload、status(pending/approved/rejected) |
| `schedules` | 周期任务 | id、store_id、goal、cron、enabled、last_run_at |

> 由现有 `init_db()` 自动建表（SQLAlchemy 模型注册后 `create_all`），无需手动迁移。

---

## 六、API 接口（9 个核心 + 3 个辅助）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/pro/goal` | 目标 → 任务树（draft 计划，含预估积分） |
| PUT | `/api/pro/plan/{plan_id}` | 修改任务树（增删改步骤/调顺序）→ 重算预估积分 |
| POST | `/api/pro/execute/{plan_id}` | 确认后开始执行 → 返回 exec_id |
| GET | `/api/pro/execution/{exec_id}/status` | 各步骤进度轮询 |
| POST | `/api/pro/approve` | 人工审批（通过则自动发布） |
| POST | `/api/pro/recharge` | 积分充值（1 元 = 1 积分） |
| GET | `/api/pro/balance/{store_id}` | 查询余额 |
| POST | `/api/pro/schedule` | 创建周期任务（cron） |
| GET | `/api/pro/schedules/{store_id}` | 周期任务列表 |
| POST | `/api/pro/schedule/{id}/toggle` | 周期任务启停（辅助） |
| GET | `/api/pro/templates` | 快捷模板列表（辅助） |
| GET | `/api/pro/transactions/{store_id}` | 积分流水（辅助） |

---

## 七、端到端交互流程（8 步）

```
① 老板下达目标（POST /goal）
       │
② AI 店长拆解任务树 + 预估积分（记忆注入）
       │
③ 老板增删改步骤 / 调顺序（PUT /plan）【确认】
       │
④ 开始执行（POST /execute）→ 预扣积分
       │
⑤ 前端轮询进度（GET /execution/{id}/status）
       │     ┌─────────────────────────────┐
       │     │ 每步：执行 → 质检 → 不通过重试×2 │
       ▼     └─────────────────────────────┘
⑥ 高风险动作 → 待审批（GET 轮询到 needs_approval）
       │
⑦ 老板点确认（POST /approve）→ 执行手脚自动推送
       │
⑧ 结算多退少补 + 产出入店铺记忆（等待下次更懂你）
```

---

## 八、技术架构

| 层级 | 技术选型（Pro 新增标注 ★） |
|------|----------|
| 后端 | FastAPI + Python 3.10+（全异步 async/await ★） |
| AI 引擎 | DeepSeek API（OpenAI 兼容，`AsyncOpenAI` ★） |
| 编排 | 自研 WorkflowEngine：依赖拓扑 + asyncio.gather 并行 ★ |
| 向量记忆 | ChromaDB 按 store_id 分 collection（复用现有 VectorStore） |
| 数据库 | SQLite（新增 5 张 Pro 表） |
| 任务调度 | 复用现有 TaskScheduler（APScheduler），零新增依赖 |
| 推送 | 复用现有企业微信机器人 |

**技术约束落实情况：**
- ✅ 现有五大业务模块（侦察兵/参谋部/创作部/后勤兵/知识库）**零修改**，仅 import 调用
- ✅ 全部新代码 `async/await` + 类型注解
- ✅ 单任务失败不影响其他任务（并行批次独立捕获）
- ✅ 质检重试、审批、计费、周期任务全部落库/可追踪

---

## 九、快速启动（与 v1.0 完全一致）

```bash
cd ai_army
pip install -r requirements.txt
# 确认 .env 已配置 DEEPSEEK_API_KEY（Pro 版 AI 店长必需）
python main.py
# 打开 http://localhost:8080
```

### 配置说明
- `DEEPSEEK_API_KEY` — DeepSeek 密钥（AI 店长 / 质检必需）
- 企业微信 Webhook（`WECOM_WEBHOOK_URL`）— 发布与周期任务推送（可选）
- 首次启动自动初始化数据库（含 Pro 版 5 张新表）

### 体验路径
1. `POST /api/pro/recharge` 充值 100 积分
2. `POST /api/pro/goal` 下达目标（或用模板）
3. `PUT /api/pro/plan/{plan_id}` 确认/修改任务树
4. `POST /api/pro/execute/{plan_id}` 执行
5. 轮询 `GET /api/pro/execution/{exec_id}/status`
6. `POST /api/pro/approve` 审批发布

---

## 十、目录结构（Pro 新增部分）

```
ai_army/
├── main.py                      # 【改】新增 include_router + 调度器绑定
├── config/
│   └── prompts/
│       ├── orchestrator.md      # 【新】AI 店长 System Prompt
│       └── quality.md           # 【新】质检 Agent System Prompt
├── src/
│   ├── db/
│   │   └── models.py            # 【改】追加 5 张 Pro 表
│   └── command/
│       └── pro/                 # 【新】Pro 版增量层（10 个文件）
│           ├── orchestrator.py  ├── workflow_engine.py
│           ├── quality_agent.py ├── approval_gate.py
│           ├── executor.py      ├── billing.py
│           ├── memory.py        ├── scheduler_pro.py
│           ├── runtime.py       └── routes.py
└── data/                        # 【运行时】SQLite + 店铺记忆向量库
```

---

## 十一、本版亮点（Pro 版交付重点）

1. **从工具箱到员工**：老板一句话，AI 店长全流程代跑，管理半径翻倍
2. **零侵入升级**：五大模块零改动，升级 = 解压 + 配 key + 重启
3. **质量闭环**：自动质检 + 最多 2 次重试，产出不过关不出门
4. **安全发布**：对外动作必须老板确认，AI 永不越权
5. **积分商业闭环**：预扣 + 多退少补 + 流水可查，付费转化路径清晰
6. **越用越懂**：店铺长期记忆，诊断与文案持续贴合店铺历史

---

## 十二、许可

MIT License — 个人创业者自由使用

**🎯 升级路径：** 将 `_v1_extracted/ai_army` 整体替换到线上项目 → 确认 `.env` → 重启 → 进入 Pro 版「AI 店长」体验一句话运营。
