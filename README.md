# steam-curator-exporter

把某个 Steam 鉴赏家组的「组评」全量拉取到本地，支持断点续传、失败重试、代理轮换，并导出为
JSON / CSV / SQLite。

项目源自一个已经跑通的单文件脚本，行为保持一致，但拆成了可安装、可测试的 Python 包。

## 特性

- **两种数据源**
  - `admin`（默认）：调用鉴赏家后台 AJAX 接口，字段完整，需要登录态。
  - `public`：读取公开页面的 HTML，无需登录，但只有 appid / 游戏名 / 链接等有限字段。
- **断点续传**：每页请求后原子写入 `state.json`，中断后重跑原命令即可继续。
- **不丢数据**：每拉到一条组评立即追加到 `reviews.jsonl` 并 `fsync`；导出时再按身份去重。
- **正确去重**：同一游戏被不同评测者分别推荐时，按「游戏 + 评测者 + 时间」保留为多行。
- **代理池**：支持 http / https / socks4 / socks5 / socks5h，按请求和重试轮换，日志自动隐藏账号密码。
- **多种导出**：JSON、CSV（Excel 友好的 UTF-8 BOM）、SQLite（主键 upsert）。
- **可离线检查**：`--status` 只读输出目录，`--dry-run` 只打印解析后的配置，都不联网。

## 安装

需要 Python 3.11+。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -e ".[dev]"
```

安装后可直接使用 `steam-curator-exporter` 命令，也可以：

```bash
python -m steam_curator_exporter --help
```

需要 socks 代理时，额外安装 PySocks：

```bash
pip install "requests[socks]"
```

## 快速开始

### 方式一：从浏览器 HAR 自动读取登录态（推荐）

1. 在浏览器打开鉴赏家后台的「组评管理」页面（`.../admin/reviews_manage`）。
2. 打开开发者工具 Network 面板，刷新页面，找到 `admin/ajaxgetrecommendations/` 请求。
3. 右键该请求 → Save all as HAR with content，导出 `capture.har`。
4. 运行：

```bash
steam-curator-exporter --har capture.har --out curator_reviews
```

程序会从 HAR 中自动读取 URL、Cookie、sessionid 和 Referer，并优先使用后台接口。

### 方式二：Cookie 文件（适合长期使用）

准备一个只包含 Cookie 字符串的文本文件 `cookie.txt`，例如：

```text
steamLoginSecure=...; sessionid=...; browserid=...
```

然后：

```bash
steam-curator-exporter --clan-id 26214428 --name "电竞狂热爱好者" \
  --cookie-file cookie.txt --out curator_reviews
```

> Windows 下也可以直接传 `--cookie "..."`，但容易遇到引号和分号转义问题，
> 因此更推荐 `--cookie-file`。

### 方式三：公开接口（无需登录）

```bash
steam-curator-exporter --source public --clan-id 26214428 --name "电竞狂热爱好者" \
  --out public_reviews
```

公开模式只解析页面上的 `a[data-ds-appid]`，没有评测者、时间、点赞数等字段；
分页在遇到空页时结束，服务端总数未知。

## 配置文件

通过 `--config config.toml` 读取 TOML；命令行参数优先于配置文件。

```toml
# config.toml
clan_id = "26214428"          # 也可以写成整数
name = "电竞狂热爱好者"
source = "admin"              # admin 或 public
cookie_file = "cookie.txt"
sessionid = ""                # 留空时从 HAR / 环境变量 / Cookie 提取
proxy = [
  "http://127.0.0.1:10279",
  "socks5://127.0.0.1:1080",
]
proxy_file = "proxies.txt"
out = "curator_reviews"
count = 25
delay = 1.5
timeout = 30
retries = 5
max_pages = 5000
formats = ["json", "csv"]     # json / csv / sqlite
fresh = false
keep_raw = false
log_level = "INFO"
```

对应的命令行：

```bash
steam-curator-exporter --config config.toml
```

Cookie 解析顺序：

```text
--cookie > --cookie-file > 配置文件的 cookie > 配置文件的 cookie_file
        > HAR > 环境变量 STEAM_COOKIE
