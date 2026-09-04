"""即梦/Doubao Seedream 文生图服务

通过火山引擎 Ark API 调用 doubao-seedream 模型生成图片。
用于 AI探店视频的配图自动化生成。
"""

import time
import httpx
from loguru import logger

from config.env import ARK_API_KEY, ARK_BASE_URL, ARK_IMAGE_MODEL

# 支持的尺寸
VALID_SIZES = ["2K", "1K", "1024x1024", "2048x2048"]


class ImageGenerator:
    """即梦 Seedream 文生图生成器"""

    def __init__(self):
        self.api_key = ARK_API_KEY
        self.base_url = ARK_BASE_URL.rstrip("/")
        self.model = ARK_IMAGE_MODEL
        self._endpoint = f"{self.base_url}/images/generations"

    def generate(
        self,
        prompt: str,
        size: str = "2K",
        watermark: bool = True,
        response_format: str = "url",
        max_retries: int = 3,
    ) -> dict:
        """生成一张图片

        Args:
            prompt: 图片描述提示词（支持中英文）
            size: 图片尺寸，可选 "2K", "1K", "1024x1024", "2048x2048"
            watermark: 是否添加水印
            response_format: 返回格式 "url" 或 "b64_json"
            max_retries: 最大重试次数

        Returns:
            dict: {"status": "success", "image_url": "...", ...}
                  或 {"status": "error", "message": "..."}
        """
        if size not in VALID_SIZES:
            logger.warning(f"不支持的尺寸 {size}，已降级为 2K")
            size = "2K"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "response_format": response_format,
            "size": size,
            "stream": False,
            "watermark": watermark,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                logger.info(f"🎨 文生图请求 (attempt {attempt + 1}/{max_retries}): {prompt[:60]}...")
                response = httpx.post(
                    self._endpoint,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(120.0, connect=10.0),
                )

                if response.status_code == 200:
                    data = response.json()
                    # 火山引擎返回格式: {"data": [{"url": "..."}]}
                    items = data.get("data", [])
                    if items and len(items) > 0:
                        image_url = items[0].get("url", "")
                        logger.info(f"✅ 图片生成成功: {image_url[:80]}...")
                        return {
                            "status": "success",
                            "image_url": image_url,
                            "model": self.model,
                            "size": size,
                            "raw": data,
                        }
                    else:
                        logger.warning(f"返回数据为空: {data}")
                        last_error = "API 返回数据为空"
                elif response.status_code == 429:
                    # 限流，等待后重试
                    wait = 2 ** attempt * 3
                    logger.warning(f"⏳ 触发限流，{wait}秒后重试...")
                    time.sleep(wait)
                    last_error = f"API 限流 (HTTP {response.status_code})"
                    continue
                else:
                    error_text = response.text[:300]
                    logger.error(f"❌ 文生图失败 (HTTP {response.status_code}): {error_text}")
                    last_error = f"HTTP {response.status_code}: {error_text}"

            except httpx.TimeoutException:
                logger.warning(f"⏱️ 请求超时 (attempt {attempt + 1})")
                last_error = "请求超时"
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
            except Exception as e:
                logger.error(f"❌ 文生图异常: {e}")
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue

        return {"status": "error", "message": last_error or "未知错误"}

    def generate_batch(
        self,
        prompts: list,
        size: str = "2K",
        watermark: bool = True,
    ) -> list:
        """批量生成图片

        Args:
            prompts: 提示词列表
            size: 图片尺寸
            watermark: 是否添加水印

        Returns:
            list[dict]: 每个元素为 {"status": "success/error", ...}
        """
        results = []
        for i, prompt in enumerate(prompts):
            logger.info(f"🎨 批量生成 [{i + 1}/{len(prompts)}]")
            result = self.generate(prompt, size=size, watermark=watermark)
            # 批次间加间隔避免限流
            if i < len(prompts) - 1:
                time.sleep(2)
            results.append(result)
        return results


# 全局单例
_image_generator: ImageGenerator | None = None


def get_image_generator() -> ImageGenerator:
    """获取图片生成器单例"""
    global _image_generator
    if _image_generator is None:
        _image_generator = ImageGenerator()
    return _image_generator
