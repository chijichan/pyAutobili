# pyAutobili — B 站每日任务（curl_cffi 轻量级浏览器模拟）

针对 BiliBiliTool / BiliBiliToolPro 每日任务因 B 站风控（HTTP 412 / `-412` / 反序列化失败）
大面积失败的问题：**不依赖真实浏览器渲染**，用 `curl_cffi` 复刻 Chrome 的 TLS/HTTP2 指纹，
让纯 HTTP 请求通过风控，恢复每日任务（登录经验 / 观看+分享 / 投币）。

```
├── main.py                # 入口：CLI + 配置加载
├── config.example.json    # 配置模板（真实 Cookie 填到 config.json，不入库）
├── requirements.txt       # 唯一依赖 curl_cffi
├── state.json             # 运行状态（投币黑名单/分享熔断，自动生成，不入库）
└── bilibili/
    ├── client.py          # curl_cffi 会话：Chrome 指纹、统一请求、CSRF、WBI 缓存
    ├── wbi.py             # WBI 签名（/x/space/wbi/* 必需）
    ├── tasks.py           # 登录校验 / 观看+分享 / 投币 / 大会员等级加速包
    ├── state.py           # state.json 读写：投币黑名单、分享熔断
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
python main.py                 # 全部任务：登录校验 -> 观看+分享 -> 投币 -> 大会员经验
python main.py --task coin     # 只投币
python main.py --task vip      # 只领大会员等级加速包
python main.py --verbose       # Debug 日志（请求/响应细节，排障用）
```

日志输出到控制台，同时写入 `logs\bili.log`（2MB 滚动保留 3 份）。

### 配置项

| 项 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| Cookie | `BILI_COOKIE` | 无（必填） | 与 BiliBiliToolPro 的 COOKIESTR 同格式 |
| 投币目标 UP 主 | `UP_IDS` | `2,928123` | 逗号分隔的 uid 列表 |
| 每日投币枚数 | `COIN_TARGET` | `5` | B 站每日投币上限 5 枚 = 50 经验 |

## 4. 部署与调度

代码本身是跨平台的（`pathlib` + `curl_cffi` + 标准库，无任何 Windows 专属调用），
Windows / Linux / NAS Docker 通用；差异只在调度方式和 `curl_cffi` 的轮子平台。

### 4.1 Linux（推荐 cron / systemd timer）

```bash
git clone <repo> /opt/pyAutobili && cd /opt/pyAutobili
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.json config.json && vi config.json     # 填 Cookie
.venv/bin/python main.py --task nav                      # 先验证
```

cron（每天 10:05，`crontab -e`）：

```cron
5 10 * * * cd /opt/pyAutobili && .venv/bin/python main.py >> logs/cron.log 2>&1
```

systemd timer（更适合长期运行，带随机延迟避免固定节奏）：

```bash
sudo cp deploy/pyautobili.service deploy/pyautobili.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now pyautobili.timer
systemctl list-timers pyautobili.timer      # 查看下次触发时间
```

> Linux 控制台默认 UTF-8，中文日志不会像 Windows 那样乱码。

### 4.2 Docker（NAS / 软路由）

```bash
docker build -t pyautobili:latest .
docker run --rm -e BILI_COOKIE="SESSDATA=...;bili_jct=..." -v $PWD/logs:/app/logs pyautobili:latest
```

或用 `docker-compose.yml`（群晖/威联通可在「计划任务」里定时执行 `docker compose run --rm pyautobili`）：

```bash
BILI_COOKIE="SESSDATA=...;bili_jct=..." docker compose run --rm pyautobili
```

镜像基于 `python:3.12-slim`，`curl_cffi` 自带静态 libcurl，无需额外系统依赖。
Cookie 建议走环境变量或挂载 `config.json`，不要打进镜像。

### 4.3 Windows（任务计划程序）

```powershell
schtasks /create /tn bili /tr "python D:\pyAutobili\main.py" /sc daily /st 10:00
```

或 GUI：触发器=每天 10:00，操作=启动程序 `python`，参数=`D:\pyAutobili\main.py`，起始于=`D:\pyAutobili`。

建议每 1~2 周手动跑一次 `--task nav` 确认 Cookie 未过期。

### 4.4 平台兼容性说明

`curl_cffi` 0.16.3 官方提供的预编译轮子（实测查询 PyPI 元数据）：

| 环境 | 支持情况 | 对应轮子 |
|---|---|---|
| Linux x86_64（Debian/Ubuntu/CentOS 7+，glibc ≥ 2.17） | ✅ | `manylinux2014_x86_64` |
| Linux aarch64（ARM NAS、树莓派 64 位） | ✅ | `manylinux2014_aarch64` |
| Alpine / musl（软路由、精简容器） | ✅ | `musllinux_1_2_{x86_64,aarch64}` |
| 32 位 ARM（armv7 软路由） | ⚠️ 有轮子但要求 glibc ≥ 2.28 | `manylinux_2_28_armv7l` |
| riscv64 | ✅ | `manylinux_2_34_riscv64` |
| Windows x64 | ✅ 已实测 | `win_amd64` |
| macOS（Intel / Apple Silicon） | ✅ | `macosx_*` |

**Python 版本要求 ≥ 3.10**：轮子是 `cp310-abi3` 稳定 ABI，3.10~3.14 通用
（本机实测 Python 3.12 + curl_cffi 0.16.0）。若平台无匹配轮子，pip 会回退到
源码编译 `curl_cffi-0.16.3.tar.gz`，需要 gcc + libcurl 开发头文件。

其它注意点：

- **时区**：脚本用 `time.time()` 生成 WBI 的 `wts`，与时区无关；但 B 站每日任务按北京时间
  0 点重置，服务器若是 UTC 时区，cron 建议写 `5 18 * * *`（= 北京时间次日 02:05）或设 `TZ=Asia/Shanghai`；
