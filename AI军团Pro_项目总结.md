# 🎖️ AI军团 Pro（AI 店长）— 项目总结

> 文档更新日期：2026-09-03 ｜ 本文基于**当前代码仓库实际实现**撰写，与仓库 `pro_version/ai_army` 保持一致。
> 相关文档：《AI军团Pro版产品总结文档.md》（产品/规划视角）、《产品总结文档.md》（v1.0 视角）。

---

## 一、项目概览

**一句话定位**：面向中小微企业主的 AI 数字化运营指挥系统。老板像指挥团队一样用大白话下达目标，系统里的 AI「士兵」（情报、数据、内容、调度、店铺运营等角色）自动拆解、执行、质检、审批并交付结果，即"让 AI 当员工，老板只做决策"。

| 维度 | 说明 |
|------|------|
| 交付形态 | FastAPI 单服务 + 内嵌 HTML 单页前端，本地 / 服务器直接运行 |
| 后端 | Python 3.10+ / FastAPI / SQLAlchemy(async) / APScheduler |
| AI 引擎 | DeepSeek API（OpenAI 兼容），异步调用 |
| 数据库 | SQLite（业务）+ ChromaDB（向量记忆 / RAG） |
| 前端 | 原生 HTML / CSS / JS（无构建依赖），同源 iframe 集成 |
| 认证 | 三套并行：商家账号 JWT、微信小程序 openid JWT、平台管理员 |
| 风格 | 衡水模式：量化一切 · 直击要害 · 战场隐喻 · 12 字诀 |

### 版本演进（仓库即最新版）

1. **v1.0 · AI 军团指挥中心**：五大模块（情报监控 / 数据分析 / 内容创作 / 任务调度 / 知识库）+ 行业基因库诊断。
2. **Pro 版 · AI 店长**（`/api/pro`）：一句话下目标 → 任务树 → 编排执行 → 质检重试 → 人工审批 → 积分计费 → 店铺长期记忆。对现有五大模块零侵入（仅 import 调用）。
3. **v2.0 · 多过程编排引擎**（`/api/v2`）：意图识别 → 画像补全 → 工具调用深度推理 → 多方案对比 → 执行指引。
4. **商家管理系统（多端）**：账号密码登录、商户后台（经营数据 / 员工 / 使用记录）、平台管理后台、微信小程序登录（openid）。
5. **营业数据大屏（本期新增）**：沉浸式可视化大屏，已集成进商户后台与指挥中心导航，可一键全屏 / 退出。

---

## 二、功能总览（按端）

### 1. 指挥中心面板 `/`（`index.html`）
- 军团总览：AI 战士、行业基因库、任务、知识库状态
- 六大业务能力：情报简报、内容创作（长文/短视频/朋友圈/代码）、数据分析、质检、知识库 RAG 问答、任务调度启停
- 店铺运营工具：店铺类型配置、**商家入驻引导（onboarding 分步引导）**、店铺问答/员工问答/FAQ 批量、AI 诊断、竞品监控（watchlist）、品牌命名建议、经营数据上传、地理位置检索
- **入口**：左侧导航「📡 营业数据大屏」→ 沉浸全屏打开大屏页，右上角常驻「返回指挥部」按钮 / `Esc` 退出

### 2. 商户后台 `/dashboard`、`/merchant`（`merchant_dashboard.html`）
- 账号密码注册登录（JWT 7 天），登录后直达
- 经营看板：门店统计（`/api/dashboard/stats`）、个人资料、员工管理（admin/operator/viewer 三角色）、AI 使用记录
- 菜单内含**营业数据大屏**入口（全屏覆盖层实现，同指挥中心一致，右上角常驻「返回商家后台」按钮）

### 3. 营业数据大屏 `/static/live_bigscreen.html`（`live_bigscreen.html`）
- 全屏可视化：指标卡 + 营业趋势 + 品类构成 + 时段热力 + 订单流水日志，每 2.5s 滚动一帧（内置 Mock 数据源）
- 独立 URL 可投屏 / 电视 / 浏览器全屏；内部同源 iframe 由父页面调用
- 真实数据接入：仅需修改文件顶部 `CFG.wsUrl`（预留 WebSocket 通道），数据字段结构与 Mock 样本一致

