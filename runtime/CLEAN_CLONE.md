# 干净 clone 一条命令（T5.3）

> 角色：D4 收口验证（T5.3）｜最后更新：2026-11-16
> 目的：证明「换一台机器 clone 仓库后，一条命令能复跑出与提交一致的检查 / 测试结果」。
> 本文数字全部来自 **2026-11-16 15:27 用最终脚本的实跑**，与结果 JSON 一一对应；
> 更早的旧版运行单独列在第 5 节，**不混用、不冒充首次**。

---

## 0. 结论

在 Windows 11 + Windows PowerShell 5.1 上，从仓库根执行 1 条命令，把当前分支 HEAD 克隆到**仓库外空目录**、
建独立 venv、按 `requirements.lock` 安装，然后跑 9 个 check + 327 个 p07 单测 + 17 个 eval schema 测试：

- 退出码 **0**，`verdict: pass`
- checks **9/9**、`tests.ran = 327`、`eval_schema.ran = 17`
- `timing.total_seconds = 67.99`（上限 900s）
- 全过程**不依赖 GPU、模型权重、运行中的模型服务**（本次未启动 Ollama / llama.cpp，11434 端口未使用）

---

## 1. 环境与现场（本次实跑）

| 项 | 值 |
|---|---|
| 日期 / 时段 | 2026-11-16 15:27:17 – 15:28:27（+08:00） |
| 仓库 | `E:\ProgramProject\travel-agent` |
| 分支 | `agent/d4-hardening` |
| 提交（本次验证的 HEAD） | `58f29120c80e13bf96857ef68a36a77768da0a6f` |
| 代码树 tree | `6c3e48bd8e9d2ff2d9b21e76561a9b8946aa34f9` |
| 操作系统 | Microsoft Windows 11 专业版 build 26200 64-bit |
| PowerShell | 5.1.26100.9711（Desktop，`C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`） |
| Git | 2.51.2.windows.1 |
| Python | 3.11.9（`C:\WINDOWS\py.exe -3.11` 创建 venv；venv 内 pip 24.0） |
| 克隆目录 | `C:\Users\HappinessJo\AppData\Local\Temp\clean_clone_t53_final`（仓库外、实跑前为空） |
| 结果 JSON | `...\clean_clone_t53_final\clean_clone_result.json` |
| 运行日志 | `...\clean_clone_t53_final\clean_clone_check.log` |

> 本次实跑针对提交 `58f2912`。随后 `runtime/clean_clone_check.ps1` 与本文一并提交、HEAD 前移；
> `runtime/` 下的脚本与文档不是 9 个 check / 327 个测试的输入，门禁口径不变。

---

## 2. 一条命令（原文）

