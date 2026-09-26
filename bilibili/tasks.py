"""每日任务：登录校验、观看+分享、投币、大会员等级加速包。

接口对照：
- 观看+分享：ranking/v2 选热门 -> view 取时长/cid -> heartbeat 上报心跳 -> share/add
- 投币：coin/today/exp 查今日已投 -> space/wbi/arc/search 取 UP 近期视频
       -> archive/coins 查是否已投 -> coin/add 投币
- 大会员：vip/experience/add 领取每日经验（等级加速包）

实测结论（2026-09-13 / 09-26 对比验证，见 README 排障章节）：
- 部分老视频每视频只允许投 1 枚，投 2 枚返回 34003 → 自动降级为 1 枚重试；
- share/add 的 -403「账号异常」是**间歇性风控拒绝**，不是永久封锁：09-13 同一天失败一次后
  1.5 分钟重试即成功（当天 4/5 成功），09-26 则约 1/10 成功（风控收紧）。紧凑重试无效
  （连续 5 次全 -403），正确做法是换时段再跑，因此不再做「连续失败即暂停 7 天」的熔断。
"""
import logging
import random
import time

from .client import BiliError, LoginError
from .state import block_coin, blocked_aids, record_share
from .utils import sleep_random

logger = logging.getLogger("bili")

# 随机间隔区间（秒）
COIN_SLEEP = (10, 25)
NEXT_UP_SLEEP = (15, 30)
COIN_403_SLEEP = (30, 60)   # 命中风控后拉长间隔
WATCH_TOTAL = (20, 35)      # 模拟观看的总时长（心跳上报值与此一致，避免"瞬间看完全片"的机器人特征）
COIN_403_LIMIT = 3          # 连续 -403 达此次数即提前结束投币任务


def _video_headers(bvid):
    """按页面类型设置 Referer/Origin，贴近真实浏览器的行为链。"""
    if not bvid:
        return None
    return {
        "Referer": f"https://www.bilibili.com/video/{bvid}",
        "Origin": "https://www.bilibili.com",
    }


def check_login(client):
    data = client.nav()
    logger.info("登录OK: %s (uid=%s)", data.get("uname"), data.get("mid"))
    return data


def get_task_status(client) -> dict:
    """查询今日任务完成状态。

    `GET /x/member/web/exp/reward` 返回：
    {"login":true,"watch":true,"coins":50,"share":true,"email":true,...}
    - login/watch/share：布尔，今日是否已完成（每日北京时间 0 点重置）
    - coins：今日投币获得的经验（50 = 已满，每枚币 10 经验）

    用途：已完成的动作直接跳过。实测对已完成的分享任务再调 share/add，
    服务端返回 `-403 账号异常,操作失败`（并非账号被封，而是重复调用被拒）。
    """
    j = client.get("/x/member/web/exp/reward")
    if j.get("code") != 0:
        logger.warning("获取今日任务状态失败: %s", j)
        return {}
    d = j.get("data") or {}
    logger.info(
        "今日任务状态: 登录%s 观看%s 分享%s 投币经验%s",
        "✓" if d.get("login") else "✗",
        "✓" if d.get("watch") else "✗",
        "✓" if d.get("share") else "✗",
        d.get("coins"),
    )
    return d


def _heartbeat(client, aid, bvid, cid, played, start_ts):
    return client.post("/x/click-interface/web/heartbeat", data={
        "bvid": bvid,
        "aid": aid,
        "cid": cid,
        "mid": client.mid or 0,
        "played_time": played,
        "realtime": played,
        "start_ts": start_ts,
        "type": 3,
        "dt": 2,
        "play_type": 1,
    }, headers=_video_headers(bvid))


def watch_and_share(client, state=None, status=None):
    """观看一个热门视频并分享（观看 +5 经验，分享 +5 经验）。返回所用视频信息 dict。

    status 为 get_task_status() 的结果：已完成的动作直接跳过，不做无用请求。
    """
    state = state if state is not None else {}
    status = status if status is not None else {}
    if not client.csrf:
        raise BiliError("Cookie 缺少 bili_jct，无法完成分享/投币，请重新抓取完整 Cookie")

    # 分享已完成：直接返回，不再调用 share/add（重复调用只会得到 -403）
    if status.get("share"):
        logger.info("分享任务今日已完成（share=true），跳过分享请求")
        return None

    j = client.get("/x/web-interface/ranking/v2", params={"rid": 0, "type": "all"})
    if j.get("code") != 0:
        raise BiliError(f"获取热门榜失败: {j}")
    video = random.choice(j["data"]["list"])
    aid, bvid = video["aid"], video["bvid"]
    logger.info("选中视频: %s (%s)", video.get("title", bvid), bvid)

    if not status.get("watch"):
        j = client.get("/x/web-interface/view", params={"bvid": bvid})
        if j.get("code") != 0:
            raise BiliError(f"获取视频信息失败: {j}")
        view = j["data"]
        cid = view.get("cid")
        duration = int(view.get("duration") or 0)

        # 心跳分两次上报，played_time 与真实流逝时间一致（不做"0 秒看完 639 秒"的假账）
        target = min(duration, random.randint(*WATCH_TOTAL)) if duration else random.randint(*WATCH_TOTAL)
        target = max(target, 1)
        first = max(int(target * random.uniform(0.3, 0.6)), 1)
        start_ts = int(time.time())
        logger.info("开始模拟观看: 目标 %ss（视频总长 %ss）", target, duration)

        time.sleep(first)
        h1 = _heartbeat(client, aid, bvid, cid, first, start_ts)
        if h1.get("code") != 0:
            raise BiliError(f"观看心跳上报失败: {h1}")
        logger.info("观看心跳1 OK: played_time=%ss", first)

        time.sleep(max(target - first, 1))
        h2 = _heartbeat(client, aid, bvid, cid, target, start_ts)
        if h2.get("code") != 0:
            raise BiliError(f"观看心跳上报失败: {h2}")
        logger.info("观看心跳2 OK: played_time=%ss（观看任务完成）", target)
    else:
        logger.info("观看任务今日已完成（watch=true），跳过观看心跳")

    # ---- 分享 ----
    # 实测（2026-09-13 vs 09-26）：share/add 的 -403 是**间歇性**风控拒绝，
    # 同一天内可能这次失败、1.5 分钟后重试就成功。所以策略是「失败就下次运行再试」，
    # 而不是紧凑循环重试（紧凑重试已被实测证明无效：连续 5 次全 -403）。
    sleep_random(5, 12)
    r = client.post("/x/web-interface/share/add",
                    data={"bvid": bvid, "csrf": client.csrf},
                    headers=_video_headers(bvid))
    code = r.get("code")
    if code == 0:
        record_share(state, True)
        logger.info("分享OK: %s", bvid)
    else:
        record_share(state, False, code, r.get("message"))
        if code == -403:
            logger.warning(
                "分享被风控拒绝: -403 账号异常（间歇性，非永久封锁）。"
                "建议稍后换个时段再跑一次 --task watch 重试，不要连续重试"
            )
        else:
            logger.warning("分享失败: code=%s message=%s", code, r.get("message"))
    return video


