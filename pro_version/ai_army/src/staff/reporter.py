"""参谋部 - 报告生成器

将AI分析结果转为格式化输出：
- Markdown报告
- HTML报告（可直接浏览器查看）
- PDF报告（需weasyprint）
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --primary: #1a1a2e;
            --accent: #e94560;
            --bg: #f8f9fa;
            --card-bg: #ffffff;
            --text: #2d3436;
            --border: #dfe6e9;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.8;
            padding: 40px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{
            background: var(--primary);
            color: white;
            padding: 40px;
            border-radius: 16px;
            margin-bottom: 30px;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
        .header .meta {{ opacity: 0.8; font-size: 14px; }}
        .badge {{
            display: inline-block;
            background: var(--accent);
            color: white;
            padding: 3px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-right: 8px;
        }}
        .card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 28px;
            margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            border: 1px solid var(--border);
        }}
        .card h2 {{ font-size: 20px; margin-bottom: 16px; color: var(--primary); }}
        .card h3 {{ font-size: 16px; margin: 16px 0 8px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0;
        }}
        th, td {{
            text-align: left;
            padding: 10px 14px;
            border-bottom: 1px solid var(--border);
        }}
        th {{ background: #f1f3f4; font-weight: 600; }}
        .tag-red {{ color: #e94560; font-weight: 600; }}
        .tag-green {{ color: #27ae60; font-weight: 600; }}
        .tag-yellow {{ color: #f39c12; font-weight: 600; }}
        .footer {{
            text-align: center;
            color: #b2bec3;
            font-size: 13px;
            margin-top: 40px;
            padding: 20px;
        }}
        code {{ background: #f1f3f4; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
        pre {{ background: #1a1a2e; color: #e0e0e0; padding: 20px; border-radius: 8px; overflow-x: auto; }}
        blockquote {{
            border-left: 4px solid var(--accent);
            padding-left: 16px;
            margin: 12px 0;
            color: #636e72;
            background: #fff5f5;
            padding: 12px 16px;
            border-radius: 0 8px 8px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <div class="meta">
                <span class="badge">AI军团参谋部</span>
                生成时间: {timestamp} | 分析引擎: DeepSeek + 衡水模式
            </div>
        </div>
        {content}
        <div class="footer">
            <p>本报告由AI军团参谋部自动生成 | 仅供决策参考</p>
        </div>
    </div>
</body>
</html>"""


def markdown_to_html_sections(md_text: str) -> str:
    """将Markdown内容转换为HTML卡片式布局

    简易转换：识别 ## 一级标题为卡片，内部保留内容。
    """
    lines = md_text.split("\n")
    sections: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    html_parts: list[str] = []
    for section in sections:
        title = section[0].replace("## ", "").strip()
        body = "\n".join(section[1:]).strip()

        # 简易Markdown→HTML转换
        body_html = _simple_md_to_html(body)

        html_parts.append(f"""
        <div class="card">
            <h2>{title}</h2>
            {body_html}
        </div>
        """)

    return "\n".join(html_parts)


def _simple_md_to_html(text: str) -> str:
    """简易Markdown→HTML（处理常见格式）"""
    import re

    html = text

    # 代码块 ```
    html = re.sub(r"```(\w*)\n(.*?)```", r"<pre><code>\2</code></pre>", html, flags=re.DOTALL)

    # 行内代码
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)

    # 粗体 **
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)

    # ### 三级标题
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)

    # 引用块 >
    lines = html.split("\n")
    result: list[str] = []
    in_quote = False
    quote_lines: list[str] = []

    for line in lines:
        if line.startswith("> "):
            if not in_quote:
                in_quote = True
                quote_lines = []
            quote_lines.append(line[2:])
        else:
            if in_quote:
                result.append("<blockquote>" + "<br>".join(quote_lines) + "</blockquote>")
                in_quote = False
            result.append(line)
    if in_quote:
        result.append("<blockquote>" + "<br>".join(quote_lines) + "</blockquote>")

    html = "\n".join(result)

    # 表格（简易处理）
    # Markdown表格转HTML表格
    table_pattern = re.compile(r"(\|.+\|\n\|[-| ]+\|\n(?:\|.+\|\n?)+)", re.MULTILINE)

    def table_replacer(m: re.Match) -> str:
        table_text = m.group(1)
        rows = table_text.strip().split("\n")
        # 跳过分隔行
        data_rows = [r for r in rows if not re.match(r"^\|[-| ]+\|$", r.strip())]
        html_rows: list[str] = []
        for i, row in enumerate(data_rows):
            cells = [c.strip() for c in row.split("|")[1:-1]]
            tag = "th" if i == 0 else "td"
            html_rows.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        return f"<table>{''.join(html_rows)}</table>"

    html = table_pattern.sub(table_replacer, html)

    # 空行→段落分隔
    html = re.sub(r"\n\n+", "<br><br>", html)
    html = re.sub(r"\n", "<br>", html)

    # 高亮标签
    html = re.sub(r"🔴\s*", r'<span class="tag-red">🔴</span> ', html)
    html = re.sub(r"🟢\s*", r'<span class="tag-green">🟢</span> ', html)
    html = re.sub(r"🟡\s*", r'<span class="tag-yellow">🟡</span> ', html)

    return html


