"""智能地理定位引擎 - AI军团 v3.1

核心变更：地理编码 → POI 搜索优先
逻辑流：地址清洗 → POI搜索(首选) → 地理编码(兜底) → 行政区降级(保底)

特性：
- 双路并发：高德(主) + 腾讯(备)，失败自动切换
- 坐标统一：全部输出 GCJ-02 坐标系
- 置信度机制：POI=0.9, 地理编码=0.6, 行政区=0.1
- Redis 缓存：Key 格式 geo:{md5(address)}，减少 API 调用
- 行业适配：从基因组读取 POI 类型码，精准搜索
- 结构化错误：不抛异常，返回可展示的错误信息
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

import httpx
from loguru import logger

from config.env import AMAP_API_KEY, BAIDU_MAP_AK, TENCENT_KEY, REDIS_URL
from config.industry_genome import get_genome
from src.shop.address_cleaner import clean_address, extract_search_keywords, extract_city_param


# ═══════════════════════════════════════════════════════════
# 坐标转换工具
# ═══════════════════════════════════════════════════════════

X_PI: float = math.pi * 3000.0 / 180.0
_A: float = 6378245.0
_EE: float = 0.00669342162296594323


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """BD-09（百度） → GCJ-02（国测局/高德/腾讯）"""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return round(z * math.cos(theta), 7), round(z * math.sin(theta), 7)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS-84（GPS/OSM） → GCJ-02（国测局/高德/腾讯）"""
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1.0 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return round(lng + dlng, 7), round(lat + dlat, 7)


def _is_in_china(lng: float, lat: float) -> bool:
    """粗略判断坐标是否在中国境内"""
    return 73.0 < lng < 135.0 and 18.0 < lat < 54.0


# ═══════════════════════════════════════════════════════════
# Redis 缓存（可选，失败时自动退化到内存缓存）
# ═══════════════════════════════════════════════════════════

class _GeoCache:
    """定位结果缓存，优先 Redis，降级为内存 LRU"""

    _redis: Any = None
    _redis_checked: bool = False
    _memory_cache: dict[str, tuple[float, dict[str, Any]]] = {}  # {key: (expire_ts, data)}
    _max_memory_entries: int = 100
    _ttl: int = 86400  # 24 小时

    _CACHE_PREFIX: str = "geo:"

    @classmethod
    def _try_redis(cls) -> Any:
        if cls._redis_checked:
            return cls._redis
        cls._redis_checked = True
        try:
            import redis
            cls._redis = redis.from_url(REDIS_URL, decode_responses=True)
            cls._redis.ping()
            logger.info("[GeoCache] Redis 缓存已连接")
            return cls._redis
        except Exception:
            logger.debug("[GeoCache] Redis 不可用，使用内存缓存")
            return None

    @classmethod
    def _make_key(cls, raw_address: str, store_type: str) -> str:
        """生成缓存 Key：geo:{md5(address|store_type)}"""
        digest = hashlib.md5(f"{raw_address}|{store_type}".encode()).hexdigest()[:12]
        return f"{cls._CACHE_PREFIX}{digest}"

    @classmethod
    def get(cls, raw_address: str, store_type: str) -> dict[str, Any] | None:
        key = cls._make_key(raw_address, store_type)

        # 优先 Redis
        r = cls._try_redis()
        if r:
            try:
                val = r.get(key)
                if val:
                    return json.loads(val)
            except Exception:
                pass

        # 内存降级
        entry = cls._memory_cache.get(key)
        if entry:
            expire_ts, data = entry
            if time.time() < expire_ts:
                return data
            del cls._memory_cache[key]
        return None

    @classmethod
    def set(cls, raw_address: str, store_type: str, data: dict[str, Any]) -> None:
        key = cls._make_key(raw_address, store_type)

        # 优先 Redis
        r = cls._try_redis()
        if r:
            try:
                r.setex(key, cls._ttl, json.dumps(data, ensure_ascii=False))
                return
            except Exception:
                pass

        # 内存降级，LRU 淘汰
        if len(cls._memory_cache) >= cls._max_memory_entries:
            oldest_key = min(cls._memory_cache, key=lambda k: cls._memory_cache[k][0])
            del cls._memory_cache[oldest_key]
        cls._memory_cache[key] = (time.time() + cls._ttl, data)


# ═══════════════════════════════════════════════════════════
# API 调用函数
# ═══════════════════════════════════════════════════════════