```

sessionid 解析顺序：

```text
--sessionid / 配置文件 sessionid > HAR > 环境变量 STEAM_SESSIONID > 从 Cookie 自动提取
```

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `--version` | 打印版本号并退出 |
| `--config FILE` | 读取 TOML 配置文件；命令行参数优先 |
| `--har FILE` | 从浏览器 HAR 自动读取 URL / Cookie / sessionid / Referer |
| `--clan-id ID` | 鉴赏家组 ID（纯数字） |
| `--name NAME` | 鉴赏家组名称，用于拼接接口 URL |
| `--url URL` | 直接指定接口完整 URL（最高优先级） |
| `--source admin/public` | 数据源，默认 `admin` |
| `--cookie TEXT` | 完整 Cookie 字符串 |
| `--cookie-file FILE` | 从文件读取 Cookie（推荐） |
| `--sessionid ID` | 显式指定 sessionid |
| `--proxy URL` | 代理地址，可重复或用逗号分隔 |
| `--proxy-file FILE` | 代理列表文件，每行一个，支持 `#` 注释 |
| `--out DIR` | 输出目录，默认 `curator_reviews` |
| `--count N` | 每页请求条数，默认 `25`；服务端可能自行截断 |
| `--delay SECONDS` | 每页之间的基础间隔，默认 `1.5`，实际带 0.8–1.2 抖动 |
| `--timeout SECONDS` | 单次请求超时，默认 `30` |
| `--retries N` | 单页最大尝试次数，默认 `5` |
| `--max-pages N` | 防御性页数上限，默认 `5000` |
| `--format NAME` | 导出格式：`json` / `csv` / `sqlite`，可重复或逗号分隔，默认 `json,csv` |
| `--resume` | 显式断点续传；存在 `state.json` 时本来就会自动续传 |
| `--fresh` | 清空本工具管理的输出后重新全量拉取 |
| `--keep-raw` | 把每页原始响应保存到 `raw/page_XXXXXX.json` |
| `--dry-run` | 只打印解析后的配置和目标 URL，不发起网络请求 |
| `--status` | 只读取输出目录并打印进度，不联网、不需要 Cookie |
| `--log-level LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`，默认 `INFO` |

## 输出文件

```text
curator_reviews/
  reviews.jsonl     # 原始组评，逐条追加并 fsync；可能包含重复行
  reviews.json      # 去重后的完整结果 + 元信息（每 10 页及结束时刷新）
  reviews.csv       # Excel 友好 CSV，utf-8-sig 编码
  reviews.sqlite3   # 可选，--format sqlite 时生成
  state.json        # 断点续传状态（原子写入）
  run.log           # 运行日志（stdout 同步输出）
  raw/              # --keep-raw 时保存的原始分页
```

`reviews.jsonl` 永远保存原始行，即使重复也不会被悄悄丢弃；`reviews.json` / `reviews.csv` /
SQLite 导出时会按组评身份去重。

CSV 列固定为：

```text
appid, app_name, time_recommended, time_recommended_local,
creator_account_id, creator_steamid64, upvote_count, comment_count,
received_for_free, received_compensation, recommendation_state,
link_url, link_text, blurb
```

- `time_recommended_local` 使用 `Asia/Shanghai` 时区（系统缺少 tzdata 时退回固定 +08:00）。
- `creator_steamid64` = `76561197960265728 + creator_account_id`。

## 断点续传、重来与查看进度

```bash
# 首次运行
steam-curator-exporter --har capture.har --out curator_reviews

# 中断后重跑同一条命令即可自动续传
steam-curator-exporter --har capture.har --out curator_reviews

# 显式要求续传
steam-curator-exporter --har capture.har --out curator_reviews --resume

# 清空后重新全量拉取
steam-curator-exporter --har capture.har --out curator_reviews --fresh

# 随时查看进度（不联网）
steam-curator-exporter --status --out curator_reviews
```

`--fresh` 只清理本工具管理的文件（`reviews.jsonl`、`reviews.json`、`reviews.csv`、
`reviews.sqlite3`、`state.json`、`*.tmp`、`raw/page_*.json`），不会删除目录里的其他文件。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功（分页完成；唯一行数少于 total_count 也可能是正常去重） |
| `1` | 运行时失败、被中断、分页没有前进等 |
| `2` | 用法或配置错误（缺参数、配置文件/代理/格式不合法） |
| `3` | 登录态失效、Cookie/sessionid 无效、接口返回登录页或 `success != 1` |
| `4` | admin 分页未抓完（`next_start < total_count`），可重跑续传 |

