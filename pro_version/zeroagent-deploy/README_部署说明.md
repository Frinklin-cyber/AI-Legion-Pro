# ZEROagent · 企业知识大脑 — 部署说明

私有化部署包。所有处理（向量化 / 检索 / 生成）均在本地完成，**数据不出域**，不调用任何公网 AI API。

## 部署方式二选一

### 方式 A：Docker 一键部署（推荐，隔离干净）

前置：目标机器已安装 Docker（Windows 装 Docker Desktop 并启动）。

```bash
cd zeroagent-deploy
docker compose up --build
# 首次启动：拉取本地模型（模型也跑在本地容器内，不触网）
docker compose exec app python scripts/pull_models.py
# 访问 http://localhost:8000
```

- 数据持久化在 `./data/`，删除容器不丢失。
- 模型持久化在 Docker 卷 `ollama_data`。

### 方式 B：裸机部署（Windows / Linux）

前置：Python 3.11+ 与 [Ollama](https://ollama.com/download) 已安装并启动。

**Windows**：双击 `start_windows.bat`（自动装依赖、拉模型、启动并打开浏览器）。
**Linux/macOS**：`bash start_linux.sh`（自动装依赖、拉模型、后台启动）。

手动流程：
```bash
pip install -r requirements.txt
ollama pull nomic-embed-text   # 向量模型 (~274MB)
ollama pull qwen2.5:7b         # 问答模型 (~4.7GB)
python main.py                 # → http://localhost:8000
```

## 使用

1. 打开 `http://localhost:8000`。
2. 左侧「知识库」上传 PDF / Word / Excel / TXT / Markdown 文档（支持批量，自动切分向量化）。
3. 右侧对话框直接提问，AI 依据内置人格自主回答：命中资料会**标注引用来源**；资料不足会坦诚说明不确定程度；无资料会给出补充方向。
4. 回答下方低调的 👍👎 用于反馈（写入 `data/feedback/`，供后续优化）。
5. 文档可随时删除（回收站图标），删除后对应向量一并清除。

## 多 Agent 工作台

左侧「Agent 工作台」可运行合同审核 / 日报生成 / 客服回复等专项 Agent，全程写入审计日志 `data/audit_log.jsonl`。通知 webhook 参考 `config/webhooks.example.json` 配置。

## 数据与备份

- 向量库 `data/vectordb/`、上传原文件 `data/uploads/`、审计 `data/audit_log.jsonl`、反馈 `data/feedback/`。
- 备份：直接复制 `data/` 目录即可（迁移到新机器时连同整个部署包一起拷贝）。

## 常见问题

| 问题 | 解决 |
|------|------|
| 8000 端口被占用 | 修改 `main.py` 末尾端口，或 `docker-compose.yml` 映射端口 |
| 页面报“无法连接本地模型服务” | 确认 Ollama 已启动（Windows 托盘图标 / `ollama serve`） |
| 上传中文文件名乱码 | 使用 `start_windows.bat` 启动（已设置 UTF-8 代码页） |
| 首次提问较慢 | qwen2.5:7b 为 CPU/GPU 本地推理，首次加载模型需数十秒属正常 |
| 想换问答模型 | 修改 `docker-compose.yml` 或 `app/config.py` 的 `LLM_MODEL`，并 `ollama pull` 对应模型 |

## 交付说明

本包已清空运行时数据（向量库 / 上传文件 / 审计日志），首次启动后全新生成。
