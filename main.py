"""B 站每日任务脚本入口（curl_cffi 轻量级浏览器模拟）。

用法：
    python main.py                      # 依次执行: nav -> watch/share -> coin -> vip
    python main.py --task nav           # 只校验登录（验证 TLS 指纹是否通过）
    python main.py --task watch         # 观看+分享（一体）
    python main.py --task coin          # 投币
    python main.py --task vip           # 大会员等级加速包（每日经验）
    python main.py --verbose            # 输出 Debug 级日志

配置优先级：环境变量 > config.json > 默认值。
    环境变量：BILI_COOKIE、UP_IDS（逗号分隔）、COIN_TARGET
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from bilibili.client import BiliClient, BiliError, LoginError
from bilibili.state import (
    acknowledge_risk_recovery,
    load_state,
    risk_rejected_today,
    save_state,
)
from bilibili.tasks import (
    check_login,
    claim_vip_exp,
    donate_coins,
    get_task_status,
    watch_and_share,
)
from bilibili.utils import setup_logging

logger = logging.getLogger("bili")

ALL_TASKS = ("nav", "watch", "coin", "vip")


def load_config(path=None):
    cfg_path = Path(path) if path else Path(__file__).parent / "config.json"
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    cookie = os.environ.get("BILI_COOKIE") or cfg.get("cookie") or ""
    if not cookie:
        raise SystemExit(
            "未找到 Cookie。\n"
            "  1) 复制 config.example.json 为 config.json 并填入 Cookie；或\n"
            "  2) 设置环境变量 BILI_COOKIE。\n"
            "Cookie 需含 SESSDATA / bili_jct / DedeUserID / DedeUserID__ckMd5。"
        )

    env_ups = os.environ.get("UP_IDS")
    up_ids = [str(u).strip() for u in (env_ups.split(",") if env_ups else cfg.get("up_ids", ["2", "928123"]))]
    coin_target = int(os.environ.get("COIN_TARGET") or cfg.get("coin_target", 5))
    return {"cookie": cookie, "up_ids": up_ids, "coin_target": coin_target}


def seconds_until_next_run(now=None, last_run_date=None):
    now = now or datetime.now()
    next_run = now.replace(hour=10, minute=5, second=0, microsecond=0)
    if last_run_date is not None and next_run.date() <= last_run_date:
        next_run = datetime.combine(last_run_date + timedelta(days=1), now.min.time())
        next_run = next_run.replace(hour=10, minute=5)
    elif next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds(), next_run


def run_once(cfg, tasks, confirm_risk_recovered=False):
    client = BiliClient(cfg["cookie"])
    state = load_state()
    if confirm_risk_recovered:
        if acknowledge_risk_recovery(state):
            logger.warning("已清除今天的本地风控熔断；本次运行若再次收到 -403，会重新停止写操作")
        else:
            logger.info("没有需要清除的当日风控熔断")
    try:
        if "nav" in tasks:
            check_login(client)
        # 先查今日任务状态：已完成的动作直接跳过，减少无谓请求与风控暴露
        status = get_task_status(client)
        if "watch" in tasks:
            watch_and_share(client, state, status)  # 观看 + 分享一体
        if "coin" in tasks:
            donate_coins(client, cfg["up_ids"], cfg["coin_target"], state)
        if "vip" in tasks:
            if risk_rejected_today(state):
                logger.warning("今天已有 -403 风控拒绝，跳过 VIP 写请求")
            else:
                claim_vip_exp(client)
    except LoginError as e:
        logger.error("登录失效，请重新抓取 Cookie: %s", e)
        return False
    except BiliError as e:
        logger.error("任务失败: %s", e)
        return False
    except Exception:
        logger.exception("未预期异常")
        return False
    finally:
        if confirm_risk_recovered and not risk_rejected_today(state):
            state.pop("risk_pause_acknowledged_at", None)
        save_state(state)  # 黑名单/熔断状态即使中途出错也要落盘
    logger.info("本轮任务完成")
    return True


def run_resident(cfg, tasks):
    logger.info("常驻模式已启动，每天本地时间 10:05 执行；Ctrl+C 退出")
    last_run_date = None
    try:
        while True:
            _, next_run = seconds_until_next_run(last_run_date=last_run_date)
            logger.info("下次执行时间: %s", next_run.strftime("%Y-%m-%d %H:%M:%S"))
            while True:
                delay = (next_run - datetime.now()).total_seconds()
                if delay <= 0:
                    break
                time.sleep(min(delay, 60))
            last_run_date = datetime.now().date()
            run_once(cfg, tasks)
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，常驻模式已退出")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="B 站每日任务（curl_cffi 轻量级浏览器模拟）",
        epilog="示例: python main.py --task nav && python main.py",
    )
    parser.add_argument("--task", action="append", choices=ALL_TASKS,
                        help="要执行的任务，可重复指定；默认全部 (nav/watch/coin/vip)")
    parser.add_argument("--config", help="配置文件路径（默认 ./config.json）")
    parser.add_argument("--verbose", action="store_true", help="输出 Debug 级日志")
    parser.add_argument("--resident", action="store_true", help="常驻进程，每天本地时间 10:05 执行")
    parser.add_argument(
        "--confirm-risk-recovered",
        action="store_true",
        help="人工确认账号已恢复后，每天临时清除一次本地熔断；新 -403 仍会立即熔断",
    )
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    cfg = load_config(args.config)
    tasks = args.task or list(ALL_TASKS)
    if args.resident:
        if args.confirm_risk_recovered:
            parser.error("--resident 不能与 --confirm-risk-recovered 同时使用")
        return run_resident(cfg, tasks)
    return 0 if run_once(cfg, tasks, args.confirm_risk_recovered) else 1


if __name__ == "__main__":
    sys.exit(main())
