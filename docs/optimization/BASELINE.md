# D0 基线快照（T0.1）

> 角色：OPS｜分支：`agent/d0-foundation`｜采样时间：2026-11-15 15:35–15:40 +08:00（Asia/Shanghai）
> 口径：**只有退出码为 0 才写“通过”**；本文件所有数字均来自本次实际命令输出，未运行的项写“未测”。
> 用途：供后续所有任务对照；任何指标变化都应与本基线比较，而不是与口头描述比较。

---

## 1. 基线提交

| 项 | 值 |
|---|---|
| 分支 | `agent/d0-foundation`（父 Agent 创建，本任务未新建/切换分支） |
| 基线 commit | `f872270c227ba664df9bc8723d655ebb180b0de1`（`f872270 P7: 补强约束闭环、分时行程与证据记录`） |
| 开工时 `git status --porcelain` | 空输出（工作区干净，exit 0） |
| 远端 | `origin https://github.com/donk-leo/travel-agent.git`（本任务**未 push**） |
| 本任务新增提交 | 见本任务报告（commit 信息 `D0/T0.1: 基线、CI 与运行时锁定`） |

---

## 2. 环境

| 项 | 实测值 |
|---|---|
| OS | Microsoft Windows 11 专业版，build 10.0.26200.0，AMD64 |
| CPU / 内存 | AMD Ryzen 5 7500F（6 核 / 12 线程）/ 31.6 GB |
| Python | **3.11.9**（CPython，MSC v.1938 64 bit AMD64），解释器 `.\.venv\Scripts\python.exe` |
| pip | **26.3**（`.venv` 内） |
| git | 2.51.2.windows.1 |
| GPU | NVIDIA GeForce RTX 4060，8188 MiB，驱动 610.88（查询时已用 6460 MiB，模型在显存中） |
| venv 包数 | 34（与 [requirements.lock](../../requirements.lock) 逐条一致） |

---

## 3. 九项 checks（9/9 退出码 0）

工作目录：仓库根；解释器：`.\.venv\Scripts\python.exe`。耗时含 Python 进程启动。

| # | 命令 | 退出码 | 耗时 | 关键输出（原文摘录） |
|---|---|---|---|---|
| 1 | `python checks/check_scenic.py scenic/changlong/data/processed/changlong_guides.csv` | 0 | 0.16s | 记录数 8，类型 `{'游客游记': 5, '官方路线': 3}`，无效 0，官方 3 / 有效游记 5 |
| 2 | `python checks/check_scenic.py scenic/baiyunshan/data/processed/baiyunshan_guides.csv` | 0 | 0.11s | 记录数 7，类型 `{'站点攻略': 1, '游客游记': 3, '官方路线': 3}`，无效 0，官方 3 / 有效游记 4 |
| 3 | `python checks/check_scenic.py scenic/wugongshan/data/processed/wugongshan_guides.csv` | 0 | 0.10s | 记录数 14，类型 `{'官方路线': 6, '游客游记': 8}`，无效 1，官方 6 / 有效游记 7；**1 条警告**：第 11 行（WGS-T-04）`clean_content` 仅 33 字，偏短（已标无效，可保留） |
| 4 | `python checks/check_entities.py` | 0 | 0.09s | 1006 条实体；类型 `{'TIME': 248, 'POI': 573, 'TRANSPORT': 185}`；景区 `{'CL': 266, 'BYS': 232, 'WGS': 508}` |
| 5 | `python checks/check_routes.py` | 0 | 0.08s | 35 条路线 / 226 个步骤；时间层级 `{'上午': 16, '中午': 11, '下午': 17, '晚上': 3, '未知': 179}`；`time_source` `{'explicit': 47, 'absent': 179}` |
| 6 | `python checks/check_coref.py` | 0 | 0.08s | 140 条消解结果；已消解 28/140；方法 `{'rule_nearest': 140}`；人工标注 20 条 |
| 7 | `python checks/check_conditions.py` | 0 | 0.08s | 36 条条件-建议；类型 `{'交通': 4, '时间': 13, '人群': 13, '体力': 2, '天气': 3, '预算': 1}`；景区 `{'广州白云山': 8, '武功山': 16, '长隆': 12}` |
| 8 | `python checks/check_graph.py analysis/p06_graph/outputs` | 0 | 0.08s | 节点 229 / 边 523；节点类型 `{'SCENIC_AREA': 3, 'POI': 141, 'TRANSPORT': 8, 'ACTIVITY': 12, 'TIME': 32, 'CONDITION': 33}`；边类型 `{'AT_TIME': 47, 'BY_TRANSPORT': 118, 'CONTAINS': 153, 'HAS_CONDITION': 33, 'NEXT': 165, 'SIMILAR_TO': 7}`；最大连通分量 229/229（100%） |
| 9 | `python checks/check_agent.py analysis/p07_agent` | 0 | 0.09s | 会话轨迹 11 个文件，共 152 步 |

