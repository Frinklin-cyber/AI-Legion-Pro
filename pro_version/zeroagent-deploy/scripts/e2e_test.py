"""
e2e_test.py
端到端验证脚本（需服务已启动: python main.py）：
  1. GET  /health      服务可用性
  2. POST /upload      上传示例 PDF → chunks_indexed > 0
  3. 检查 ./data/vectordb/ 已生成 ChromaDB 文件
  4. GET  /documents   列表中包含该文档
  5. POST /ask         命中知识库 → status="ok" + answer + references
  6. references 每条含 source_file + page_number
  7. POST /ask         完全无关问题 → status="ok"（AI 依据人格坦诚回答并给方向）
  8. POST /ask         相近概念问题 → status="ok"（AI 依据人格自主决定如何回应）
  9. POST /feedback    收集"回答不准"反馈 → 写入 data/feedback/feedback.jsonl
  10. DELETE /documents/{name}  删除文档（向量 + 原文件）并刷新列表
  11. Ollama 未运行时返回友好 503（不崩溃）

用法: python scripts/e2e_test.py [服务地址] [示例PDF路径]
"""

import json
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
SAMPLE_PDF = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "员工手册.pdf"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, extra: str = ""):
    global PASS, FAIL
    mark = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{mark}] {name}" + (f"  — {extra}" if extra else ""))


