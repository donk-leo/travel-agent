# P7 Web 安全与隐私（T5.2）

> 状态：D4 / T5.2 落地｜最后更新：2026-11-16
> 代码：`analysis/p07_agent/src/security.py`；Web 接线：`analysis/p07_agent/src/web_app.py`
> 测试：`analysis/p07_agent/tests/test_security.py`（另见 `test_progress.py` / `test_workflow.py` / `test_observability.py`）
> 相关：`docs/optimization/PRODUCT_SPEC.md` §9 N8（隐私边界）、`docs/optimization/LOGGING.md`（应用日志）

---

## 0. 一句话

P7 Web 是**本机单用户、只监听 `127.0.0.1`、无登录**的演示服务。T5.2 在不动业务判定、不引第三方依赖、不改模板的前提下，补上了四件事：默认回环绑定、服务端渲染的 CSRF token（无 JS 可用）、昂贵提交的进程内限流、以及会话/任务/轨迹的保留期说明。**它不是公网服务，也没有多租户鉴权、HTTPS 或分布式限流。**

---

## 1. 威胁模型

### 1.1 部署假设

| 项 | 假设 |
|---|---|
| 运行位置 | 本机开发/演示环境，服务只绑定 `127.0.0.1:5000` |
| 用户 | 本机单用户；没有账号、登录、角色或租户隔离 |
| 网络 | 不经过公网；默认不通过局域网访问 |
| 浏览器 | 本机浏览器；页面无 JS、无外部资源、无第三方脚本 |
| 模型 | 本机/受控模型服务，页面不接收模型密钥 |

### 1.2 主要资产

1. 用户输入的旅行需求原文（可能含同行人、儿童年龄等个人信息）；
2. 生成结果、图谱证据、会话轨迹；
3. 本机模型服务与运行环境（不希望被任意网页/脚本反复调用）；
4. 应用日志（只应有 request-id、耗时、状态、query 哈希，不含原文）。

### 1.3 值得防的威胁

| # | 威胁 | 默认缓解 |
|---|---|---|
| T1 | 服务误绑 `0.0.0.0`，被同网段其他人访问 | 显式 `host="127.0.0.1"`、`debug=False`；见 §2.1 |
| T2 | 恶意网页让本机浏览器向 `127.0.0.1:5000` 自动提交表单（CSRF / 跨站请求伪造） | 每会话 token + 服务端校验；见 §2.2 |
| T3 | 脚本/误触连续提交昂贵查询，占满本机模型 | 每 IP 每分钟固定窗口限流；见 §2.3 |
| T4 | token/query 被写进 URL、日志或独立明文 cookie | token 只放表单隐藏字段与签名 session；日志只记哈希；见 §2.4 |
| T5 | 会话/任务/轨迹无限期留存用户原文 | 进程内 TTL + 容量上限；轨迹目录写明需手动清理；见 §3 |
| T6 | 模板/前端被改动引入脚本或外部请求 | 本任务**未改** `web/**` 与 `static/**`；token 由后端注入 |

### 1.4 明确不防的威胁（非目标）

- 能直接读本机文件系统、进程内存或浏览器 cookie 的攻击者；
- 拥有本机账户的人（等价于服务所有者）；
- 公网 DDoS、0day、供应链投毒、模型提示注入（后者由输入/工具边界单独处理）；
- 通过反向代理配置错误造成的越权（本任务不提供代理配置）。

---

## 2. 已做控制

### 2.1 默认只绑定回环地址

`web_app.py`：

```python
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

def _serve():
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False)
```

- 启动入口只调用 `_serve()`；`debug=False`，不开启 debug/reloader；
- 不提供 `0.0.0.0` 默认值；
- 需要局域网访问时**必须**自行加反向代理、TLS 与鉴权（§5），不要直接把 host 改成 `0.0.0.0`；
- 单测：`test_security.py::SecurityConfigTests.test_default_host_is_loopback_and_debug_is_off`。

### 2.2 CSRF：服务端 token + 无 JS 表单

- 每会话一个 token：`secrets.token_urlsafe(32)`，存在 Flask session 的 `csrf_token` 键；
- 首页/错误页/结果页的 HTML 响应由 `web_app._inject_csrf_token()` 在**每个 `</form>` 前**注入一次：

  ```html
  <input type="hidden" name="csrf_token" value="...">
  ```

  注入是纯服务端字符串替换，不依赖 JS，也不改模板；已有 token 的页面不会重复注入。
