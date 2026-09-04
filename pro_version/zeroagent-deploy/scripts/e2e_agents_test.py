"""
e2e_agents_test.py
多 Agent 编排端到端验证（需服务已启动: python main.py）：
  1. GET  /agents          注册表含 3 个专项 Agent
  2. POST /agents/run      合同审核（显式指定 agent）
  3. POST /agents/run      日报生成（自动路由）
  4. POST /agents/run      客服回复（use_kb 检索知识库）
  5. data/audit_log.jsonl  已写入执行审计
  6. POST /agents/notify   webhook 未配置时友好提示（不崩溃）

用法: python scripts/e2e_agents_test.py [服务地址]
"""

import json
import sys
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
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


def pretty(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)[:160]


def main():
    print(f"服务地址: {BASE}")
    print("-" * 60)

    # 1. 注册表
    r = httpx.get(f"{BASE}/agents", timeout=10)
    agents = r.json().get("agents", [])
    names = {a["name"] for a in agents}
    check("GET /agents 返回 3 个专项 Agent",
          {"contract_review", "daily_report", "customer_service"} <= names,
          f"共 {len(agents)} 个: {sorted(names)}")
    check("Agent 均有 description 与 parameters（工具自描述）",
          all(a.get("description") and a.get("parameters") for a in agents))

    # 2. 合同审核（显式指定）
    contract = (
        "软件开发服务合同（部分条款）\n"
        "第一条 付款方式：甲方应于本合同签订后5个工作日内支付合同总额的50%作为预付款，"
        "剩余50%于系统验收合格后30日内一次性付清。\n"
        "第二条 违约责任：如甲方逾期付款，每逾期一日按未付款项的0.5%支付违约金，逾期超过30日乙方有权解除合同。\n"
        "第三条 知识产权：本项目开发的软件源代码及全部文档的知识产权归乙方所有。\n"
        "第四条 保密条款：双方应对合作中知悉的对方商业信息承担保密义务，保密期限为本合同终止后3年。\n"
        "第五条 争议解决：因本合同引起的争议，双方协商不成的，提交乙方所在地人民法院诉讼解决。"
    )
    try:
        r = httpx.post(f"{BASE}/agents/run",
                       json={"task": contract, "agent": "contract_review"}, timeout=300)
    except httpx.ConnectError:
        check("服务可访问", False, "无法连接服务，请先启动: python main.py")
        sys.exit(1)
    data = r.json()
    check("合同审核执行成功", r.status_code == 200 and data.get("ok"),
          f"agent={data.get('agent')} 质检={data.get('quality', {}).get('score')}")
    issues = data.get("result", {}).get("issues") if isinstance(data.get("result"), dict) else None
    check("审核结果含 issues 数组", isinstance(issues, list) and len(issues) > 0,
          pretty(data.get("result")))
    check("质检报告含 checks", isinstance(data.get("quality", {}).get("checks"), list) and len(data["quality"]["checks"]) > 0)
    check("返回 audit_id (task_id)", bool(data.get("task_id")))
    print("  审核摘要:", str(data.get("result", {}).get("summary", ""))[:100])

    # 3. 日报生成（自动路由）
    r = httpx.post(f"{BASE}/agents/run",
                   json={"task": "帮我写今天的工作日报：上午完成了合同审核模块开发，下午修复了3个bug并写了测试"}, timeout=300)
    data = r.json()
    check("日报生成自动路由成功", r.status_code == 200 and data.get("ok"),
          f"agent={data.get('agent')} 路由={data.get('routing', {}).get('method')}")
    check("日报路由到 daily_report", data.get("agent") == "daily_report",
          f"实际路由到 {data.get('agent')}")
    completed = data.get("result", {}).get("completed") if isinstance(data.get("result"), dict) else None
    check("日报含 completed 数组", isinstance(completed, list) and len(completed) > 0,
          pretty(data.get("result")))

    # 4. 客服回复（use_kb 检索知识库）
    r = httpx.post(f"{BASE}/agents/run",
                   json={"task": "客户问：请问入职满两年能休几天年假？", "agent": "customer_service"}, timeout=300)
    data = r.json()
    check("客服回复执行成功", r.status_code == 200 and data.get("ok"),
          f"质检={data.get('quality', {}).get('score')}")
    reply = data.get("result", {}).get("reply") if isinstance(data.get("result"), dict) else ""
    # 员工手册：入职满1年不满10年 → 年休假5天（模型须按知识库精确匹配，不得答10天/15天）
    correct_days = ("年假" in reply or "年休假" in reply) and ("5天" in reply or "5 天" in reply or "五天" in reply)
    check("回复按知识库精确匹配（满2年→5天）", bool(reply) and correct_days,
          str(reply)[:120])
    print("  客服回复:", str(reply)[:120])

    # 5. 审计日志
    audit_file = DATA_DIR / "audit_log.jsonl"
    if audit_file.exists():
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        done = [json.loads(l) for l in lines if l.strip() and json.loads(l).get("stage") == "done"]
        check("audit_log.jsonl 已生成且有完成记录", len(done) >= 3,
              f"共 {len(lines)} 条审计，其中 {len(done)} 条完成")
    else:
        check("audit_log.jsonl 已生成且有完成记录", False, "文件不存在")

    # 6. webhook 未配置友好提示
    r = httpx.post(f"{BASE}/agents/notify",
                   json={"channel": "wecom", "message": "测试通知"}, timeout=10)
    ok_hint = r.status_code in (502,) and "webhook" in r.json().get("detail", "").lower()
    check("webhook 未配置时友好提示", ok_hint,
          f"HTTP {r.status_code}: {r.json().get('detail', '')[:80]}" if not ok_hint else "已返回 502 + 配置指引")

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
