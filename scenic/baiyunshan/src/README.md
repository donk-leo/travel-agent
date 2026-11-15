# 白云山数据生成与来源归档说明

本目录数据由 T0coke 按 `docs/01_统一规范.md` 代整理，待白云山负责人复核后转正。

## 脚本来源与归属

白云山**历史数据**的采集过程沿用了项目 1 早期的通用脚本，脚本与原始结果统一冻结保存在：

`archive/legacy_collect_2026-10-28/`

- `采集.py`：通用公开网页采集脚本，其中包含白云山官网、去哪儿等白云山来源；同时提供 HTML 文本解析器和小红书链接读取功能；
- `小红书登录采集.py`：依赖用户在 Chrome 中完成登录并手动粘贴公开分享链接，使用 `采集.py` 的解析器采集小红书笔记；归档结果中的 3 篇白云山小红书笔记对应最终数据的 `BYS-T-02`～`BYS-T-04`；
- `采集结果.csv/json`、`小红书采集结果.csv/json`：上述脚本产生的历史采集结果；
- `失败记录.json`、`小红书失败记录.json`：采集失败记录，可用于报告中的问题分析。

归档脚本面向多个景区，不应直接视为白云山专属脚本；归档目录保持冻结，不在其中继续修改。

2026-11-15 起，本目录新增白云山专属、可重放的采集脚本 `src/collect.py`（只采公开页、无需登录态，
详见下文“一键采集（可重放）”）。归档脚本仍是历史数据（2026-10-28 快照）的来源与证据，
`collect.py` 不读取、不修改 `archive/`。

## 输入

- 平台原始 CSV：`archive/legacy_collect_2026-10-28/采集结果.csv`、
  `archive/legacy_collect_2026-10-28/小红书采集结果.csv`
  （白云山可用来源：去哪儿 1 条、小红书 3 条）；
- 官方路线页面：`data/raw/sources.csv` 中 `BYS-O-01`～`BYS-O-03` 的 URL。
  这三条 A/B/C 具体路线是后续从白云山官网“游览推荐”页面补采的，替代了早期通用脚本采集到的景区指南首页。

`data/raw/sources.csv` 是 `collect.py` 的唯一输入清单（7 行，UTF-8-SIG），脚本只读不写。

## 处理

1. 从归档采集结果中筛选白云山记录；去哪儿记录标为 `站点攻略`，小红书记录标为 `游客游记`；
2. 小红书原“正文”是整页文本，按笔记标题最后一次出现截取正文；纯图片/视频笔记剔除；
3. 补入官网 A/B/C 三条具体路线，按官网发布日期和线路类型整理；
4. 清洗沿用项目1的 R1–R8 规则，另加官网菜单、去哪儿“发布时间”、小红书页脚等平台噪声规则
   （实现见 `scenic/wugongshan/src/clean.py` 与 `scenic/summary/src/` 的说明）；
5. 24 列字段与 `standards/schema_scenic.json` 对齐，输出 UTF-8-SIG。

因此，当前 `baiyunshan_guides.csv` 是“归档采集结果 + 官网补采 + 人工筛选/正文截取 + 标准化清洗”的结果，
不是 `collect.py` 直接生成的原始输出。`collect.py` 负责**采集可重放**，不参与本轮 24 列数据的生成。

## 一键采集（可重放）

`src/collect.py` 只用 Python 3.11 标准库（urllib/csv/hashlib…），无需 requests/bs4/PyYAML，
无需登录态，也不会读取任何 cookie。所有命令在**仓库根**执行。

### 常用命令

```powershell
# 1) 只看计划：不发请求、不写文件，退出码 0
.\.venv\Scripts\python.exe scenic\baiyunshan\src\collect.py --dry-run

# 2) 全量采集（7 条；已有 html 快照且 manifest 有记录时复用为 cached）
.\.venv\Scripts\python.exe scenic\baiyunshan\src\collect.py

# 3) 只采 / 重采指定条目（--only 与 --force 可组合）
.\.venv\Scripts\python.exe scenic\baiyunshan\src\collect.py --only BYS-O-01 BYS-O-02
.\.venv\Scripts\python.exe scenic\baiyunshan\src\collect.py --force --only BYS-T-01

# 4) 复算 manifest 与落盘快照是否一致
.\.venv\Scripts\python.exe -c "import csv,hashlib,pathlib;rows=list(csv.DictReader(open(r'scenic\baiyunshan\data\raw\manifest.csv',encoding='utf-8-sig')));print([(r['doc_id'],hashlib.sha256(pathlib.Path(r['raw_file']).read_bytes()).hexdigest()==r['sha256']) for r in rows if r['status'] in ('ok','cached')])"
```

