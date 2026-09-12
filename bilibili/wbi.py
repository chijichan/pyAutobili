"""B 站 WBI 签名实现（/x/space/wbi/* 等接口必需）。

算法参考：https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/sign/wbi.md
"""
import functools
import hashlib
import time
from urllib.parse import urlencode

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def get_mixin_key(img_key: str, sub_key: str) -> str:
    """由 nav 接口的 wbi_img 两个 key 计算 mixin key（取打乱后前 32 字符）。"""
    raw = img_key + sub_key
    return functools.reduce(lambda acc, i: acc + raw[i], MIXIN_KEY_ENC_TAB[:32], "")


def sign_params(params: dict, img_key: str, sub_key: str) -> dict:
    """对参数做 WBI 签名，返回追加了 wts 与 w_rid 的新参数字典。"""
    params = dict(params)
    params["wts"] = int(time.time())
    params = dict(sorted(params.items()))
    query = urlencode(params)
    w_rid = hashlib.md5((query + get_mixin_key(img_key, sub_key)).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params
