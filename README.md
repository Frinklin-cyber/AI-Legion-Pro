# 🎖️ AI军团 Pro（AI Legion Pro）

> 从"衡水模式"走出来的企业 AI 改革加速引擎 —— 让 90% 的执行工作由 AI 完成，你只需做战略决策。

AI军团是一套面向中小微企业主的 **AI 数字化运营指挥系统**，将情报监控、数据分析、内容创作、任务调度、店铺诊断五大能力整合为一个"虚拟军团"，以可交互的指挥中心面板统一调度，内置 **12 种行业基因库**，可自动对店铺进行诊断分析并输出可直接落地的运营建议。

---

## 📂 仓库结构

| 路径 | 说明 |
|------|------|
| [`pro_version/ai_army/`](pro_version/ai_army/) | AI 军团主服务（FastAPI 单服务 + 指挥中心控制面板） |
| [`pro_version/zeroagent-deploy/`](pro_version/zeroagent-deploy/) | 零号智能体部署模块（多 Agent 架构，可独立部署） |
| [`AI军团Pro版产品总结文档.md`](AI军团Pro版产品总结文档.md) | 产品总结文档（v1.0） |
| [`AI军团Pro版_CodeBuddy技术需求文档.docx`](AI军团Pro版_CodeBuddy技术需求文档.docx) | 技术需求文档 |
| [`AI_Legion_Product_v1.0.zip`](AI_Legion_Product_v1.0.zip) | 产品 v1.0 交付包 |

## 🚀 快速开始

```bash
# 进入主服务目录
cd pro_version/ai_army

# 配置环境变量（复制模板后填写）
cp .env.example .env

# 启动
python main.py
# 或使用 Docker
docker compose up -d
```

详细部署与使用说明见 [`pro_version/ai_army/README.md`](pro_version/ai_army/README.md) 与 [`pro_version/zeroagent-deploy/README_部署说明.md`](pro_version/zeroagent-deploy/README_部署说明.md)。

## 🧭 五大能力

- 📡 **侦察兵** —— 情报监控：7×24 行业资讯与竞品动态爬取，DeepSeek 生成结构化简报，企微/文件推送
- 📊 **参谋部** —— 数据分析：CSV / 业务数据问答式分析，自动生成 HTML 可视化报告
- ✍️ **特种部队** —— 内容创作：批量文案 / 代码生成
- ⏰ **后勤兵** —— 任务调度：定时任务自动执行
- 🧠 **知识库** —— ChromaDB + RAG 引擎，语义检索与知识管理

## ⚙️ 技术栈

FastAPI · SQLAlchemy · ChromaDB · DeepSeek LLM · Docker · 高德/腾讯/百度 POI

---

> 详细产品设计、功能清单与验收标准请参阅本仓库根目录的产品总结文档与技术需求文档。
