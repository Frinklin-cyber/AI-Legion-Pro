"""区域上下文增强器 (Region Enricher)

处理流程：
1. 调用高德地图地理编码 API → 获取区域坐标 + 行政区划代码
2. 调用高德 POI 搜索 → 获取同行业商家 + 商圈 + 消费场所
3. 调用 AI 解读原始数据 → 生成结构化 RegionContext
4. 缓存结果，避免重复调用
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any

from loguru import logger

from config.industry_genome import get_genome
from src.shop.region_context import (
    RegionContext, EconomyContext, PopulationContext,
    CompetitionContext, HotContext,
)


# ═══════════════════════════════════════════════════════════
# 内存缓存（文件持久化）
# ═══════════════════════════════════════════════════════════

class _RegionCache:
    """区域上下文缓存，文件持久化 + 内存 LRU"""

    _memory_cache: dict[str, tuple[float, dict]] = {}
    _max_memory: int = 50
    _cache_dir: str = ""

    @classmethod
    def _get_cache_dir(cls) -> str:
        if not cls._cache_dir:
            cls._cache_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "region_cache"
            )
            os.makedirs(cls._cache_dir, exist_ok=True)
        return cls._cache_dir

    @classmethod
    def _make_key(cls, region_name: str, store_type: str) -> str:
        digest = hashlib.md5(f"{region_name}|{store_type}".encode()).hexdigest()[:12]
        return f"region_{digest}"

    @classmethod
    def _cache_file(cls, key: str) -> str:
        return os.path.join(cls._get_cache_dir(), f"{key}.json")

    @classmethod
    def get(cls, region_name: str, store_type: str, ttl_seconds: int = 86400 * 14) -> dict | None:
        """获取缓存，默认14天有效期"""
        key = cls._make_key(region_name, store_type)

        # 先查内存
        entry = cls._memory_cache.get(key)
        if entry:
            expire_ts, data = entry
            if time.time() < expire_ts:
                return data
            del cls._memory_cache[key]

        # 查文件
        cache_file = cls._cache_file(key)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                expire_ts = data.get("_expire_ts", 0)
                if time.time() < expire_ts:
                    cls._memory_cache[key] = (expire_ts, data)
                    return data
                else:
                    os.remove(cache_file)
            except Exception:
                pass
        return None

    @classmethod
    def set(cls, region_name: str, store_type: str, data: dict, ttl_seconds: int = 86400 * 14) -> None:
        """写入缓存"""
        key = cls._make_key(region_name, store_type)
        expire_ts = time.time() + ttl_seconds
        data["_expire_ts"] = expire_ts

        # 内存
        if len(cls._memory_cache) >= cls._max_memory:
            oldest = min(cls._memory_cache, key=lambda k: cls._memory_cache[k][0])
            del cls._memory_cache[oldest]
        cls._memory_cache[key] = (expire_ts, data)

        # 文件
        cache_file = cls._cache_file(key)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[RegionCache] 文件写入失败: {e}")


# ═══════════════════════════════════════════════════════════
# 区域上下文增强器主逻辑
# ═══════════════════════════════════════════════════════════

def _extract_region_name(address: str, city: str = "") -> str:
    """从地址提取区/县级别地名"""
    if not address:
        return city or ""
    import re
    
    # 尝试提取 X区 / X县 / X州 / X市
    patterns = [
        r'([^\s,，]{2,6}(?:区|县|市|州|镇|乡))',
    ]
    for p in patterns:
        matches = re.findall(p, address)
        if matches:
            # 返回最具体的（最后一个匹配项）
            if len(matches) >= 2 and "市" in matches[-2] and ("区" in matches[-1] or "县" in matches[-1]):
                return f"{matches[-2]}{matches[-1]}"
            return matches[-1]
    
    # 如果有 city，返回 city
    if city:
        return city
    
    return address[:8].strip()


async def _fetch_raw_region_data(
    region_name: str,
    store_type: str = "",
    products: str = "",
) -> dict[str, Any]:
    """调用高德 API 获取原始区域数据"""
    from src.shop.geo import _amap_geocode, _amap_poi_search, _amap_around_search

    if not region_name:
        return {"status": "no_region", "data": {}}

    # 尝试导入 API key 检查
    try:
        from config.env import AMAP_API_KEY
        if not AMAP_API_KEY:
            logger.warning("[RegionEnricher] 未配置 AMAP_API_KEY，跳过 API 调用")
            return {"status": "no_key", "data": {}}
    except Exception:
        return {"status": "no_key", "data": {}}

    result: dict[str, Any] = {
        "geocode": None,
        "business_districts": [],
        "competitors": [],
        "consumer_places": [],
    }

    # Step 1: 地理编码
    try:
        geocode_results = await _amap_geocode(region_name)
        if geocode_results:
            result["geocode"] = geocode_results[0]
            logger.info(f"[RegionEnricher] 地理编码成功: {region_name} → {geocode_results[0].get('lat')},{geocode_results[0].get('lon')}")
    except Exception as e:
        logger.warning(f"[RegionEnricher] 地理编码失败: {e}")

    lat = result["geocode"].get("lat", 0) if result["geocode"] else 0
    lng = result["geocode"].get("lon", 0) if result["geocode"] else 0

    if not lat or not lng:
        logger.warning(f"[RegionEnricher] 无法获取 {region_name} 坐标")
        return {"status": "no_location", "data": result}

    # Step 2: 搜索商圈（商务住宅 + 公司企业）
    try:
        districts = await _amap_around_search(
            lat=lat, lng=lng, radius=5000,
            poi_type="商务住宅|公司企业",
            offset=15,
        )
        result["business_districts"] = districts
        logger.info(f"[RegionEnricher] 商圈搜索: {len(districts)} 条")
    except Exception as e:
        logger.warning(f"[RegionEnricher] 商圈搜索失败: {e}")

    # Step 3: 搜索同行竞品
    try:
        keywords = products or store_type
        genome = get_genome(store_type) if store_type else None
        amap_type = genome.amap_poi_type if genome else ""

        competitors = await _amap_around_search(
            lat=lat, lng=lng, radius=5000,
            poi_type=amap_type,
            keywords=keywords,
            offset=20,
        )
        result["competitors"] = competitors
        logger.info(f"[RegionEnricher] 竞品搜索: {len(competitors)} 条")
    except Exception as e:
        logger.warning(f"[RegionEnricher] 竞品搜索失败: {e}")

    # Step 4: 搜索消费场所（购物 + 餐饮）
    try:
        consumer = await _amap_around_search(
            lat=lat, lng=lng, radius=3000,
            poi_type="购物服务|餐饮服务",
            offset=15,
        )
        result["consumer_places"] = consumer
        logger.info(f"[RegionEnricher] 消费场所搜索: {len(consumer)} 条")
    except Exception as e:
        logger.warning(f"[RegionEnricher] 消费场所搜索失败: {e}")

    return {"status": "ok", "data": result}


def _build_enrichment_prompt(raw_data: dict[str, Any], region_name: str, store_type: str, products: str) -> str:
    """构建让 AI 解读原始数据的 Prompt"""
    geocode = raw_data.get("geocode")
    biz = raw_data.get("business_districts", [])
    competitors = raw_data.get("competitors", [])
    consumer = raw_data.get("consumer_places", [])

    # 格式化为可读文本
    geocode_text = f"坐标: lat={geocode.get('lat')}, lng={geocode.get('lon')}, adcode={geocode.get('adcode', '')}" if geocode else "无"

    biz_names = [b.get("name", "") for b in biz[:10] if b.get("name")]
    biz_text = "\n".join(f"  - {n} ({b.get('poi_type', '')})" for b, n in zip(biz[:10], biz_names)) if biz_names else "无"

    comp_list = []
    for c in competitors[:15]:
        name = c.get("name", "")
        rating = c.get("rating", "")
        cost = c.get("avg_cost", "")
        dist = c.get("distance_m", -1)
        if name:
            line = f"  - {name}"
            extras = []
            if rating:
                extras.append(f"评分{rating}")
            if cost:
                extras.append(f"人均¥{cost}")
            if dist >= 0:
                extras.append(f"{dist}m")
            if extras:
                line += f"（{'，'.join(extras)}）"
            comp_list.append(line)
    comp_text = "\n".join(comp_list) if comp_list else "无"

    consumer_text = "\n".join(
        f"  - {c.get('name', '')}（{c.get('poi_type', '')}，人均¥{c.get('avg_cost', '')}）"
        for c in consumer[:10] if c.get("name") and c.get("avg_cost")
    ) or "无（消费场所数据不足，请根据常识推断）"

    prompt = f"""你是一个中国区域经济分析专家。请根据以下高德地图POI数据，为「{region_name}」生成一份本地化上下文数据包。

