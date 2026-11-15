# 模型运行时（runtime）

> 角色：OPS（T0.1）｜最后更新：2026-11-15
> 本目录只有文档，**不含模型权重、不含密钥**。目标是：换一台机器，按本文能把 P7 的推理后端跑起来，
> 并且能验证“跑的是不是同一份模型”。所有命令都用仓库根变量或环境变量，不依赖某个人的绝对路径。

---

## 0. 事实边界（先读）

- 仓库**不提交**模型权重（5 GB，远超仓库 50 MB 上限）。干净 clone 后必须自己准备模型。
- 项目 7 只依赖一个接口：`POST http://127.0.0.1:11434/api/chat`，模型名默认 `qwen3:8b`
  （`analysis/p07_agent/src/config.py`）。因此有两条合法路径：
  - **方式 A：官方 Ollama**（默认推荐，最省事）；
  - **方式 B：llama.cpp + 一个 Ollama 兼容层**（本机 2026-11-15 实际在用，见第 3 节）。
- 两种方式对项目完全等价；差别只在“谁提供 11434 端口”。
- 本文记录的摘要/SHA256 是本机实测值，不是官方发布值；**换模型时必须重新记录**。

---

## 1. 模型摘要（本机实测，2026-11-15）

| 项 | 值 |
|---|---|
| 模型 | Qwen3-8B |
| 量化 | `Q4_K_M`（llama.cpp `model_ftype: Q4_K - Medium`） |
| 参数量 | 8,190,735,360 |
| 文件大小 | **5,027,783,488 B**（4.68 GiB） |
| 文件 | `.downloads/Qwen3-8B-Q4_K_M.gguf`（相对仓库根） |
| SHA256 | `D98CDCBD03E17CE47681435B5150E34C1417F50B5C0019DD560E4882C5745785` |
| 上下文 | `n_ctx=8192`（`-c 8192`）；并发槽 `total_slots=4` |
| 兼容层自报 | `model=qwen3:8b`，`digest=local-qwen3-8b-q4_k_m`，`size=5027783488` |
| llama.cpp | `version: 1.0.0-dev (build 12359, commit b1b770d90)`，Clang 20.1.8，Windows x86_64 |
| 启动器 SHA256 | `38C5AFFB81C9A8F88F5538C7D11BC445E13BC46A2C6EDA05694B8B31A8D45995`（`llama-server.exe`，9,728 B launcher） |

> `digest=local-qwen3-8b-q4_k_m` 是**兼容层自报的本地标识**，不是 Ollama registry digest。
> 用 `ollama pull qwen3:8b` 得到的官方产物可能与该 GGUF 不同（字节不同、digest 不同）；
> 换用官方 tag 时，把 `ollama list` 里的 digest 记到本表，才算锁住。

---

## 2. 方式 A：官方 Ollama（推荐）

```powershell
# 1) 启动服务：默认监听 127.0.0.1:11434
ollama serve

# 2) 另开一个终端，拉取模型（约 5 GB）
ollama pull qwen3:8b

# 3) 记录实际摘要（换机后可对比）
ollama list
```

校验：

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing | Select-Object -ExpandProperty Content
# 期望 200，且 models[].model = "qwen3:8b"
Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/version" -UseBasicParsing | Select-Object -ExpandProperty Content
```

要点：

- 官方 Ollama **不需要** OpenAI API key，也不要往仓库里写任何 key；
- 如果 tag 不是 `qwen3:8b`，用 `P07_OLLAMA_MODEL` 覆盖（见第 5 节），不要改代码；
- Ollama 默认只监听 `127.0.0.1`；不要为了局域网访问改成 `0.0.0.0`（见 `02_AGENT_PROTOCOL` 第 10 节）。

---

## 3. 方式 B：llama.cpp + Ollama 兼容层（本机实际用法）

本机没有安装官方 Ollama（`ollama` 不在 PATH），实际是：
**llama.cpp（Vulkan，RTX 4060）+ `ollama_shim.py` 兼容层**，把 `/api/chat` 转给 llama.cpp 的 OpenAI 接口。
兼容层脚本在仓库外的运行目录 `travel-agent-run/`（`travel-agent-run/README.md` 记录了原因：官方安装包下载约 0.02–0.04 MB/s，改用同一份 Q4_K_M GGUF）。

### 3.1 文件布局（相对仓库根）

```
<repo>/.downloads/Qwen3-8B-Q4_K_M.gguf          # 5,027,783,488 B，不入库
<repo>/.downloads/llama/vulkan/llama-server.exe # + 同目录 dll（ggml-vulkan.dll 等）
<repo>/../travel-agent-run/ollama_shim.py       # 兼容层，仓库外，可选（有官方 Ollama 就不需要）
```

### 3.2 启动 llama.cpp（用仓库根变量，不写死盘符）

```powershell
$RepoRoot    = (git rev-parse --show-toplevel)
$ModelPath   = if ($env:MODEL_FILE)       { $env:MODEL_FILE }       else { Join-Path $RepoRoot ".downloads\Qwen3-8B-Q4_K_M.gguf" }
$LlamaServer = if ($env:LLAMA_SERVER_DIR) { Join-Path $env:LLAMA_SERVER_DIR "llama-server.exe" } else { Join-Path $RepoRoot ".downloads\llama\vulkan\llama-server.exe" }

