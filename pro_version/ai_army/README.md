# 🎖️ AI军团 — 企业AI改革加速引擎

> 从"衡水模式"走出来的个人AI军团，让90%的执行工作由AI完成，你只需做战略决策。

---

## 📖 目录

- [架构概览](#架构概览)
- [快速开始](#快速开始)
- [五大模块](#五大模块)
- [使用示例](#使用示例)
- [部署指南](#部署指南)
- [开发路线图](#开发路线图)

---

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                  第一层：指挥中心（你）                 │
│              定战略 · 分任务 · 判质量 · 做决策           │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│ 第二层    │ 第三层    │ 第四层    │ 第五层    │ 中枢     │
│ 侦察兵    │ 参谋部    │ 特种部队  │ 后勤兵    │ 知识库   │
│          │          │          │          │         │
│ 7x24     │ 数据分析  │ 内容创作  │ 任务自动  │ ChromaDB │
│ 情报监控  │ 策略建议  │ 代码生成  │ 定时调度  │ RAG引擎  │
│          │          │          │          │         │
│ 爬虫     │ Pandas   │ DeepSeek │ n8n      │ 向量检索 │
│ DeepSeek │ DeepSeek │ Midjourney│ Celery   │ 语义问答 │
│ 企微推送  │ HTML报告  │ 批量产出  │ 邮件/DB  │ 知识管理 │
└──────────┴──────────┴──────────┴──────────┴─────────┘
```

### 技术栈

| 层级 | 技术选型 |
|------|----------|
| **后端** | FastAPI + Python 3.10+ |
| **AI引擎** | DeepSeek API（OpenAI兼容） |
| **数据库** | ChromaDB（向量） + Redis（队列） |
| **任务调度** | Celery + Celery Beat |
| **容器化** | Docker + Docker Compose |
| **部署** | 腾讯云Lighthouse / 任意VPS |

---

## 快速开始

### 前置条件

- Python 3.10+
- Redis（可选，用于异步任务队列）
- DeepSeek API Key（[获取地址](https://platform.deepseek.com)）
- 企业微信机器人 Webhook URL（可选，用于消息推送）

### 5分钟部署

```bash
# 1. 克隆项目
cd ai_army

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 DEEPSEEK_API_KEY

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务
python main.py

# 5. 打开浏览器
# http://localhost:8000 → 指挥中心面板
```

### Docker 一键部署

```bash
# 配置环境变量后
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f command-center
```

---

## 五大模块

### 📡 模块1：情报监控机器人（侦察兵）

```python
from src.scouts.crawler import crawl_all
from src.scouts.summarizer import IntelligenceSummarizer
from src.scouts.push import push_briefing

# 爬取资讯
news = crawl_all()

# AI生成简报
summarizer = IntelligenceSummarizer()
result = summarizer.execute({"items": news, "focus_keywords": ["AI大模型", "企业服务"]})

# 推送
push_briefing(result["briefing"], channels=["wecom", "file"])
```

### 📊 模块2：数据分析Agent（参谋部）

```python
from src.staff.data_agent import DataAnalyst
from src.staff.reporter import save_report

analyst = DataAnalyst()
analyst.load_data("data/sales_2024.csv")

# 数据分析提问
report = analyst.ask_question("分析Q3销售下滑的根因，给出3条可执行的建议")

# 生成HTML报告
save_report(report, fmt="html")
```

### ✍️ 模块3：内容创作流水线（特种部队）

```python
from src.special_forces.content_gen import ContentCreator, BatchGenerator

creator = ContentCreator()

# 生成长文
article = creator.create_article("企业AI改革的第一性原理")

# 生成短视频脚本
script = creator.create_video_script("怎么用AI省下80%人工成本")

# 批量生成朋友圈
batch = BatchGenerator()
result = batch.execute({"template": "weekly_posts", "topic": "中小企业AI改革", "count": 7})
```

### ⚙️ 模块4：自动化工作流（后勤兵）

```python
from src.logistics.task_scheduler import TaskScheduler
from src.logistics.python_tasks import send_email, backup_database, clean_temp_files

scheduler = TaskScheduler()

@scheduler.cron("0 8 * * *")
def daily_briefing():
    """每天8:00 发送情报简报"""
    ...

@scheduler.interval(hours=4)
def health_check():
    """每4小时健康检查"""
    ...

scheduler.start()
```

### 🎛️ 模块5：指挥中心控制面板

```python
from src.command.dispatcher import CommandDispatcher
from src.command.quality_checker import QualityChecker

# 任务分发
dispatcher = CommandDispatcher()
dispatcher.register_soldier(summarizer)
mission = dispatcher.dispatch("scout_summarizer", {...})

# 质量审核
checker = QualityChecker()
report = checker.review_output(content, task_type="情报简报")
print(f"质量分: {report.overall_score}/100")
```

---

## 部署指南

### 单机部署（推荐入门）

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 .env
cp .env.example .env
nano .env  # 填入 DEEPSEEK_API_KEY

# 启动
python main.py
# 访问 http://localhost:8000
```

### Docker Compose 部署（推荐生产）

```bash
# 完整启动（含Redis + Celery）
docker-compose up -d

# 只启动Web面板
docker-compose up -d command-center redis

# 停止
docker-compose down
```

### 腾讯云 Lighthouse 部署

```bash
# 1. SSH登录服务器
ssh root@your-server-ip

# 2. 安装Docker
curl -fsSL https://get.docker.com | sh

# 3. 上传项目
scp -r ai_army/ root@your-server-ip:/opt/

# 4. 启动
cd /opt/ai_army
docker-compose up -d
```

---

## 衡水人设语调库

本项目的"灵魂"是**衡水模式**驱动的品牌语调：

| 特点 | 说明 |
|------|------|
| **量化一切** | 能写"转化率+37%"绝不写"显著提升" |
| **直击要害** | 不看"建议关注"，要看"周一前做这3步" |
| **战场隐喻** | 商业竞争就是"AI军备竞赛" |
| **12字诀** | 目标量化→拆解执行→死磕细节→复盘迭代 |

详见 [`config/prompts/brand_tone_library.md`](config/prompts/brand_tone_library.md)

---

## 项目结构

```
ai_army/
├── main.py                     # FastAPI 入口
├── config/
│   ├── env.py                  # 环境变量管理
│   ├── tasks.yaml              # 定时任务配置
│   └── prompts/                # Prompt模板
│       ├── analysis_prompts.py # 数据分析Prompt
│       ├── content_prompts.py  # 内容创作Prompt
│       └── brand_tone_library.md # 品牌语调库
├── src/
│   ├── core.py                 # AI战士基类
│   ├── scouts/                 # 侦察兵模块
│   │   ├── crawler.py          # 爬虫引擎
│   │   ├── summarizer.py       # AI摘要生成
│   │   └── push.py             # 消息推送
│   ├── staff/                  # 参谋部模块
│   │   ├── data_agent.py       # 数据分析Agent
│   │   └── reporter.py         # 报告生成器
│   ├── special_forces/         # 特种部队模块
│   │   ├── content_gen.py      # 内容创作引擎
│   │   └── code_gen.py         # AI代码生成
│   ├── logistics/              # 后勤兵模块
│   │   ├── task_scheduler.py   # 定时调度器
│   │   └── python_tasks.py     # 自动化脚本集
│   ├── command/                # 指挥中心
│   │   ├── dispatcher.py       # 任务调度器
│   │   ├── quality_checker.py  # 质量审核
│   │   └── dashboard/          # 控制面板
│   └── knowledge/              # 知识库中枢
│       ├── vector_store.py     # ChromaDB封装
│       └── rag_engine.py       # RAG引擎
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## 开发路线图

### ✅ P0（已完成）
- [x] 情报监控机器人（爬虫+摘要+推送）
- [x] 内容创作Prompt模板库（含衡水人设）
- [x] 数据分析Agent MVP
- [x] 指挥中心控制面板原型

### 🔄 P1（进行中）
- [ ] 自动化工作流引擎（连接日历+邮箱+DB）
- [ ] 知识库中枢完善（自动分块+多格式支持）
- [ ] 质量趋势分析面板

### 📋 P2（规划中）
- [ ] 多AI协同作战（Agent间自动传递任务）
- [ ] 三层质检自动化闭环
- [ ] 进化反馈回路

---

## 许可证

MIT License — 个人创业者自由使用

---

**🎯 现在就开始：** 复制 `.env.example` → 填入API Key → `python main.py` → 打开 `localhost:8000`