采集参数：请求间隔 ≥2 秒（同一站点 robots 只读一次并缓存）；超时 30 秒；失败最多尝试 3 次，
403/404/410 不重试；真实浏览器 UA + `Accept-Language: zh-CN`；支持 gzip/deflate；
编码按“合法 UTF-8 优先 → 响应头/meta 声明 → 候选编码打分”探测（UTF-8/GB18030/GBK/Big5）。

写盘护栏：脚本只写 `data/raw/`，**永不写 `data/processed/`**；结束时用 SHA256 复验
`data/raw/sources.csv` 未被改动。退出码 0 表示脚本跑完（个别页面失败看 manifest），
1 表示环境/护栏/自身一致性错误。

### 输出文件

| 文件 | 是否入库 | 说明 |
|---|---|---|
| `data/raw/manifest.csv` | ✅ | 每条 1 行，共 7 行；增量合并，按 `sources.csv` 顺序输出 |
| `data/raw/sources_rejected.csv` | ✅ | 只写真实失败/拒采；本轮 3 行，全部为 robots 拒采 |
| `data/raw/html/<doc_id>.html` | ❌（`.gitignore`） | 抓取成功的原始页快照（UTF-8 字节），本地证据；用 URL + SHA256 追溯 |

> 注：根 `.gitignore` 的 `*/data/raw/html/*.html` 只匹配一层目录，覆盖不到
> `scenic/baiyunshan/data/raw/html/*.html`，因此本目录新增 `data/raw/.gitignore`
> 忽略 `html/*.html`。原始 HTML 体积大且可重采，不入库。

### manifest.csv 列含义（前 14 列与武功山同序，第 15 列新增 `robots`）

| # | 列 | 含义 / 取值 |
|---:|---|---|
| 1 | `doc_id` | 与 `sources.csv` 一致（BYS-O-01…BYS-T-04） |
| 2 | `scenic_area` | `广州白云山` |
| 3 | `doc_type` | `官方路线` / `游客游记` / `站点攻略` |
| 4 | `title` | 标题（来自 `sources.csv`） |
| 5 | `source_site` | `去哪儿` / `小红书` / `白云山官网` |
| 6 | `source_url` | 原始链接（来自 `sources.csv`，含小红书的 `xsec_token`） |
| 7 | `http_status` | 页面真实 HTTP 状态码；robots 拒采时为空（未请求页面） |
| 8 | `content_bytes` | 传输解压后的响应体字节数；失败/拒采为 0 |
| 9 | `charset` | 实际解码所用编码（如 `utf-8`、`gbk`） |
| 10 | `fetch_time` | 本机时间 `YYYY-MM-DD HH:MM:SS`（该次尝试开始时刻） |
| 11 | `sha256` | 落盘 HTML 文本按 UTF-8 编码后的 SHA256，64 位小写 hex |
| 12 | `raw_file` | 相对仓库根的 posix 路径（如 `scenic/baiyunshan/data/raw/html/BYS-O-01.html`） |
| 13 | `status` | `ok` / `cached` / `failed` / `rejected` |
| 14 | `error` | 失败/拒采摘要（≤300 字）；成功为空 |
| 15 | `robots` | `allowed` / `disallowed` / `no_robots_txt` / `unavailable:<status>` |

### robots 结论（2026-11-15 本轮实测）

每个站点在抓取前请求一次 `robots.txt`（同一 origin 本次运行内缓存），只解析 `User-agent: *` 组：

| 站点 | robots.txt | `User-agent: *` 规则 | 结论 | 本轮处理 |
|---|---|---|---|---|
| `travelnews.qunar.com` | HTTP 200 | 1 条 | `allowed` | 抓取 `BYS-T-01`，200 / 65,031 bytes |
| `www.xiaohongshu.com` | HTTP 200 | 1 条 | `disallowed` | 目标 `/explore/<note_id>` 命中 Disallow，3 条**均未请求页面**，记 `robots_disallowed` |
| `www.baiyunshan.com.cn` | HTTP 404 | — | `no_robots_txt` | 视为无禁止规则，抓取 `BYS-O-01/02/03`，均 200 |

`unavailable:<status>` 表示 robots.txt 明确返回非 200/404/410；`unavailable:000` 表示网络层
没有拿到 HTTP 响应（或历史 manifest 未记录 robots）。

### 小红书为什么是“拒采”而不是“抓取成功”