汇总：**9 项全部退出码 0，`[错误]` 0 条，`[警告]` 1 条（第 3 项 WGS-T-04）**。9 项脚本执行累计约 0.87s（不含人工操作）。

---

## 4. 离线测试（72 条）

```
.\.venv\Scripts\python.exe -m unittest discover -s analysis\p07_agent\tests -v
```

| 项 | 值 |
|---|---|
| 退出码 | **0** |
| 末尾原文 | `Ran 72 tests in 0.374s` / `OK` |
| `... ok` 行数 | 64（其余因控制台宽度折行，未以 `... ok` 结尾；条数以 `Ran 72 tests` 行为准） |
| FAIL / ERROR 行数 | 0 |
| 墙钟耗时 | 0.78s |

> 测试通过 mock 替换 `urllib.request.urlopen`，**不访问模型、不需要 GPU、不需要网络**（`analysis/p07_agent/tests/test_route_optimization.py` 中 `fake_model`），因此可以进 CI。

---

## 5. 模型运行时（本机实测取证）

本机**没有安装官方 Ollama**：`ollama` 不在 PATH（`Get-Command ollama` 无结果），`ollama --version` 无法执行。
实际运行的是 **llama.cpp（Vulkan 构建）+ 一个 Ollama `/api/chat` 兼容层**，详见 `travel-agent-run/README.md`（该目录**不在本仓库内**）。下面的摘要名不是官方 Ollama registry digest，而是兼容层自报的本地标识，**不可当作可拉取的模型名**。

| 项 | 实测值 | 取证方式 |
|---|---|---|
| Ollama 兼容层 | `http://127.0.0.1:11434`，version `0.0.0-llama.cpp-shim` | `GET /api/version` |
| 模型名（兼容层） | `qwen3:8b` | `GET /api/tags` |
| 模型摘要 | `digest=local-qwen3-8b-q4_k_m`（本地标识，非官方 digest） | `GET /api/tags` |
| 模型大小 | `5027783488` B（4.68 GiB） | `GET /api/tags` |
| 量化 | `Q4_K_M`（llama.cpp `model_ftype: Q4_K - Medium`） | `/api/tags`、`/props` |
| 参数量 | `8190735360`（8B 级） | `GET /props` |
| 上下文 | `n_ctx=8192`，`total_slots=4` | `GET /props` |
| llama.cpp 服务 | `http://127.0.0.1:11435`，`version: 1.0.0-dev (build 12359, commit b1b770d90)`，`built with Clang 20.1.8 for Windows x86_64` | `llama-server.exe --version`、`/props` |
| 模型文件 | `.downloads/Qwen3-8B-Q4_K_M.gguf`，**5027783488 B** | `Get-Item` |
| 模型文件 SHA256 | `D98CDCBD03E17CE47681435B5150E34C1417F50B5C0019DD560E4882C5745785` | `Get-FileHash -Algorithm SHA256` |
| 启动器 SHA256 | `38C5AFFB81C9A8F88F5538C7D11BC445E13BC46A2C6EDA05694B8B31A8D45995`（`llama-server.exe` 为 9,728 B 的 launcher，实际代码在 `llama-server-impl.dll`） | `Get-FileHash` |
| 实际启动命令 | `llama-server.exe -m <repo>\.downloads\Qwen3-8B-Q4_K_M.gguf -c 8192 -ngl 99 --host 127.0.0.1 --port 11435 --jinja --no-webui` | `Get-CimInstance Win32_Process` |
| 端口占用 | 11434 → PID 46772（`ollama_shim.py`）；11435 → PID 8260（`llama-server.exe`）；5000 → PID 30800（`run_web.py`）；均只监听 `127.0.0.1` | `Get-NetTCPConnection -State Listen` |
| 项目侧超时 | 单次模型调用 `timeout=180` 秒（`analysis/p07_agent/src/`，8 处 `urlopen(..., timeout=180)`，分布 6 个模块） | 源码 |
| 项目侧配置 | `P07_OLLAMA_URL` 默认 `http://localhost:11434/api/chat`；`P07_OLLAMA_MODEL` 默认 `qwen3:8b`；`P07_ROUTE_NUM_CTX` 默认 8192 | `analysis/p07_agent/src/config.py` |

