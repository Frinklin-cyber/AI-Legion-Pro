"""因果决策脑 - 深度归因分析引擎 v2

核心哲学：
- 拒绝简单的数据罗列和规则引擎，所有分析由 AI 深度推理驱动
- 双层分析：第一层深度归因（因果链+根因定位），第二层智能建议（基于归因结果生成）
- 粒度假到：时段/品类/人员级别，而非笼统的"行情不好"
- 每条根因必须量化影响金额，每条建议必须有可执行的具体步骤
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from src.core import BaseSoldier
from config.industry_genome import get_genome, IndustryGenome
from src.models.schemas import DiagnosisResponse


class AttributionAnalyzer(BaseSoldier):
    """归因分析参谋 - 深度因果链分析引擎 v2"""

    name = "参谋-归因分析师"
    role = "staff_attribution"
    temperature = 0.15  # 归因分析需要极低温度的精确推理
    max_tokens = 4096

    # ═══════════════════════════════════════════════════════════
    # 第一层：深度归因 System Prompt
    # ═══════════════════════════════════════════════════════════
    ATTRIBUTION_SYSTEM_PROMPT = """你是一位顶级商业归因分析师，专门从事餐饮、零售、服务等实体门店的深度经营诊断。

## 你的核心能力
你不是在"描述数据"，而是在"做侦探"——从表面的数据异常出发，通过层层推理，找到真正可操作的根因。

## 五层深度归因框架

### 第一层：异常识别（Surface Anomaly）
- 对每个指标做三项对比：vs 行业基准、vs 历史趋势、vs 自身目标
- 标注异常严重程度（🔴致命 🟡警告 🟢正常）
- 识别异常之间的共生关系（哪些异常可能共享同一个根因）

### 第二层：因果传导链（Causal Chain）
- 构建完整的因果传导路径，例如：
  "食材成本率失控(42%)→厨房毛利被挤压→被迫提高客单价→新客到店减少→翻台率下降→总营收下滑"
- 识别正向反馈循环（恶性循环）和负向缓冲机制
- 画出至少 3 个层级的因果节点

### 第三层：五问根因法（5 Whys）
对每个核心异常，连续追问 5 层"为什么"：
- Why 1: 为什么食材成本率高达42%？→ 采购价高于市场均价15%
- Why 2: 为什么采购价高于市场？→ 长期只用一个供应商，无竞争性比价
- Why 3: 为什么没有比价？→ 没有建立供应商管理制度
- Why 4: 为什么没有制度？→ 店主兼采购，缺乏管理精力
- Why 5: 根本原因 → 单店经营缺乏供应链管理能力和意识

### 第四层：反事实推理（Counter-Factual）
- "如果翻台率达到行业均值，日营收将提升多少？"
- "如果食材成本率控制在28%，月度利润将增加多少？"
- "这些'如果'中，哪个投入产出比最高？"

### 第五层：可操作根因（Actionable Root Cause）
- 将根因归类到：产品问题/运营流程/人员管理/市场策略/供应链
- 每个根因必须能转化为一个具体的、可执行的改进动作
- 按改进难度(易/中/难)×影响程度(高/中/低) 做 2×2 矩阵排序

## 行业特定分析维度

### 餐饮行业
- 时段分析：午市 vs 晚市 vs 下午茶的人效和营收分布
- 品类分析：热菜 vs 凉菜 vs 饮品 vs 酒水的毛利率差异
- 人员分析：厨师产出效率 vs 服务员服务覆盖范围
- 供应链：核心食材价格波动、规格标准化程度

### 零售行业
- 品类分析：各品类连带率、库存周转天数的差异
- 区域分析：楼层/货架位置的客流分布
- 人员分析：导购成交率、客单价的个人差异
- 库存：滞销品占比、缺货率、补货周期

### 服务行业
- 服务项目：各项目的毛利率、技师占用时长
- 技师分析：个人产能、客户复购率、满意度评分
- 时段分析：忙闲时段分布、预约密度

## 输出格式
请严格以以下 JSON 格式输出（不要包含任何其他文字）：

