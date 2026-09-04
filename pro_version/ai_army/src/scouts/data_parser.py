"""全知感知网 - 经营数据解析器

升级 src/scouts/，增加对商家上传的 Excel/CSV 经营数据的解析能力。
这是 AI军团的"核心优势"——不仅监控外部情报，更深度理解内部经营数据。

支持：
- 自动识别行业相关列名（中文/英文）
- 行业基因驱动的列映射
- 数据质量报告（缺失值、异常值、格式问题）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import io

import pandas as pd
from loguru import logger

from config.industry_genome import get_genome, IndustryGenome


class DataParser:
    """经营数据解析器

    使用示例:
        parser = DataParser("restaurant")
        df, report = parser.parse("uploads/sales_2024.xlsx")
        validated = parser.validate_against_genome(df)
    """

    def __init__(self, store_type: str = "custom") -> None:
        self.store_type = store_type
        self.genome: IndustryGenome = get_genome(store_type)
        self._df: pd.DataFrame | None = None

    # ── 文件解析 ──────────────────────────────────────

    def parse(self, filepath: str) -> tuple[pd.DataFrame, dict[str, Any]]:
        """解析经营数据文件

        Returns:
            (DataFrame, 解析报告)
        """
        path = Path(filepath)
        suffix = path.suffix.lower()

        if suffix == ".csv":
            df = pd.read_csv(filepath, encoding="utf-8")
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {suffix}，仅支持 .csv / .xlsx / .xls")

        self._df = df
        report = self._build_parse_report(df, path.name)
        logger.info(f"[感知网] 解析完成: {path.name} ({len(df)}行 x {len(df.columns)}列)")
        return df, report

    def parse_bytes(self, filename: str, content: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
        """从上传的字节内容解析"""
        suffix = Path(filename).suffix.lower()

        if suffix == ".csv":
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")

        self._df = df
        report = self._build_parse_report(df, filename)
        logger.info(f"[感知网] 解析完成: {filename} ({len(df)}行 x {len(df.columns)}列)")
        return df, report

    def _build_parse_report(self, df: pd.DataFrame, filename: str) -> dict[str, Any]:
        """构建解析报告"""
        # 识别可映射的KPI列
        mapped_columns = self._map_columns(df)
        unmapped = [c for c in df.columns if c not in mapped_columns]

        # 数据质量
        total_cells = df.size
        missing_cells = df.isnull().sum().sum()
        missing_pct = round(missing_cells / total_cells * 100, 1) if total_cells else 0

        return {
            "filename": filename,
            "rows": len(df),
            "columns": len(df.columns),
            "industry": self.genome.name,
            "mapped_kpi_columns": {k: v for k, v in mapped_columns.items()},
            "unmapped_columns": unmapped,
            "kpi_coverage": f"{len(mapped_columns)}/{len(self.genome.kpi_formulas)} 行业KPI已识别",
            "data_quality": {
                "missing_cells": int(missing_cells),
                "missing_pct": missing_pct,
                "quality": "good" if missing_pct < 5 else ("fair" if missing_pct < 15 else "poor"),
            },
        }

    # ── 列名智能映射 ──────────────────────────────────

    def _map_columns(self, df: pd.DataFrame) -> dict[str, str]:
        """将DataFrame的列名智能映射到行业KPI"""
        mapping: dict[str, str] = {}
        kpi_names = list(self.genome.kpi_formulas.keys())

        for col in df.columns:
            col_lower = str(col).lower().strip()
            for kpi in kpi_names:
                kpi_lower = kpi.lower()
                # 精确匹配或包含匹配
                if col_lower == kpi_lower or kpi_lower in col_lower or col_lower in kpi_lower:
                    mapping[col] = kpi
                    break
        return mapping

    # ── 基因组驱动的数据验证 ──────────────────────────

    def validate_against_genome(self, df: pd.DataFrame | None = None) -> dict[str, Any]:
        """将数据与行业基因库的基准和红线对比验证

        Returns:
            验证报告：KPI快照、对比结果、红线触发、整体健康度
        """
        df = df or self._df
        if df is None:
            return {"error": "请先解析数据"}

        mapped = self._map_columns(df)
        if not mapped:
            return {
                "warning": "未能将任何列映射到行业KPI，请检查列名是否与行业KPI名称匹配",
                "expected_kpis": list(self.genome.kpi_formulas.keys()),
            }

        # 计算每个识别到的KPI的实际值
        kpi_values: dict[str, float] = {}
        kpi_snapshots: list[dict[str, Any]] = []
        genome = self.genome

        for col_name, kpi_name in mapped.items():
            series = df[col_name]
            if not pd.api.types.is_numeric_dtype(series):
                continue

            actual = float(series.mean())
            kpi_values[kpi_name] = actual

            benchmark = genome.get_benchmark(kpi_name, "average")
            comparison = genome.benchmark_comparison(kpi_name, actual)
            deviation = None
            if benchmark:
                deviation = round((actual / benchmark - 1) * 100, 1)

            kpi_snapshots.append({
                "name": kpi_name,
                "actual": round(actual, 2),
                "unit": genome.kpi_formulas.get(kpi_name, {}).get("unit", ""),
                "benchmark": benchmark,
                "deviation_pct": deviation,
                "comparison_text": comparison,
            })

        # 检查红线
        red_flags_triggered = genome.check_red_flags(kpi_values)

        # 健康度评估
        critical_flags = [f for f in red_flags_triggered if f.get("severity") == "critical"]
        high_flags = [f for f in red_flags_triggered if f.get("severity") == "high"]
        if critical_flags:
            health = "critical"
        elif high_flags:
            health = "warning"
        else:
            health = "healthy"

        return {
            "store_type": self.store_type,
            "industry": genome.name,
            "kpi_snapshots": kpi_snapshots,
            "mapped_count": len(mapped),
            "total_kpis": len(genome.kpi_formulas),
            "red_flags_triggered": red_flags_triggered,
            "health": health,
            "health_description": {
                "critical": "存在严重经营风险，需要立即干预",
                "warning": "部分指标偏离基准，需要关注",
                "healthy": "当前各项指标均在安全范围内",
            }.get(health, ""),
        }

    # ── 数据快照生成 ──────────────────────────────────

    def build_data_snapshot(self, df: pd.DataFrame | None = None) -> str:
        """构建数据快照文本（用于注入AI分析）"""
        df = df or self._df
        if df is None:
            return ""

        lines: list[str] = [
            f"## 数据概览 ({self.genome.name})",
            f"- 行数: {len(df)}",
            f"- 列数: {len(df.columns)}",
            f"- 列名: {', '.join(df.columns.tolist())}",
            f"- 缺失值: {df.isnull().sum().sum()} 个",
            "",
            "## 行业KPI识别结果",
        ]

        mapped = self._map_columns(df)
        for col, kpi in mapped.items():
            formula = self.genome.kpi_formulas.get(kpi, {})
            lines.append(f"- {col} → **{kpi}** ({formula.get('unit', '')}): {formula.get('formula', '')}")

        lines.append("")
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
                top5 = df[col].value_counts().head(5)
                lines.append("- Top5值:")
                for val, cnt in top5.items():
                    lines.append(f"  - {val}: {cnt}次")

        lines.append("\n## 数据样本（前5行）")
        lines.append(df.head(5).to_string())

        return "\n".join(lines)
