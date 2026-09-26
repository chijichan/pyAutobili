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
from pathlib import Path

from bilibili.client import BiliClient, BiliError, LoginError
from bilibili.state import load_state, save_state
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


def main():
    parser = argparse.ArgumentParser(
        description="B 站每日任务（curl_cffi 轻量级浏览器模拟）",
        epilog="示例: python main.py --task nav && python main.py",
    )
    parser.add_argument("--task", action="append", choices=ALL_TASKS,
                        help="要执行的任务，可重复指定；默认全部 (nav/watch/coin/vip)")
    parser.add_argument("--config", help="配置文件路径（默认 ./config.json）")
    parser.add_argument("--verbose", action="store_true", help="输出 Debug 级日志")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    cfg = load_config(args.config)
    tasks = args.task or list(ALL_TASKS)

    client = BiliClient(cfg["cookie"])
    state = load_state()
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
            claim_vip_exp(client)
    except LoginError as e:
        logger.error("登录失效，请重新抓取 Cookie: %s", e)
        sys.exit(1)
    except BiliError as e:
        logger.error("任务失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期异常")
        sys.exit(1)
    finally:
        save_state(state)  # 黑名单/熔断状态即使中途出错也要落盘
    logger.info("全部任务完成")


if __name__ == "__main__":
    main()
