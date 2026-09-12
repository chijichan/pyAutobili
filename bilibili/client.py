"""B 站 API 客户端：curl_cffi 复刻 Chrome TLS/HTTP2 指纹，纯 HTTP 无浏览器。

关键点：
- `requests.Session(impersonate="chrome")` 让 TLS ClientHello / HTTP2 帧 /
  头顺序与真实 Chrome 一致，解决 requests/aiohttp/.NET HttpClient 被
  无 JS 风控识别的 TLS 指纹问题。
- 统一 JSON 解析、登录态校验、CSRF 提取、WBI mixin key 缓存。
"""
import logging
import re
import time

from curl_cffi import requests

from .wbi import sign_params

logger = logging.getLogger("bili")

API = "https://api.bilibili.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# WBI mixin key 缓存时长（秒）
WBI_TTL = 600


class BiliError(RuntimeError):
    """业务/网络层错误。"""


class LoginError(BiliError):
    """登录态失效。"""


class BiliClient:
    def __init__(self, cookie: str, api: str = API, ua: str = UA):
        self.api = api.rstrip("/")
        self.cookie = cookie.strip()
        self.session = requests.Session(impersonate="chrome")
        self.session.headers.update({
            "User-Agent": ua,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cookie": self.cookie,
        })
        m = re.search(r"bili_jct=([^;]+)", self.cookie)
        self.csrf = m.group(1) if m else None
        self.mid = None
        self._wbi_keys = None
        self._wbi_fetched_at = 0.0

    # ---------- 底层请求 ----------
    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = path if path.startswith("http") else self.api + path
        resp = self.session.request(method, url, timeout=20, **kwargs)
        try:
            j = resp.json()
        except ValueError:
            raise BiliError(
                f"{method} {url} 返回非 JSON（HTTP {resp.status_code}）:\n{resp.text[:500]}"
            )
        logger.debug("%s %s -> code=%s message=%s", method, path, j.get("code"), j.get("message"))
        return j

    def get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs)

    # ---------- 登录态 ----------
    def nav(self) -> dict:
        """登录校验；code==0 且能拿到 uname 即有效。同时缓存 uid。"""
        j = self.get("/x/web-interface/nav")
        if j.get("code") != 0:
            raise LoginError(f"登录失效 (code={j.get('code')}): {j.get('message')}")
        data = j["data"]
        self.mid = data.get("mid")
        return data

    # ---------- WBI ----------
    def get_wbi_keys(self, force: bool = False):
        now = time.time()
        if self._wbi_keys and not force and now - self._wbi_fetched_at < WBI_TTL:
            return self._wbi_keys
        data = self.nav()
        img = data["wbi_img"]["img_url"]
        sub = data["wbi_img"]["sub_url"]
        img_key = img.rsplit("/", 1)[1].split(".")[0]
        sub_key = sub.rsplit("/", 1)[1].split(".")[0]
        self._wbi_keys = (img_key, sub_key)
        self._wbi_fetched_at = now
        logger.info("已刷新 WBI mixin key")
        return self._wbi_keys

    def wbi_get(self, path: str, params: dict) -> dict:
        """带 WBI 签名的 GET。"""
        img_key, sub_key = self.get_wbi_keys()
        signed = sign_params(params, img_key, sub_key)
        return self.get(path, params=signed)
