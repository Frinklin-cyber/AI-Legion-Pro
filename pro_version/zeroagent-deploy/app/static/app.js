/* ZEROagent 企业知识大脑 - 前端逻辑 */

const $ = (id) => document.getElementById(id);

const dropZone = $("drop-zone");
const fileInput = $("file-input");
const uploadBtn = $("upload-btn");
const uploadStatus = $("upload-status");
const docList = $("doc-list");
const docEmpty = $("doc-empty");
const messages = $("messages");
const question = $("question");
const sendBtn = $("send");
const banner = $("health-banner");

let selectedFile = null;

/* ── 健康检查 ───────────────────────────── */
async function checkHealth() {
  try {
    const r = await fetch("/health");
    const data = await r.json();
    if (data.ollama === "") {
      banner.style.display = "none";
    } else {
      banner.textContent = "⚠ " + (data.message || "本地模型服务未就绪");
      banner.style.display = "block";
    }
  } catch (e) {
    banner.textContent = "⚠ 无法连接服务";
    banner.style.display = "block";
  }
}

/* ── 文档列表 ───────────────────────────── */
async function loadDocuments() {
  try {
    const r = await fetch("/documents");
    const data = await r.json();
    const docs = data.documents || [];
    docList.innerHTML = "";
    if (docs.length === 0) {
      docEmpty.textContent = "还没有索引任何文档，请先上传。";
      return;
    }
    docEmpty.textContent = "";
    docs.forEach((d) => {
      const li = document.createElement("li");
      const left = document.createElement("div");
      left.className = "doc-info";
      const name = document.createElement("span");
      name.className = "doc-name";
      name.textContent = d.source_file;
      name.title = d.source_file;
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = d.chunk_count + " 块";
      const del = document.createElement("button");
      del.className = "del-btn";
      del.textContent = "删除";
      del.title = "删除该文档（向量索引 + 原文件）";
      del.addEventListener("click", () => confirmDelete(d.source_file));
      left.append(name, count);
      li.append(left, del);
      docList.appendChild(li);
    });
  } catch (e) {
    docEmpty.textContent = "加载文档列表失败。";
  }
}

/* ── 上传 ───────────────────────────────── */
function selectFile(f) {
  if (!f) return;
  selectedFile = f;
  uploadStatus.textContent = "已选择: " + f.name + " (" + (f.size / 1024).toFixed(1) + " KB)";
}

dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => selectFile(e.target.files[0]));
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag");
  if (e.dataTransfer.files.length) selectFile(e.dataTransfer.files[0]);
});

uploadBtn.addEventListener("click", async () => {
  if (!selectedFile) {
    uploadStatus.textContent = "请先选择文件。";
    return;
  }
  uploadBtn.disabled = true;
  uploadStatus.textContent = "正在上传并索引…";
  const fd = new FormData();
  fd.append("file", selectedFile);
  try {
    const r = await fetch("/upload", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "上传失败");
    uploadStatus.textContent =
      "✓ 已索引 " + data.source_file + "（" + data.chunks_indexed + " 个文本块）";
    selectedFile = null;
    fileInput.value = "";
    loadDocuments();
  } catch (e) {
    uploadStatus.textContent = "✗ " + e.message;
  } finally {
    uploadBtn.disabled = false;
  }
});

/* ── 对话 ───────────────────────────────── */
function addMessage(role, html, refs, meta) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = html;
  // 统一渲染：有引用 → 显示引用；无引用 → 只显示 AI 文本，不附加任何提示框
  if (refs && refs.length) {
    const refBox = document.createElement("div");
    refBox.className = "refs";
    refs.forEach((ref, i) => {
      const b = document.createElement("span");
      b.className = "ref";
      const page = ref.page_number ? " · 第" + ref.page_number + "页" : "";
      b.textContent = "[" + (i + 1) + "] " + ref.source_file + page;
      b.addEventListener("click", () => showRef(ref));
      refBox.appendChild(b);
    });
    div.appendChild(refBox);
  }
  // 反馈：保留但低调（小图标 👍👎，hover 才明显），不喧宾夺主
  if (role === "bot" && meta && meta.answer) {
    const fb = document.createElement("div");
    fb.className = "fb-bar";
    const up = document.createElement("button");
    up.className = "fb-btn";
    up.textContent = "👍";
    up.title = "回答有帮助";
    up.addEventListener("click", () => sendFeedback(meta, "up"));
    const down = document.createElement("button");
    down.className = "fb-btn";
    down.textContent = "👎";
    down.title = "回答不准确";
    down.addEventListener("click", () => sendFeedback(meta, "down"));
    fb.append(up, down);
    div.appendChild(fb);
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

/* ── 反馈（👍👎） ───────────────────────── */
async function sendFeedback(meta, rating) {
  try {
    const r = await fetch("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: meta.question,
        answer: meta.answer,
        status: meta.status || "",
        rating: rating || "",
        references: meta.references || [],
      }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "反馈失败");
    toast(data.message || "感谢反馈，这将帮助我们优化未来的回答。");
  } catch (e) {
    toast("反馈提交失败：" + e.message);
  }
}

