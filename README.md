# pyAutobili — B 站每日任务（curl_cffi 轻量级浏览器模拟）

针对 BiliBiliTool / BiliBiliToolPro 每日任务因 B 站风控（HTTP 412 / `-412` / 反序列化失败）
大面积失败的问题：**不依赖真实浏览器渲染**，用 `curl_cffi` 复刻 Chrome 的 TLS/HTTP2 指纹，
让纯 HTTP 请求通过风控，恢复每日任务（登录经验 / 观看+分享 / 投币）。

```
├── main.py                # 入口：CLI + 配置加载
├── config.example.json    # 配置模板（真实 Cookie 填到 config.json，不入库）
├── requirements.txt       # 唯一依赖 curl_cffi
└── bilibili/
    ├── client.py          # curl_cffi 会话：Chrome 指纹、统一请求、CSRF、WBI 缓存
    ├── wbi.py             # WBI 签名（/x/space/wbi/* 必需）
    ├── tasks.py           # 登录校验 / 观看+分享 / 投币
    └── utils.py           # 日志（控制台+文件滚动）与随机节奏
```

## 0. 动手前：先确认根因

先跑一次登录校验，看是哪一类问题，再决定要不要继续：

```bash
python main.py --task nav
```

| 现象 | 结论 | 处理 |
|---|---|---|
| 输出 `登录OK: xxx` | Cookie 有效、TLS 指纹已通过 | 直接跑全部任务 |
| `登录失效 (code=-101)` 等 | Cookie 过期/缺失 | 重新抓 Cookie（见下） |
| 非 JSON / HTTP 412 / `-412` | IP 或指纹仍被拦 | 换 IP（手机热点最快）；仍不行再上方案 B（Playwright） |
| 其它接口 `code:0` 但解析失败 | 接口字段变更 | 对照接口表更新本仓库代码，或等上游修复 |

## 1. 安装

```bash
# Python 3.10+
pip install -r requirements.txt
```

## 2. 抓取 Cookie

1. 浏览器（建议用与脚本相同 UA 的 Chrome）登录 https://www.bilibili.com；
2. F12 → Network → 刷新页面 → 任选一个 `api.bilibili.com` 请求 → Headers → Request Headers → `Cookie`；
3. 把整段 Cookie 复制进 `config.json`（或环境变量 `BILI_COOKIE`）。

必须包含：`SESSDATA`、`bili_jct`（投币/分享的 csrf 来源）、`DedeUserID`、`DedeUserID__ckMd5`。
Cookie 每 1~2 周可能失效，失效时脚本会明确报「登录失效」。

```bash
copy config.example.json config.json
# 编辑 config.json，填入 cookie、up_ids（要投币的 UP 主 uid）
```

## 3. 运行

```bash
python main.py --task nav      # 第 0 步的验证脚本
python main.py                 # 全部任务：登录校验 -> 观看+分享 -> 投币
python main.py --task coin     # 只投币
python main.py --verbose       # Debug 日志（请求/响应细节，排障用）
```

日志输出到控制台，同时写入 `logs\bili.log`（2MB 滚动保留 3 份）。

### 配置项

| 项 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| Cookie | `BILI_COOKIE` | 无（必填） | 与 BiliBiliToolPro 的 COOKIESTR 同格式 |
| 投币目标 UP 主 | `UP_IDS` | `2,928123` | 逗号分隔的 uid 列表 |
| 每日投币枚数 | `COIN_TARGET` | `5` | B 站每日投币上限 5 枚 = 50 经验 |

## 4. 计划任务（Windows）

```powershell
schtasks /create /tn bili /tr "python D:\pyAutobili\main.py" /sc daily /st 10:00
```

或任务计划程序 GUI：触发器=每天 10:00，操作=启动程序 `python`，参数=`D:\pyAutobili\main.py`，
起始于=`D:\pyAutobili`。建议每 1~2 周手动跑一次 `--task nav` 确认 Cookie 未过期。

## 5. 接口对照（与文档一致）

| 用途 | 方法与路径 | 实现位置 |
|---|---|---|
| 登录校验 / 用户信息 | `GET /x/web-interface/nav` | `client.nav()` |
| WBI mixin key 来源 | 同上 `wbi_img` | `client.get_wbi_keys()` |
| 热门视频列表 | `GET /x/web-interface/ranking/v2?rid=0&type=all` | `tasks.watch_and_share` |
| 视频信息（时长/cid） | `GET /x/web-interface/view?bvid=` | 同上 |
| 观看心跳 | `POST /x/click-interface/web/heartbeat` | 同上 |
| 分享视频 | `POST /x/web-interface/share/add`（`bvid,csrf`） | 同上 |
| 今日投币经验 | `GET /x/web-interface/coin/today/exp`（`data`=经验值，每枚币 10 经验，上限 50） | `tasks.donate_coins` |
| UP 视频列表（需 WBI） | `GET /x/space/wbi/arc/search` | 同上 |
| 查视频已投币 | `GET /x/web-interface/archive/coins?aid=` | 同上 |
| 投币 | `POST /x/web-interface/coin/add`（`aid,multiply,select_like,csrf`） | 同上 |

## 6. 风控规避要点（已内置）

- 全程单一 Chrome UA + 浏览器风格 Headers（Referer / Origin / Sec-Fetch 风格）；
- 请求间隔 8~25 秒随机，不固定节奏（`utils.sleep_random`）；
- WBI mixin key 缓存 10 分钟，避免频繁请求 nav；
- 心跳上报用接近全片长的 `played_time`，模拟真实播放完成。

还需自行保证的：**IP 干净**（首选家宽，手机热点是快速验证手段）、**单 IP 单账号**、
**Cookie 保鲜**（1~2 周重抓一次）。GitHub Actions 等机房 IP 即使指纹正确也大概率被拦，
建议只在住宅网络环境运行。

## 7. 风险提示

- 自动化操作违反 B 站用户协议，账号有被限流/封禁风险，仅供个人学习与技术研究；
- 脚本只做「少赚经验」级别的轻量任务，请控制频率；账号安全优先级更高。

## 8. 方案 B（仅当方案 A 仍被拦）

文档中的 Playwright + stealth 方案（真实无头浏览器）未在此仓库实现，需要时按文档第 4 节搭建：
手动扫码登录一次 → `storage_state` 存盘复用登录态 → 逐页播放/点投币。