- 所有 POST（含 `action=reset`）在 `before_request` 中校验 `request.form["csrf_token"]`，用 `secrets.compare_digest` 常量时间比较；
- 缺失/错误 token → **400** 可读 HTML 页，**不创建 job、不调用模型**；
- 无 JS 流程：`GET /` → 表单隐藏 token → `POST /` 带 token → **303** 到 `/run/<job_id>` 进度页。

单测覆盖：无 token 被拒、错误 token 被拒、`action=reset` 也要 token、带 token 仍 303、首页恰好一个隐藏字段、token 不进入 `Location`。

### 2.3 昂贵 POST 限流

- 仅对 `/` 的“要建任务”的 POST 计数；`GET`、`action=reset`、空输入不消耗限额；
- 进程内固定窗口：默认**每 IP 每分钟 5 次**，key 为 `request.remote_addr`；
- 超限返回 **429** + 可读 HTML 页 + `Retry-After` 头，**不创建 job、不调用模型**；
- 线程安全（`threading.RLock`），键数量有上限，过期窗口会被清理；
- 环境变量 `P07_RATE_LIMIT_PER_MIN` 可覆盖默认值（正整数，非法值回退 5）；
- 代码内可用 `web_app._configure_rate_limit(n)` / `web_app._reset_rate_limiter()` 配置与清空（测试即如此）。

这是**单进程内存**限流：重启清空、多 worker 不共享；若要抗公网流量，应在反向代理层再做一层限流。

### 2.4 会话 cookie 与日志

- `SESSION_COOKIE_HTTPONLY=True`（JS 读不到）；
- `SESSION_COOKIE_SAMESITE="Lax"`（跨站 POST 不携带会话 cookie，配合 token 双重缓解）；
- `PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)`，创建 token 时 `session.permanent=True`；
- `app.secret_key = os.urandom(32)`：进程内随机，重启/多进程会换；本机单用户可接受，见 §4；
- 不设置独立的明文 CSRF cookie；token 只在签名 session cookie 与表单隐藏字段中。**Flask 默认 session 是签名（可验证完整性）而非加密**，能读浏览器 cookie 的人可以看到 token；HttpOnly 降低 XSS 窃取面，但不要把它当服务端机密；
- T5.1 应用日志只记录 method/path/status/耗时/错误类型/query 的 SHA256 前缀与长度，不记录表单、token、cookie、`trace_json` 或 query 原文（详见 `LOGGING.md`）。

### 2.5 保留期（会话 / 任务 / 缓存 / 轨迹）

| 数据 | 位置 | 默认保留 | 清理行为 |
|---|---|---|---|
| Flask session（`csrf_token`、追问用 `pending_query`） | 浏览器端签名 cookie | 30 分钟 | 过期由浏览器丢弃；重启进程后 `secret_key` 变化，旧 session 失效 |
| JobStore（任务、query 原文、结果） | 进程内存 | 30 分钟 / 最多 16 条 | 创建/读取任务时按 `created_at` 清理过期项；超上限淘汰最旧 |
| ResultCache（完整结果，含 query） | 进程内存 | 30 分钟 / 最多 8 条 | 读取时惰性删除过期项；LRU 淘汰 |
| `trace_log.SessionTrace` 轨迹 | 仓库外 `P07_SESSION_DIR`（默认 `<repo>/../p7_agent_sessions`） | **无自动 TTL** | 每次运行一个 `session_<uuid>.jsonl`，含 `user_input` 与工具参数/观察；需手动删除目录或指向受控临时目录 |
| 应用日志（T5.1） | 仓库外 `P07_LOG_DIR` | 7 天轮转（可配） | 按天/体积轮转，不含用户原文 |

说明：

- `JobStore` / `ResultCache` 都是**进程内**结构，不写盘、不进 cookie；进程退出即清空；
- 本任务没有新增任何持久化用户原文的路径，也没有修改 `trace_log.py` 的落盘行为；
- `pending_query` 是 T3.2 已有的追问拼接行为：用户原文会短暂存在浏览器 session cookie 中，30 分钟后过期；这是本机单用户可接受的边界，已在此显式说明。

---

## 3. 测试与验收证据

`analysis/p07_agent/tests/test_security.py` 覆盖：