## 行业信息
- 商家行业：{store_type or '通用零售/服务'}
- 主营产品/服务：{products or '未指定'}

## 原始 POI 数据

### 地理编码
{geocode_text}

### 商圈/商务住宅/企业
{biz_text}

### 同行业竞品（共{len(competitors)}家）
{comp_text}

### 周边消费场所（购物+餐饮）
{consumer_text}

---

## 任务

请基于以上真实POI数据，结合你对「{region_name}」的了解（如全国知名、城市定位等常识），生成以下JSON格式的区域上下文。**对于POI数据无法覆盖的维度（如GDP、人均收入、人口等），使用你对该地区的常识知识进行合理推断，不要留空。**

输出格式必须是纯JSON（不要markdown代码块）：

```json
{{
  "economy_context": {{
    "gdp_level": "经济水平描述，如『中等（约550亿元）』",
    "per_capita_income": "人均收入描述，如『约42000元/年』",
    "major_industries": ["主导产业1", "主导产业2", "主导产业3"],
    "consumption_level": "消费特征描述，如『平价消费为主，对价格敏感』",
    "business_districts": ["商圈名1", "商圈名2"]
  }},
  "population_context": {{
    "total_population": "区域人口描述，如『约40万人』",
    "avg_age": "平均年龄，如『33岁』",
    "typical_consumer": "典型消费者画像，包含年龄、收入、职业等，如『本地居民为主，25-45岁，月入3000-6000元』",
    "consumer_concerns": ["价格实惠", "质量可靠", "售后方便"],
    "speak_style": "本地语言特色和说话风格，如『云南方言特色，喜欢用「整」「咋个」「板扎」等词汇』"
  }},
  "competition_context": {{
    "total_competitors": {len(competitors)},
    "top_competitors": [
      {{"name": "商家名", "address": "地址", "rating": "评分"}},
      ...
    ],
    "market_saturation": "市场饱和度判断及特征描述",
    "differentiation_opportunity": "基于竞品数据的差异化机会描述"
  }},
  "hot_context": {{
    "recent_hot_topics": ["本地近期热点或活动1", "本地近期热点或活动2"],
    "local_slang": ["本地流行语1", "本地流行语2", "本地流行语3"]
  }}
}}
```

