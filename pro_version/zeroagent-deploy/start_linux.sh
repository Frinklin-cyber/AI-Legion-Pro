#!/usr/bin/env bash
# ZEROagent 企业知识大脑 - 一键启动 (Linux/macOS)
set -e
cd "$(dirname "$0")"

echo "============================================"
echo " ZEROagent 企业知识大脑 - 一键启动 (Linux)"
echo "============================================"

# 1. 检查 Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 未检测到 Python3，请先安装 Python 3.11+"
  exit 1
fi

# 2. 安装依赖
echo "[1/4] 安装 Python 依赖..."
python3 -m pip install -r requirements.txt

# 3. 检查 Ollama
if ! command -v ollama >/dev/null 2>&1; then
  echo "[错误] 未检测到 Ollama，请先安装:"
  echo "       curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "[提示] Ollama 未在运行，尝试后台启动..."
  nohup ollama serve >/dev/null 2>&1 &
  sleep 3
fi

# 4. 拉取本地模型（数据不出域）
echo "[2/4] 检查并拉取本地模型（首次约 5GB，视网速可能需要几分钟）..."
ollama list | grep -q "nomic-embed-text" || ollama pull nomic-embed-text
ollama list | grep -q "qwen2.5:7b" || ollama pull qwen2.5:7b

# 5. 启动服务
echo "[3/4] 启动服务: http://localhost:8000"
nohup python3 main.py >/dev/null 2>&1 &
sleep 4
echo "[4/4] 服务已在后台运行，浏览器访问: http://localhost:8000"