| 用例 | 断言 |
|---|---|
| `test_default_host_is_loopback_and_debug_is_off` | `_serve()` 以 `host=127.0.0.1`、`debug=False` 调用 `app.run` |
| `test_get_home_has_exactly_one_hidden_csrf_token` | GET `/` 恰好一个服务端 hidden token |
| `test_post_without_token_is_rejected_without_job` | 无 token POST=400，job 数不增，`run_agent` 未调用 |
| `test_post_with_wrong_token_is_rejected_without_job` | 错误 token POST=400，不建 job |
| `test_no_js_flow_get_token_then_post_returns_303_and_progress` | GET 拿 token → POST=303 → 进度/结果页 |
| `test_reset_action_also_requires_token` | `action=reset` 同样要 token |
| `test_expensive_post_is_rate_limited_but_get_is_not` | 超限=429、不建 job、GET 仍 200、有 `Retry-After` |
| `test_fixed_window_limiter_is_deterministic` | 固定窗口计数与窗口重置可复算 |
| `test_job_store_ttl_cleanup` / `test_result_cache_ttl_cleanup` | 过期项被清除 |
| `test_session_cookie_flags_and_lifetime` | HttpOnly / SameSite=Lax / 30 分钟 / 无独立明文 CSRF cookie |

运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
& .\.venv\Scripts\python.exe -m unittest discover -s analysis\p07_agent\tests -q
& .\.venv\Scripts\python.exe checks\check_agent.py analysis\p07_agent
```

---

## 4. 已知限制

1. **单进程**：JobStore、ResultCache、限流计数都在内存；多 worker 各自一份，重启清空。
2. **`secret_key` 随进程随机**：重启后旧 session/CSRF token 失效；多 worker 之间 session 无法互认。这是本机单用户的有意取舍，不是可水平扩展的部署方案。
3. **限流 key 是 `request.remote_addr`**：直接暴露时是客户端 IP；放在反向代理后若不配 `ProxyFix`，所有请求会共享代理 IP，需在代理层另行限流。
4. **CSRF token 在签名 session cookie 中可见**：Flask 默认 session 只签名不加密；HttpOnly + SameSite 降低风险，但它不是服务端秘密。
5. **无鉴权、无 HTTPS、无 Host 头校验**：任何能访问端口的人都能提交查询；不要把 `127.0.0.1` 改成 `0.0.0.0` 直接暴露。
6. **Flask 开发服务器**：本任务按约束不引入 Waitress/Gunicorn；它适合本机演示，不适合公网。
7. **轨迹无自动清理**：`P07_SESSION_DIR` 下的 `session_*.jsonl` 会保留到手动删除；不要把该目录提交进仓库。
8. **限流只保护“建任务”的 POST**：它不防 GET 刷页面，也不防已获得 token 的本机用户持续提交；公网场景需网关层限流/WAF。

---

## 5. 部署建议（仅在本机以外需要时）

默认建议保持不变：`http://127.0.0.1:5000`，单进程，不对外。

如果确实要让局域网/他人访问，按以下顺序做，缺一不可：

1. **保持应用只绑回环**；用 Caddy/nginx 反向代理到 `127.0.0.1:5000`；
2. **TLS**：代理终止 HTTPS，禁止明文 HTTP；
3. **鉴权**：代理层加 Basic Auth / OIDC / 访问 token；应用本身没有账号体系；
4. **代理层限流**：对 `/` 的 POST 做 IP/用户级限流，与应用内 5 次/分钟叠加；
5. **网络边界**：防火墙只放行代理端口，数据库/模型端口不暴露；
6. **日志与轨迹**：`P07_LOG_DIR`、`P07_SESSION_DIR` 指向受控目录，设置清理策略，确认不含密钥/用户原文；
7. **单进程运行**：在引入共享 session/限流存储前，不要起多 worker；
8. 重新做威胁建模：多用户、多租户、公网暴露都超出本文件假设。

---

## 6. 明确不做（Non-goals）

- 多用户/多租户、登录、RBAC、配额计费；
- 公网 HTTPS、证书管理、WAF、DDoS 防护；
- Redis/数据库版分布式限流、跨进程任务队列；
- CSRF token 加密存储、一次性 token、每请求轮换；
- 审计级不可抵赖日志、密钥管理/KMS；
- 对模型输出做安全过滤（属于内容安全，另立任务）。

---

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-16 | T5.2：新增 `security.py`；默认 `127.0.0.1` + `debug=False`；CSRF 隐藏字段与 POST 校验；POST 限流；会话/任务/轨迹保留期说明；新增 `test_security.py`，既有 Web POST 测试改为带 token 的等价断言（GET/无障碍断言未改） |
