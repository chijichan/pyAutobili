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


# ---------------- 分享结果记录（仅记录，不做熔断）----------------
# 实测：share/add 的 -403 是**间歇性**风控拒绝，不是永久封锁——2026-09-13 同一天内
# 失败一次、1.5 分钟后再试即成功，当天 4/5 成功；09-26 则约 1/10 成功（风控收紧）。
# 因此正确策略是「换个时段再试」，而不是长期停用分享（那样只会白丢经验）。
def record_share(state: dict, ok: bool, code=None, message=None) -> None:
    """记录分享结果，便于观察成功/失败趋势。"""
    info = state.setdefault("share", {})
    info["last_at"] = _today().isoformat()
    info["last_code"] = code
    info["last_message"] = message
    if ok:
        info["last_ok_at"] = info["last_at"]
        info["fail_streak"] = 0
    else:
        info["fail_streak"] = int(info.get("fail_streak", 0)) + 1