Test-Path $ModelPath; Test-Path $LlamaServer   # 都应返回 True

& $LlamaServer -m $ModelPath -c 8192 -ngl 99 --host 127.0.0.1 --port 11435 --jinja --no-webui
```

> 本节出现的 `MODEL_FILE` / `LLAMA_SERVER_DIR` / `SHIM_PATH` 只是**启动脚本的约定变量**（本文件定义），
> 项目代码只读第 5 节的 `P07_*` 变量；没有这些变量时按默认相对路径走。

- `-ngl 99` 表示全部层放 GPU；无 GPU 时改 `-ngl 0`（CPU 会慢很多，**本机未验证**）；
- 首次加载模型约 8 秒（历史记录），加载完再启兼容层；
- 只监听 `127.0.0.1:11435`。

### 3.3 启动兼容层（仓库外脚本）

```powershell
$Shim = if ($env:SHIM_PATH) { $env:SHIM_PATH } else { Join-Path (Split-Path $RepoRoot -Parent) "travel-agent-run\ollama_shim.py" }
& ".\.venv\Scripts\python.exe" $Shim
```

兼容层对外提供 `127.0.0.1:11434` 的 `/api/chat`、`/api/tags`、`/api/version`。
没有这份脚本时，自己写一个最小转发（Ollama `/api/chat` → llama.cpp `POST /v1/chat/completions`，逐行透传流式 token）即可；
或者直接用方式 A，跳过兼容层。

### 3.4 验收

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/version" -UseBasicParsing | Select-Object -ExpandProperty Content
# 方式 B 期望 {"version":"0.0.0-llama.cpp-shim"}；方式 A 期望正常版本号

Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing | Select-Object -ExpandProperty Content
# 期望 200 且包含 qwen3:8b

(Invoke-WebRequest -Uri "http://127.0.0.1:11435/props" -UseBasicParsing).Content | ConvertFrom-Json | Select-Object model_path, n_ctx, total_slots
& $LlamaServer --version   # 期望 version: 1.0.0-dev (build 12359, commit b1b770d90)
```

### 3.5 端口冲突（本机真实踩坑）

