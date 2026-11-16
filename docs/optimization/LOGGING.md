# P7 应用日志与可观测性（T5.1）

> 状态：D4 / T5.1 落地｜最后更新：2026-11-16
> 代码：`analysis/p07_agent/src/observability.py`；Web 接线：`analysis/p07_agent/src/web_app.py`
> 合成样例：`runtime/logging_sample.jsonl`（**不是真实请求**）

---

## 0. 一句话

P7 的每个 Web 请求和后台任务都有唯一 `request-id`；请求/任务结束写一行 JSONL，
记录耗时、状态、错误类型和**模型交互次数的事件近似值**。日志只保留 query 的
SHA256 前缀与长度，绝不记录用户原文、表单、`trace_json`、cookie 或密钥。

---

## 1. 边界（先读）

1. **这是应用运行日志，不是模型对话记录。** 它只回答“哪个请求、多久、什么状态、
   错在哪类、调了几次模型”，不保存用户输入或模型输出。
2. **不改变业务。** 日志是旁路：`log_event()` 内部吞掉所有异常，日志目录不可写、
   轮转失败、JSON 序列化失败都不会改变路由、状态判定、303 跳转或页面渲染。
3. **与 `trace_log.py` 的 `SessionTrace` 是两套东西。** `SessionTrace` 是受控调试
   会话记录，会把 `user_request` 等调试信息写到仓库外的 `P07_SESSION_DIR`
   （默认 `<repo>/../p7_agent_sessions`），用于复现工具调用链；它不是应用日志，
   本任务没有新增第二份“用户原文日志”，也没有修改它的行为。**不要把会话目录
   或应用日志目录提交进仓库。**
4. **模型交互次数是事件近似值**，定义见第 5 节；不能当作 provider 账单级精确值。

---

## 2. 目录、轮转与保留期

| 项 | 默认值 | 说明 |
|---|---|---|
| 日志目录 | `<repo>/../p7_agent_logs` | 仓库**外**同级目录；本机即 `E:\ProgramProject\p7_agent_logs` |
| 覆盖变量 | `P07_LOG_DIR` | 指向其他可写目录；若解析后落在仓库内，**跳过并回退**到仓库外默认目录 |
| 文件名 | `p07_app.jsonl` | 一行一个 JSON 对象 |
| 轮转 | UTC 午夜 | 标准库 `TimedRotatingFileHandler(when="midnight", utc=True)` |
| 保留期 | 7 天 | `backupCount = retention_days`；`P07_LOG_RETENTION_DAYS` 可覆盖 |
| 单文件上限 | 10 MiB | 超过即提前轮转；`P07_LOG_MAX_BYTES` 可覆盖 |

实现里用 `SizeCappedTimedRotatingFileHandler` 在标准库时间轮转之外补了体积上限，
仍是标准库实现，没有新增第三方依赖。备份文件形如 `p07_app.jsonl.2026-11-16`。

代码内也可显式配置（测试即如此）：

```python
import observability
observability.configure_logging(
    log_dir=r"D:\p7_logs", retention_days=3, max_bytes=4096)
print(observability.logging_status())
```

`logging_status()` 返回实际目录、`when`、`backup_count`、`max_bytes`、`utc`，
排错/验收时不用猜 handler 参数。

---

## 3. 事件与字段