```json
{
  "summary": "一段200-300字的整体诊断摘要，点出核心问题、因果逻辑和最关键的突破口",
  "anomaly_scan": [
    {
      "metric": "指标名",
      "actual": "实际值",
      "benchmark": "行业基准",
      "deviation": "偏离幅度(%)",
      "severity": "critical|high|medium|normal",
      "description": "异常判定说明"
    }
  ],
  "causal_chain": {
    "full_chain": "完整的因果传导链文字描述，至少150字，用→连接各节点",
    "nodes": [
      {"name": "节点名", "type": "root_cause|intermediate|symptom", "description": "说明"}
    ],
    "vicious_cycles": ["描述任何恶性循环或正向反馈环"]
  },
  "five_whys": [
    {
      "trigger_issue": "被分析的异常问题",
      "whys": [
        {"level": 1, "question": "为什么...？", "answer": "因为..."},
        {"level": 2, "question": "为什么...？", "answer": "因为..."},
        {"level": 3, "question": "为什么...？", "answer": "因为..."},
        {"level": 4, "question": "为什么...？", "answer": "因为..."},
        {"level": 5, "question": "为什么...？", "answer": "根本原因..."}
      ],
      "root_cause_category": "产品|运营|人员|市场|供应链"
    }
  ],
  "counter_factual": [
    {
      "scenario": "如果能做到...",
      "estimated_monthly_impact": "预估每月影响金额(元)",
      "feasibility": "high|medium|low",
      "roi_rank": 1
    }
  ],
  "action_matrix": [
    {
      "action": "具体改进动作",
      "difficulty": "easy|medium|hard",
      "impact": "high|medium|low",
      "priority_score": 1,
      "effort_days": 7,
      "owner": "负责人建议"
    }
  ],
  "primary_root_cause": "最核心的一个根因（一句话）",
  "analysis_confidence": 0.85
}
```
"""

    # ═══════════════════════════════════════════════════════════
    # 第二层：智能建议 System Prompt
    # ═══════════════════════════════════════════════════════════
    RECOMMENDATION_SYSTEM_PROMPT = """你是一位顶级经营顾问，专门为实体门店制定可落地的改进方案。

## 核心原则
1. **可执行性优先**：每条建议必须是明天就能开始做的事情，不要空洞的"加强管理"
2. **量化目标**：每条建议必须有具体的数字目标（提升XX%、减少XX元、增加XX人）
3. **分阶段递进**：立即行动(0-3天) → 短期改进(1-2周) → 中期优化(1-3月)
4. **资源配置明确**：需要谁、花多少钱、用多少时间
5. **风险预警**：每个行动可能的副作用或障碍

