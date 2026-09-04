"""编排状态定义：步骤元数据 + 事件结构"""

# 编排五步（与进阶版指令 Step1→5 一致）
STEPS = [
    {"id": 1, "key": "intent",    "label": "意图识别",     "icon": "🔍", "desc": "判断问题所属领域并路由"},
    {"id": 2, "key": "profile",   "label": "上下文画像",   "icon": "👤", "desc": "结合店铺 / 行业 / 地区画像补全"},
    {"id": 3, "key": "tools",     "label": "工具与推理",   "icon": "🛠",  "desc": "检索知识库 / 计算 / 诊断等工具调用"},
    {"id": 4, "key": "plans",     "label": "方案对比",     "icon": "⚖",  "desc": "生成 2-3 套方案并对比成本风险"},
    {"id": 5, "key": "finalize",  "label": "执行指引",     "icon": "✅",  "desc": "行动清单 + 可直接复制的模板"},
]

STEP_BY_KEY = {s["key"]: s for s in STEPS}


def make_event(etype: str, **kw):
    """构造一条编排进度事件（前端据此渲染右侧编排面板）"""
    ev = {"type": etype}
    ev.update(kw)
    return ev