_AMAP_POI_URL = "https://restapi.amap.com/v3/place/text"
_AMAP_AROUND_URL = "https://restapi.amap.com/v3/place/around"
_AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
_AMAP_DISTRICT_URL = "https://restapi.amap.com/v3/config/district"
_TENCENT_POI_URL = "https://apis.map.qq.com/ws/place/v1/suggestion"
_TENCENT_GEO_URL = "https://apis.map.qq.com/ws/geocoder/v1/"
_BAIDU_SUGGESTION_URL = "https://api.map.baidu.com/place/v2/suggestion"
_BAIDU_PLACE_URL = "https://api.map.baidu.com/place/v2/search"
_BAIDU_GEO_URL = "https://api.map.baidu.com/geocoding/v3/"


async def _amap_poi_search(
    keywords: str,
    city: str = "",
    poi_type: str = "",
    offset: int = 10,
) -> list[dict[str, Any]]:
    """高德 POI 关键字搜索（GCJ-02）"""
    if not AMAP_API_KEY:
        return []

    params: dict[str, Any] = {
        "key": AMAP_API_KEY,
        "keywords": keywords,
        "output": "JSON",
        "offset": offset,
        "page": 1,
        "extensions": "all",
        "citylimit": "true" if city else "false",
    }
    if city:
        params["city"] = city  # 支持 adcode 和城市名
    if poi_type:
        params["types"] = poi_type

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_AMAP_POI_URL, params=params)
            data = resp.json()

            if data.get("status") != "1":
                info = data.get("info", "")
                if "LIMIT" in info.upper() or "OVER" in info.upper():
                    logger.warning(f"[AMAP POI] 限流: {info}")
                    raise _GeoError("api_rate_limited", f"高德POI搜索限流: {info}")
                return []

            pois = data.get("pois", [])
            results: list[dict[str, Any]] = []
            for poi in pois:
                loc = poi.get("location", "").split(",")
                if len(loc) != 2:
                    continue
                parts = [poi.get("name", "")]
                addr = poi.get("address", "")
                if addr:
                    parts.append(addr)
                display_name = " - ".join(filter(None, parts))

                # 类型处理
                ptype = poi.get("type", "")
                biz_area = (poi.get("business_area") or "").strip()
                if biz_area:
                    ptype = f"{biz_area} · {ptype}" if ptype else biz_area

                item: dict[str, Any] = {
                    "display_name": display_name,
                    "lat": float(loc[1]),
                    "lon": float(loc[0]),
                    "coord_sys": "GCJ-02",
                    "confidence": 0.9,
                    "provider": "amap_poi",
                    "poi_name": poi.get("name", ""),
                    "poi_address": addr,
                    "poi_type": ptype,
                    "poi_tel": (poi.get("tel") or "").strip(),
                    "city": poi.get("cityname", ""),
                    "district": poi.get("adname", ""),
                    "adcode": poi.get("adcode", ""),
                }
                rating = poi.get("biz_ext", {}).get("rating", "")
                if rating:
                    item["rating"] = rating
                deep_info = poi.get("deep_info")
                if deep_info:
                    item["deep_info"] = deep_info
                results.append(item)
            return results
    except _GeoError:
        raise
    except httpx.TimeoutException:
        logger.warning("[AMAP POI] 请求超时")
        return []
    except Exception as e:
        logger.warning(f"[AMAP POI] 异常: {e}")
        return []


async def _amap_around_search(
    lat: float,
    lng: float,
    radius: int = 1000,
    poi_type: str = "",
    keywords: str = "",
    offset: int = 25,
) -> list[dict[str, Any]]:
    """高德周边 POI 搜索（以坐标为中心，圆形范围搜索，GCJ-02）

    Args:
        lat, lng:  中心坐标 (GCJ-02)
        radius:    搜索半径（米），最大 50000
        poi_type:  高德 POI 类型码（如 "050000" 餐饮），为空则不限
        keywords:  搜索关键词
        offset:    每页数量，最大 25
    """
    if not AMAP_API_KEY:
        return []

    actual_radius = min(radius, 50000)  # 高德限制最大 50km
    params: dict[str, Any] = {
        "key": AMAP_API_KEY,
        "location": f"{lng},{lat}",
        "radius": actual_radius,
        "output": "JSON",
        "offset": min(offset, 25),
        "page": 1,
        "extensions": "all",
    }
    if poi_type:
        params["types"] = poi_type
    if keywords:
        params["keywords"] = keywords

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_AMAP_AROUND_URL, params=params)
            data = resp.json()

            if data.get("status") != "1":
                info = data.get("info", "")
                if "LIMIT" in info.upper() or "OVER" in info.upper():
                    logger.warning(f"[AMAP Around] 限流: {info}")
                return []

            pois = data.get("pois", [])
            results: list[dict[str, Any]] = []
            for poi in pois:
                loc = poi.get("location", "").split(",")
                if len(loc) != 2:
                    continue

                distance_str = poi.get("distance", "")
                try:
                    distance_m = int(distance_str)
                except (ValueError, TypeError):
                    distance_m = -1

                ptype = poi.get("type", "").strip()
                biz_area = (poi.get("business_area") or "").strip()
                type_label = "; ".join(filter(None, [biz_area, ptype]))

                item: dict[str, Any] = {
                    "name": poi.get("name", ""),
                    "address": poi.get("address", ""),
                    "lat": float(loc[1]),
                    "lon": float(loc[0]),
                    "distance_m": distance_m,
                    "poi_type": type_label,
                }

                # 评分
                biz_ext = poi.get("biz_ext")
                if isinstance(biz_ext, dict):
                    rating = biz_ext.get("rating", "")
                    if rating:
                        item["rating"] = rating
                    cost = biz_ext.get("cost", "")
                    if cost:
                        item["avg_cost"] = cost

                # 电话
                tel = (poi.get("tel") or "").strip()
                if tel:
                    item["tel"] = tel

                results.append(item)

            return results
    except Exception as e:
        logger.warning(f"[AMAP Around] 异常: {e}")
        return []