**复现注意**：`.downloads/` 只在 `.git/info/exclude` 中排除（**该文件不入库**），因此干净 clone 不会带模型；模型权重不入库（见 [runtime/README.md](../../runtime/README.md)）。

---

## 6. 查询延迟

**未测**：本任务只做基线与离线门禁，未跑真实模型评测（避免占用 T0.3/T4.2 的评测口径与时间盒）。

可引用的历史记录（**非本次复测**，来自 `travel-agent-run/README.md` 的 2026-11-15 验收记录）：
长隆亲子+老人一日约 33–40 秒、白云山老人一日约 53 秒、武功山朋友两日约 158 秒。

> 这些数字没有写进本基线的指标栏；P50/P95 以 T4.2 runner 的输出为准。

---

## 7. 复算命令块（可直接复制运行）

```powershell
# 0) 前置：仓库根、venv
Set-Location E:\ProgramProject\travel-agent
$py = ".\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"

# 1) 基线与环境
git branch --show-current          # 期望 agent/d0-foundation
git rev-parse HEAD                 # 本文件所在提交；其父提交（本基线起点）为 f872270c227ba664df9bc8723d655ebb180b0de1
git status --porcelain             # 期望空（或仅有本任务新增文件）
& $py -VV                          # Python 3.11.9
& $py -m pip --version             # pip 26.3

# 2) 九项 checks（逐条，任何一条非 0 即为红）
& $py checks\check_scenic.py scenic\changlong\data\processed\changlong_guides.csv
& $py checks\check_scenic.py scenic\baiyunshan\data\processed\baiyunshan_guides.csv
& $py checks\check_scenic.py scenic\wugongshan\data\processed\wugongshan_guides.csv
& $py checks\check_entities.py
& $py checks\check_routes.py
& $py checks\check_coref.py
& $py checks\check_conditions.py
& $py checks\check_graph.py analysis\p06_graph\outputs
& $py checks\check_agent.py analysis\p07_agent

# 3) 离线测试（期望 Ran 72 tests ... OK）
& $py -m unittest discover -s analysis\p07_agent\tests -v

# 4) 依赖锁：应无输出差异（34 条 pin）
cmd /c ".\.venv\Scripts\python.exe -m pip freeze --exclude-editable > %TEMP%\freeze_check.txt"
Compare-Object (Get-Content requirements.lock) (Get-Content "$env:TEMP\freeze_check.txt")
& $py -m pip check                 # 期望 No broken requirements found.

# 5) 模型运行时（期望 200 + qwen3:8b）
Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing | Select-Object -ExpandProperty Content
Get-FileHash -Algorithm SHA256 .downloads\Qwen3-8B-Q4_K_M.gguf
```

---

## 8. 已知缺口（必须承认）