每条日志的公共字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts` | string | UTC ISO8601，毫秒精度，以 `Z` 结尾 |
| `level` | string | `debug/info/warning/error/critical`，当前默认 `info` |
| `event` | string | 事件名，见下表 |
| `request_id` | string | 服务端生成时为 32 位十六进制；客户端传入合法自定义值时为 8–64 位 `[A-Za-z0-9-]`；无上下文时为 `-` |

### 3.1 `http_request`（每个 HTTP 响应一条，`after_request`）

| 字段 | 说明 |
|---|---|
| `method` | `GET/POST/...` |
| `path` | 仅 URL path（如 `/`、`/run/<job_id>`），**不含 query string** |
| `status` | HTTP 状态码（303、200、404、500…） |
| `duration_ms` | 从 `before_request` 到响应生成的墙钟毫秒，int |
| `error_type` | 正常为 `null`；异常为异常类名（如 `RuntimeError`）；无信号的 5xx 为 `internal_error` |
| `query_sha256_12` | query 的 SHA256 前 12 位；无 query 为 `null` |
| `query_len` | query 的 Unicode 字符数；无 query 为 `0` |

### 3.2 `job_started` / `job_finished`（后台任务线程）

| 字段 | 说明 |
|---|---|
| `job_id` | 32 位任务 id（与 `/run/<job_id>` 一致） |
| `request_id` | 与创建该任务的 POST 请求相同 |
| `duration_ms` | 任务从线程开始到结束的毫秒（`job_finished`） |
| `status` | `done` / `error`（与 `_job_finish` 的任务状态一致） |
| `result_status` | 业务四值：`verified/partial/clarify/error`（只观测，不参与判定） |
| `model_calls` | 模型交互次数的**事件近似值**，int，定义见第 5 节 |
| `model_calls_known` | `false` 仅出现在任务抛异常、拿不到 trace 时；此时 `model_calls=0` 不代表真的没调用 |
| `error_type` | 正常 `null`；异常为异常类名；业务 `error` 为 `agent_error` |
| `error_code` | 业务 `error` 时的原因码（如 `model_error`），否则 `null` |
| `query_sha256_12` / `query_len` | 与请求事件同一口径，便于关联而不用原文 |

### 3.3 错误路径

- 视图抛未捕获异常：Flask 的 `got_request_exception` 信号把异常类名写进 `g.error_type`，
  `after_request` 仍会写 `http_request`（`status=500`、`error_type=<类名>`、同一 `request_id`），
  响应头也带同一个 `X-Request-ID`。
- 后台任务抛异常：`job_finished` 的 `status=error`、`error_type=<类名>`、
  `model_calls_known=false`；任务状态机仍按原逻辑落 `error`，页面行为不变。
- **异常 message 不写入日志**（可能夹带用户输入），只写异常类型。

---

## 4. request-id

- 每个请求在 `before_request` 生成 `uuid4().hex`（32 位，不可猜测）。
- 如果客户端带 `X-Request-ID` 且匹配 `^[A-Za-z0-9-]{8,64}$`，则沿用；否则重新生成。
- 响应头总会写 `X-Request-ID`，便于用户/排错时把页面问题和日志对上。
- 每个请求的 id 相互独立；同一请求内的 `http_request` 与它创建的 `job_started/job_finished`
  共用同一个 id。
- 后台线程不依赖 `threading` 自动继承 `contextvars`：`_run_job()` 从任务表取出
  `request_id` 并重新 `set_request_id()`，保证任务事件与 POST 请求同 id。
- `request-id` 只用于关联日志，**不是认证凭据**，不能用来授权或识别用户。

---

## 5. 模型交互次数（`model_calls`）的定义

`observability.count_model_calls(trace_events)` 读取 `agent.run_agent()` 写入
`result["trace_json"]` 的 `trace.events`，按**已知事件类型**计数：

| trace 事件 | 计数 | 说明 |
|---|---|---|
| `intent` 或 `intent_call_error` | +1 | 意图解析最多一次模型调用；成功/失败都算一次尝试 |
| `decision` | +1 | 仅当 trace 中**没有** `fast_decision`；有 fast 分支时是确定性规则 |
| `tool_call` 且 `tool == "select_tools"` | 每个 +1 | 每轮工具选择一次模型调用（`MAX_DECISION_ROUNDS` 内可能多轮） |
| `requirement_check` | +1 | 仅当 trace 中**没有** `fast_requirement_check`；`requirement_check_fallback` 也按一次尝试计，但同一阶段不重复计 |
| `plan_check` | +1 | 仅当 trace 中**没有** `fast_plan_check`；`plan_check_fallback` 同上 |

**不计入的模型调用（重要）：**

- `condition_selector.select_conditions()` 的筛选调用和 `generate_reasons()` 的理由生成调用
  （一次条件查询最多 2 次 HTTP 请求）没有逐次写入 trace；
- `route_planner.plan_route()` 的首次规划、失败后重规划以及可能的二次 `plan_route`
  （每次 1–2 次 HTTP 请求）也没有逐次写入 trace。

因此 `model_calls` 是**可复核的事件近似值 / 下限**，用于观察“这次请求大概调了几次模型、
是否走了 fast 路径”，**不是 provider 账单级精确值**，不能用于计费或对外承诺。
需要精确值时，应在每个模型调用点统一埋点（本任务不做，避免改动业务调用链）。

> 位置说明：POST 在模型运行前就返回 303，所以 `model_calls` 只出现在
> `job_finished`（任务结束时才有 trace）；`http_request` 记录请求本身的
> `duration_ms/status/error_type`，不强行填一个当时还不存在的模型次数。

---

## 6. 隐私边界：日志里绝不会出现什么

- 用户 query 原文、追问拼接后的原文；
- query string、表单字段原文、`request.form` / `request.args` 原文；
- `trace_json`、`trace.events`、模型输入/输出、路线明细；
- cookie、session、`Authorization`、`X-API-Key`、环境变量中的密钥；
- 异常 message / 堆栈（只记异常类型）。

只保留：

- `query_sha256_12`：query 的 SHA256 十六进制前 12 位；
- `query_len`：query 的 Unicode 字符数；
- `path`：不含 query string 的 URL path。

`log_event()` 还有一层防御：即使调用方误传 `query`、`user_text`、`trace_json`、
`cookie`、`authorization`、`token`、`api_key` 等字段，也会被丢弃，并在该行写
`redacted_fields`，避免“新代码顺手把原文塞进日志”。

合成样例 `runtime/logging_sample.jsonl` 只含哈希/长度，**没有任何真实用户原文**；
它由人工构造并标注为合成样例，不是从真实日志拷贝的。

---

## 7. 排错

在仓库根执行（PowerShell）：

```powershell
# 1) 看当前配置
& .\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'analysis/p07_agent/src'); import observability; print(observability.logging_status())"

