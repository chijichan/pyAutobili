"""每日任务：登录校验、观看+分享、投币。

与文档接口对照：
- 观看+分享：ranking/v2 选热门 -> view 取时长/cid -> heartbeat 上报心跳 -> share/add
- 投币：coin/today/exp 查今日已投 -> space/wbi/arc/search 取 UP 近期视频
       -> archive/coins 查是否已投 -> coin/add 投币
"""
import logging
import random
import time

from .client import BiliError
from .utils import sleep_random

logger = logging.getLogger("bili")

# 随机间隔区间（秒）
WATCH_SLEEP = (8, 20)
COIN_SLEEP = (10, 25)
NEXT_UP_SLEEP = (15, 30)


def check_login(client):
    data = client.nav()
    logger.info("登录OK: %s (uid=%s)", data.get("uname"), data.get("mid"))
    return data


def watch_and_share(client):
    """观看一个热门视频并分享（每日 +5 经验）。返回所用视频信息 dict。"""
    j = client.get("/x/web-interface/ranking/v2", params={"rid": 0, "type": "all"})
    if j.get("code") != 0:
        raise BiliError(f"获取热门榜失败: {j}")
    video = random.choice(j["data"]["list"])
    aid, bvid = video["aid"], video["bvid"]
    logger.info("选中视频: %s (%s)", video.get("title", bvid), bvid)

    j = client.get("/x/web-interface/view", params={"bvid": bvid})
    if j.get("code") != 0:
        raise BiliError(f"获取视频信息失败: {j}")
    view = j["data"]
    cid = view.get("cid")
    duration = int(view.get("duration") or 0)
    # 心跳的 played_time 用接近全片长的值（留 5 秒余量，最短 1 秒）
    played = max(duration - 5, 1)

    if not client.csrf:
        raise BiliError("Cookie 缺少 bili_jct，无法完成分享/投币，请重新抓取完整 Cookie")

    heart = client.post("/x/click-interface/web/heartbeat", data={
        "bvid": bvid,
        "aid": aid,
        "cid": cid,
        "mid": client.mid or 0,
        "played_time": played,
        "realtime": played,
        "start_ts": int(time.time()),
        "type": 3,
        "dt": 2,
        "play_type": 1,
    })
    if heart.get("code") != 0:
        raise BiliError(f"观看心跳上报失败: {heart}")
    logger.info("观看心跳OK: %s（模拟播放 %ss）", video.get("title", bvid), played)

    sleep_random(*WATCH_SLEEP)

    j = client.post("/x/web-interface/share/add", data={"bvid": bvid, "csrf": client.csrf})
    if j.get("code") != 0:
        # 分享失败（可能已分享过）不阻断后续投币
        logger.warning("分享失败(不影响后续): code=%s message=%s", j.get("code"), j.get("message"))
    else:
        logger.info("分享OK: %s", bvid)
    return video


def donate_coins(client, up_ids, target: int = 5):
    """给指定 UP 主的近期视频投币，目标 target 枚（默认 5 枚 = 每日上限）。

    返回本次实际投出的币数。
    """
    today = client.get("/x/web-interface/coin/today/exp")
    if today.get("code") != 0:
        raise BiliError(f"获取今日投币情况失败: {today}")
    data = today["data"]
    # 该接口 data 为「今日投币获得的经验值」：每枚币 = 10 经验，每日上限 50（5 枚）。
    # 兼容个别时期返回 {"coins": n} 对象（直接视为已投币数）的情况。
    if isinstance(data, dict):
        coins_done = int(data.get("coins") or 0)
    else:
        coins_done = int(data) // 10
    need = target - coins_done
    if need <= 0:
        logger.info("今日已投 %s 枚（目标 %s），无需再投", coins_done, target)
        return 0
    logger.info("今日已投 %s 枚，还需 %s 枚", coins_done, need)

    if not client.csrf:
        raise BiliError("Cookie 缺少 bili_jct，无法投币")

    done = 0
    for uid in up_ids:
        if done >= need:
            break
        j = client.wbi_get("/x/space/wbi/arc/search", {
            "mid": str(uid),
            "ps": "30",
            "pn": "1",
            "order": "pubdate",
        })
        if j.get("code") != 0:
            logger.warning("获取 UP %s 视频列表失败: %s", uid, j)
            continue
        vlist = j["data"]["list"]["vlist"]
        random.shuffle(vlist)
        for v in vlist:
            if done >= need:
                break
            aid = v["aid"]
            c = client.get("/x/web-interface/archive/coins", params={"aid": aid})
            if c.get("code") != 0 or (c["data"].get("multiply") or 0) > 0:
                continue  # 已给此视频投过，跳过
            # 剩余额度不足 2 枚时只投 1 枚，避免超出每日 5 枚上限
            multiply = 2 if (need - done) >= 2 else 1
            r = client.post("/x/web-interface/coin/add", data={
                "aid": aid,
                "multiply": str(multiply),
                "select_like": "1",
                "csrf": client.csrf,
            })
            if r.get("code") == 0:
                done += multiply
                logger.info("已给 aid=%s 投 %s 枚 (%s)", aid, multiply, v.get("title", ""))
            else:
                logger.warning("投币失败 aid=%s: code=%s message=%s",
                               aid, r.get("code"), r.get("message"))
            sleep_random(*COIN_SLEEP)
        sleep_random(*NEXT_UP_SLEEP)

    logger.info("本次投币 %s 枚（目标 %s 枚）", done, target)
    return done