def main():
    print(f"服务地址: {BASE}")
    print(f"示例文档: {SAMPLE_PDF}")
    print("-" * 60)

    # 1. 健康检查
    try:
        r = httpx.get(f"{BASE}/health", timeout=10)
        health = r.json()
        check("GET /health 服务在线", r.status_code == 200)
    except httpx.ConnectError:
        check("GET /health 服务在线", False, "无法连接服务，请先启动: python main.py")
        sys.exit(1)

    if health.get("ollama") != "":
        check("Ollama 就绪", False, f"Ollama 未就绪: {health.get('message')} —— 上传/问答验证将被跳过，这是符合预期的友好降级")
        _skip_upload_ask()
        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        sys.exit(1 if FAIL else 0)

    check("Ollama 就绪", True, f"embed={health.get('message') or '正常'}")

    # 2. 上传
    if not SAMPLE_PDF.exists():
        check("示例 PDF 存在", False, f"未找到 {SAMPLE_PDF}，请先运行 python scripts/make_sample_pdf.py")
        sys.exit(1)
    check("示例 PDF 存在", True, SAMPLE_PDF.name)

    with open(SAMPLE_PDF, "rb") as f:
        r = httpx.post(f"{BASE}/upload", files={"file": (SAMPLE_PDF.name, f, "application/pdf")}, timeout=300)
    if r.status_code == 503:
        check("POST /upload 友好提示（Ollama 不可用）", True, r.json().get("detail", "")[:60])
        _skip_upload_ask()
        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        sys.exit(1 if FAIL else 0)
    upload = r.json()
    check("POST /upload 成功", r.status_code == 200 and upload.get("chunks_indexed", 0) > 0,
          json.dumps(upload, ensure_ascii=False))

    # 3. 向量库文件
    db_files = list((DATA_DIR / "vectordb").glob("*"))
    has_db = any(db_files)
    check("./data/vectordb/ 已生成 ChromaDB 文件", has_db,
          ", ".join(p.name for p in db_files[:3]) if has_db else "目录为空")

    # 4. 文档列表
    r = httpx.get(f"{BASE}/documents", timeout=10)
    docs = r.json().get("documents", [])
    check("GET /documents 包含刚上传的文档",
          any(d["source_file"] == SAMPLE_PDF.name for d in docs),
          json.dumps(docs, ensure_ascii=False))

    # 5. 提问（文档原文命中：员工手册第三章休假制度 → 强相关 → status=ok）
    question = "公司年假是怎么规定的？"
    try:
        r = httpx.post(f"{BASE}/ask", json={"question": question}, timeout=300)
    except httpx.ConnectError:
        check("POST /ask 可调用", False, "服务连接失败")
        sys.exit(1)

    if r.status_code == 503:
        check("POST /ask 友好提示（Ollama 不可用）", True, r.json().get("detail", "")[:60])
        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        sys.exit(1 if FAIL else 0)

    data = r.json()
    has_answer = bool(data.get("answer"))
    has_refs = isinstance(data.get("references"), list) and len(data["references"]) > 0
    check("POST /ask 返回 answer", has_answer, f"answer 长度 {len(data.get('answer',''))}")
    check("POST /ask 返回 references 数组", has_refs)
    check("POST /ask 返回 status=ok", data.get("status") == "ok",
          f"status={data.get('status')}")
    check("POST /ask 命中知识库内容", "年假" in data.get("answer", "") or "年休假" in data.get("answer", ""),
          data.get("answer", "")[:80])

    # 6. references 元数据
    if has_refs:
        all_ok = all(
            ref.get("source_file") and "page_number" in ref
            for ref in data["references"]
        )
        check("references 每条含 source_file + page_number", all_ok,
              json.dumps(
                  [{"source_file": r2.get("source_file"), "page_number": r2.get("page_number")}
                   for r2 in data["references"]],
                  ensure_ascii=False))
        sample = data["references"][0]
        check("references 含原文片段", bool(sample.get("text")), f"片段长度 {len(sample.get('text',''))}")
    else:
        check("references 每条含 source_file + page_number", False, "references 为空")

    # 7. 打印答案摘要
    print("-" * 60)
    print("答案摘要:", data.get("answer", "")[:200])

    # 7. 完全无关问题：人格驱动下统一 status=ok，AI 依据人格坦诚说明无资料并给方向
    out_question = "量子纠缠对量子计算机有什么影响？"
    try:
        r = httpx.post(f"{BASE}/ask", json={"question": out_question}, timeout=300)
        data2 = r.json()
        check("无关问题返回 status=ok",
              data2.get("status") == "ok", f"status={data2.get('status')}")
        check("无关问题 AI 正常给出回答",
              bool(data2.get("answer") or data2.get("message")),
              (data2.get("answer") or "")[:100])
    except Exception as e:
        check("无关问题分支可调用", False, str(e))

    # 8. 相近概念问题：人格驱动下统一 status=ok，AI 自主决定如何回应
    try:
        r = httpx.post(f"{BASE}/ask",
                       json={"question": "动量矩定理的适用条件是什么？"}, timeout=300)
        data3 = r.json()
        check("相近概念返回 status=ok",
              data3.get("status") == "ok", f"status={data3.get('status')}")
        check("相近概念 AI 正常给出回答",
              bool(data3.get("answer") or data3.get("message")),
              (data3.get("answer") or "")[:100])
    except Exception as e:
        check("相近概念分支可调用", False, str(e))

    # 9. 负面反馈：POST /feedback → 写入 data/feedback/feedback.jsonl（JSONL）
    try:
        r = httpx.post(f"{BASE}/feedback", json={
            "question": out_question,
            "answer": data2.get("message", ""),
            "status": data2.get("status", ""),
            "rating": "down",
            "references": data2.get("references", []),
        }, timeout=15)
        d = r.json()
        check("POST /feedback 返回 ok", r.status_code == 200 and d.get("status") == "ok",
              json.dumps(d, ensure_ascii=False))
        check("POST /feedback 含感谢文案",
              "感谢反馈，这将帮助我们优化未来的回答" in d.get("message", ""),
              d.get("message", ""))
        fb_file = DATA_DIR / "feedback" / "feedback.jsonl"
        check("data/feedback/feedback.jsonl 已生成", fb_file.exists())
        if fb_file.exists():
            lines = [x for x in fb_file.read_text(encoding="utf-8").strip().splitlines() if x.strip()]
            entry = json.loads(lines[-1])
            check("feedback 记录含 ts/question/answer/rating/references",
                  all(k in entry for k in ("ts", "question", "answer", "rating", "references")),
                  json.dumps(entry, ensure_ascii=False))
    except Exception as e:
        check("POST /feedback 可调用", False, str(e))

    # 10. 删除文档：DELETE /documents/{name} → 向量 + 原文件同步删除，列表刷新
    try:
        r = httpx.delete(f"{BASE}/documents/{quote(SAMPLE_PDF.name)}", timeout=15)
        d = r.json()
        check("DELETE /documents/{name} 返回 ok",
              r.status_code == 200 and d.get("status") == "ok",
              json.dumps(d, ensure_ascii=False))
        check("DELETE 删除向量数 > 0", d.get("vectors_deleted", 0) > 0,
              f"vectors={d.get('vectors_deleted')}")
        check("DELETE 同步删除上传原文件", d.get("file_removed") is True)
        r2 = httpx.get(f"{BASE}/documents", timeout=10)
        docs2 = r2.json().get("documents", [])
        check("删除后 GET /documents 不再包含该文档",
              all(x["source_file"] != SAMPLE_PDF.name for x in docs2),
              json.dumps(docs2, ensure_ascii=False))
        upload_file = DATA_DIR / "uploads" / SAMPLE_PDF.name
        check("data/uploads/ 原文件已删除", not upload_file.exists())
    except Exception as e:
        check("DELETE /documents/{name} 可调用", False, str(e))

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


def _skip_upload_ask():
    """Ollama 未就绪时跳过依赖模型的验证，但仍检查友好提示"""
    r = httpx.post(f"{BASE}/ask", json={"question": "测试"}, timeout=10)
    check("POST /ask 友好提示（Ollama 不可用）", r.status_code == 503,
          r.json().get("detail", "")[:60] if r.status_code == 503 else f"HTTP {r.status_code}")


if __name__ == "__main__":
    main()
