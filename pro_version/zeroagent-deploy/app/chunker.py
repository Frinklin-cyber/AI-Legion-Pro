"""
chunker.py
切分策略：
- chunk_size=500 字符，overlap=50 字符（滑窗）
- 优先按章节/标题切分（Markdown 标题 #/##，或 "第X章/X节" 中文标题）
- 每个 chunk 保留 source_file + page_number 元数据
"""

import re
from dataclasses import dataclass

# 标题行：Markdown #/##/###/#### 或 中文"第X章/节/部"
HEADING_RE = re.compile(r"(?m)^(#{1,4}\s.*|第[一二三四五六七八九十百千万0-9０-９]+[章节部].*)$")


@dataclass
class Chunk:
    source_file: str
    page_number: int
    index: int
    text: str


def split_by_headings(text: str):
    """按标题切分为 [(heading, section_text), ...]。无标题时返回 [("", 全文)]。"""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group().strip(), text[start:end]))
    return sections


def _slide(text: str, chunk_size: int, overlap: int) -> list:
    """字符滑窗切分（首尾重叠 overlap 字符）"""
    if len(text) <= chunk_size:
        return [text]
    step = max(1, chunk_size - overlap)
    parts = []
    start = 0
    while start < len(text):
        parts.append(text[start:start + chunk_size])
        start += step
    return parts


def chunk_pages(pages, source_file: str, chunk_size: int = 500, overlap: int = 50) -> list:
    """
    将提取出的文本页切分为 chunk 列表。
    pages: extractor 输出的 ExtractedPage 列表。
    """
    chunks = []
    idx = 0
    for page in pages:
        for heading, body in split_by_headings(page.text):
            seg = f"{heading}\n{body}" if heading else body
            for part in _slide(seg, chunk_size, overlap):
                part = part.strip()
                if not part:
                    continue
                chunks.append(Chunk(
                    source_file=source_file,
                    page_number=page.page_number,
                    index=idx,
                    text=part,
                ))
                idx += 1
    return chunks
