"""AI军团 - 统一API响应模型

所有核心 API 返回结构遵循诊断五步法：
Observation → Attribution → Recommendation → Expected Impact → Action Items
"""

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DiagnosisResponse(BaseModel):
    """核心诊断响应 - 所有分析类API的返回标准"""
    observation: str = Field(..., description="客观事实（含数据对比）")
    attribution: str = Field(..., description="归因分析（根本原因）")
    recommendation: str = Field(..., description="具体建议方案")
    expected_impact: str = Field(..., description="预期收益（量化指标）")
    action_items: list[str] = Field(default_factory=list, description="待办事项列表")
    benchmarks_used: dict[str, Any] = Field(default_factory=dict)
    red_flags_triggered: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class KpiSnapshot(BaseModel):
    """KPI快照：实际值 vs 基准值"""
    name: str
    actual: float
    unit: str = ""
    benchmark: Optional[float] = None
    benchmark_level: Optional[str] = None
    deviation_pct: Optional[float] = None
    comparison_text: str = ""


class BriefingResponse(BaseModel):
    """情报简报响应"""
    briefing: str
    diagnosis: Optional[DiagnosisResponse] = None
    item_count: int = 0
    tokens_used: int = 0
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class DataAnalysisResponse(BaseModel):
    """数据分析响应 - 兼容原有API且增强"""
    report: str
    diagnosis: Optional[DiagnosisResponse] = None
    kpi_snapshots: list[KpiSnapshot] = Field(default_factory=list)
    df_shape: tuple[int, int] = (0, 0)
    columns: list[str] = Field(default_factory=list)
    tokens_used: int = 0


class KnowledgeResponse(BaseModel):
    """知识库问答响应"""
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    context_count: int = 0


class SoldierInfo(BaseModel):
    """战士信息"""
    name: str
    role: str
    status: str = "active"


class MissionRecord(BaseModel):
    """任务记录"""
    task_id: str
    soldier: str
    status: str
    input: str
    output: str = ""
    duration: str = ""
    tokens: int = 0
    error: str = ""


class SystemStatus(BaseModel):
    """系统总状态"""
    soldiers: int = 0
    missions: int = 0
    knowledge_docs: int = 0
    scheduler_active: bool = False
    genome_count: int = 0