在仓库根执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File runtime\clean_clone_check.ps1 -WorkDir C:\Users\HappinessJo\AppData\Local\Temp\clean_clone_t53_final -OutJson C:\Users\HappinessJo\AppData\Local\Temp\clean_clone_t53_final\clean_clone_result.json
```

- 退出码：**0**
- 换机器时只改 `-WorkDir` / `-OutJson` 两个路径；`-WorkDir` **必须位于仓库外，且不存在或为空目录**，
  脚本会先做这项校验，非空直接失败。
- 只想校验参数、不执行（约 2s）：

```powershell
powershell -NoProfile -File runtime\clean_clone_check.ps1 -DryRun
```

本次 DryRun 退出码 0，解析出的执行计划与上面一致（clone → venv → pip install → pip check → 9 checks → tests → eval）。

---

## 3. 实测数字（来自本次结果 JSON）

| 指标 | 实测值 | JSON 字段 |
|---|---|---|
| 进程退出码 | 0 | — |
| 判定 | `pass` | `verdict` |
| 门禁项 | **9 / 9**，全部 exit 0 | `checks_passed` / `checks_total` |
| p07 单元测试 | **327** ran（下限 327），`OK` | `tests.ran` |
| eval schema 测试 | **17** ran（下限 17），`OK` | `eval_schema.ran` |
| clone → tests 总耗时 | **67.99 s** | `timing.total_seconds` |
| 脚本总耗时（含 preflight / 汇总） | 69.61 s | `timing.script_total_seconds` |
| 外部墙钟（调用方计时） | 69.96 s | — |
| 耗时上限 | 900 s | `timing.max_seconds` |
| clone 文件数 | 348 | `clone.files` |
| clone 后 HEAD / tree 与源一致 | true / true | `clone.head`、`clone.tree_matches_source` |
| clone 后 git 状态 | clean（空） | `clone.status_porcelain` |
| lock 校验 | 34 / 34 pin 命中，missing 0、mismatch 0 | `install.lock_pins_verified` |
| `pip check` | exit 0，`No broken requirements found.` | `pip_check` |
| 仓库事后状态 | clean（空） | `post_status_clean` |

### 3.1 各阶段耗时

| 阶段 | 秒 | 说明 |
|---|---:|---|
| preflight（参数 / 源仓库 / 解释器探测） | 1.62 | 不含在 clone→tests 总耗时内 |
| clone | 1.48 | `git clone --branch agent/d4-hardening --single-branch --no-hardlinks`，本地路径源 |
| venv | 7.80 | Python 3.11.9，隔离 venv |
| install | **50.70** | `pip install -r requirements.lock`，**cache hits 67 / downloads 0** |
| pip check | 0.74 | 依赖自洽检查 |
| checks（9 项合计） | 0.91 | 单项 0.08–0.12 s |
| p07 unittest | 2.31 | `Ran 327 tests in 1.751s` |
| eval schema | 0.18 | `Ran 17 tests in 0.006s` |
| **合计（clone→tests）** | **67.99** | 脚本总耗时 69.61 s |

### 3.2 9 个 check（全部 exit 0）

| # | 检查 | 命令参数 | exit | 秒 |
|---|---|---|---:|---:|
| 1 | P1 changlong | `checks/check_scenic.py scenic/changlong/data/processed/changlong_guides.csv` | 0 | 0.11 |
| 2 | P1 baiyunshan | `checks/check_scenic.py scenic/baiyunshan/data/processed/baiyunshan_guides.csv` | 0 | 0.12 |
| 3 | P1 wugongshan | `checks/check_scenic.py scenic/wugongshan/data/processed/wugongshan_guides.csv` | 0 | 0.10 |
| 4 | P2 entities | `checks/check_entities.py` | 0 | 0.10 |
| 5 | P3 routes | `checks/check_routes.py` | 0 | 0.09 |
| 6 | P4 coref | `checks/check_coref.py` | 0 | 0.09 |
| 7 | P5 conditions | `checks/check_conditions.py` | 0 | 0.08 |
| 8 | P6 graph | `checks/check_graph.py analysis/p06_graph/outputs` | 0 | 0.09 |
| 9 | P7 agent | `checks/check_agent.py analysis/p07_agent` | 0 | 0.11 |

标准输出末尾（原样摘录）：

```text
checks         : 9/9 exit 0（0.91s）
p07 unittest   : 327 tests（min 327）, exit 0（2.31s）
eval schema    : 17 tests（min 17）, exit 0（0.18s）
阶段耗时(s)    : clone=1.48 venv=7.8 install=50.7 pipcheck=0.74 checks=0.91 tests=2.31 eval=0.18
总耗时         : 67.99s / 上限 900s
判定           : PASS
```

---

## 4. 环境假设

1. **Python 3.11.x 必须可用**。脚本优先用 `py -3.11`，其次 `python`（并要求版本为 3.11.x），都没有则
   fail-fast；也可用 `-Python <exe>` 显式指定。本次为 3.11.9。
2. **pip 能装 `requirements.lock`**。本次 `cache hits 67 / downloads 0`，34 个 pin 全部命中本机 pip 缓存，
   **没有实际走 PyPI 网络**；换到无缓存机器时需要能访问 PyPI（或内网镜像），install 耗时会明显变长。
3. **Git 可用，分支 `agent/d4-hardening` 存在**。clone 源是本地仓库路径 + `--no-hardlinks`，
   因此**不需要 GitHub 网络**；但要求 `.git` 完整。若从远程 clone，clone 阶段耗时取决于网络，本表 1.48s 不适用。
4. **`-WorkDir` 在仓库外，且不存在或为空目录**；脚本会拒绝仓库内路径、仓库上级目录和非空目录。
5. **磁盘与权限**：需在 `%TEMP%` 下写约 1 个 venv（含 34 个包）+ 一份克隆；本次正常。
6. **不依赖 GPU / 模型权重 / 运行中服务**：327 个 p07 测试为单测，2.31s 跑完；本次未启动 Ollama / llama.cpp。
7. **不提交 `.venv`、pip 缓存、克隆目录**：它们只存在于 `%TEMP%` 的克隆目录内，`.gitignore` 已忽略
   `.venv/`、`__pycache__/`；脚本事后确认源仓库 `git status` 为空（`post_status_clean=true`）。

---

## 5. 首次旧版 vs 最终版本次（分开记录）

同一天更早的运行使用的是**最终脚本最后一版（14:11:42）之前**的版本，只作历史对照，**不是本次验收证据**：

| 运行 | 脚本版本 | 起止（+08:00） | clone→tests | checks | p07 tests | eval | 说明 |
|---|---|---|---:|---|---:|---:|---|
| 旧版第 1 次 | 14:11:42 之前 | 14:07:37 – 14:09:10 | **90.88 s** | 9/9 | 327 | 17 | 首次；install 69.97 s |
| 旧版第 2 次 | 14:11:42 之前 | 14:09:49 – 14:11:12 | **81.15 s** | 9/9 | 327 | 17 | install 61.5 s |
| **最终版（本次）** | **14:11:42，38367 B** | **15:27:17 – 15:28:27** | **67.99 s** | **9/9** | **327** | **17** | **★ 本次验收证据** |

要点：

- **首次（旧版）是 90.88 s，最终版本次是 67.99 s**，两者分开写；67.99 s 不是首次成本。
- 差异主要来自 install 阶段（69.97 s → 50.70 s），三次均为 `cache hits 67 / downloads 0`，
  波动来自本机磁盘 / 杀软 / 进程负载，不是代码差异。
- 另有一次 14:11:51–14:13:10 的预提交复跑（同一最终脚本，total 76.89 s，同样 9/9、327、17），
  本次 15:27 为提交前最终复核，以本次 67.99 s 为准。
- 三次历史 JSON 均与本次同样 `verdict=pass`，但只有本次对应当前最终脚本，且是唯一写入本文的数字来源。

---

## 6. 限制与已知失败模式（如实）

1. **本机 `pwsh` 不在 PATH**，所有命令必须用 Windows PowerShell 5.1 的 `powershell`；
   PowerShell 7（`pwsh`）未在本机验证，不要写成 `pwsh`。
2. **脚本只验证提交后的状态**：未跟踪 / 未提交的工作区改动不会进入 clone。本次运行时
   `runtime/clean_clone_check.ps1` 尚未提交，所以克隆树里没有它——这不影响门禁（脚本本身不参与 checks / tests），
   提交之后第三方即可直接在 clone 中运行。
3. **install 是主要成本（50.7 s / 68 s）**，且依赖 pip 缓存或网络；冷缓存机器会更慢，
   但仍应远低于 900 s 上限。
4. **仅 Windows 验证**：依赖 `py` 启动器、`.venv\Scripts\python.exe` 和 PowerShell；
   未在 Linux / macOS 验证。
5. **`-ExecutionPolicy Bypass`** 仅用于绕过脚本执行策略限制；策略允许时省略也可。
6. **门禁不等于模型质量验证**：它证明「干净 clone 能复跑 checks / tests」，不评估 p07 回答质量，
   也不覆盖运行时模型（见 `runtime/README.md`）。
7. 本次单机配置（AMD Ryzen 5 7500F / 31.6 GB RAM）下 67.99 s；其他机器数字会不同，以本机 JSON 为准。

---

## 7. 复跑 / 验收清单

```powershell
# 1) 确认机器上有 Python 3.11 与 git
py -3.11 --version
git --version

# 2) 参数自检（不执行）
powershell -NoProfile -File runtime\clean_clone_check.ps1 -DryRun

# 3) 实跑（WorkDir 换成仓库外的空目录）
powershell -NoProfile -ExecutionPolicy Bypass -File runtime\clean_clone_check.ps1 `
  -WorkDir C:\Users\<you>\AppData\Local\Temp\clean_clone_t53_final `
  -OutJson C:\Users\<you>\AppData\Local\Temp\clean_clone_t53_final\clean_clone_result.json

# 4) 看判定
(Get-Content ...\clean_clone_result.json -Raw -Encoding UTF8 | ConvertFrom-Json) |
  Select-Object verdict, checks_passed, checks_total, @{n='tests';e={$_.tests.ran}}, @{n='eval';e={$_.eval_schema.ran}}, @{n='total';e={$_.timing.total_seconds}}
```

通过标准（与本次一致）：`verdict=pass`、`checks_passed=9`、`tests.ran=327`、`eval_schema.ran=17`、
`timing.total_seconds < 900`。
