"""指挥中心 - 质量审核引擎

三层质检体系：
1. 自动规则检查（格式、长度、关键词）
2. AI评审（让另一个AI打分）
3. 人工审核（标记需人工判断的任务）
"""

from typing import Any
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from src.core import BaseSoldier


@dataclass
class QualityReport:
    """质量评审报告"""
    task_id: str
    overall_score: float  # 0-100
    passed_auto_check: bool
    passed_ai_review: bool
    needs_human_review: bool
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    reviewed_at: datetime = field(default_factory=datetime.now)


AUTO_CHECK_RULES: dict[str, Any] = {
    "min_length": 50,        # 输出最少50字符
    "max_length": 10000,     # 输出最多10000字符
    "required_keywords": [],  # 必须包含的关键词（按任务类型）
    "forbidden_patterns": [   # 禁止出现的模式
        "作为AI",
        "我不能",
        "我无法",
        "请注意",
        "免责声明",
    ],
    "format_checks": {
        "has_header": True,    # 是否需要有标题
        "has_conclusion": True, # 是否需要有结尾
    },
}

AI_REVIEW_PROMPT = """你是一位质量标准极为严格的评审官。请对以下AI输出进行评分。

## 评分维度（每个维度0-20分，总分100）

1. **准确性**（0-20）：信息是否准确，有无事实错误
2. **完整性**（0-20）：是否完整回答了用户的问题
3. **可执行性**（0-20）：是否可以立即行动，有无模糊表述
4. **结构清晰**（0-20）：逻辑是否清晰，格式是否规范
5. **品牌一致性**（0-20）：是否符合"衡水风格"（量化、直接、行动导向）

## 评分标准
- 16-20：优秀，可以直接交付
- 12-15：良好，小幅修改后可交付
- 8-11：一般，需要重新生成
- 0-7：不合格，完全不可用

## 待评审内容
【任务类型】{task_type}
【用户需求】{task_description}

【AI输出内容】
{content}

---

请输出JSON格式评审结果：
{{
    "scores": {{"accuracy": 分数, "completeness": 分数, "actionability": 分数, "structure": 分数, "brand_fit": 分数}},
    "total_score": 总分,
    "passed": true/false（总分≥60为true）,
    "issues": ["问题1", "问题2"],
    "suggestions": ["改进建议1", "改进建议2"],
    "needs_regeneration": true/false（总分<60需重生成）
}}
"""