# 2) 看最近事件
Get-Content ..\p7_agent_logs\p07_app.jsonl -Tail 20

# 3) 按 request-id 关联（页面响应头的 X-Request-ID）
Select-String -Path ..\p7_agent_logs\p07_app.jsonl -Pattern '"request_id":"<32位id>"'

# 4) 按 job_id 关联
Select-String -Path ..\p7_agent_logs\p07_app.jsonl -Pattern '"job_id":"<32位id>"'

# 5) 确认日志里没有 query 原文（应无输出）
Select-String -Path ..\p7_agent_logs\p07_app.jsonl -Pattern '<要检查的 query 原文>'
```

常见问题：

- **没有日志文件**：handler 是 `delay=True`，第一次 `log_event` 才建文件；先发一个请求。
  也可能是 `P07_LOG_DIR` 不可写，此时会回退默认目录；`logging_status()` 显示实际目录。
- **日志目录在仓库里**：实现会跳过仓库内路径并回退仓库外默认目录；
  若自定义目录仍被判定在仓库内，检查 `is_within_repo()` 的解析结果。
- **轮转/保留期不符合预期**：`logging_status()["backup_count"]`、`["max_bytes"]`、
  `["when"]` 是实际 handler 参数；环境变量只影响下一次配置（进程启动时生效）。
- **多进程部署**：每个进程各自持有 handler，写同一个文件可能交错；需要汇总时
  让每个进程写不同 `P07_LOG_DIR`，或换集中式日志系统（本任务不引入）。

---

## 8. 测试与验收

```powershell
$env:PYTHONIOENCODING='utf-8'
& .\.venv\Scripts\python.exe -m unittest analysis.p07_agent.tests.test_observability -q
& .\.venv\Scripts\python.exe -m unittest discover -s analysis\p07_agent\tests -q
& .\.venv\Scripts\python.exe checks\check_agent.py analysis\p07_agent
```

`tests/test_observability.py` 覆盖：

- request-id 每次不同、响应头存在、非法客户端 id 被拒绝；
- 请求/任务日志共享 request_id，`job_finished` 的 `model_calls` 是 int；
- 错误路径（500、后台任务异常）有 request_id 与 error_type；
- 日志中不出现 query 原文，只有 `query_sha256_12` / `query_len`；
- 默认目录在仓库外、`P07_LOG_DIR` 生效、仓库内路径回退；
- `when/backup_count/max_bytes` 可断言，且小上限确实触发轮转；
- 原有 303 + 进度页契约不被破坏。

---

## 9. 已知限制

1. **模型计数是下限**：见第 5 节，条件筛选/路线规划的内部调用未逐次入 trace。
2. **体积轮转的日期后缀**：沿用 `TimedRotatingFileHandler` 的日期命名；同一天内多次
   触发体积轮转可能复用同名备份，极端情况下互相覆盖。保留期仍按 `backupCount`。
3. **单进程假设**：进程内 handler 不跨进程协调；多 worker 写同一文件会交错/轮转竞争。
4. **没有指标导出/链路追踪**：只有 JSONL；没有 Prometheus、OpenTelemetry 等（不新增依赖）。
5. **耗时口径**：`http_request.duration_ms` 是请求级墙钟，`job_finished.duration_ms` 是
   任务线程级墙钟；都不是单次模型调用的延迟，也不包含浏览器渲染时间。
6. **客户端可伪造 `X-Request-ID`**：只用于日志关联；不参与鉴权、限流或业务判断。