### 4. AI 店长（Pro）`/api/pro`
老板一句话 → AI 店长全流程代跑：
- **编排**：目标 → JSON 任务树（部门 / 动作 / 依赖 / 预估积分 / 是否需审批），老板可增删改后确认
- **执行**：依赖分层 + 并行执行 + 进度轮询；每步 `等待中 → 执行中 → 质检中 → 通过/重试(≤2 次)/失败`
- **质检审批**：quality_agent 评分把关；高风险动作（发企微 / 定时发布）必须老板确认才执行
- **计费**：预扣 + 多退少补 + 流水可查；**周期任务**（cron）服务重启自动恢复
- **记忆**：按 store_id 分 collection 持久化店铺历史，越用越懂这家店

### 5. 平台管理后台 `/admin-login`、`/admin/**`（`admin_dashboard.html`）
- 平台管理员登录、商户列表与启停、平台统计、用户数据查看

### 6. 微信小程序端（开放 API，`/api/auth/wx-login`）
- code2session 换取 openid JWT（72h），老版 admin 用户体系基于 JSON 文件 + 数据隔离

---

## 三、行业基因库

`config/industry_genome/*.yaml`，共 **12 个行业模板**（含 custom），每个 YAML 定义行业指标、诊断维度与话术，支撑「自动识别行业 → 一键 AI 诊断」：

`restaurant 餐饮 / retail 零售 / education 教育培训 / healthcare 健康养生 / hotel 酒店民宿 / real_estate 房产中介 / fitness 健身 / florist 花店 / entertainment 休闲娱乐 / auto 汽车服务 / service 生活服务 / custom 自定义`

> 另有 `config/prompts/`（分析/内容/质检/orchestrator/衡水语调库）与 `config/store_templates.py`（各行业模板）。

---

## 四、代码结构（`pro_version/ai_army/`）

```
ai_army/
├── main.py                        # FastAPI 入口：挂载路由 + 页面 FileResponse + 全局实例
├── alembic/  alembic.ini          # 数据库迁移（SQLite：zhitan_ai.db）
├── config/
│   ├── env.py                     # 环境变量管理
│   ├── industry_genome/           # 12 个行业 YAML 基因库
│   ├── store_templates.py         # 行业模板（40KB）
│   └── prompts/                   # 分析/内容/质检/AI店长 orchestrator/衡水语调库
├── seed_data.py                   # 演示数据播种脚本
├── Dockerfile / docker-compose.yml
├── requirements.txt               # 核心依赖（fastapi/pandas/openai/chromadb/celery/apscheduler/jwt…）
└── src/
    ├── core.py                    # AI 战士基类 BaseSoldier（chat/run/重试/日志）
    ├── admin/                     # 老版平台用户管理（JSON）+ admin dashboard 前端
    ├── auth/                      # merchant_auth.py（bcrypt+JWT）/ wechat.py（openid JWT）
    ├── command/                   # 指挥中枢
    │   ├── dispatcher.py          # CommandDispatcher 任务分发 + 任务状态机
    │   ├── quality_checker.py     # 质量审核
    │   ├── dashboard/             # ★ 全部 HTML 前端（见「页面清单」）
    │   └── pro/                   # ★ Pro「AI 店长」增量层（11 个文件）
    ├── data/                      # users.json（微信老体系）
    ├── db/                        # models.py（9 张表）/ deps.py（get_db、JWT 鉴权依赖）
    ├── knowledge/                 # vector_store.py（ChromaDB）/ rag_engine.py（RAG）
    ├── logistics/                 # task_scheduler.py（APScheduler）/ python_tasks.py（自动化脚本）
    ├── models/schemas.py          # Pydantic 响应模型（诊断/KPI/简报…）
    ├── orchestrator/              # ★ v2.0 多过程编排引擎（/api/v2）
    ├── routers/                   # auth_routes / merchant_routes / admin_routes
    ├── scouts/                    # 侦察兵：crawler / summarizer / push(企微·飞书·文件) / data_parser
    ├── shop/                      # 店铺运营：geo 地理编码 / 诊断 / 竞对 / 商家数据等
    ├── special_forces/            # 特种部队：content_gen / code_gen / image_gen(文生图)
    └── staff/                     # 参谋部：data_agent / attribution_analyzer(深度归因) / reporter
```

