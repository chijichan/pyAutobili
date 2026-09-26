"""运行状态持久化（state.json，与 config.json 同级，不含任何机密）。

用途：
- 投币黑名单：记录「该视频不接受投币」（34003）的 aid，避免每天重复试同一批视频；
- 分享熔断：分享连续失败达阈值则暂停若干天，给账号降温（账号安全优先于经验）。
"""
import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger("bili")

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"

COIN_BLOCK_DAYS = 30        # 投币黑名单有效期（天）
SHARE_PAUSE_AFTER_DAYS = 3  # 分享连续失败多少天后暂停
SHARE_PAUSE_DAYS = 7        # 暂停天数

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        logger.warning("读取 state.json 失败，按空状态处理: %s", e)
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as e:
        logger.warning("写入 state.json 失败: %s", e)


def _today() -> date:
    return date.today()


# ---------------- 投币黑名单 ----------------
def blocked_aids(state: dict) -> set:
    """返回仍在黑名单有效期内的 aid 集合。"""
    limit = _today() - timedelta(days=COIN_BLOCK_DAYS)
    alive = set()
    for aid, info in (state.get("coin_blocked") or {}).items():
        try:
            if date.fromisoformat(str(info.get("at"))) >= limit:
                alive.add(int(aid))
        except (ValueError, TypeError):
            continue
    return alive


def block_coin(state: dict, aid: int, code, message: str) -> None:
    info = (state.setdefault("coin_blocked", {})).setdefault(str(aid), {"count": 0})
    info["count"] = int(info.get("count", 0)) + 1
    info["code"] = code
    info["message"] = message
    info["at"] = _today().isoformat()


# ---------------- 分享熔断 ----------------
def share_paused(state: dict):
    """分享是否处于暂停期。返回 (是否暂停, 恢复日期或 None)。"""
    until = state.get("share_skip_until")
    if not until:
        return False, None
    try:
        if date.fromisoformat(str(until)) > _today():
            return True, str(until)
    except (ValueError, TypeError):
        pass
    return False, None


def record_share(state: dict, ok: bool, code=None, message=None) -> None:
    """记录分享结果；连续失败达阈值则进入暂停期。"""
    if ok:
        if state.pop("share_fail_streak", None):
            logger.info("分享已恢复，清除连续失败计数")
        state.pop("share_skip_until", None)
        return
    streak = int(state.get("share_fail_streak", 0)) + 1
    state["share_fail_streak"] = streak
    state["share_last_code"] = code
    state["share_last_message"] = message
    state["share_last_at"] = _today().isoformat()
    if streak >= SHARE_PAUSE_AFTER_DAYS:
        until = (_today() + timedelta(days=SHARE_PAUSE_DAYS)).isoformat()
        state["share_skip_until"] = until
        state["share_fail_streak"] = 0
        logger.warning(
            "分享已连续失败 %s 天，暂停至 %s，期间只做观看不做分享（给账号降温）",
            SHARE_PAUSE_AFTER_DAYS, until,
        )