def donate_coins(client, up_ids, target: int = 5, state=None):
    """给指定 UP 主的近期视频投币，目标 target 枚（默认 5 枚 = 每日上限）。

    返回本次实际投出的币数。
    """
    state = state if state is not None else {}
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

    blocked = blocked_aids(state)
    if blocked:
        logger.info("按 state.json 黑名单跳过 %s 个不可投币视频", len(blocked))

    done = 0
    streak_403 = 0
    stop = False
    for uid in up_ids:
        if done >= need or stop:
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
            if done >= need or stop:
                break
            aid, bvid = v["aid"], v.get("bvid")
            if aid in blocked:
                continue  # 已知不可投币：秒跳，不浪费间隔
            c = client.get("/x/web-interface/archive/coins", params={"aid": aid})
            if c.get("code") != 0 or (c["data"].get("multiply") or 0) > 0:
                continue  # 已给此视频投过
            # 剩余额度不足 2 枚时只投 1 枚，避免超出每日上限
            multiply = 2 if (need - done) >= 2 else 1
            r = client.post("/x/web-interface/coin/add", data={
                "aid": aid,
                "multiply": str(multiply),
                "select_like": "1",
                "csrf": client.csrf,
            }, headers=_video_headers(bvid))
            code = r.get("code")

            # 34003：该视频不接受 2 枚（老视频常见），降级为 1 枚（实测可成功）
            if code == 34003 and multiply == 2:
                logger.info("aid=%s 不接受 2 枚(34003)，降级为 1 枚重试", aid)
                multiply = 1
                r = client.post("/x/web-interface/coin/add", data={
                    "aid": aid,
                    "multiply": "1",
                    "select_like": "1",
                    "csrf": client.csrf,
                }, headers=_video_headers(bvid))
                code = r.get("code")

            if code == 0:
                done += multiply
                streak_403 = 0
                logger.info("已给 aid=%s 投 %s 枚 (%s)", aid, multiply, v.get("title", ""))
                sleep_random(*COIN_SLEEP)
            elif code == -403:
                streak_403 += 1
                logger.warning("投币被风控拦截 aid=%s: -403 账号异常（连续 %s 次）", aid, streak_403)
                if streak_403 >= COIN_403_LIMIT:
                    logger.error(
                        "连续 %s 次 -403，提前结束投币任务以免加重风控（今日已投 %s 枚）",
                        streak_403, done,
                    )
                    stop = True
                    break
                sleep_random(*COIN_403_SLEEP)
            else:
                streak_403 = 0
                if code == 34003:
                    block_coin(state, aid, code, r.get("message"))
                    logger.warning("aid=%s 不可投币(%s %s)，已记入黑名单，后续跳过",
                                   aid, code, r.get("message"))
                else:
                    logger.warning("投币失败 aid=%s: code=%s message=%s",
                                   aid, code, r.get("message"))
                sleep_random(*COIN_SLEEP)
        if not stop:
            sleep_random(*NEXT_UP_SLEEP)

    logger.info("本次投币 %s 枚（目标 %s 枚）", done, target)
    return done


def claim_vip_exp(client):
    """领取大会员每日经验（等级加速包）。非大会员/权益不可用时属正常，不报错。"""
    if not client.csrf:
        raise BiliError("Cookie 缺少 bili_jct，无法领取大会员经验")
    j = client.post("/x/vip/experience/add", data={"csrf": client.csrf})
    code = j.get("code")
    if code == 0:
        logger.info("大会员等级加速包领取OK")
    elif code == 69198:
        logger.info("大会员等级加速包今日已领取")
    elif code == 6034007:
        logger.warning("大会员经验领取过于频繁(6034007)，稍后可重跑 --task vip")
    elif code == -101:
        raise LoginError("领取大会员经验失败：账号未登录(-101)")
    else:
        logger.warning("大会员等级加速包领取失败: code=%s message=%s（非大会员或权益不可用时属正常）",
                       code, j.get("message"))
    return j