async def search_nearby_competitors(
    lat: float,
    lng: float,
    radius: int = 1000,
    store_type: str = "",
    keywords: str = "",
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """搜索周边竞品 POI（供竞品分析使用）

    用高德周边搜索 API 获取指定坐标周边的真实商家 POI 数据。

    Args:
        lat, lng:     店铺坐标 (GCJ-02)
        radius:       搜索半径（米）
        store_type:   行业类型 ID（如 "restaurant"），用于 POI 类型码过滤
        keywords:     额外搜索关键词
        max_results:  最大返回数量

    Returns:
        POI 列表，按距离排序，每项包含 name/address/distance_m/poi_type/rating/avg_cost
    """
    # 获取行业 POI 类型码
    genome = get_genome(store_type) if store_type else None
    amap_type = genome.amap_poi_type if genome else ""

    # 第一轮：按行业类型搜索
    results = await _amap_around_search(
        lat=lat, lng=lng, radius=radius,
        poi_type=amap_type,
        keywords=keywords,
        offset=min(max_results, 25),
    )

    # 如果结果不足且有关键词，追加一次不限类型的搜索（捕捉跨行业竞品）
    if len(results) < 8 and keywords:
        existing_names = {r["name"] for r in results}
        extra = await _amap_around_search(
            lat=lat, lng=lng, radius=radius,
            keywords=keywords,
            offset=15,
        )
        for item in extra:
            if item["name"] not in existing_names and len(results) < max_results:
                existing_names.add(item["name"])
                results.append(item)

    # 过滤掉距离为0的POI（即店铺自身）以及可能的重复
    seen_names: set[str] = set()
    filtered: list[dict[str, Any]] = []
    for r in results:
        name = r.get("name", "")
        dist = r.get("distance_m", -1)
        if dist == 0:
            continue  # 自身店铺
        if name in seen_names:
            continue
        seen_names.add(name)
        filtered.append(r)

    logger.info(
        f"[Geo] 周边竞品搜索完成: {len(filtered)} 条 POI "
        f"(坐标={lat},{lng} 半径={radius}m 行业={store_type or '不限'})"
    )
    return filtered


def _format_poi_for_analysis(pois: list[dict[str, Any]], store_lat: float, store_lng: float) -> str:
    """将 POI 列表格式化为 AI 可读的竞品数据文本"""
    if not pois:
        return "（未获取到周边商家POI数据，可能该区域POI数据较少或API异常）"

    lines = [f"以下是通过高德地图API获取的周边 {len(pois)} 家真实商家POI数据：\n"]
    lines.append("| # | 商家名称 | 类型 | 距离 | 地址 | 评分 | 人均 |")
    lines.append("|---|---|---|---|---|---|---|")

    for i, poi in enumerate(pois, 1):
        name = poi.get("name", "未知")
        ptype = poi.get("poi_type", "")
        dist = poi.get("distance_m", -1)
        dist_str = f"{dist}m" if dist >= 0 else "未知"
        addr = poi.get("address", "")
        rating = poi.get("rating", "")
        rating_str = f"⭐{rating}" if rating else "-"
        cost = poi.get("avg_cost", "")
        cost_str = f"¥{cost}" if cost else "-"

        # 截断过长的地址
        if len(addr) > 25:
            addr = addr[:25] + "..."

        lines.append(f"| {i} | {name} | {ptype} | {dist_str} | {addr} | {rating_str} | {cost_str} |")

    return "\n".join(lines)


def search_nearby_competitors_sync(
    lat: float,
    lng: float,
    radius: int = 1000,
    store_type: str = "",
    keywords: str = "",
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """同步包装器（供 LocalIntel 等同步上下文调用）"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(search_nearby_competitors(
            lat=lat, lng=lng, radius=radius,
            store_type=store_type, keywords=keywords,
            max_results=max_results,
        ))
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                search_nearby_competitors(
                    lat=lat, lng=lng, radius=radius,
                    store_type=store_type, keywords=keywords,
                    max_results=max_results,
                ),
            )
            return future.result()


async def _tencent_poi_search(
    keyword: str,
    region: str = "",
    poi_category: str = "",
) -> list[dict[str, Any]]:
    """腾讯 POI 建议搜索（GCJ-02）"""
    if not TENCENT_KEY:
        return []

    params: dict[str, Any] = {
        "key": TENCENT_KEY,
        "keyword": keyword,
        "output": "json",
    }
    if region:
        params["region"] = region
    if poi_category:
        # 腾讯 POI 类型过滤通过 keyword 前缀实现
        params["keyword"] = f"{poi_category} {keyword}" if poi_category else keyword

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_TENCENT_POI_URL, params=params)
            data = resp.json()

            if data.get("status") != 0:
                msg = data.get("message", "")
                if "限流" in msg or "超过" in msg:
                    logger.warning(f"[Tencent POI] 限流: {msg}")
                    raise _GeoError("api_rate_limited", f"腾讯POI搜索限流: {msg}")
                return []

            results: list[dict[str, Any]] = []
            for item in data.get("data", []):
                loc = item.get("location", {})
                if not loc or "lat" not in loc:
                    continue

                parts = [item.get("title", "")]
                addr = item.get("address", "")
                if addr:
                    parts.append(addr)
                display_name = " - ".join(filter(None, parts))

                ad_info = item.get("ad_info", {})
                results.append({
                    "display_name": display_name,
                    "lat": float(loc["lat"]),
                    "lon": float(loc["lng"]),
                    "coord_sys": "GCJ-02",
                    "confidence": 0.9,
                    "provider": "tencent_poi",
                    "poi_name": item.get("title", ""),
                    "poi_address": addr,
                    "poi_type": item.get("category", ""),
                    "poi_tel": (item.get("tel") or "").strip(),
                    "city": ad_info.get("province", ""),
                    "district": ad_info.get("district", ""),
                    "adcode": str(ad_info.get("adcode", "")),
                    "poi_id": item.get("id", ""),
                })
            return results
    except _GeoError:
        raise
    except httpx.TimeoutException:
        logger.warning("[Tencent POI] 请求超时")
        return []
    except Exception as e:
        logger.warning(f"[Tencent POI] 异常: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# 百度地图 API
# ═══════════════════════════════════════════════════════════

async def _baidu_place_search(
    keyword: str,
    region: str = "",
    city_limit: bool = True,
    offset: int = 10,
) -> list[dict[str, Any]]:
    """百度地点检索（POI 搜索），输出统一为 GCJ-02。"""
    if not BAIDU_MAP_AK:
        return []

    params: dict[str, Any] = {
        "ak": BAIDU_MAP_AK,
        "query": keyword,
        "output": "json",
        "page_size": offset,
        "page_num": 0,
        "scope": 2,
    }
    if region:
        params["region"] = region
        params["city_limit"] = "true" if city_limit else "false"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_BAIDU_PLACE_URL, params=params)
            data = resp.json()

            if data.get("status") != 0:
                msg = data.get("msg", "")
                if "配额" in msg or "频次" in msg or "limit" in msg.lower():
                    logger.warning(f"[Baidu Place] 限流: {msg}")
                    raise _GeoError("api_rate_limited", f"百度POI搜索限流: {msg}")
                return []

            results: list[dict[str, Any]] = []
            for poi in data.get("results", []):
                loc = poi.get("location", {})
                lng = loc.get("lng")
                lat = loc.get("lat")
                if lng is None or lat is None:
                    continue
                gcj_lng, gcj_lat = bd09_to_gcj02(float(lng), float(lat))

                addr = (poi.get("address") or "").strip()
                name = (poi.get("name") or "").strip()
                display_name = f"{name} - {addr}" if addr else name

                # 百度 POI 类型为三级分类，如 "美食;中餐厅;火锅店"
                detail_info = poi.get("detail_info", {})
                ptype = detail_info.get("type") or poi.get("tag", "")
                if not ptype:
                    detail = poi.get("detail") or {}
                    ptype = detail.get("tag", "")

                # 行政区划信息
                province = (poi.get("province") or "").strip()
                city_name = (poi.get("city") or "").strip()
                district = (poi.get("area") or "").strip()

                item: dict[str, Any] = {
                    "display_name": display_name,
                    "lat": gcj_lat,
                    "lon": gcj_lng,
                    "coord_sys": "GCJ-02",
                    "confidence": 0.9,
                    "provider": "baidu_poi",
                    "poi_name": name,
                    "poi_address": addr,
                    "poi_type": ptype,
                    "poi_tel": (poi.get("telephone") or "").strip(),
                    "city": city_name or province,
                    "district": district,
                    "poi_id": str(poi.get("uid", "")),
                }
                rating = detail_info.get("overall_rating")
                if rating:
                    item["rating"] = rating
                results.append(item)
            return results
    except _GeoError:
        raise
    except httpx.TimeoutException:
        logger.warning("[Baidu Place] 请求超时")
        return []
    except Exception as e:
        logger.warning(f"[Baidu Place] 异常: {e}")
        return []


async def _baidu_suggestion(
    keyword: str,
    region: str = "",
) -> list[dict[str, Any]]:
    """百度地点输入提示（Suggestion），输出统一为 GCJ-02。

    该接口适合地址联想/自动补全场景，POI 数据较丰富。
    """
    if not BAIDU_MAP_AK:
        return []

    params: dict[str, Any] = {
        "ak": BAIDU_MAP_AK,
        "query": keyword,
        "output": "json",
    }
    if region:
        params["region"] = region
        params["city_limit"] = "true"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_BAIDU_SUGGESTION_URL, params=params)
            data = resp.json()

            if data.get("status") != 0:
                msg = data.get("msg", "")
                if "配额" in msg or "频次" in msg or "limit" in msg.lower():
                    logger.warning(f"[Baidu Suggestion] 限流: {msg}")
                    raise _GeoError("api_rate_limited", f"百度Suggestion限流: {msg}")
                return []

            results: list[dict[str, Any]] = []
            for poi in data.get("result", []):
                loc = poi.get("location", {})
                lng = loc.get("lng")
                lat = loc.get("lat")
                if lng is None or lat is None:
                    continue
                gcj_lng, gcj_lat = bd09_to_gcj02(float(lng), float(lat))

                addr = (poi.get("address") or "").strip()
                name = (poi.get("name") or "").strip()
                district = (poi.get("district") or "").strip()
                city_name = (poi.get("city") or "").strip()
                province = (poi.get("province") or "").strip()

                # 子类型（更具体）优先
                ptype = (poi.get("tag") or "").strip()
                if not ptype:
                    ptype = (poi.get("category") or "").strip()

                results.append({
                    "display_name": f"{name} - {addr}" if addr else name,
                    "lat": gcj_lat,
                    "lon": gcj_lng,
                    "coord_sys": "GCJ-02",
                    "confidence": 0.85,
                    "provider": "baidu_suggestion",
                    "poi_name": name,
                    "poi_address": addr,
                    "poi_type": ptype,
                    "city": city_name or province,
                    "district": district,
                })
            return results
    except _GeoError:
        raise
    except httpx.TimeoutException:
        logger.warning("[Baidu Suggestion] 请求超时")
        return []
    except Exception as e:
        logger.warning(f"[Baidu Suggestion] 异常: {e}")
        return []


async def _baidu_geocode(address: str, region: str = "") -> list[dict[str, Any]]:
    """百度地理编码（地址 → 坐标，兜底用），输出统一为 GCJ-02。"""
    if not BAIDU_MAP_AK:
        return []

    params: dict[str, Any] = {
        "ak": BAIDU_MAP_AK,
        "address": address,
        "output": "json",
    }
    if region:
        params["city"] = region

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_BAIDU_GEO_URL, params=params)
            data = resp.json()

            if data.get("status") != 0:
                msg = data.get("msg", "")
                if "配额" in msg or "频次" in msg or "limit" in msg.lower():
                    logger.warning(f"[Baidu Geo] 限流: {msg}")
                    raise _GeoError("api_rate_limited", f"百度地理编码限流: {msg}")
                return []

            loc = data.get("result", {}).get("location", {})
            lng = loc.get("lng")
            lat = loc.get("lat")
            if lng is None or lat is None:
                return []

            gcj_lng, gcj_lat = bd09_to_gcj02(float(lng), float(lat))
            return [{
                "display_name": address,
                "lat": gcj_lat,
                "lon": gcj_lng,
                "coord_sys": "GCJ-02",
                "confidence": 0.55,
                "provider": "baidu_geo",
                "poi_type": "",
            }]
    except _GeoError:
        raise
    except httpx.TimeoutException:
        return []
    except Exception as e:
        logger.warning(f"[Baidu Geo] 异常: {e}")
        return []


async def _amap_geocode(address: str, city: str = "") -> list[dict[str, Any]]:
    """高德地理编码（纯地址→坐标，兜底用，GCJ-02）"""
    if not AMAP_API_KEY:
        return []

    params: dict[str, Any] = {
        "key": AMAP_API_KEY,
        "address": address,
        "output": "JSON",
    }
    if city:
        params["city"] = city

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_AMAP_GEO_URL, params=params)
            data = resp.json()
            if data.get("status") != "1":
                info = data.get("info", "")
                if "LIMIT" in info.upper():
                    raise _GeoError("api_rate_limited", f"高德地理编码限流: {info}")
                return []

            results: list[dict[str, Any]] = []
            for g in data.get("geocodes", []):
                loc = g.get("location", "").split(",")
                if len(loc) != 2:
                    continue
                results.append({
                    "display_name": g.get("formatted_address", address),
                    "lat": float(loc[1]),
                    "lon": float(loc[0]),
                    "coord_sys": "GCJ-02",
                    "confidence": 0.6,
                    "provider": "amap_geo",
                    "adcode": g.get("adcode", ""),
                    "level": g.get("level", ""),
                })
            return results
    except _GeoError:
        raise
    except httpx.TimeoutException:
        return []
    except Exception as e:
        logger.warning(f"[AMAP Geo] 异常: {e}")
        return []


async def _tencent_geocode(address: str) -> list[dict[str, Any]]:
    """腾讯地理编码（纯地址→坐标，兜底用，GCJ-02）"""
    if not TENCENT_KEY:
        return []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_TENCENT_GEO_URL, params={"key": TENCENT_KEY, "address": address})
            data = resp.json()
            if data.get("status") != 0:
                msg = data.get("message", "")
                if "限流" in msg:
                    raise _GeoError("api_rate_limited", f"腾讯地理编码限流: {msg}")
                return []

            r = data.get("result", {})
            loc = r.get("location", {})
            if not loc or "lat" not in loc:
                return []

            # 精度评估：腾讯 geocoding 返回 reliability 和 level
            reliability = r.get("reliability", 5)
            confidence = {"1": 0.3, "3": 0.5, "5": 0.6, "7": 0.7, "9": 0.8}.get(str(reliability), 0.6)

            comps = r.get("address_components", {})
            return [{
                "display_name": r.get("address", address),
                "lat": float(loc["lat"]),
                "lon": float(loc["lng"]),
                "coord_sys": "GCJ-02",
                "confidence": confidence,
                "provider": "tencent_geo",
                "city": comps.get("city", ""),
                "district": comps.get("district", ""),
                "adcode": comps.get("adcode", ""),
                "level": r.get("level", ""),
            }]
    except _GeoError:
        raise
    except httpx.TimeoutException:
        return []
    except Exception as e:
        logger.warning(f"[Tencent Geo] 异常: {e}")
        return []


async def _admin_center_fallback(
    admin_region: str,
    store_type: str = "",
) -> dict[str, Any] | None:
    """行政区中心点降级（保底策略）。

    用高德行政区划API获取区/县/市的中心坐标。
    """
    if not AMAP_API_KEY or not admin_region:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_AMAP_DISTRICT_URL, params={
                "key": AMAP_API_KEY,
                "keywords": admin_region,
                "subdistrict": 0,
                "output": "JSON",
            })
            data = resp.json()
            if data.get("status") != "1":
                return None

            districts = data.get("districts", [])
            if not districts:
                return None

            center = districts[0].get("center", "")
            if not center:
                return None

            lng_str, lat_str = center.split(",")
            return {
                "display_name": f"{admin_region}（行政区中心，精确地址请补充地标）",
                "lat": float(lat_str),
                "lon": float(lng_str),
                "coord_sys": "GCJ-02",
                "confidence": 0.1,
                "provider": "admin_fallback",
                "admin_name": districts[0].get("name", ""),
                "adcode": districts[0].get("adcode", ""),
            }
    except Exception as e:
        logger.warning(f"[Admin Fallback] 异常: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════════════════════════

class _GeoError(Exception):
    """内部地理编码错误，携带结构化错误码"""
    def __init__(self, error_type: str, detail: str = "") -> None:
        self.error_type = error_type  # "api_rate_limited" | "address_resolution_failed"
        self.detail = detail
        super().__init__(detail)


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

async def resolve_address_to_coord(
    address: str,
    *,
    city: str = "",
    store_type: str = "",
    adcode: str = "",
    use_cache: bool = True,
) -> dict[str, Any]:
    """智能地址解析为坐标（POI 优先策略）。

    Args:
        address:    原始地址或商家名称（如 "宾川县XX路123号奶茶店"）
        city:       城市限定（如 "大理州" 或 adcode "532924"）
        store_type: 行业类型（如 "restaurant"），用于 POI 类型码过滤
        adcode:     行政区划代码（如 "320100"），优先用于 POI 搜索限定
        use_cache:  是否使用缓存（默认开启）

    Returns:
        {
            "status":        "success" | "degraded" | "failed",
            "lat":           float,
            "lon":           float,
            "display_name":  str,
            "confidence":    0.0~1.0,
            "provider":      str,
            "coord_sys":     "GCJ-02",
            "error":         None | "api_rate_limited" | "address_resolution_failed",
            "error_detail":  str,
            "results":       [dict, ...],  # 所有候选结果
            "clean_result":  {dict},       # 地址清洗结果
            "cached":        bool,
        }
    """
    # ── 步骤0：缓存检查 ───────────────────────────────────
    if use_cache:
        cached = _GeoCache.get(address, store_type)
        if cached:
            cached["cached"] = True
            return cached

    # ── 步骤1：地址清洗 ───────────────────────────────────
    clean_result = clean_address(address)
    keywords = extract_search_keywords(clean_result)
    search_city = adcode or city or extract_city_param(clean_result)

    # 行业 POI 类型码
    genome = get_genome(store_type) if store_type else None
    amap_type = genome.amap_poi_type if genome else ""
    tencent_cat = genome.tencent_poi_type if genome else ""

    logger.info(
        f"[Geo] 地址解析: '{address[:60]}' -> 清洗='{keywords[:60]}' city='{search_city}' "
        f"行业={store_type or '无'} amap_type={amap_type} tencent_cat={tencent_cat}"
    )

    all_results: list[dict[str, Any]] = []
    rate_limited = False
    errors: list[str] = []

    # ── 步骤2：POI 搜索（首选） ────────────────────────────
    # 2.1 高德 POI 搜索
    try:
        amap_pois = await _amap_poi_search(
            keywords=keywords,
            city=search_city,
            poi_type=amap_type,
        )
        all_results.extend(amap_pois)
        if amap_pois:
            logger.info(f"[Geo] 高德POI命中: {len(amap_pois)} 条")
    except _GeoError as e:
        if e.error_type == "api_rate_limited":
            rate_limited = True
        errors.append(f"高德POI: {e.detail}")

    # 2.2 腾讯 POI 搜索（不管高德有没有结果都并发尝试，丰富候选）
    if TENCENT_KEY:
        try:
            tencent_pois = await _tencent_poi_search(
                keyword=keywords,
                region=search_city,
                poi_category=tencent_cat,
            )
            all_results.extend(tencent_pois)
            if tencent_pois:
                logger.info(f"[Geo] 腾讯POI命中: {len(tencent_pois)} 条")
        except _GeoError as e:
            if e.error_type == "api_rate_limited":
                rate_limited = True
            errors.append(f"腾讯POI: {e.detail}")

    # 2.3 百度 POI 搜索
    if BAIDU_MAP_AK:
        try:
            baidu_pois = await _baidu_place_search(
                keyword=keywords,
                region=search_city,
            )
            all_results.extend(baidu_pois)
            if baidu_pois:
                logger.info(f"[Geo] 百度POI命中: {len(baidu_pois)} 条")
        except _GeoError as e:
            if e.error_type == "api_rate_limited":
                rate_limited = True
            errors.append(f"百度POI: {e.detail}")

    # 2.4 百度 Suggestion（丰富地址联想候选，置信度略低）
    if BAIDU_MAP_AK and len(all_results) < 6:
        try:
            baidu_sug = await _baidu_suggestion(
                keyword=keywords,
                region=search_city,
            )
            all_results.extend(baidu_sug)
            if baidu_sug:
                logger.info(f"[Geo] 百度Suggestion命中: {len(baidu_sug)} 条")
        except _GeoError as e:
            if e.error_type == "api_rate_limited":
                rate_limited = True
            errors.append(f"百度Suggestion: {e.detail}")

    # ── 步骤3：地理编码（兜底） ────────────────────────────
    if not all_results:
        # 3.1 高德地理编码
        try:
            geo_amap = await _amap_geocode(address, city=search_city)
            all_results.extend(geo_amap)
            if geo_amap:
                logger.info(f"[Geo] 高德地理编码兜底: {len(geo_amap)} 条")
        except _GeoError as e:
            if e.error_type == "api_rate_limited":
                rate_limited = True
            errors.append(f"高德GEO: {e.detail}")

        # 3.2 腾讯地理编码
        if not all_results and TENCENT_KEY:
            try:
                geo_tencent = await _tencent_geocode(address)
                all_results.extend(geo_tencent)
                if geo_tencent:
                    logger.info(f"[Geo] 腾讯地理编码兜底: {len(geo_tencent)} 条")
            except _GeoError as e:
                if e.error_type == "api_rate_limited":
                    rate_limited = True
                errors.append(f"腾讯GEO: {e.detail}")

        # 3.3 百度地理编码
        if not all_results and BAIDU_MAP_AK:
            try:
                geo_baidu = await _baidu_geocode(address, region=search_city)
                all_results.extend(geo_baidu)
                if geo_baidu:
                    logger.info(f"[Geo] 百度地理编码兜底: {len(geo_baidu)} 条")
            except _GeoError as e:
                if e.error_type == "api_rate_limited":
                    rate_limited = True
                errors.append(f"百度GEO: {e.detail}")

    # ── 步骤4：行政区中心降级（保底） ──────────────────────
    admin_fallback_result: dict[str, Any] | None = None
    if not all_results:
        admin = clean_result.get("admin_region", "") or search_city
        if admin:
            admin_fallback_result = await _admin_center_fallback(admin, store_type)
            if admin_fallback_result:
                all_results.append(admin_fallback_result)
                logger.info(f"[Geo] 行政区降级: {admin}")

    # ── 步骤5：构建响应 ───────────────────────────────────
    if not all_results:
        # 全部失败
        error_type = "api_rate_limited" if rate_limited else "address_resolution_failed"
        error_detail = (
            "所有地图API均不可用（限流/无Key），请稍后重试"
            if rate_limited
            else f"无法解析地址 '{address[:50]}'，请补充地标信息（如：XX路XX商场对面）"
        )
        return {
            "status": "failed",
            "error": error_type,
            "error_detail": error_detail,
            "errors": errors,
            "results": [],
            "clean_result": clean_result,
            "display_name": address,
            "lat": 0.0,
            "lon": 0.0,
            "confidence": 0.0,
            "provider": "none",
            "coord_sys": "GCJ-02",
            "cached": False,
        }

    # 按置信度排序，取最高
    all_results.sort(key=lambda r: r.get("confidence", 0), reverse=True)
    best = all_results[0]
    confidence = best.get("confidence", 0.5)

    # 状态判断
    if confidence >= 0.8:
        status = "success"
    elif confidence >= 0.3:
        status = "degraded"
    else:
        status = "degraded"  # 低置信度但仍返回结果

    response = {
        "status": status,
        "lat": best["lat"],
        "lon": best["lon"],
        "display_name": best.get("display_name", address),
        "confidence": confidence,
        "provider": best.get("provider", "unknown"),
        "coord_sys": "GCJ-02",
        "error": None if status == "success" else None,
        "error_detail": "",
        "results": all_results,
        "clean_result": {
            "cleaned": clean_result["cleaned"],
            "hints": clean_result["hints"],
            "admin_region": clean_result["admin_region"],
            "landmark": clean_result["landmark"],
            "shop_name": clean_result["shop_name"],
        },
        "cached": False,
    }

    # 低置信度警告
    if confidence < 0.3:
        response["error"] = "address_resolution_failed"
        response["error_detail"] = (
            f"定位置信度仅 {confidence:.0%}（行政区中心估算）。"
            f"建议补充地标信息重新搜索。"
        )

    # ── 步骤6：缓存 ──────────────────────────────────────
    if use_cache and status != "failed":
        try:
            _GeoCache.set(address, store_type, response)
        except Exception as e:
            logger.debug(f"[GeoCache] 写入失败: {e}")

    return response


def resolve_address_sync(address: str, **kwargs: Any) -> dict[str, Any]:
    """同步包装器（方便在非异步上下文中调用）"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(resolve_address_to_coord(address, **kwargs))
    else:
        # 已有事件循环，用 run_in_executor 包装
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, resolve_address_to_coord(address, **kwargs))
            return future.result()