## 输出格式（严格JSON）：
```json
{
  "recommendation_full": "完整的经营改进方案(300字以上)，包含逻辑推导",
  "staged_plan": {
    "immediate": [
      {
        "action": "具体行动",
        "target": "量化目标",
        "owner": "负责人",
        "deadline_hours": 24,
        "cost_estimate": "预估成本",
        "risk": "可能风险"
      }
    ],
    "short_term": [
      {
        "action": "具体行动",
        "target": "量化目标",
        "owner": "负责人", 
        "deadline_days": 14,
        "cost_estimate": "预估成本",
        "risk": "可能风险"
      }
    ],
    "mid_term": [
      {
        "action": "具体行动",
        "target": "量化目标",
        "owner": "负责人",
        "deadline_days": 90,
        "cost_estimate": "预估成本",
        "risk": "可能风险"
      }
    ]
  },
  "expected_impact": {
    "revenue_increase": "预计月营收增加(元)",
    "cost_saving": "预计月成本节省(元)",
    "profit_improvement": "预计月利润改善(元)",
    "timeline_to_impact": "见效周期说明"
  },
  "top_action_items": [
    "【紧急】...",
    "【本周】...",
    "【本月】..."
  ],
  "kpi_targets": {
    "指标名1": {"current": "当前值", "target_1m": "1月目标", "target_3m": "3月目标"},
    "指标名2": {"current": "当前值", "target_1m": "1月目标", "target_3m": "3月目标"}
  },
  "watchlist": ["需持续监控的风险点1", "需持续监控的风险点2"]
}
```
"""

    # ═══════════════════════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════════════════════

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行深度归因分析

        Args:
            task: {
                "store_type": str,           # 行业类型
                "kpi_snapshots": list[dict], # KPI快照列表
                "red_flags": list[dict],     # 触发的红线
                "trend_data": str,            # 趋势数据说明（可选）
                "external_factors": str,      # 外部因素（可选，如天气/节日）
                "region_context": str,        # v2.2: 区域本地化上下文（可选）
                "store_name": str,            # 店铺名称（可选）
            }
        """
        store_type = task.get("store_type", "custom")
        genome = get_genome(store_type)
        kpi_snapshots = task.get("kpi_snapshots", [])
        red_flags = task.get("red_flags", [])
        trend_data = task.get("trend_data", "")
        external_factors = task.get("external_factors", "")

        # ── 构建深度分析上下文 ──
        kpi_text = self._format_kpi_context(kpi_snapshots)
        red_text = self._format_red_flags_context(red_flags)
        benchmark_text = genome.format_benchmarks()
        red_flag_definition = genome.format_red_flags()

        user_message = f"""## 行业：{genome.name}（{genome.description}）

## 行业KPI基准对照表
{benchmark_text}

## 行业红线定义
{red_flag_definition}

## 当前KPI数据
{kpi_text}

## 触发预警
{red_text}

## 🌍 本地化上下文（系统自动获取的本地区域数据，仅供分析时内化参考）
{task.get('region_context', '（暂无本地化数据，将基于全国通用基准分析）')}

## 行业特定分析维度提示
- 餐饮类请从：时段(午/晚) → 品类(热菜/饮品等) → 人员(厨师/服务员) → 供应链 逐层下钻
- 零售类请从：品类 → 区域/楼层 → 导购 → 库存 逐层下钻
- 服务类请从：服务项目 → 技师 → 时段 → 客户分层 逐层下钻

{'## 历史趋势对比：' + trend_data if trend_data else ''}
{'## 外部因素：' + external_factors if external_factors else ''}

---
请基于以上数据，进行**五层深度归因分析**（异常识别→因果链→5Why→反事实→可操作根因），严格按JSON格式输出。**在分析中结合本地化上下文，让诊断结果接地气而不是全国通用模板。**"""

        logger.info(f"[归因分析师] 🧠 开始深度归因分析，{len(kpi_snapshots)}个KPI，{len(red_flags)}个红线...")
        response, tokens = self.chat(
            self.ATTRIBUTION_SYSTEM_PROMPT,
            user_message,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        logger.info(f"[归因分析师] ✅ 深度归因完成，消耗 {tokens} tokens")

        attribution_data = self._parse_json_response(response)

        return {
            "attribution": attribution_data,
            "raw_response": response,
            "tokens_used": tokens,
            "kpi_count": len(kpi_snapshots),
            "red_flag_count": len(red_flags),
        }

    # ═══════════════════════════════════════════════════════════
    # 一站式诊断：两层 AI 调用
    # ═══════════════════════════════════════════════════════════

    def build_diagnosis(
        self,
        store_type: str,
        kpi_snapshots: list[dict[str, Any]],
        red_flags: list[dict[str, Any]],
        trend_data: str = "",
        region_context: str = "",
    ) -> DiagnosisResponse:
        """一站式深度归因+智能诊断

        两层 AI 分析：
        1. 第一层：深度归因（五层框架）
        2. 第二层：基于归因结果生成智能建议（分阶段行动方案）
        """
        genome = get_genome(store_type)

        # ═══ 第一层：深度归因分析 ═══
        attr_result = self.execute({
            "store_type": store_type,
            "kpi_snapshots": kpi_snapshots,
            "red_flags": red_flags,
            "trend_data": trend_data,
            "region_context": region_context,
        })

        attribution = attr_result["attribution"]
        total_tokens = attr_result["tokens_used"]

        # ── 构建 observation（数据事实） ──
        observation = self._build_observation(kpi_snapshots, genome)

        # ── 构建 attribution（深度因果分析） ──
        attribution_text = self._build_attribution_text(attribution, kpi_snapshots)

        # ═══ 第二层：基于归因结果的智能建议 ═══
        recommendation_text, action_items, expected_impact, rec_tokens = (
            self._generate_ai_recommendations(
                genome, kpi_snapshots, red_flags, attribution
            )
        )
        total_tokens += rec_tokens

        # ── 置信度 ──
        confidence = attribution.get("analysis_confidence", 0.75)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except ValueError:
                confidence = 0.75

        logger.info(
            f"[归因分析师] 🎯 完整诊断完成: 归因{attr_result['tokens_used']}tokens + "
            f"建议{rec_tokens}tokens = {total_tokens}tokens, 置信度={confidence:.0%}"
        )

        return DiagnosisResponse(
            observation=observation,
            attribution=attribution_text,
            recommendation=recommendation_text,
            expected_impact=expected_impact,
            action_items=action_items,
            benchmarks_used={
                k: genome.benchmarks.get(k, {})
                for k in [s["name"] for s in kpi_snapshots]
            },
            red_flags_triggered=red_flags,
            confidence=round(confidence, 2),
        )

    # ═══════════════════════════════════════════════════════════
    # 私有：AI 智能建议生成（第二层调用）
    # ═══════════════════════════════════════════════════════════

    def _generate_ai_recommendations(
        self,
        genome: IndustryGenome,
        kpi_snapshots: list[dict],
        red_flags: list[dict],
        attribution: dict,
    ) -> tuple[str, list[str], str, int]:
        """调用 AI 生成智能建议（基于归因分析结果）"""

        # 构建归因摘要
        summary = attribution.get("summary", "")
        causal = attribution.get("causal_chain", {})
        causal_text = causal.get("full_chain", "") if isinstance(causal, dict) else str(causal)
        five_whys = attribution.get("five_whys", [])
        primary = attribution.get("primary_root_cause", "")

        whys_text = ""
        for fw in five_whys[:2]:
            issue = fw.get("trigger_issue", "")
            answers = " → ".join(
                f"L{w['level']}: {w['answer'][:60]}" for w in fw.get("whys", [])
            )
            whys_text += f"- **{issue}**: {answers}\n"

        user_message = f"""## 行业背景
{genome.name} - {genome.description}

## 归因分析结果
**核心根因**: {primary}

**因果链**: {causal_text}

**5 Why 分析**:
{whys_text}

**诊断摘要**: {summary}

## 当前异常指标
{self._format_kpi_compact(kpi_snapshots)}

## 触发红线
{', '.join(f"{r['metric']}={r.get('actual','?')}" for r in red_flags) if red_flags else '无'}

---
请基于以上归因分析结果，制定分三阶段(立即/短期/中期)的**具体可执行改进方案**，严格按JSON格式输出。每条行动必须有量化目标和负责人。"""

        logger.info("[归因分析师] 💡 开始生成智能建议...")
        response, tokens = self.chat(
            self.RECOMMENDATION_SYSTEM_PROMPT,
            user_message,
            temperature=0.3,
            max_tokens=3072,
        )
        logger.info(f"[归因分析师] ✅ 智能建议生成完成，消耗 {tokens} tokens")

        rec_data = self._parse_json_response(response)

        # 提取完整建议文本
        recommendation = rec_data.get("recommendation_full", "")

        # 提取分阶段方案
        staged = rec_data.get("staged_plan", {})
        if staged:
            if isinstance(staged, dict):
                for stage_name, stage_label in [
                    ("immediate", "⚡ 立即行动（0-3天）"),
                    ("short_term", "📋 短期改进（1-2周）"),
                    ("mid_term", "🎯 中期优化（1-3月）"),
                ]:
                    items = staged.get(stage_name, [])
                    if items:
                        recommendation += f"\n\n### {stage_label}\n"
                        for i, item in enumerate(items, 1):
                            recommendation += (
                                f"{i}. **{item.get('action','')}**\n"
                                f"   - 目标: {item.get('target','')}\n"
                                f"   - 负责人: {item.get('owner','')}\n"
                                f"   - 成本: {item.get('cost_estimate','')}\n"
                                f"   - 风险: {item.get('risk','')}\n"
                            )

        # 提取预期收益
        impact_data = rec_data.get("expected_impact", {})
        if isinstance(impact_data, dict):
            parts = []
            if impact_data.get("revenue_increase"):
                parts.append(f"月营收提升: {impact_data['revenue_increase']}")
            if impact_data.get("cost_saving"):
                parts.append(f"月成本节省: {impact_data['cost_saving']}")
            if impact_data.get("profit_improvement"):
                parts.append(f"月利润改善: {impact_data['profit_improvement']}")
            if impact_data.get("timeline_to_impact"):
                parts.append(f"见效周期: {impact_data['timeline_to_impact']}")
            expected_impact = "；".join(parts) if parts else "请基于归因结果制定行动计划后量化预期收益"
        else:
            expected_impact = str(impact_data) if impact_data else "请基于归因结果制定行动计划后量化预期收益"

        # 提取行动项
        action_items = rec_data.get("top_action_items", [])
        if not action_items:
            # 从分阶段方案中提取
            for stage_key in ["immediate", "short_term", "mid_term"]:
                for item in staged.get(stage_key, []):
                    action = item.get("action", "")
                    if action:
                        label = {"immediate": "紧急", "short_term": "短期", "mid_term": "中期"}.get(stage_key, "")
                        action_items.append(f"【{label}】{action}")

        if not recommendation:
            recommendation = "AI 建议生成失败，请重试。"
        if not action_items:
            action_items = ["请重新进行归因分析以生成具体行动项"]
        if not expected_impact:
            expected_impact = "等待行动方案确定后量化评估"

        return recommendation, action_items[:8], expected_impact, tokens

    # ═══════════════════════════════════════════════════════════
    # 私有：格式化工具
    # ═══════════════════════════════════════════════════════════

    def _format_kpi_context(self, kpi_snapshots: list[dict]) -> str:
        """格式化 KPI 数据为分析上下文"""
        lines = []
        for s in kpi_snapshots:
            actual = s.get("actual")
            unit = s.get("unit", "")
            benchmark = s.get("benchmark")
            comparison = s.get("comparison_text", "")

            if actual is not None and actual != "" and actual != 0:
                status = "⚠️" if "低于" in str(comparison) or "落后" in str(comparison) else "✅"
                lines.append(
                    f"- {status} **{s['name']}**: {actual}{unit} | "
                    f"行业基准: {benchmark}{unit} | {comparison}"
                )
            else:
                lines.append(f"- ⚪ **{s['name']}**: 未提供数据（单位: {unit}）")

        return "\n".join(lines)

    def _format_red_flags_context(self, red_flags: list[dict]) -> str:
        """格式化红线预警"""
        if not red_flags:
            return "✅ 无红线触发"
        lines = []
        for r in red_flags:
            sev_icon = {"critical": "🔴🔴", "high": "🔴", "medium": "🟡"}.get(
                r.get("severity", ""), "⚪"
            )
            lines.append(
                f"- {sev_icon} **{r['metric']}**: 实际={r.get('actual','?')} "
                f"(阈值: {r.get('threshold','?')}) → {r.get('description','')}"
            )
        return "\n".join(lines)

    def _format_kpi_compact(self, kpi_snapshots: list[dict]) -> str:
        """紧凑格式的 KPI 列表（用于第二层建议生成）"""
        items = []
        for s in kpi_snapshots:
            actual = s.get("actual")
            if actual is not None and actual != "":
                items.append(f"{s['name']}={actual}{s.get('unit','')}")
        return ", ".join(items)

    def _build_observation(self, kpi_snapshots: list[dict], genome: IndustryGenome) -> str:
        """构建观察部分——数据事实"""
        has_data = any(
            s.get("actual") not in (None, 0, "", "0")
            for s in kpi_snapshots
        )

        lines = []
        if has_data:
            lines.append(f"## 📊 {genome.name}当日经营数据诊断\n")

        for s in kpi_snapshots:
            actual = s.get("actual")
            name = s["name"]
            unit = s.get("unit", "")
            comparison = s.get("comparison_text", "")
            benchmark = s.get("benchmark")

            if actual is not None and actual != "" and actual != 0:
                # 判断状态
                if "领先" in str(comparison):
                    icon = "🟢"
                elif "落后" in str(comparison) or "低于" in str(comparison):
                    icon = "🔴"
                else:
                    icon = "🟡"
                bm_str = f" | 行业基准 {benchmark}{unit}" if benchmark else ""
                lines.append(f"- {icon} **{name}**: {actual}{unit}{bm_str} → {comparison}")
            else:
                lines.append(f"- ⚪ **{name}**: 未提供{(' (单位: '+unit+')') if unit else ''}，{comparison}")

        return "\n".join(lines)

    def _build_attribution_text(self, attribution: dict, kpi_snapshots: list[dict]) -> str:
        """构建完整的深度归因文本——保留 AI 的完整分析"""

        sections = []

        # 1. 诊断摘要
        summary = attribution.get("summary", "")
        if summary:
            sections.append(f"## 🧠 诊断摘要\n\n{summary}")

        # 2. 核心根因
        primary = attribution.get("primary_root_cause", "")
        if primary:
            sections.append(f"## 🎯 核心根因\n\n> {primary}")

        # 3. 完整因果链
        causal = attribution.get("causal_chain", {})
        if isinstance(causal, dict):
            full_chain = causal.get("full_chain", "")
            if full_chain:
                sections.append(f"## 🔗 因果传导链\n\n{full_chain}")

            # 因果节点图
            nodes = causal.get("nodes", [])
            if nodes:
                node_lines = []
                for n in nodes:
                    icon = {"root_cause": "🔴", "intermediate": "🟡", "symptom": "🔵"}.get(
                        n.get("type", ""), "⚪"
                    )
                    node_lines.append(f"- {icon} **{n.get('name','')}** → {n.get('description','')}")
                sections.append(f"### 因果节点\n" + "\n".join(node_lines))

            # 恶性循环
            cycles = causal.get("vicious_cycles", [])
            if cycles:
                sections.append(f"### ⚠️ 恶性循环\n" + "\n".join(f"- {c}" for c in cycles))

        elif isinstance(causal, str) and causal:
            sections.append(f"## 🔗 因果传导链\n\n{causal}")

        # 4. 5 Why 分析
        five_whys = attribution.get("five_whys", [])
        if five_whys:
            sections.append("## 🔍 根因深挖 (5 Whys)")
            for fw in five_whys[:3]:
                issue = fw.get("trigger_issue", "")
                category = fw.get("root_cause_category", "")
                sections.append(f"\n### {issue}")
                for w in fw.get("whys", []):
                    sections.append(f"- **L{w['level']}**: {w['question']}\n  → {w['answer']}")
                if category:
                    sections.append(f"\n→ 归类: **{category}**")

        # 5. 反事实推理
        cf = attribution.get("counter_factual", [])
        if cf:
            sections.append("\n## 🔮 反事实推理（What If）")
            for item in sorted(cf, key=lambda x: x.get("roi_rank", 99)):
                sections.append(
                    f"- 如果 **{item.get('scenario','')}** → 预估每月可{'+' if '增加' in str(item.get('scenario','')) else '节省'}"
                    f"**{item.get('estimated_monthly_impact','?')}元** "
                    f"| 可行性: {'⭐⭐⭐' if item.get('feasibility')=='high' else '⭐⭐' if item.get('feasibility')=='medium' else '⭐'}"
                )

        # 6. 行动优先级矩阵
        matrix = attribution.get("action_matrix", [])
        if matrix:
            sections.append("\n## 📊 改进优先级矩阵")
            sections.append("| 优先级 | 行动 | 难度 | 影响 | 预计天数 | 负责人 |")
            sections.append("|--------|------|------|------|----------|--------|")
            for item in sorted(matrix, key=lambda x: x.get("priority_score", 99)):
                sections.append(
                    f"| #{item.get('priority_score','?')} | {item.get('action','')} | "
                    f"{item.get('difficulty','?')} | {item.get('impact','?')} | "
                    f"{item.get('effort_days','?')}天 | {item.get('owner','?')} |"
                )

        # 7. 异常扫描
        anomalies = attribution.get("anomaly_scan", [])
        if anomalies:
            sections.append("\n## 📋 异常扫描明细")
            sections.append("| 指标 | 实际值 | 基准 | 偏离 | 严重度 |")
            sections.append("|------|--------|------|------|--------|")
            for a in anomalies:
                sections.append(
                    f"| {a.get('metric','')} | {a.get('actual','')} | "
                    f"{a.get('benchmark','')} | {a.get('deviation','')} | "
                    f"{a.get('severity','')} |"
                )

        if sections:
            return "\n".join(sections)

        # 兜底：如果 AI 没有返回结构化数据
        raw = attribution.get("causal_chain", attribution.get("summary", str(attribution)))
        if isinstance(raw, dict):
            raw = raw.get("full_chain", json.dumps(raw, ensure_ascii=False, indent=2))
        return str(raw)

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """从AI响应中提取JSON"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到最外层的 { }
        brace_start = response.find("{")
        brace_end = response.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(response[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("[归因分析师] 无法解析JSON响应，返回原始文本")
        return {
            "summary": response[:500],
            "causal_chain": {"full_chain": response},
            "primary_root_cause": "解析失败，请查看原始分析",
            "analysis_confidence": 0.5,
        }