- 小红书 `robots.txt` 对目标 `/explore/` 路径返回 Disallow，按“robots 禁止即不抓”的约定，
  本轮 3 条在请求页面之前就终止，`reason=robots_disallowed`，`http_status` 为空；
- 脚本**不加载**登录态/cookie、不模拟登录、不破解验证码；即使 robots 允许，也只会做**一次**
  无 cookie 普通 GET，并检查是否登录墙/空壳：
  - 出现登录提示且无笔记正文 → `login_wall`；
  - 只拿到不含笔记 ID/标题/状态对象的空壳页 → `requires_login`；
  - 只有同时命中笔记 ID + 标题或笔记状态对象，才按 `ok` 落盘；
- 因此本轮没有伪造小红书的 HTTP 状态、SHA256 或正文。

### 本轮（2026-11-15）采集结果

| doc_id | 状态 | HTTP | 字节 | robots | 说明 |
|---|---|---|---:|---|---|
| BYS-T-01 | `ok` | 200 | 65,031 | `allowed` | 去哪儿攻略页 |
| BYS-T-02 | `rejected` | — | 0 | `disallowed` | robots 禁止 `/explore/`，未请求页面 |
| BYS-T-03 | `rejected` | — | 0 | `disallowed` | 同上 |
| BYS-T-04 | `rejected` | — | 0 | `disallowed` | 同上 |
| BYS-O-01 | `ok` | 200 | 12,632 | `no_robots_txt` | 官网 A 线 |
| BYS-O-02 | `ok` | 200 | 12,032 | `no_robots_txt` | 官网 B 线 |
| BYS-O-03 | `ok` | 200 | 11,958 | `no_robots_txt` | 官网 C 线 |

合计：成功 4 / 7（`ok` 4），失败 0，拒采 3。成功数不设下限，抓不到就如实记失败/拒采。

### 与归档脚本的关系

| 维度 | `archive/legacy_collect_2026-10-28/` | `src/collect.py`（本任务） |
|---|---|---|
| 范围 | 多景区通用 | 白云山专属，输入固定为 `data/raw/sources.csv` |
| 依赖 | 含小红书登录态脚本，需 Chrome 登录 + 手动分享链接 | 仅标准库，无需登录态 |
| 可重放 | 依赖人工操作，不能一键复现 | `--dry-run` / 全量 / `--only` / `--force` 均可重放 |
| 产物 | 历史 `采集结果.csv/json`（2026-10-28 快照） | `manifest.csv` + `sources_rejected.csv` + 本地 HTML 快照 |
| 关系 | 历史数据来源与证据，保持冻结、不修改 | 只补“采集可重放”，不重写历史数据，不生成 24 列 CSV |

## 校验

```powershell
python checks/check_scenic.py scenic/baiyunshan/data/processed/baiyunshan_guides.csv
```

预期：7 条，官方 3 / 有效游记 4（3 篇游客游记 + 1 篇站点攻略，`check_scenic.py` 口径），通过。

## 复现边界

- **可重放的是“采集”**：`collect.py` 能按 `sources.csv` 重新抓取当前公开页面，并留下
  URL / HTTP 状态 / 字节数 / 时间 / SHA256 / robots 结论；`data/raw/html/` 不入库，
  干净 clone 重跑会重新抓取**当时**的页面，SHA256 随时间可能变化（manifest 记录的是本轮结果）。
- **不能重放的是“2026-10-28 的历史文本”**：归档脚本与归档结果冻结在 `archive/`，
  页面可能改版；本脚本不承诺复现归档快照，也不改写已冻结的 `clean_content` / `doc_id`。
- **小红书仍不可无条件复现**：`xsec_token` 会过期，且本轮 robots 已禁止 `/explore/`；
  脚本按约定不绕登录，故 3 条小红书只有拒采记录，没有 HTML 快照。
- **24 列标准化数据不由本脚本生成**：`baiyunshan_guides.csv` 仍来自“归档结果 + 官网补采 +
  人工筛选/截取 + 清洗”，`collect.py` 只补采集证据链；采样页面后仍需人工筛选正文。

## 注意

- 小红书 `source_url` 带 `xsec_token`，过期后需重新登录获取（本脚本不获取、不使用登录态）；
- 官方 B/C 线原文仅 63/64 字，项目 3 解析时建议优先用 A 线（395 字）；
- `manifest.csv` 的 `robots` 结论是本轮（2026-11-15）实测，站点规则可能变化，重跑会刷新；
- 本轮 `sources_rejected.csv` 有 3 行，均为 `robots_disallowed`；没有“抓取失败”行。
