"""参谋部 - 数据分析Agent

核心能力：
- 读取CSV/Excel数据并自动探索
- 基于自然语言对数据提问
- 调用DeepSeek生成分析洞察
"""

from typing import Any
from pathlib import Path

import pandas as pd
from loguru import logger

from src.core import BaseSoldier
from config.prompts.analysis_prompts import ANALYSIS_SYSTEM_PROMPT


class DataAnalyst(BaseSoldier):
    """数据分析参谋 - 自动分析数据并生成洞察"""

    name = "参谋-数据分析师"
    role = "staff_analyst"
    temperature = 0.3  # 数据分析要求精确，降低温度
    max_tokens = 2500

    def __init__(self) -> None:
        super().__init__()
        self.current_df: pd.DataFrame | None = None
        self.data_path: str = ""

    def load_data(self, filepath: str) -> pd.DataFrame:
        """加载数据文件（支持CSV和Excel）

        Args:
            filepath: 数据文件路径

        Returns:
            加载的DataFrame
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"数据文件不存在: {filepath}")

        suffix = path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(filepath, encoding="utf-8")
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {suffix}，仅支持 .csv / .xlsx / .xls")

        self.current_df = df
        self.data_path = filepath
        logger.info(f"[数据分析师] 已加载数据: {filepath} ({len(df)} 行 x {len(df.columns)} 列)")
        return df

    def _build_data_snapshot(self, df: pd.DataFrame) -> str:
        """构建数据快照文本，供AI分析"""
        lines: list[str] = []

        # 基本信息
        lines.append(f"## 数据概览")
        lines.append(f"- 行数: {len(df)}")
        lines.append(f"- 列数: {len(df.columns)}")
        lines.append(f"- 列名: {', '.join(df.columns.tolist())}")
        lines.append(f"- 缺失值: {df.isnull().sum().sum()} 个")
        lines.append("")

        # 各列基础统计
        lines.append("## 各列统计")
        for col in df.columns:
            lines.append(f"\n### {col} (类型: {df[col].dtype})")
            lines.append(f"- 缺失: {df[col].isnull().sum()}")
            lines.append(f"- 唯一值: {df[col].nunique()}")

            if pd.api.types.is_numeric_dtype(df[col]):
                desc = df[col].describe()
                lines.append(f"- 均值: {desc['mean']:.2f}")
                lines.append(f"- 标准差: {desc['std']:.2f}")
                lines.append(f"- 最小值: {desc['min']:.2f}")
                lines.append(f"- 中位数: {desc['50%']:.2f}")
                lines.append(f"- 最大值: {desc['max']:.2f}")
            else:
                # 分类/文本列：展示Top5
                top5 = df[col].value_counts().head(5)
                lines.append("- Top5值:")
                for val, cnt in top5.items():
                    lines.append(f"  - {val}: {cnt}次")

        # 数据样本
        lines.append("\n## 数据样本（前5行）")
        lines.append(df.head(5).to_string())

        return "\n".join(lines)

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行数据分析任务

        Args:
            task: {
                "filepath": str,          # 数据文件路径
                "question": str,           # 分析问题（可选）
                "analysis_type": str,      # general/sales/trend/anomaly（可选）
            }

        Returns:
            {"report": str, "tokens_used": int, "df_shape": tuple}
        """
        # 加载数据
        filepath = task.get("filepath")
        if filepath:
            df = self.load_data(filepath)
        elif self.current_df is not None:
            df = self.current_df
        else:
            raise ValueError("请先提供数据文件路径或调用 load_data()")

        question = task.get("question", "请对该数据进行全面分析，发现关键洞察和趋势。")
        analysis_type = task.get("analysis_type", "general")

        # 构建数据快照
        data_snapshot = self._build_data_snapshot(df)

        # 构建分析问题
        type_guidance = {
            "general": "全面分析数据特征、趋势和关键洞察",
            "sales": "重点分析销售趋势、客户行为、转化漏斗",
            "trend": "重点分析时间趋势、周期性模式和增长率",
            "anomaly": "重点识别异常值、突变点和需要警觉的指标",
        }

        user_message = f"""【分析类型】{type_guidance.get(analysis_type, type_guidance['general'])}

【用户问题】{question}

【数据详情】
{data_snapshot}

请按照系统指令中的衡水风格分析框架，给出你的专业分析报告。"""

        logger.info(f"[数据分析师] 开始分析 (类型: {analysis_type})...")
        report, tokens = self.chat(ANALYSIS_SYSTEM_PROMPT, user_message)
        logger.info(f"[数据分析师] 分析完成，消耗 {tokens} tokens")

        return {
            "report": report,
            "tokens_used": tokens,
            "df_shape": (len(df), len(df.columns)),
            "columns": df.columns.tolist(),
        }

    def ask_question(self, question: str) -> str:
        """直接对已加载的数据提问

        Args:
            question: 自然语言问题

        Returns:
            AI回答
        """
        if self.current_df is None:
            return "⚠️ 请先使用 load_data() 加载数据文件"

        result = self.execute({
            "question": question,
            "analysis_type": "general",
        })
        return result["report"]

    def detect_anomalies(self, column: str | None = None) -> dict[str, Any]:
        """检测数据异常

        Args:
            column: 指定列名，为None时检测所有数值列

        Returns:
            异常检测结果
        """
        if self.current_df is None:
            return {"error": "请先加载数据"}

        df = self.current_df
        if column:
            columns = [column]
        else:
            columns = df.select_dtypes(include=["number"]).columns.tolist()

        anomalies: dict[str, list[dict[str, Any]]] = {}
        for col in columns:
            values = df[col].dropna()
            mean = values.mean()
            std = values.std()
            threshold = 2 * std
            outlier_mask = abs(values - mean) > threshold
            anomaly_indices = df.index[df[col].notna() & (abs(df[col] - mean) > threshold)].tolist()

            if anomaly_indices:
                anomalies[col] = [
                    {"index": idx, "value": float(df.loc[idx, col]), "deviation": float((df.loc[idx, col] - mean) / std)}
                    for idx in anomaly_indices
                ]

        return {
            "total_anomalies": sum(len(v) for v in anomalies.values()),
            "columns_analyzed": len(columns),
            "anomalies": anomalies,
            "threshold": "2σ (2个标准差)",
        }


# ====== 使用示例 ======
if __name__ == "__main__":
    # 创建分析官
    analyst = DataAnalyst()

    # 如果有数据文件就直接分析
    # analyst.load_data("data/sales_2024.csv")
    # report = analyst.ask_question("分析Q3销售下滑的原因")

    # 或者用代码创建一个示例数据做演示
    import numpy as np
    demo_df = pd.DataFrame({
        "日期": pd.date_range("2024-01-01", periods=30),
        "销售额": np.random.normal(10000, 2000, 30).cumsum() / 10,
        "客户数": np.random.randint(50, 200, 30),
        "转化率": np.random.uniform(0.02, 0.08, 30),
        "渠道": np.random.choice(["官网", "广告", "转介绍", "活动"], 30),
    })

    # 保存为示例文件
    import os
    os.makedirs("data", exist_ok=True)
    demo_df.to_csv("data/demo_sales.csv", index=False)

    # 分析
    analyst.load_data("data/demo_sales.csv")
    report = analyst.ask_question("分析我的业务表现，找出最大问题和最大机会")
    print(report)