- **目录权限**：`logs/` 需要运行用户可写（systemd 的 `User=` 要与项目目录属主一致）；
- **控制台编码**：Linux 默认 UTF-8，中文日志不会像 Windows 那样受代码页影响。

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
| 大会员等级加速包（每日经验） | `POST /x/vip/experience/add`（`csrf`） | `tasks.claim_vip_exp` |

## 6. 风控规避要点（已内置）

- 全程单一 Chrome UA + 浏览器风格 Headers；写操作按页面类型带 `Referer: https://www.bilibili.com/video/{bvid}`；
- 请求间隔 8~25 秒随机，不固定节奏（`utils.sleep_random`）；命中 -403 后拉长到 30~60 秒；
- WBI mixin key 缓存 10 分钟，避免频繁请求 nav；
- **心跳分两次上报，`played_time` 与真实流逝时间一致**（`min(视频时长, 20~35s)`）。
  早期版本谎报全片长（如"0.2 秒看完 639 秒"），是一眼可识别的机器人特征，已修正；
- 投币命中 `34003` 自动降级为 1 枚重试；仍失败才进黑名单（`state.json`）秒跳；
- **连续 3 次 -403 即提前结束投币任务**，不在风控期持续冲撞；
- **分享连续失败 3 天自动暂停 7 天**（账号安全优先于那 5 点经验）。

还需自行保证的：**IP 干净**（首选家宽，手机热点是快速验证手段）、**单 IP 单账号**、
**Cookie 保鲜**（1~2 周重抓一次）。GitHub Actions 等机房 IP 即使指纹正确也大概率被拦，
建议只在住宅网络环境运行。

## 7. 排障：分享 -403 与投币 34003（2026-09-26 实测结论）

### 7.1 分享 `-403 账号异常`

现象：`POST /x/web-interface/share/add` 连续多日返回 `{"code":-403,"message":"账号异常,操作失败"}`。

逐一实测**排除**的原因（全部无效，别再往这些方向查）：

| 假设 | 实测方法 | 结果 |
|---|---|---|
| 缺 `buvid4` 设备指纹 | 调 `/x/frontend/finger/spi` 取 `b_4` 注入 Cookie 后重试 | 仍 -403 |
| 缺 `bili_ticket` 票据 | 按 `HMAC-SHA256(key="XgwSnGZ1p", msg="ts"+ts)` 调 `GenWebTicket`（返回 code 0、156 字符票据）后重试 | 仍 -403 |
| Referer 不是视频页 | 改带 `Referer: https://www.bilibili.com/video/{bvid}` | 仍 -403 |
| 假观看心跳触发的 | 完全不发心跳、冷启动直接分享 | 仍 -403（5/5） |
| 重试可穿透 | 连续分享 5 个不同视频 | `[-403,-403,-403,-403,-403]`，经验增量 0 |

对照结论：

- **点赞接口正常**（`archive/like` 返回 code 0）→ 不是账号整体写操作被封，而是**分享接口被单独限制**；
- 出口 IP 为**移动家宽**（`hosting:false`）→ 排除机房 IP 信誉问题；
- 故这是**账号级风控状态**，换参数/换 Cookie 都无效，只能靠时间 + 降低自动化特征恢复。

脚本处理：**不重试**（已证无效），但记录连续失败天数，**连续 3 天失败自动暂停分享 7 天**
（`state.json` 的 `share_skip_until`），期间只做观看，给账号降温。

建议：暂停期用真实浏览器手动分享/浏览几次；**如果 BiliBiliToolPro 的定时任务还开着，务必关掉**——
同一账号双份自动化会显著推高风险评分。判断依据：本脚本当时尚无大会员经验功能，
但 `vip/experience/add` 已返回「用户经验已经领取」，说明**还有另一个自动化在操作这个账号**。

### 7.2 投币 `34003 非法的投币数量`

现象：每天固定那 9~10 个 aid（来自 `mid=2` 的 2009~2010 年老视频）返回 `34003`，其它视频正常。

实测结论：**这些老视频每视频只允许投 1 枚**。

| 请求 | 结果 |
|---|---|
| `coin/add` + `multiply=2` | `34003 非法的投币数量` |
| `coin/add` + `multiply=1` | `code 0` 成功（随后 `archive/coins` 变为 `multiply:1`） |

脚本处理：命中 34003 且原本要投 2 枚时，**自动降级为 1 枚重试**；1 枚仍 34003 才把该 aid 写入
`state.json` 黑名单（30 天有效），后续秒跳——省掉每天白等的 10~25 秒 × 10 个视频。

顺带实测：取消点赞要用 `like=2`（`like=0` 会返回 `-400 请求错误`）。

### 7.3 `state.json`

运行状态，自动生成，已在 `.gitignore` 中，不含任何机密：

```json
{
  "coin_blocked": {
    "110737": { "count": 1, "code": 34003, "message": "非法的投币数量", "at": "2026-09-26" }
  },
  "share_fail_streak": 1,
  "share_last_code": -403,
  "share_skip_until": "2026-10-03"
}
```

删掉该文件即可重置全部黑名单/熔断状态。

## 8. 风险提示

- 自动化操作违反 B 站用户协议，账号有被限流/封禁风险，仅供个人学习与技术研究；
- 脚本只做「少赚经验」级别的轻量任务，请控制频率；账号安全优先级更高。

## 9. 方案 B（仅当方案 A 仍被拦）

文档中的 Playwright + stealth 方案（真实无头浏览器）未在此仓库实现，需要时按文档第 4 节搭建：
手动扫码登录一次 → `storage_state` 存盘复用登录态 → 逐页播放/点投币。