**严格要求：**
1. economy_context 必须包含基于常识推断的经济数据，不能全为空字符串
2. population_context 的 typical_consumer 和 speak_style 必须有实质内容
3. competition_context 的 total_competitors 使用 POI 数据的真实数量
4. top_competitors 最多取5个，必须来自上方POI数据
5. local_slang 必须是该地区真正常用的表达方式"""

    return prompt


async def enrich_region(
    region_name: str,
    store_type: str = "",
    products: str = "",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> RegionContext:
    """区域上下文增强器主入口

    传入区域名称（如"呈贡区"），返回完整的 RegionContext。

    Args:
        region_name:  区域名称（如"昆明市呈贡区"、"义乌市"）
        store_type:   行业类型 ID
        products:     主营产品
        use_cache:    是否使用缓存
        force_refresh: 强制刷新，忽略缓存

    Returns:
        RegionContext 对象
    """
    if not region_name:
        return RegionContext()

    # Step 0: 缓存检查
    if use_cache and not force_refresh:
        cached = _RegionCache.get(region_name, store_type)
        if cached:
            logger.info(f"[RegionEnricher] ✅ 命中缓存: {region_name}")
            return RegionContext.from_dict(cached)

    # Step 1: 调用高德 API 获取原始数据
    logger.info(f"[RegionEnricher] 🔍 开始收集 '{region_name}' 区域数据...")
    raw_result = await _fetch_raw_region_data(region_name, store_type, products)
    raw_data = raw_result.get("data", {})

    geocode = raw_data.get("geocode")
    if not geocode or not geocode.get("lat"):
        # 无法获取坐标，返回空上下文
        logger.warning(f"[RegionEnricher] ⚠️ 无法获取 {region_name} 坐标信息")
        return RegionContext()

    # Step 2: 使用 AI 解读原始数据
    prompt = _build_enrichment_prompt(raw_data, region_name, store_type, products)

    # 构建 system prompt
    system_prompt = """你是一个中国区域经济分析专家，精通中国各地的区域经济、消费习惯、方言文化。
