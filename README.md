# pyAutobili — B 站每日任务（curl_cffi 轻量级浏览器模拟）

用于执行 B 站每日任务（登录经验 / 观看+分享 / 投币）。平台可能限制自动化请求；遇到拒绝时，
脚本会停止对应操作，不保证任务一定成功，也不会尝试绕过平台限制。

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
# 官网人工确认账号恢复后，清除当日旧熔断并只运行投币
python main.py --task coin --confirm-risk-recovered
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
| **今日任务完成状态** | `GET /x/member/web/exp/reward`（`login/watch/share` 布尔，`coins` 为投币经验） | `tasks.get_task_status()` |
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

## 6. 风控响应处理

- 分享当天收到 `-403` 后，`state.json` 会记录拒绝结果，当天不再自动重试。
- 分享或投币任一写请求收到 `-403` 后，当天跳过后续投币和 VIP 写请求；投币拒绝日期会写入
  `state.json`，分享拒绝也会记录在其中。
- 收到 `-403` 时请暂停自动任务，并在官方客户端或网页端检查账号通知和账号状态。不要通过
  更换视频、设备标识、网络或反复运行来试探限制；脚本无法解除平台限制。
- 人工确认账号恢复后，可用 `--confirm-risk-recovered` 在本次运行中临时清除旧熔断；建议同时
  指定单一任务，例如 `--task coin`。每天仅能确认一次；确认标记不会持久化，本次运行若再遇到
  `-403`，新熔断会保存，且当天不能再次使用确认开关。
- 投币 `34003` 表示当前视频/投币数量不被接受，与 `-403` 风控拒绝不同；符合条件时脚本仍会
  将双币请求降为单币请求。

熔断日期使用运行主机的本地日期。若主机时区与北京时间不同，请留意日期切换时间。

## 7. 排障：分享 -403 与投币 34003

### 7.1 分享 `-403 账号异常`

现象：`POST /x/web-interface/share/add` 返回 `{"code":-403,"message":"账号异常,操作失败"}`。

`-403` 表示平台拒绝了这次操作，单凭该响应不能判断是临时限制还是账号存在异常。检查官方
客户端/网页端的账号状态；在确认限制解除前不要继续自动请求。脚本记录的分享拒绝会在主机
本地日期变化后失效，但这不代表平台限制已解除。

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
