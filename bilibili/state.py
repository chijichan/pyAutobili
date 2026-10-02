"""运行状态持久化（state.json，与 config.json 同级，不含任何机密）。

用途：投币黑名单——记录「该视频不接受投币」（34003）的 aid，
避免每天重复试同一批视频、白等随机间隔。
"""
import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger("bili")

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"

COIN_BLOCK_DAYS = 30  # 投币黑名单有效期（天）


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


# ---------------- 风控拒绝记录 ----------------
def share_blocked_today(state: dict) -> bool:
    """分享被 -403 拒绝后，当天不再自动重试。"""
    info = state.get("share") or {}
    today = _today().isoformat()
    return (
        info.get("last_code") == -403
        and info.get("last_at") == today
        and state.get("risk_pause_acknowledged_at") != today
    )


def coin_paused_today(state: dict) -> bool:
    """投币被 -403 拒绝后，当天不再自动尝试。"""
    info = state.get("coin_risk_pause") or {}
    today = _today().isoformat()
    return (
        info.get("at") == today
        and state.get("risk_pause_acknowledged_at") != today
    )


def risk_rejected_today(state: dict) -> bool:
    """任一分享或投币写请求被拒绝后，当天不再执行其它写操作。"""
    return share_blocked_today(state) or coin_paused_today(state)


def acknowledge_risk_recovery(state: dict) -> bool:
    """人工确认恢复后，本地熔断每天最多临时清除一次。"""
    today = _today().isoformat()
    if state.get("risk_pause_override_used_at") == today:
        return False
    if not (share_blocked_today(state) or coin_paused_today(state)):
        return False
    state["risk_pause_acknowledged_at"] = today
    state["risk_pause_override_used_at"] = today
    return True


def pause_coin(state: dict, code, message: str) -> None:
    state.pop("risk_pause_acknowledged_at", None)
    state["coin_risk_pause"] = {
        "at": _today().isoformat(),
        "code": code,
        "message": message,
    }


def record_share(state: dict, ok: bool, code=None, message=None) -> None:
    """记录分享结果；-403 会阻止当天后续自动尝试。"""
    info = state.setdefault("share", {})
    info["last_at"] = _today().isoformat()
    info["last_code"] = code
    info["last_message"] = message
    if code == -403:
        state.pop("risk_pause_acknowledged_at", None)
    if ok:
        info["last_ok_at"] = info["last_at"]
        info["fail_streak"] = 0
    else:
        info["fail_streak"] = int(info.get("fail_streak", 0)) + 1
