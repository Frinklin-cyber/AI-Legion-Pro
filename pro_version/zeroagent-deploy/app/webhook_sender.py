"""
webhook_sender.py
对接企业微信 / 钉钉 / 飞书 群机器人 Webhook。
配置读取自 data/webhooks.json（未配置时发送功能自动禁用，不影响主流程）。
提供 config/webhooks.example.json 作为配置模板。

data/webhooks.json 结构：
{
  "wecom":    {"url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"},
  "dingtalk": {"url": "https://oapi.dingtalk.com/robot/send?access_token=xxx", "secret": "可选，加签密钥"},
  "feishu":   {"url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"}
}
"""

import hashlib
import hmac
import base64
import json
import time
import urllib.parse
from pathlib import Path

import requests

CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "webhooks.json"


def load_webhook_config(path: Path = CONFIG_FILE) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _dingtalk_sign(secret: str) -> str:
    """钉钉加签"""
    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return ts, sign


def send_webhook(channel: str, message: str, config: dict = None) -> dict:
    """
    发送文本消息到指定渠道。
    channel: "wecom" | "dingtalk" | "feishu"
    返回 {"sent": bool, "channel": ..., "error": 失败原因}
    """
    config = config if config is not None else load_webhook_config()
    conf = config.get(channel)
    if not conf or not conf.get("url"):
        return {"sent": False, "channel": channel, "error": f"未配置 {channel} webhook（参考 config/webhooks.example.json）"}

    url = conf["url"]
    if channel == "wecom":
        payload = {"msgtype": "text", "text": {"content": message}}
        headers = {"Content-Type": "application/json"}
    elif channel == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": message}}
        if conf.get("secret"):
            ts, sign = _dingtalk_sign(conf["secret"])
            url += f"&timestamp={ts}&sign={sign}"
        headers = {"Content-Type": "application/json"}
    elif channel == "feishu":
        payload = {"msg_type": "text", "content": {"text": message}}
        headers = {"Content-Type": "application/json"}
    else:
        return {"sent": False, "channel": channel, "error": f"未知渠道: {channel}"}

    try:
        resp = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                             headers=headers, timeout=10)
        body = resp.text[:200]
        if resp.status_code == 200:
            return {"sent": True, "channel": channel, "response": body}
        return {"sent": False, "channel": channel, "error": f"HTTP {resp.status_code}: {body}"}
    except requests.RequestException as e:
        return {"sent": False, "channel": channel, "error": f"网络异常: {e}"}