| # | 缺口 | 现状/证据 | 影响与后续 |
|---|---|---|---|
| 1 | **远程 CI 未验证** | [ci.yml](../../.github/workflows/ci.yml) 已写，但本任务**不能 push**；GitHub Actions 未运行 | `ci_remote=pending`。需人类 push `agent/d0-foundation` 后看 Actions 结果；本地已按同样步骤复跑通过 |
| 2 | 白云山采集脚本缺失 | `scenic/baiyunshan/src/` 无 `collect.py`（与总规划 §1 一致） | T1.1 负责；本任务不改数据 |
| 3 | 运行时未锁 | 模型权重不入库；官方 Ollama 未安装；兼容层 `travel-agent-run/ollama_shim.py` 在仓库外 | 换机需按 [runtime/README.md](../../runtime/README.md) 重装；模型摘要/SHA256 已记录，可校验但不可自动获取 |
| 4 | P4 旁支 | 28/140 消解，方法全为 `rule_nearest`，不在 P6/P7 主链路 | 按总规划 D4 冻结，不投入 |
| 5 | 测试数 72 < 目标 110 | 本任务只记录现状，不新增业务测试 | T4.5 负责补齐到 ≥110 |
| 6 | CI 依赖的会话轨迹被 `.gitignore` 忽略但已 tracked | `analysis/p07_agent/outputs/sessions/` 在 `.gitignore` 中，但 11 个 `*.jsonl` 已纳入索引（`git ls-files` 可查） | 若有人 `git rm --cached` 清理，`check_agent.py` 会红；改动前需评估 |
| 7 | 本机存在两组 Python 进程 | `.venv` 与系统 Python 3.11 各起了一份 `ollama_shim.py`/`run_web.py`；**监听 11434/5000 的是系统 Python（PID 46772/30800）** | 重启前先 `stop_all.ps1`，避免端口冲突；不影响 checks 与测试 |
| 8 | WGS-T-04 短文本 | `clean_content` 33 字，已标 `is_valid` 无效 | 不阻塞；由 DATA 决定是否补采 |
| 9 | CI 无 Windows/GPU 覆盖 | 设计上只跑离线 checks + unittest | 真实模型评测不进 CI（总规划 §5/任务板 T0.1 风险栏） |

---

## 9. 本任务产出与校验

| 文件 | 作用 | 本地校验 |
|---|---|---|
| `docs/optimization/BASELINE.md` | 本文件 | 数字逐条对应第 3/4/5 节命令输出 |
| [.github/workflows/ci.yml](../../.github/workflows/ci.yml) | 推送/PR 时跑 9 项 checks + unittest | PyYAML 解析 + 本地按步骤复跑（见下） |
| [requirements.lock](../../requirements.lock) | 34 条精确 pin | `pip freeze` 二次输出逐字节一致；干净 venv 实际安装成功（57.6s）并跑通 9/9 checks + 72 tests；`pip check` 通过 |
| [runtime/README.md](../../runtime/README.md) | 两种跑法 + 模型摘要 + 端口 + 超时 | 命令均在本机实际执行过（`/api/tags`、`--version`、`Get-FileHash`） |

- `ci.yml` 校验：仓库 venv **未安装 PyYAML**（未安装，以保持 lock 干净），改用系统 Python 3.11.9 + PyYAML 6.0.3 执行 `yaml.safe_load`，并断言 `on/jobs/permissions/env` 结构；未向 venv 安装任何新包。
- `requirements.lock` 校验（比 DoD 的 `--dry-run` 更进一步，且**不污染仓库 venv**）：
  1. 连续两次 `pip freeze --exclude-editable` 输出**逐字节一致**（`Get-FileHash` 相同）；本文件由该命令直接重定向生成，Windows 下为 CRLF 行尾，git 依 `.gitattributes`（`eol=lf`）以 LF 入库，`pip` 两种行尾都能读；
  2. 在 `%TEMP%` 新建干净 venv（仅自带 pip 24.0，Python 3.11.9）实际执行 `pip install -r requirements.lock` → **exit 0，57.6s**，`pip check` → `No broken requirements found.`；
  3. 在该干净 venv 下复跑：checks **9/9 exit 0**，unittest `Ran 72 tests in 0.436s` / `OK`，exit 0；
  4. 结构检查：34 行全部为 `name==version`（34/34），无 `file:`、`-e `、`@ ` URL、盘符路径、key/token 字样；
  5. 跨平台预检：8 个二进制依赖在 PyPI 均有 cp311 manylinux x86_64 wheel（manylinux_2_27/2_28），`jieba==0.42.1` 仅有 sdist（CI 需联网构建，属正常）。
- `ci_remote=pending`：GitHub Actions 无法在本任务内触发，需人类推送后确认。
- 回滚：四个文件均为新增，`git revert <本任务 commit>` 即可；CI 可单独 revert，lock 不兼容时回退 `requirements.txt`（任务板 T0.1 回滚栏）。