## 代理

```bash
# 单个
steam-curator-exporter --har capture.har --proxy http://127.0.0.1:10279

# 多个（每个请求/每次重试轮换）
steam-curator-exporter --har capture.har \
  --proxy http://127.0.0.1:10279 \
  --proxy socks5://127.0.0.1:1080

# 逗号分隔
steam-curator-exporter --har capture.har \
  --proxy "http://a:8080,socks5h://b:1080"

# 文件
steam-curator-exporter --har capture.har --proxy-file proxies.txt
```

- 不写协议时自动补 `http://`，例如 `127.0.0.1:8080`。
- 支持 `http` / `https` / `socks4` / `socks5` / `socks5h`。
- 日志中的代理账号密码会显示为 `http://***@host:port`。
- socks 代理需要 PySocks；缺失时会提示 `pip install "requests[socks]"`。
- 不传 `--proxy` / `--proxy-file` 时，requests 会读取 `HTTP_PROXY` / `HTTPS_PROXY`
  环境变量；都没有则直连。

## FAQ

### 为什么 `total_count` 是 1788，导出只有 1733 条？

这是正常现象。Steam 的 `total_count` 统计的是分页条目数，其中可能包含：

- 同一游戏被同一位评测者重复提交/重复出现的行；
- 已被删除但服务端分页计数尚未同步的行。

同一游戏被不同评测者分别推荐的行会**保留**（身份键不同），不会造成这个差额。

本工具的组评身份是：

```text
appid|accountid_creator|time_recommended
```

缺少评测者或时间时退回 `appid|sha1(link_url|blurb)`。

因此分页完整时，本地唯一行数少于 `total_count` 属于正常去重，程序会记录一条 INFO 日志并
仍然退出 `0`。**只有 `next_start < total_count`（分页没抓完）才会退出 `4`。**

### 为什么同一游戏在 CSV 里出现多行？

因为不同评测者分别推荐了它。按 `appid` 单键去重会错误地丢掉这些行，所以本工具使用
「游戏 + 评测者 + 时间」作为身份键。

### 中断后 `reviews.jsonl` 最后一行不完整怎么办？

读取时会忽略无法解析的半行（这是唯一被静默跳过的 JSON 错误），已经完整落盘的数据不受影响。
重跑会自动续传。

### 公开模式为什么字段很少？

公开页面只提供 HTML 片段。程序只能尽力解析 `a[data-ds-appid]`、链接和游戏名；
评测者、时间、点赞数等字段为 `None` / `0`，去重会使用链接与正文指纹兜底。
如果 Steam 改版导致选择器失效，公开模式可能需要更新解析逻辑。

## 安全警告

Cookie 和 HAR 等同于登录凭据：

- HAR 里通常包含完整 Cookie、`steamLoginSecure`、sessionid，甚至 Steam Guard 令牌。
- **不要**把 `*.har`、`cookie.txt`、`config.toml` 提交到 Git 或发给他人。
- 本仓库的 `.gitignore` 已忽略这些常见文件，但请自行确认。
- 本项目的日志只打印 Cookie 长度和 sessionid 是否存在，不打印其内容；代理凭据会打码。
- 如果怀疑泄露，请在 Steam 中退出所有设备并重新登录，使旧 Cookie 失效。

## 开发

```bash
python -m pytest -q
python -m compileall -q src
ruff check .
```

测试全部使用内存中的假 transport，不会访问 Steam。CI 在 Python 3.11 / 3.12 / 3.13 上
运行 ruff 和 pytest。

## 已知限制

- 公开模式依赖 Steam 当前 HTML 结构，解析是 best-effort；字段不完整且没有总数。
- admin 模式需要有效登录态；Cookie 过期会以退出码 `3` 结束。
- 默认页间隔 1.5 秒是出于礼貌和降低被限流风险；不要盲目调小。
- 单进程顺序拉取，没有并发/异步，也不包含 Web UI、数据库 ORM 或定时任务。
- 本项目不会自动执行 `git init` / `git commit`，版本管理由使用者自行决定。