**Pro 版「AI 店长」核心文件**（`src/command/pro/`，11 个）：

| 文件 | 职责 |
|------|------|
| `orchestrator.py` | 主代理：目标 → JSON 任务树 + 记忆注入 |
| `workflow_engine.py` | 编排：依赖分层 / 并行 / 预扣 / 质检重试 / 结算 |
| `quality_agent.py` | 质检 Agent（approved/score/feedback/must_fix） |
| `approval_gate.py` | 人工审批网关（待审批动作列表） |
| `executor.py` | 执行手脚：分发到各业务模块 |
| `billing.py` | 积分：充值/预扣/退还/结算/流水 |
| `memory.py` | 店铺长期记忆（ChromaDB 按 store_id 分 collection） |
| `scheduler_pro.py` | 周期任务调度（重启自动恢复） |
| `runtime.py` | 执行单/步骤状态内存（供前端轮询） |
| `routes.py` | `/api/pro` 路由（12 个接口） |

---

## 五、页面清单（`src/command/dashboard/`）

| 页面文件 | URL | 角色 | 说明 |
|----------|-----|------|------|
| `login.html` | `/login` | 商家 | 登录 / 注册 |
| `merchant_dashboard.html` | `/dashboard`、`/merchant` | 商家 | 商户后台（含大屏入口 + 全屏层） |
| `index.html` | `/` | 老板/运营 | 指挥中心面板（含大屏入口 + 全屏层） |
| `live_bigscreen.html` | `/static/live_bigscreen.html` | 展示 | 营业数据大屏（独立页，Mock 数据） |
| `admin_dashboard.html` | `/admin-login`、`/admin/**` | 平台管理员 | 管理后台 |

> 大屏集成机制：父页面内建 `#bigscreenLayer` 全屏覆盖层 + 同源 `<iframe>` 懒加载 `live_bigscreen.html`；`openBigscreen()/closeBigscreen()` 控制；退出支持右上角常驻按钮、`Esc`（父页 + iframe 双监听），退出后恢复原导航高亮。

---

## 六、API 一览（路由前缀）

| 前缀 | 来源 | 主要接口 |
|------|------|----------|
| `/auth` | `routers/auth_routes.py` | `POST /register`、`POST /login`、`GET /me`（商家 JWT，7 天） |
| `/api/dashboard` | `routers/merchant_routes.py` | `GET /stats`、`GET/PUT /profile`、`GET/POST /employees`、`DELETE /employees/{id}`、`GET /usage-logs` |
| `/api/admin` | `routers/admin_routes.py` + main.py | `POST /login`、`GET /merchants`、`PUT /merchants/{tid}/toggle`、`GET /stats`、`GET /users`… |
| `/api/pro` | `src/command/pro/routes.py` | `POST /goal`、`PUT /plan/{id}`、`POST /execute/{id}`、`GET /execution/{id}/status`、`POST /approve`、`POST /recharge`、`GET /balance/{sid}`、`POST /schedule`、`GET /schedules/{sid}`、`POST /schedule/{id}/toggle`、`GET /templates`、`GET /transactions/{sid}` |
| `/api/v2` | `src/orchestrator/routes.py` | 多过程编排（意图识别 → 深度推理 → 方案对比） |
| `/api`（main.py 内联） | — | `status/missions/soldiers`、`briefing/generate`、`content/generate`、`video/*`、`code/generate`、`data/analyze`、`quality/review`、`knowledge/*`、`scheduler/*`、`store/*`（types/type/config/onboarding/chat/analyze/diagnosis/competitor/merchant-data/brand-suggest…）、`geocode/search`、`dashboard/summary`、`auth/wx-login` |