/* ── 文档删除（带确认弹窗） ──────────────── */
let pendingDelete = null;
function confirmDelete(name) {
  pendingDelete = name;
  $("del-target").textContent =
    "确定要删除「" + name + "」吗？将同时移除向量索引与原文件，此操作不可恢复。";
  $("del-mask").classList.add("show");
}
async function doDelete(name) {
  try {
    const r = await fetch("/documents/" + encodeURIComponent(name), { method: "DELETE" });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "删除失败");
    uploadStatus.textContent = "✓ 已删除 " + name + "（移除 " + data.vectors_deleted + " 个向量" +
      (data.file_removed ? "，原文件已删除" : "）");
    toast("已删除「" + name + "」");
    loadDocuments();
  } catch (e) {
    toast("删除失败：" + e.message);
  }
}
function initDeleteModal() {
  $("del-cancel").addEventListener("click", () => {
    $("del-mask").classList.remove("show");
    pendingDelete = null;
  });
  $("del-confirm").addEventListener("click", () => {
    const name = pendingDelete;
    $("del-mask").classList.remove("show");
    pendingDelete = null;
    if (name) doDelete(name);
  });
  $("del-mask").addEventListener("click", (e) => {
    if (e.target === $("del-mask")) {
      $("del-mask").classList.remove("show");
      pendingDelete = null;
    }
  });
}

/* ── 轻提示 toast ────────────────────────── */
function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, 2600);
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function ask(q) {
  addMessage("user", escapeHtml(q));
  const thinking = addMessage("bot", "<i style='color:#8b93a7'>正在检索知识库并生成答案…</i>");
  try {
    const r = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ question: q }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "请求失败");
    thinking.remove();
    const meta = {
      question: q,
      answer: data.answer || data.message || "",
      status: data.status || "",
      references: data.references || [],
    };
    addMessage(
      "bot",
      escapeHtml(data.message || data.answer || "(空回答)"),
      data.references || [],
      meta
    );
  } catch (e) {
    thinking.remove();
    addMessage("err", "⚠ " + e.message);
  }
}

sendBtn.addEventListener("click", doSend);
question.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    doSend();
  }
});

function doSend() {
  const q = question.value.trim();
  if (!q) return;
  question.value = "";
  ask(q);
}

/* ── 引用弹窗 ───────────────────────────── */
const modalMask = $("modal-mask");
function showRef(ref) {
  $("modal-title").textContent = ref.source_file;
  const page = ref.page_number ? "第 " + ref.page_number + " 页" : "无分页（Word/Excel/Markdown）";
  $("modal-meta").textContent = page + " · 相似度 " + (ref.score != null ? ref.score : "-");
  $("modal-body").textContent = ref.text;
  modalMask.classList.add("show");
}
$("modal-close").addEventListener("click", () => modalMask.classList.remove("show"));
modalMask.addEventListener("click", (e) => {
  if (e.target === modalMask) modalMask.classList.remove("show");
});

/* ── Tab 切换 ───────────────────────────── */
document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("view-" + t.dataset.tab).classList.add("active");
  });
});

/* ── Agent 工作台 ───────────────────────── */
async function loadAgents() {
  try {
    const r = await fetch("/agents");
    const data = await r.json();
    const sel = $("agent-select");
    data.agents.forEach((a) => {
      const opt = document.createElement("option");
      opt.value = a.name;
      opt.textContent = a.title + "（" + a.name + "）";
      sel.appendChild(opt);
    });
  } catch (e) { /* 忽略：Agent 列表加载失败不影响主功能 */ }
}

function renderResult(res) {
  const box = $("agent-result");
  box.style.display = "block";
  $("res-agent").textContent = "Agent: " + (res.agent_title || res.agent || "-");
  $("res-route").textContent = "路由: " + (res.routing ? res.routing.method + " · " + res.routing.reasoning : "-");
  $("res-taskid").textContent = "审计ID: " + res.task_id;

  const q = $("res-quality");
  const quality = res.quality || {};
  q.textContent = "质检 " + (quality.score ?? "-") + "分 · " + (quality.passed ? "通过" : "未通过");
  q.className = "badge " + (quality.passed ? "ok" : "fail");

  $("res-time").textContent = "耗时 " + (res.elapsed_ms ?? 0) + "ms · " + (res.attempts ?? 1) + " 次尝试";

  const checksBox = $("res-checks");
  checksBox.innerHTML = "";
  (quality.checks || []).forEach((c) => {
    const item = document.createElement("div");
    item.className = "check-item";
    const dot = document.createElement("span");
    dot.className = "dot " + (c.passed ? "ok" : "fail");
    item.append(dot, document.createTextNode(c.name + " — " + c.detail));
    checksBox.appendChild(item);
  });

  const notify = res.notify;
  $("res-meta").textContent = notify
    ? "Webhook 通知: " + (notify.sent ? "已发送 → " + notify.channel : "失败: " + (notify.error || "-"))
    : "未配置 Webhook 通知";

  const body = $("res-body");
  if (typeof res.result === "string") {
    body.textContent = res.result;
  } else {
    body.textContent = JSON.stringify(res.result, null, 2);
  }
}

$("agent-run").addEventListener("click", async () => {
  const task = $("agent-task").value.trim();
  if (!task) {
    $("agent-status").textContent = "请输入任务内容。";
    return;
  }
  $("agent-run").disabled = true;
  $("agent-status").textContent = "路由 Agent 正在分发任务，专项 Agent 执行中…（本地模型生成，可能需要 10-60 秒）";
  try {
    const r = await fetch("/agents/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: task, agent: $("agent-select").value || null }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "执行失败");
    renderResult(data);
    $("agent-status").textContent = "✓ 任务完成";
  } catch (e) {
    $("agent-status").textContent = "✗ " + e.message;
  } finally {
    $("agent-run").disabled = false;
  }
});

/* ── 初始化 ───────────────────────────── */
checkHealth();
loadDocuments();
loadAgents();
initDeleteModal();