def generate_html_report(analysis_text: str, title: str = "数据分析报告") -> str:
    """生成HTML格式分析报告

    Args:
        analysis_text: AI分析文本（Markdown格式）
        title: 报告标题

    Returns:
        HTML字符串
    """
    content_html = markdown_to_html_sections(analysis_text)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    return HTML_TEMPLATE.format(
        title=title,
        timestamp=timestamp,
        content=content_html,
    )


def generate_markdown_report(analysis_text: str, title: str = "数据分析报告") -> str:
    """生成Markdown格式分析报告（添加页眉页脚）

    Args:
        analysis_text: AI分析文本
        title: 报告标题

    Returns:
        完整的Markdown文本
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"# {title}\n\n> 📅 生成时间: {timestamp} | 🏛️ 生成引擎: AI军团参谋部\n\n---\n\n"
    footer = f"\n\n---\n\n*📌 本报告由AI军团参谋部自动生成 | 衡水模式 v1.0 | {timestamp}*"
    return header + analysis_text + footer


def save_report(analysis_text: str, output_dir: str = "./data/reports",
                fmt: str = "both", title: str = "数据分析报告") -> dict[str, str]:
    """保存报告到文件

    Args:
        analysis_text: 分析内容
        output_dir: 输出目录
        fmt: 格式 "md"/"html"/"both"
        title: 报告标题

    Returns:
        {"md": "path/to/file.md", "html": "path/to/file.html"}
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    results: dict[str, str] = {}

    if fmt in ("md", "both"):
        md_path = f"{output_dir}/report_{date_str}.md"
        md_content = generate_markdown_report(analysis_text, title)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        results["md"] = md_path
        logger.info(f"[报告] Markdown已保存: {md_path}")

    if fmt in ("html", "both"):
        html_path = f"{output_dir}/report_{date_str}.html"
        html_content = generate_html_report(analysis_text, title)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        results["html"] = html_path
        logger.info(f"[报告] HTML已保存: {html_path}")

    return results


# ====== 使用示例 ======
if __name__ == "__main__":
    sample = """## 一、核心指标速览
| 指标 | 当前值 | 环比变化 | 状态 |
|------|--------|----------|------|
| 日活用户 | 12,340 | +8.5% | 🟢 增长 |

## 二、关键发现
### 🔴 问题发现
- 转化率从3.2%降至2.1%，下降幅度达34%

### 🟢 亮点发现
- 自然搜索流量增长45%，SEO效果显著

## 三、根因分析
- 第1层：转化率下降主要发生在移动端
- 第2层：移动端页面加载速度从2.1s劣化至4.3s
- 第3层：上周CDN迁移时未做性能回退方案

## 四、行动建议
- 🔴 P0 - 立即回退CDN配置，恢复移动端加载速度
- 🟡 P1 - 建立页面性能监控告警（阈值>3s自动通知）
- 🟢 P2 - 制定发版checklist，包含性能测试环节
"""

    save_report(sample, fmt="both", title="示例分析报告")
    print("✅ 报告已生成在 ./data/reports/ 目录")