---

## 七、数据库（`src/db/models.py`，SQLite）

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `merchants` | 商家主体 | tenant_id、account、密码哈希、状态 |
| `shop_users` | 店铺员工 | role：admin/operator/viewer |
| `business_data` | 商家经营数据 | 上传的经营数据记录 |
| `usage_logs` | AI 使用日志 | 供后台统计 / 计费依据 |
| `balances` | 积分余额 | store_id 主键、balance |
| `transactions` | 积分流水 | recharge/deduct/refund/settle |
| `plans` | Pro 执行计划 | goal、plan_json 任务树、estimated_cost、status |
| `approvals` | 人工审批队列 | action、payload、pending/approved/rejected |
| `schedules` | Pro 周期任务 | goal、cron、enabled、last_run_at |

> 初始化：`init_db()` 自动建表；另有 alembic 迁移支持后续演进。

---

## 八、启动与部署

```bash
# 方式一：Windows 一键启动（推荐）
双击 pro_version/start_server.bat   # 或直接在其中执行 python main.py

# 方式二：手动
cd pro_version/ai_army
pip install -r requirements.txt
python main.py                        # 默认端口 8000（uvicorn）

# 访问入口
# http://localhost:8000/login          → 商家登录（注册演示账号后进入商户后台）
# http://localhost:8000/dashboard      → 商户后台（别名 /merchant）
# http://localhost:8000/               → 指挥中心面板
# http://localhost:8000/static/live_bigscreen.html → 营业数据大屏（独立投屏）
# http://localhost:8000/admin-login    → 平台管理后台
```

**关键配置**（`.env`）：`DEEPSEEK_API_KEY`（AI 必需）、企业微信 Webhook（推送/发布）、地图 AK（地址联想，高德/腾讯/百度多源兜底）。

**试运行已覆盖**：注册演示商户 → 登录 → 商家后台各面板 → 指挥中心导航 → 大屏全屏进出 → 退出按钮点击/Esc 均验证通过。

---

## 九、本期（2026-09 会话）工作记录

1. **营业数据大屏集成进产品**
   - 商户后台（`merchant_dashboard.html`）与指挥中心（`index.html`）左侧导航新增「营业数据大屏」入口
   - 点击后沉浸式全屏打开大屏（iframe 懒加载 `live_bigscreen.html`），侧栏/主框架自动隐藏
2. **大屏退出体验修复**
   - 原退出按钮仅在悬停右上角隐形热区时出现 → 改为**右上角常驻半透明按钮**（悬停变亮）
   - 底部操作提示常驻：「点右上角按钮 或 按 ESC 键退出」，不再数秒后自动消失
   - 双端（父页 + 同源 iframe）同时监听 `Esc`；退出后恢复原视图高亮
3. **验证记录**：JS 语法校验通过；浏览器实测 登录 → 导航进大屏 → 按钮可见可点 → 退出回后台，全链路正常。

---

## 十、当前状态与后续事项

- [x] 多端登录 / 鉴权（商家、管理员、微信）
- [x] 商户后台与指挥中心全功能可用
- [x] 大屏集成与退出体验
- [ ] 大屏接入真实数据：改 `live_bigscreen.html` 顶部 `CFG.wsUrl` 为后端 WebSocket 地址（当前为 Mock 2.5s/帧）
- [ ] 生产环境 PostgreSQL 切换（依赖已预留 asyncpg 注释）
- [ ] 微信小程序端 UI 联调（后端 openid 登录已就绪）

---

## 附：相关文档

| 文档 | 视角 |
|------|------|
| `AI军团Pro版产品总结文档.md` | Pro 版产品规划与验收（根目录） |
| `产品总结文档.md` | v1.0 产品定位与模块说明（根目录） |
| `pro_version/产品总结文档.md` | 仓库内产品说明 |
| `pro_version/ai_army/README.md` | 代码仓快速上手 |
| `pro_version/zeroagent-deploy/` | 部署工具集（README_部署说明） |
