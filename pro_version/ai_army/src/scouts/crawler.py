"""侦察兵 - 网络爬虫引擎

支持：
- 静态页面爬取（requests + BeautifulSoup）
- 动态页面爬取（Playwright）
- RSS订阅源解析
- 可配置的目标站点列表
"""

import time
import random
from typing import Any
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import feedparser
from loguru import logger

from config.env import USER_AGENT, CRAWL_DELAY, CRAWL_MAX_RETRIES

# ========== 默认监控目标 ==========
DEFAULT_TARGETS: list[dict[str, Any]] = [
    {
        "name": "36氪AI频道",
        "url": "https://36kr.com/newsflashes",
        "type": "static",
        "selector": ".newsflash-item",  # 新闻条目选择器
        "title_selector": ".item-title",
        "link_attr": "href",
    },
    {
        "name": "机器之心",
        "url": "https://www.jiqizhixin.com/rss",
        "type": "rss",
    },
    {
        "name": "GitHub Trending",
        "url": "https://github.com/trending/python?since=daily",
        "type": "static",
        "selector": "article.Box-row",
        "title_selector": "h2 a",
        "link_attr": "href",
    },
]


def fetch_page(url: str, timeout: int = 30) -> str | None:
    """获取页面HTML（带重试和随机延迟）"""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    for attempt in range(1, CRAWL_MAX_RETRIES + 1):
        try:
            time.sleep(random.uniform(CRAWL_DELAY * 0.5, CRAWL_DELAY * 1.5))
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"[爬虫] {url} 第{attempt}次失败: {e}")
            if attempt == CRAWL_MAX_RETRIES:
                logger.error(f"[爬虫] {url} 全部重试失败")
                return None
            time.sleep(3 ** attempt)
    return None


def parse_rss(url: str) -> list[dict[str, str]]:
    """解析RSS源"""
    items: list[dict[str, str]] = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:  # 最多取20条
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "")[:500],
                "published": entry.get("published", ""),
                "source": feed.feed.get("title", url),
            })
        logger.info(f"[RSS] {url} → 获取 {len(items)} 条")
    except Exception as e:
        logger.error(f"[RSS] {url} 解析失败: {e}")
    return items


def parse_html(html: str, config: dict[str, Any], base_url: str = "") -> list[dict[str, str]]:
    """从HTML中提取新闻条目"""
    items: list[dict[str, str]] = []
    try:
        soup = BeautifulSoup(html, "lxml")
        elements = soup.select(config.get("selector", "a"))

        for el in elements[:15]:
            title_el = el.select_one(config.get("title_selector", "")) if config.get("title_selector") else el
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            link = ""
            if config.get("link_attr"):
                link_el = el if config.get("link_attr") in (el.attrs or {}) else title_el
                link = link_el.get(config["link_attr"], "")
                if link and not link.startswith("http"):
                    link = base_url.rstrip("/") + "/" + link.lstrip("/")

            items.append({
                "title": title,
                "link": link,
                "source": config.get("name", base_url),
                "crawled_at": datetime.now().isoformat(),
            })

        logger.info(f"[HTML] {config.get('name', base_url)} → 获取 {len(items)} 条")
    except Exception as e:
        logger.error(f"[HTML] 解析失败: {e}")
    return items


def crawl_all(targets: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """爬取所有目标站点，返回新闻列表

    Args:
        targets: 目标站点配置列表，为None时使用默认配置

    Returns:
        所有爬取到的新闻条目（去重合并）
    """
    if targets is None:
        targets = DEFAULT_TARGETS

    all_items: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for target in targets:
        target_type = target.get("type", "static")
        name = target.get("name", target.get("url", "unknown"))
        url = target.get("url", "")

        logger.info(f"[爬虫] 开始爬取: {name}")

        if target_type == "rss":
            items = parse_rss(url)
        else:
            html = fetch_page(url)
            if html:
                items = parse_html(html, target, url)
            else:
                items = []

        # 去重
        for item in items:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                all_items.append(item)

    logger.info(f"[爬虫] 总计获取: {len(all_items)} 条（去重后）")
    return all_items


if __name__ == "__main__":
    # 测试爬虫
    news = crawl_all()
    for i, n in enumerate(news[:10], 1):
        print(f"{i}. {n['title']}")
        print(f"   {n['link']}")
        print(f"   来源: {n['source']}")
        print()