2026-11-15 采基线时，本机同时存在**两组** `python.exe` 在跑 `ollama_shim.py` / `run_web.py`：
`.venv` 的 PID 17508/33772 与系统 Python 3.11 的 PID 46772/30800；
**实际持有 11434 与 5000 监听的是系统 Python 进程**。重启前先确认端口归属：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 11434,11435,5000 | Select-Object LocalPort,OwningProcess
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId,CommandLine
```

仓库外的 `travel-agent-run/start_all.ps1` / `stop_all.ps1` 可一键起停；本仓库不包含这两个脚本。

---

## 4. 端口与超时

| 端口 | 用途 | 监听 | 备注 |
|---|---|---|---|
| 11434 | Ollama `/api/chat`（方式 A 官方，或方式 B 兼容层） | `127.0.0.1` | 项目默认地址 |
| 11435 | llama.cpp OpenAI 兼容 API | `127.0.0.1` | 仅方式 B |
| 5000 | P7 Flask 网页；应用在 `analysis/p07_agent/src/web_app.py`，本机用仓库外 `run_web.py` 启动（关闭 debug reloader） | `127.0.0.1` | 验收入口 |

超时（以代码为准，`analysis/p07_agent/src/*.py`）：

| 层 | 值 | 位置 |
|---|---|---|
| 单次模型调用 | **180 s** | `urlopen(..., timeout=180)`，共 8 处（intent_parser 1 / tool_decider 1 / tool_selector 1 / constraint_checker 1 / condition_selector 3 / route_planner 1） |
| 输出上限 | 1200 token（普通）/ 1800 token（路线） | `P07_MAX_TOKENS` / `P07_ROUTE_MAX_TOKENS` |
| 上下文 | 8192 | `P07_ROUTE_NUM_CTX` 与 llama.cpp `-c 8192` |

实测历史（**非本次复测**，见 `travel-agent-run/README.md`）：单次完整查询约 33–158 秒；
因此任何客户端/反向代理的读超时都应 ≥180 秒，不要设 30 秒。

---

## 5. 项目侧配置（只用环境变量，不写 .env）

程序读取**进程环境变量**，不自动加载 `.env`；`.env` 与 `.env.*` 已被 `.gitignore` 排除（`.env.example` 除外）。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `P07_OLLAMA_URL` | `http://localhost:11434/api/chat` | 指向方式 A 或方式 B 暴露的 `/api/chat` |
| `P07_OLLAMA_MODEL` | `qwen3:8b` | 模型名；官方 Ollama tag 不同就改这里 |
| `P07_MAX_TOKENS` | `1200` | 意图/理由等调用的输出上限 |
| `P07_ROUTE_MAX_TOKENS` | `1800` | 路线 JSON 的输出上限 |
| `P07_ROUTE_NUM_CTX` | `8192` | 路线 prompt 的上下文预算 |
| `P07_SESSION_DIR` | 未设置 | 会话轨迹目录；不设置时落到仓库外的可写目录，避免把用户原话提交进仓库 |

示例（PowerShell，当前终端生效）：

```powershell
$env:P07_OLLAMA_URL   = "http://127.0.0.1:11434/api/chat"
$env:P07_OLLAMA_MODEL = "qwen3:8b"
```

**不要在 `runtime/` 或任何提交物里放 API key / cookie / 登录态**；本地 Ollama 方案不需要密钥。

---

## 6. 模型权重不入库 + 校验命令

- 模型 5 GB，超过仓库 50 MB 上限，**禁止提交**；
- 本机 `.downloads/` 仅在 `.git/info/exclude` 中排除，**该文件不入库**，所以干净 clone **不会**忽略 `.downloads/`。
  在新机器上请二选一：
  1. 把权重放在仓库**外**（推荐），用 `MODEL_FILE` 指过去（该变量只被本文 3.2 的启动脚本读取）；
  2. 或在本机 `.git/info/exclude` 追加 `.downloads/`，并且**永远不要 `git add .` / `git add -A`**。

校验（Windows）：

```powershell
$ModelPath = Join-Path (git rev-parse --show-toplevel) ".downloads\Qwen3-8B-Q4_K_M.gguf"
(Get-Item $ModelPath).Length                                   # 5027783488
(Get-FileHash -Algorithm SHA256 $ModelPath).Hash               # D98C...5785
```

校验（Linux/macOS）：

```bash
stat -c '%s' Qwen3-8B-Q4_K_M.gguf      # 5027783488（macOS: stat -f '%z'）
sha256sum Qwen3-8B-Q4_K_M.gguf         # d98c...5785
```

确认没有被误加入索引：

```powershell
git status --porcelain          # 不应出现 .downloads/
git ls-files .downloads         # 应为空
```

---

## 7. 验收清单（换机后逐条打勾）

- [ ] `GET /api/tags` 返回 200，包含 `qwen3:8b`，size 与第 1 节一致（或已记录新值）
- [ ] `GET /api/version`（方式 A 正常版本；方式 B `0.0.0-llama.cpp-shim`）
- [ ] `llama-server --version` 为 `1.0.0-dev (build 12359, commit b1b770d90)`（方式 B）
- [ ] 模型文件 SHA256 与第 1 节一致
- [ ] 11434/11435/5000 只监听 `127.0.0.1`
- [ ] `git ls-files .downloads` 为空（权重未入库）
- [ ] 不跑模型也能过门禁：`python checks/check_agent.py analysis/p07_agent` 与
      `python -m unittest discover -s analysis/p07_agent/tests`（CI 即按此设计，见 `.github/workflows/ci.yml`）

---

## 8. 已知限制 / 回滚

- 方式 B 的兼容层是**仓库外**脚本，仓库内没有它的副本；T5.3（干净 clone 一条命令）若要覆盖推理后端，需要把它纳入 `scripts/` 或提供等价最小实现。
- 官方 Ollama 的 `qwen3:8b` 与本机 GGUF 不保证逐字节一致；输出不会完全相同，指标比较必须同机同摘要。
- 8 GB 显存下 8K 上下文约占 6.3 GB，多人并发会排队（`total_slots=4`）。
- 回滚：删掉本文件不影响任何代码；推理后端切换只改 `P07_OLLAMA_URL` / `P07_OLLAMA_MODEL` 两个环境变量。
