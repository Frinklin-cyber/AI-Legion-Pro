"""行业基因库

主动的 AI-SOP 商业操作系统的第一层：行业基因库 (Genome Layer)。

所有行业配置从 YAML 文件读取，严禁在 Python 代码中硬编码行业名称或指标公式。
"""

from config.industry_genome.loader import (
    IndustryGenome,
    GenomeLoader,
    get_loader,
    get_genome,
    infer_genome_from_poi_type,
    list_genomes,
)

__all__ = [
    "IndustryGenome",
    "GenomeLoader",
    "get_loader",
    "get_genome",
    "infer_genome_from_poi_type",
    "list_genomes",
]