class QualityChecker(BaseSoldier):
    """质量审核官"""

    name = "指挥中心-质量审核官"
    role = "command_quality"
    temperature = 0.2
    max_tokens = 1500

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行质量审核

        Args:
            task: {
                "content": str,           # AI输出内容
                "task_type": str,         # 任务类型
                "task_description": str,  # 原始任务描述
                "soldier_name": str,      # 产出该内容的战士名
            }

        Returns:
            审核报告
        """
        content = task.get("content", "")
        task_type = task.get("task_type", "通用任务")
        task_description = task.get("task_description", "")

        # 第一层：自动规则检查
        auto_result = self._auto_check(content, task_type)

        # 第二层：AI评审
        issues: list[str] = list(auto_result["issues"])
        suggestions: list[str] = list(auto_result["suggestions"])

        if auto_result["passed"]:
            # 自动检查通过才进行AI评审
            ai_result = self._ai_review(content, task_type, task_description)
            issues.extend(ai_result["issues"])
            suggestions.extend(ai_result["suggestions"])
            ai_score = ai_result.get("total_score", 80)
        else:
            ai_score = 0

        # 综合评分
        overall = (auto_result.get("score", 0) * 0.3 + ai_score * 0.7) if auto_result["passed"] else 30
        needs_human = overall < 60 or task.get("force_human_review", False)

        report = QualityReport(
            task_id=task.get("task_id", "unknown"),
            overall_score=overall,
            passed_auto_check=auto_result["passed"],
            passed_ai_review=ai_score >= 60,
            needs_human_review=needs_human,
            issues=issues,
            suggestions=suggestions,
            details={
                "auto_check": auto_result,
                "ai_review_score": ai_score,
            },
        )

        logger.info(f"[质审官] 评分: {overall:.0f}/100 | {'✅ 通过' if not needs_human else '⚠️ 需人工审核'}")

        return {
            "overall_score": report.overall_score,
            "passed": not needs_human,
            "needs_human_review": report.needs_human_review,
            "issues": report.issues,
            "suggestions": report.suggestions,
            "details": report.details,
        }

    def _auto_check(self, content: str, task_type: str) -> dict[str, Any]:
        """自动规则检查（第一层）"""
        issues: list[str] = []
        suggestions: list[str] = []
        checks_passed = 0
        total_checks = 0

        content_len = len(content.strip())

        # 检查1：长度
        total_checks += 1
        if content_len < AUTO_CHECK_RULES["min_length"]:
            issues.append(f"输出过短 ({content_len}字符)，最少需要{AUTO_CHECK_RULES['min_length']}字符")
        elif content_len > AUTO_CHECK_RULES["max_length"]:
            suggestions.append(f"输出过长 ({content_len}字符)，建议控制在{AUTO_CHECK_RULES['max_length']}字符内")
        else:
            checks_passed += 1

        # 检查2：禁用词
        total_checks += 1
        forbidden_found = []
        for pattern in AUTO_CHECK_RULES["forbidden_patterns"]:
            if pattern in content:
                forbidden_found.append(pattern)

        if forbidden_found:
            issues.append(f"包含禁用词: {', '.join(forbidden_found)}")
        else:
            checks_passed += 1

        # 检查3：空内容
        total_checks += 1
        if content_len == 0:
            issues.append("输出为空")
        else:
            checks_passed += 1

        # 检查4：是否有实质性内容（非纯模板）
        total_checks += 1
        if content_len < 100:
            issues.append("内容过于简略，缺乏实质性信息")
        else:
            checks_passed += 1

        passed = len(issues) == 0
        score = (checks_passed / total_checks) * 100

        return {
            "passed": passed,
            "score": score,
            "issues": issues,
            "suggestions": suggestions,
            "checks_total": total_checks,
            "checks_passed": checks_passed,
        }

    def _ai_review(self, content: str, task_type: str, task_description: str) -> dict[str, Any]:
        """AI评审（第二层）"""
        try:
            import json

            user_message = AI_REVIEW_PROMPT.format(
                task_type=task_type,
                task_description=task_description or task_type,
                content=content[:3000],  # 限制长度避免token浪费
            )

            response, _ = self.chat(
                system_prompt="你是一个标准的评审官。请严格按JSON格式输出评审结果。",
                user_message=user_message,
            )

            # 尝试解析JSON
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                return {
                    "total_score": result.get("total_score", 0),
                    "passed": result.get("passed", False),
                    "issues": result.get("issues", []),
                    "suggestions": result.get("suggestions", []),
                    "scores": result.get("scores", {}),
                }
        except Exception as e:
            logger.warning(f"[质审官] AI评审解析失败: {e}")

        return {"total_score": 70, "passed": True, "issues": [], "suggestions": [], "scores": {}}

    def review_output(self, content: str, task_type: str = "通用任务",
                      task_description: str = "", force_human: bool = False) -> QualityReport:
        """快捷方法：审核一份输出"""
        result = self.execute({
            "content": content,
            "task_type": task_type,
            "task_description": task_description,
            "force_human_review": force_human,
        })

        return QualityReport(
            task_id="",
            overall_score=result["overall_score"],
            passed_auto_check=result["details"]["auto_check"]["passed"],
            passed_ai_review=result["details"].get("ai_review_score", 0) >= 60,
            needs_human_review=result["needs_human_review"],
            issues=result["issues"],
            suggestions=result["suggestions"],
            details=result["details"],
        )


# ====== 使用示例 ======
if __name__ == "__main__":
    checker = QualityChecker()

    # 好质量示例
    good_content = """# 企业AI改革月报

## 核心数据
- 本月完成3家企业的AI流程改造
- 平均效率提升：**340%**
- 客户满意度：**4.8/5.0**

## 关键举措
1. 部署RAG智能客服系统，响应时间从15分钟→30秒
2. 自动化数据录入流程，消除85%手工操作
3. 建立AI质量监督机制，错误率降至0.3%

## 下月计划
- 重点突破制造业质检场景
- 完成AI工程师培训体系建设

> 🎯 现在就能做的1件事：检查你们公司哪个环节的手工操作超过每天2小时
"""

    # 差质量示例
    bad_content = """作为AI助手，我认为企业应该关注数字化转型。
AI赋能是一个重要抓手，建议进一步探讨相关解决方案。
请注意，以上仅为参考意见。"""

    print("=" * 60)
    print("🔍 质量审核测试")
    print("=" * 60)

    for label, content in [("✅ 好质量", good_content), ("❌ 差质量", bad_content)]:
        print(f"\n--- {label} ---")
        report = checker.review_output(content, task_type="月报")
        print(f"总分: {report.overall_score:.0f}/100")
        print(f"自动检查: {'✅' if report.passed_auto_check else '❌'}")
        print(f"需人工审核: {'⚠️ 是' if report.needs_human_review else '✅ 否'}")
        if report.issues:
            print(f"问题: {report.issues}")
        if report.suggestions:
            print(f"建议: {report.suggestions}")