你的任务是根据高德地图POI数据和对该地区的常识知识，生成准确、有用的本地化上下文数据。
所有推断必须基于常识和真实数据，不能凭空编造。"""

    try:
        from src.core import BaseSoldier
        soldier = BaseSoldier()
        soldier.name = "区域上下文增强器"
        soldier.temperature = 0.3
        soldier.max_tokens = 2048

        ai_response, tokens = soldier.chat(system_prompt, prompt)
        logger.info(f"[RegionEnricher] AI 解读完成，消耗 {tokens} tokens")

        # 解析 JSON
        import re
        try:
            parsed = json.loads(ai_response)
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)```', ai_response)
            if match:
                parsed = json.loads(match.group(1))
            else:
                brace_start = ai_response.find("{")
                brace_end = ai_response.rfind("}")
                if brace_start >= 0 and brace_end > brace_start:
                    parsed = json.loads(ai_response[brace_start:brace_end + 1])
                else:
                    logger.warning("[RegionEnricher] 无法解析 AI 响应")
                    return RegionContext()

        # Step 3: 构建 RegionContext
        adcode = geocode.get("adcode", "")
        lat = float(geocode.get("lat", 0))
        lng = float(geocode.get("lon", 0))

        eco = parsed.get("economy_context", {})
        pop = parsed.get("population_context", {})
        comp = parsed.get("competition_context", {})
        hot = parsed.get("hot_context", {})

        ctx = RegionContext(
            region_name=region_name,
            adcode=str(adcode),
            location={"lat": lat, "lng": lng},
            economy_context=EconomyContext(
                gdp_level=eco.get("gdp_level", ""),
                per_capita_income=eco.get("per_capita_income", ""),
                major_industries=eco.get("major_industries", []),
                consumption_level=eco.get("consumption_level", ""),
                business_districts=eco.get("business_districts", []),
            ),
            population_context=PopulationContext(
                total_population=pop.get("total_population", ""),
                avg_age=pop.get("avg_age", ""),
                typical_consumer=pop.get("typical_consumer", ""),
                consumer_concerns=pop.get("consumer_concerns", []),
                speak_style=pop.get("speak_style", ""),
            ),
            competition_context=CompetitionContext(
                total_competitors=int(comp.get("total_competitors", 0)),
                top_competitors=comp.get("top_competitors", []),
                market_saturation=comp.get("market_saturation", ""),
                differentiation_opportunity=comp.get("differentiation_opportunity", ""),
            ),
            hot_context=HotContext(
                recent_hot_topics=hot.get("recent_hot_topics", []),
                local_slang=hot.get("local_slang", []),
            ),
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # Step 4: 写入缓存（14天）
        if use_cache:
            _RegionCache.set(region_name, store_type, ctx.to_dict(), ttl_seconds=86400 * 14)

        logger.info(f"[RegionEnricher] ✅ 区域上下文生成完成: {region_name}")
        return ctx

    except Exception as e:
        logger.error(f"[RegionEnricher] AI 解读失败: {e}")
        # 降级：返回只有基本信息的上下文
        from datetime import datetime
        ctx = RegionContext(
            region_name=region_name,
            adcode=str(geocode.get("adcode", "")),
            location={"lat": float(geocode.get("lat", 0)), "lng": float(geocode.get("lon", 0))},
            economy_context=EconomyContext(),
            population_context=PopulationContext(),
            competition_context=CompetitionContext(
                total_competitors=len(raw_data.get("competitors", [])),
            ),
            generated_at=datetime.now().isoformat(),
        )
        return ctx


def enrich_region_sync(
    region_name: str,
    store_type: str = "",
    products: str = "",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> RegionContext:
    """同步包装器（供非异步上下文调用）"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(enrich_region(
            region_name=region_name,
            store_type=store_type,
            products=products,
            use_cache=use_cache,
            force_refresh=force_refresh,
        ))
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                enrich_region(
                    region_name=region_name,
                    store_type=store_type,
                    products=products,
                    use_cache=use_cache,
                    force_refresh=force_refresh,
                ),
            )
            return future.result()
