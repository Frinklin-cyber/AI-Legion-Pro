"""
main.py
ZEROagent 企业知识大脑 PoC - FastAPI 入口。
启动：python main.py  →  http://localhost:8000

端点：
  POST   /upload             上传文件并触发 ingestion
  POST   /ask                提问（人格驱动，模型自主决定如何回答，不区分状态）
  GET    /documents          列出已索引文档
  DELETE /documents/{name}   删除指定文档（向量 + 原文件）
  POST   /feedback           收集 👍👎 反馈（data/feedback/*.jsonl）
"""

import json
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import audit
from app.config import (
    ALLOWED_EXTENSIONS, DATA_DIR, FEEDBACK_FILE, MAX_UPLOAD_SIZE_MB, STATIC_DIR,
    UPLOAD_DIR, VECTOR_DB_PATH, OLLAMA_HOST, EMBED_MODEL, LLM_MODEL,
    CHUNK_SIZE, CHUNK_OVERLAP, TOP_K,
)
from app.ollama_client import OllamaClient, OllamaUnavailableError
from app.vector_store import VectorStore
from app.rag import RAGEngine
from app.agent_registry import load_agents_from_dir, list_agents
from app.agent_orchestrator import AgentOrchestrator
from app.webhook_sender import send_webhook

# ─────────────────────────────────────────────
# 全局单例
# ─────────────────────────────────────────────
ollama = OllamaClient(
    host=OLLAMA_HOST, embed_model=EMBED_MODEL, llm_model=LLM_MODEL,
)
store = VectorStore(VECTOR_DB_PATH)
engine = RAGEngine(ollama, store, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K)
orchestrator = AgentOrchestrator(ollama, rag_engine=engine)

ollama_status = "unavailable"  # "" / "unavailable" / "embed" / "llm"


def _ollama_hint(status: str) -> str:
    hints = {
        "unavailable": f"本地模型服务 (Ollama) 未运行。请先执行 `ollama serve` 启动，然后刷新页面重试。",
        "embed": f"Ollama 已运行，但缺少向量模型 {EMBED_MODEL}。请执行: `ollama pull {EMBED_MODEL}`",
        "llm": f"Ollama 已运行，但缺少对话模型 {LLM_MODEL}。请执行: `ollama pull {LLM_MODEL}`",
    }
    return hints.get(status, "本地模型服务不可用")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global ollama_status
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # 加载专项 Agent 配置
    loaded_agents = load_agents_from_dir()
    audit.log("system", f"已注册 {len(loaded_agents)} 个专项 Agent: {', '.join(loaded_agents)}")
    ollama_status = ollama.check_ready()
    if ollama_status == "":
        audit.log("system", f"服务启动，Ollama 连接正常 ({OLLAMA_HOST})")
    else:
        audit.log("system", f"服务启动，Ollama 未就绪: {_ollama_hint(ollama_status)}", status="WARN")
    yield


app = FastAPI(title="ZEROagent 企业知识大脑 PoC", lifespan=lifespan)


# ─────────────────────────────────────────────
# 全局错误处理：Ollama 不可用 → 友好 503
# ─────────────────────────────────────────────
@app.exception_handler(OllamaUnavailableError)
async def _ollama_error_handler(_request: Request, exc: OllamaUnavailableError):
    return JSONResponse(status_code=503, content={"error": exc.message})


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str


def _client_ip(request: Request) -> str:
    try:
        return request.client.host if request.client else "-"
    except Exception:
        return "-"


@app.post("/upload")
async def upload_file(file: UploadFile = File(...), request: Request = None):
    if ollama_status != "":
        raise HTTPException(status_code=503, detail=_ollama_hint(ollama_status))

    original = Path(file.filename or "upload").name  # 防路径穿越
    ext = original.lower().rsplit(".", 1)[-1] if "." in original else ""
    ext = f".{ext}"
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 {ext}，支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    save_path = UPLOAD_DIR / original
    size = 0
    try:
        with open(save_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {MAX_UPLOAD_SIZE_MB}MB 限制",
                    )
                out.write(chunk)
    except HTTPException:
        save_path.unlink(missing_ok=True)
        raise

    if size == 0:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传的文件为空")

    ip = _client_ip(request)
    try:
        result = engine.index_file(save_path)
        audit.log("upload", f"file={result['source_file']} chunks={result['chunks_indexed']}", client_ip=ip)
        return result
    except ValueError as e:
        save_path.unlink(missing_ok=True)
        audit.log("upload", f"file={original} 失败: {e}", client_ip=ip, status="ERROR")
        raise HTTPException(status_code=400, detail=str(e))
    except OllamaUnavailableError as e:
        audit.log("upload", f"file={original} 失败: Ollama 不可用", client_ip=ip, status="ERROR")
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/ask")
async def ask(req: AskRequest, request: Request = None):
    # 强制使用 UTF-8 解码请求体，避免 Windows 环境下中文被错误解码为 GBK
    raw_body = await request.body()
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        data = await request.json()
    question = (data.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if ollama_status != "":
        raise HTTPException(status_code=503, detail=_ollama_hint(ollama_status))

    ip = _client_ip(request)
    try:
        result = engine.ask(question)
        audit.log(
            "ask",
            f"question={question[:80]} status={result.get('status')} refs={len(result['references'])}",
            client_ip=ip,
        )
        return result
    except OllamaUnavailableError as e:
        audit.log("ask", f"question={question[:80]} 失败: Ollama 不可用", client_ip=ip, status="ERROR")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/documents")
async def documents():
    return {"documents": store.list_documents()}


@app.delete("/documents/{filename}")
async def delete_document(filename: str, request: Request = None):
    """删除指定文档：先从向量库删除该 source_file 的全部 chunk，再删除上传原文件。"""
    safe = Path(filename).name  # 防路径穿越：仅接受纯文件名
    if safe != filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    vectors_deleted = store.delete_by_source(safe)

    upload = UPLOAD_DIR / safe
    file_removed = False
    if upload.exists():
        try:
            upload.unlink()
            file_removed = True
        except OSError:
            pass

    audit.log("delete", f"file={safe} vectors={vectors_deleted} file_removed={file_removed}",
              client_ip=_client_ip(request))

    if vectors_deleted == 0 and not file_removed:
        raise HTTPException(status_code=404, detail=f"文档 {safe} 不存在")

    return {
        "status": "ok",
        "source_file": safe,
        "vectors_deleted": vectors_deleted,
        "file_removed": file_removed,
    }


class FeedbackRequest(BaseModel):
    question: str
    answer: str = ""
    status: str = ""
    rating: str = ""        # "up" / "down"（👍👎），可空表示仅标记
    references: list = []


@app.post("/feedback")
async def feedback(req: FeedbackRequest, request: Request = None):
    """收集 👍👎 反馈：写入 data/feedback/feedback.jsonl（JSONL）。"""
    if not (req.question or "").strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "question": req.question,
        "answer": req.answer,
        "status": req.status,
        "rating": req.rating,
        "references": req.references,
    }
    try:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        audit.log("feedback", f"question={req.question[:80]} 保存失败: {e}",
                  client_ip=_client_ip(request), status="ERROR")
        raise HTTPException(status_code=500, detail=f"反馈保存失败: {e}")
    audit.log("feedback", f"question={req.question[:80]} status={req.status}",
              client_ip=_client_ip(request))
    return {"status": "ok", "message": "感谢反馈，这将帮助我们优化未来的回答。"}


# ─────────────────────────────────────────────
# 多 Agent 编排 API
# ─────────────────────────────────────────────
class RunAgentRequest(BaseModel):
    task: str
    agent: str = None        # 可选：指定专项 Agent（auto/留空则自动路由）
    params: dict = None      # 可选：Agent 参数（缺省时自动填入 task）
    webhook_channel: str = None  # 可选: wecom / dingtalk / feishu


@app.get("/agents")
async def agents():
    """列出已注册的专项 Agent 及其 schema（工具自描述）"""
    return {"agents": list_agents()}


@app.post("/agents/run")
async def run_agent(req: RunAgentRequest, request: Request = None):
    """路由 Agent → 专项 Agent → 质检 Agent → 返回最终结果"""
    if ollama_status != "":
        raise HTTPException(status_code=503, detail=_ollama_hint(ollama_status))
    ip = _client_ip(request)
    try:
        result = orchestrator.run(
            task=req.task,
            agent=req.agent or None,
            params=req.params,
            webhook_channel=req.webhook_channel,
        )
        audit.log("agent_run", f"task={req.task[:80]} agent={result.get('agent')} ok={result.get('ok')}",
                  client_ip=ip, status="OK" if result.get("ok") else "WARN")
        return result
    except ValueError as e:
        audit.log("agent_run", f"task={req.task[:80]} 参数错误: {e}", client_ip=ip, status="ERROR")
        raise HTTPException(status_code=400, detail=str(e))
    except OllamaUnavailableError as e:
        audit.log("agent_run", f"task={req.task[:80]} 失败: Ollama 不可用", client_ip=ip, status="ERROR")
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/agents/notify")
async def notify(request: Request = None):
    """测试 webhook 通知（企微/钉钉/飞书）"""
    body = await request.json()
    channel = (body or {}).get("channel", "")
    message = (body or {}).get("message", "")
    if not channel or not message:
        raise HTTPException(status_code=400, detail="需要 channel 和 message 字段")
    result = send_webhook(channel, message)
    audit.log("agent_notify", f"channel={channel} sent={result['sent']}", client_ip=_client_ip(request),
              status="OK" if result["sent"] else "WARN")
    if not result["sent"]:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.get("/health")
async def health():
    return {
        "status": "ok" if ollama_status == "" else "degraded",
        "ollama": ollama_status,
        "message": "" if ollama_status == "" else _ollama_hint(ollama_status),
        "indexed_chunks": store.count(),
    }


# ─────────────────────────────────────────────
# 前端
# ─────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
