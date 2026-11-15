# P7 前端：设计系统与双视图（T3.1 + T3.2）

T3.1 交付可复用的设计系统（调色板、四状态徽标、响应式样式表、基础模板）；
**T3.2 已接线**：`analysis/p07_agent/src/web_app.py` 不再使用 `render_template_string`，
改为渲染 `web/templates/` 下的 Jinja2 模板，提供访客视图与评审视图。

- 访客视图：`web/templates/result.html`（正文抽到 `_visitor_body.html`，与评审视图共用）
- 评审视图：`web/templates/auditor.html`（在访客内容之后追加 `<details>` 评审面板）
- 首屏查询页：`web/templates/index.html`（GET `/`）
- 设计口径：`docs/optimization/PRODUCT_SPEC.md` §4.1 / §5 / §6 / §7 / §9

页面默认**无 JS、零外部资源**：所有内容服务端渲染，图标是 Unicode 字符，
字体只用系统栈，断网也能打开已返回的结果。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `static/style.css` | 唯一样式表：`:root` 调色板、移动优先、`@media` 断点、T3.2 双视图样式 |
| `web/templates/base.html` | 基础模板：页头、动态覆盖篇数、视图切换、状态徽标区、免责句区、页脚限制 |
| `web/templates/_status_badge.html` | 四状态徽标宏（图标 + 文字 + 颜色三重编码），未知状态回退 `error` |
| `web/templates/index.html` | 首屏查询页（T3.2）：表单 + 3 个示例 + 提交；无结果时渲染 |
| `web/templates/result.html` | 访客视图结果页（T3.2），`extends "base.html"` |
| `web/templates/auditor.html` | 评审视图结果页（T3.2），`extends "base.html"` |
| `web/templates/_visitor_body.html` | 两个结果页共用的访客正文，避免双视图内容漂移 |
| `web/preview/result_preview.html` | T3.1 静态预览页（引用 `../../static/style.css`），数据全部标注为示例 |
| `web/preview/screenshot_375.png`、`screenshot_1280.png` | T3.1 静态预览截图 |
| `web/preview/visitor_375.png`、`visitor_1280.png` | T3.2 访客视图真实模板渲染截图（fixture 数据） |
| `web/preview/auditor_1280.png` | T3.2 评审视图真实模板渲染截图（fixture 数据） |
| `web/README.md` | 本文件：调色板、对比度、接线说明、状态映射、截图复现 |

## 2. 设计口径（先读）

- 文案与配色依据 `docs/optimization/PRODUCT_SPEC.md`：§5.2 固定免责句、§5.3 四状态配色、
  §5.6 连接核验与行程可行分开、§9 N3/N4/N5/N6/N7。
- **四状态色值与 §5.3 逐字一致，未做任何微调**（因此没有“原值/新值”差异需要记录）。
- **访客优先（Q1 已签字）**：访客视图不放 intent JSON、trace、`tool_decisions`、图谱指标；
  这些只出现在 `auditor.html` 的 `audit-panels` 里。正文模板 `_visitor_body.html`
  不含任何调试字段。
- **零外部资源**：样式表不引用任何外部字体、图标、脚本、CDN；图标全部是 Unicode 字符
  （✅ ⚠️ ❓ ❌ ✔ ▶ ○），字体只用系统栈。
- **无 JS 也能读**：所有内容都是服务端渲染的静态 HTML；模板里没有任何脚本标签。
- **状态只由后端判定**：`web_app.py` 只调用 `status.normalize_status()` 与
  `status.is_contract_violation()`，不改 `agent.py` 的业务判定。

## 3. 调色板（`static/style.css` 的 `:root`）

| 变量 | 色值 | 用途 |
|---|---|---|
| `--color-ink` | `#1A2028` | 正文前景 |
| `--color-ink-soft` | `#4A5560` | 次要文字（说明、标签） |
| `--color-canvas` | `#F5F7F9` | 页面底色 |
| `--color-surface` | `#FFFFFF` | 卡片/表单底色 |
| `--color-line` | `#CBD4DC` | 装饰性分隔线 |
| `--color-line-strong` | `#7C8791` | 输入框/按钮等控件边框（对白底 3.66:1） |
| `--color-accent` | `#14532D` | 主按钮、链接、强调标签 |
| `--color-accent-ink` | `#FFFFFF` | 主按钮文字 |
| `--color-accent-soft` | `#ECF3EE` | 强调标签底色 |
| `--color-focus` | `#0B5FB4` | 焦点环 |
| `--status-verified-fg` / `-bg` | `#1E6B34` / `#E8F5EC` | verified 前景/底色 |
| `--status-partial-fg` / `-bg` | `#8A5A00` / `#FFF4D6` | partial 前景/底色 |
| `--status-clarify-fg` / `-bg` | `#1F5FA8` / `#E7F0FB` | clarify 前景/底色 |
| `--status-error-fg` / `-bg` | `#A12622` / `#FDECEA` | error 前景/底色 |

间距、圆角、字体栈也用变量（`--space-*`、`--radius-*`、`--font-sans`、`--font-mono`）。
版心 `--wrap: 68rem`，不用固定 px 宽度。

## 4. 四状态徽标（`_status_badge.html`）

| 状态 | 图标 | 徽标文字（可见） | 前景 | 底色 | 对比度 |
|---|---|---|---|---|---|
| `verified` | ✅ | 图谱连接核验通过 | `#1E6B34` | `#E8F5EC` | 5.83:1 |
| `partial` | ⚠️ | 部分可参考 | `#8A5A00` | `#FFF4D6` | 5.41:1 |
| `clarify` | ❓ | 需要补充信息 | `#1F5FA8` | `#E7F0FB` | 5.60:1 |
| `error` | ❌ | 处理失败 | `#A12622` | `#FDECEA` | 6.52:1 |

三重编码：

1. **图标**：装饰性（`aria-hidden="true"`），保证“不只靠颜色”；
2. **文字**：中文徽标文案始终可见，并有 `visually-hidden` 的“状态：”前缀；
3. **颜色**：前景/底色成对定义，均 ≥4.5:1。

未知状态（含 `working`、`reply`、空值、`None`）由 `web_app.py` 先归一为 `error`，
页面不会输出未知状态原文；评审视图另加 `contract_violation=1` 标记。

## 5. 对比度

### 5.1 计算方式（WCAG 2.x）

1. 把 `#RRGGBB` 拆成 R、G、B，各除以 255 得到 sRGB 通道 `c`；
2. 线性化：`c <= 0.03928` 时 `c / 12.92`，否则 `((c + 0.055) / 1.055) ** 2.4`；
3. 相对亮度：`L = 0.2126*R + 0.7152*G + 0.0722*B`；
4. 对比度：`(L_亮 + 0.05) / (L_暗 + 0.05)`。

阈值：正文与徽标文字 **≥4.5:1**；焦点环/控件边框（非文本）≥3:1。
下面的数字全部由脚本从 `style.css` 读取真实色值计算，不是手写估值；
`style.css` 中凡同一条规则同时声明 `color` 与 `background-color` 的地方，都写六位字面量色值，
以便脚本逐对复算（`:root` 变量是同一套色值的唯一来源，二者数值一致）。

T3.2 追加的样式（第 19 节）只做布局与占位，不新增“同一条规则内 color + background”
的色对，因此下表的 22 对仍然逐对成立。

可用下面脚本从仓库根目录复算（只依赖标准库）：

```python
import pathlib, re

css = pathlib.Path("analysis/p07_agent/static/style.css").read_text(encoding="utf-8")
css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

def lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

def ratio(fg, bg):
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)

for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
    decl = {}
    for part in body.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            decl[k.strip()] = v.strip()
    bg_key = "background-color" if "background-color" in decl else ("background" if "background" in decl else None)
    if "color" in decl and bg_key:
        print(selector.strip(), decl["color"], decl[bg_key], round(ratio(decl["color"], decl[bg_key]), 2))
```

### 5.2 同一条规则内的「前景 + 背景」逐对复算（22 对，全部 ≥4.5:1）

| # | 规则 | 前景 | 背景 | 对比度 |
|---|---|---|---|---|
| 1 | `body` | `#1A2028` | `#F5F7F9` | 15.26:1 |
| 2 | `.skip-link` | `#FFFFFF` | `#14532D` | 9.11:1 |
| 3 | `.site-header` | `#1A2028` | `#FFFFFF` | 16.39:1 |
| 4 | `textarea` | `#1A2028` | `#FFFFFF` | 16.39:1 |
| 5 | `.chip` | `#14532D` | `#ECF3EE` | 8.08:1 |
| 6 | `.btn` | `#FFFFFF` | `#14532D` | 9.11:1 |
| 7 | `.btn--secondary` | `#14532D` | `#FFFFFF` | 9.11:1 |
| 8 | `.status-badge--verified` | `#1E6B34` | `#E8F5EC` | 5.83:1 |
| 9 | `.status-badge--partial` | `#8A5A00` | `#FFF4D6` | 5.41:1 |
| 10 | `.status-badge--clarify` | `#1F5FA8` | `#E7F0FB` | 5.60:1 |
| 11 | `.status-badge--error` | `#A12622` | `#FDECEA` | 6.52:1 |
| 12 | `.disclaimer-line` | `#1A2028` | `#FFFFFF` | 16.39:1 |
| 13 | `.feasibility` | `#8A5A00` | `#FFF4D6` | 5.41:1 |
| 14 | `.person-note` | `#1F5FA8` | `#E7F0FB` | 5.60:1 |
| 15 | `.stepper__step` | `#4A5560` | `#FFFFFF` | 7.61:1 |
| 16 | `.stepper__step--done` | `#1E6B34` | `#E8F5EC` | 5.83:1 |
| 17 | `.stepper__step--active` | `#1F5FA8` | `#E7F0FB` | 5.60:1 |
| 18 | `.tag` | `#14532D` | `#ECF3EE` | 8.08:1 |
| 19 | `.evidence-card__quote` | `#2B333B` | `#F2F5F7` | 11.70:1 |
| 20 | `.example-banner` | `#1A2028` | `#FFF4D6` | 14.96:1 |
| 21 | `.site-footer` | `#3C4650` | `#E8EDF1` | 8.16:1 |
| 22 | `pre` | `#1A2028` | `#F2F5F7` | 14.97:1 |

最低一对是 `.status-badge--partial` / `.feasibility` 的 **5.41:1**，仍高于 4.5:1。

### 5.3 跨规则的继承组合（人工核对，保证“子元素文字 + 父级底色”也达标）

| 组合 | 前景 | 背景 | 对比度 |
|---|---|---|---|
| 卡片正文（`.card` 继承 body 前景） | `#1A2028` | `#FFFFFF` | 16.39:1 |
| 页面次要文字（`.muted` / `.status-note` / `.status-badge__desc` / `.site-tagline`） | `#4A5560` | `#F5F7F9` | 7.09:1 |
| 卡片内次要文字（`.muted` / `.day-meta` / `.period__label`） | `#4A5560` | `#FFFFFF` | 7.61:1 |
| 链接与 `.evidence > summary` | `#14532D` | `#FFFFFF` | 9.11:1 |
| 链接（页面底色上） | `#14532D` | `#F5F7F9` | 8.48:1 |
| 焦点环 | `#0B5FB4` | `#FFFFFF` | 6.34:1 |
| 焦点环（页面底色上） | `#0B5FB4` | `#F5F7F9` | 5.91:1 |
| 控件边框 `--color-line-strong` | `#7C8791` | `#FFFFFF` | 3.66:1（非文本 ≥3:1） |
| 控件边框（页面底色上） | `#7C8791` | `#F5F7F9` | 3.41:1（非文本 ≥3:1） |
| 页脚文字（与页脚底色） | `#3C4650` | `#E8EDF1` | 8.16:1 |

`--color-line`（`#CBD4DC`）只用于装饰性分隔线，不用于控件边界，因此不按 3:1 要求。

## 6. 响应式与断点

移动优先：基础规则面向 375px，窄屏不加横向滚动；向上用 `min-width` 增强，另保留
`max-width: 480px` 的小屏微调断点。

| 断点 | 触发 | 变化 |
|---|---|---|
| 基础 | 默认（含 375px） | 单列；容器 `width: 100%` + `max-width`；按钮/输入框整宽；行程时段单列 |
| `@media (min-width: 40em)` | ≥640px | 页头改横向两栏；`h1` 1.875rem；表单/卡片加大内边距；`audit-list` 两列 |
| `@media (min-width: 64em)` | ≥1024px | 版心 68rem；行程的三个时段改为 3 列 |
| `@media (max-width: 480px)` | ≤480px | 页面内边距收紧；状态徽标紧凑；操作按钮整行 |
| `@media (prefers-reduced-motion: reduce)` | 系统设置 | 关闭全部过渡与动画，`scroll-behavior: auto` |

断点全部用 `em`/`max-width` 表达，没有对页面元素写 `width: <N>px` 的固定宽度。

## 7. 375px 无横向滚动的实现约束与实测

- 容器：`.wrap { width: 100%; max-width: 68rem; }`，内边距用 `padding-inline` + `box-sizing: border-box`；
- 文本：标题/段落 `overflow-wrap: break-word`，长串（`pre`、`code`、`route-chain`、引文）`overflow-wrap: anywhere`；
- `pre`：`white-space: pre-wrap` + `overflow-x: auto`，不会撑破页面；
- 表格：`width: 100%`，外层 `.table-scroll` 可横向滚动（评审视图的逐段核验表、指标表）；
- 图片：`max-width: 100%; height: auto`（本项目不使用图片）；
- 全表扫描：`style.css` 中唯一的 px 宽度是 `.visually-hidden` 的 `1px`，其余宽度均为 `%` 或 `rem`；
- 实测（CDP `Emulation.setDeviceMetricsOverride`，`visitor_375.png`）：
  `window.innerWidth = 375`、`documentElement.scrollWidth = 375`、`clientWidth = 375`，
  即 **scrollWidth 等于视口宽度，没有横向滚动**；整页 `scrollHeight = 3371`。
  1280 视口同理（访客页 `scrollWidth = 1280`、`scrollHeight = 2313`；
  评审页 `scrollWidth = 1280`、`scrollHeight = 4386`）。

## 8. 无障碍

- 焦点：全局 `:focus-visible { outline: 3px solid #0B5FB4; outline-offset: 2px; }`，
  对白底 6.34:1（≥3:1）；跳转链接 `跳到主要内容` 在聚焦时出现；
- 表单：`index.html` 的 `<textarea>` 有可见 `<label for>` 与 `aria-describedby` 提示；
- 状态：徽标有可见中文文字 + `visually-hidden` 的“状态：”前缀，图标 `aria-hidden`；
  `.status-area` 带 `aria-live="polite"`；
- 触控：按钮、chip、`summary` 的 `min-height: 2.75rem`（44px），输入框字号 16px；
- 对比度：见 §5；`prefers-reduced-motion` 关闭动效；页面不依赖 JS。

固定免责句 `核验通过只证明连接有据，不证明一天走得完` 在 `base.html` 中都是
**可见正文**（不是 `title`/`aria-label`），字号 1rem（≥14px），与正文同色 `#1A2028`；
仅在 `verified` / `partial` 出现。

## 9. T3.2 接线说明（已实现）

### 9.1 Flask 的 `template_folder` / `static_folder`

`src/web_app.py` 用绝对路径注册模板与静态目录，避免工作目录不同导致找不到文件：

```python
BASE_DIR = Path(__file__).resolve().parents[1]   # analysis/p07_agent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "web" / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
```

`base.html` 用 `url_for('static', filename='style.css')` 生成样式表地址，默认得到
`/static/style.css`，不需要额外路由。

### 9.2 路由与视图白名单

| 请求 | 行为 |
|---|---|
| `GET /` | 渲染 `index.html`：查询表单 + 3 个示例 + 提交；`?query=` 可回填输入框 |
| `POST /` | 读 `query`，跑一次 `run_agent(query)`，按 `view` 渲染 `result.html` / `auditor.html` |
| `view` 取值 | 只认 `visitor` / `auditor`；缺失、大小写混杂或其他值一律回退 `visitor` |
| `?view=auditor` | 首屏预选评审视图（表单 hidden `view` 随之提交）；结果页由 POST 的 `view` 决定 |
| 空 query / `action=reset` | 回到首屏并给出提示，不调用模型 |

视图切换链接（`base.html`）保留当前 `query` 与目标 `view`：
`?view=<另一个视图>&query=<当前输入>`。本任务不引入服务端结果缓存，
所以从结果页点切换会回到“已回填输入框”的首屏，再提交即以另一视图渲染；
这样不需要 JS，也不会把上一次结果悄悄持久化。

### 9.3 状态归一与映射规则（只归一，不判定）

`web_app._build_context()` 对 `run_agent()` 返回的 `status` 依次做：

1. `contract_violation = status.is_contract_violation(raw_status)`；
2. `status = status.normalize_status(raw_status)`；
3. 只有归一后的四值之一进入模板；模板从不输出原始状态字符串。

| 后端原值 | 归一后 | 页面表现 |
|---|---|---|
| `verified` | `verified` | ✅ 徽标 + 免责句；`reasons` 按契约清空 |
| `partial` | `partial` | ⚠️ 徽标 + reasons 人话 + 免责句 |
| `clarify` | `clarify` | ❓ 徽标 + 追问原因；无免责句 |
| `error` | `error` | ❌ 徽标 + 失败说明；不把中间结果当核验结论 |
| `complete`（旧值） | `verified` | 迁移映射（§5.4），不算违例 |
| `reply`（旧值） | `clarify` | 迁移映射（§5.4），不算违例 |
| `None` / 缺失 / `working` / 其他 | `error` | 记 `contract_violation=1`，评审视图显示标记；访客页不出现未知值原文 |

模板侧的统一口径：

- 徽标由 `_status_badge.html` 宏渲染，带 `data-status="<四值>"`；
- 免责句只在 `verified` / `partial` 由 `base.html` 的 `{% block disclaimer %}` 渲染；
- 访客看 `reasons[].text`（人话），评审另看 `reasons[].code`；
- 访客不显示原始 `error` / 异常堆栈 / trace 文件路径；评审视图只显示 trace 文件名，
  不显示本机目录。

### 9.4 覆盖篇数动态化（不再硬编码 29）

`base.html` 的“当前 N 篇”来自 `web_app.DOC_COUNT`，启动时按三个景区
`scenic/*/data/processed/*_guides.csv` 的数据行数求和（T1.5 后为 **32**）。
复算命令：

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -c "import csv,glob; print(sum(1 for p in glob.glob('scenic/*/data/processed/*_guides.csv') for _ in csv.DictReader(open(p, encoding='utf-8-sig'))))"
```

统计失败时模板显示“收录篇数暂不可用”，不会回退成某个写死的数字。

### 9.5 渲染异常兜底

`_render_result()` 包住模板渲染；任何模板异常都返回一个纯服务端 error 页
（`data-status="error"`、无 500 白屏），页面不泄露异常堆栈。
`run_agent()` 本身抛异常时，路由也会兜成 `status="error"` 再走同一套 error 渲染。

### 9.6 双视图差异

| 区块 | 访客视图 `result.html` | 评审视图 `auditor.html` |
|---|---|---|
| 状态徽标 / reasons / 免责句 | 有 | 有（reasons 带 code） |
| 查询回显 | 有 | 有 |
| 行程卡（天/上午/中午/下午/时长标签） | 有 | 有 |
| 路线顺序（文字箭头，无坐标） | 有 | 有 |
| 地点列表（折叠 + 计数） | 有 | 有 |
| 条件建议（条件/建议/理由/来源 doc_id） | 有 | 有 |
| 未核验项清单 | 有 | 有 |
| intent JSON | **无** | 有（`<pre>` 转义） |
| decision / `tool_decisions` | **无** | 有 |
| 逐段 evidence（from→to + `source_doc_ids`） | **无**（只在“路线顺序”里给箭头） | 有（表格） |
| `route.metrics` 图谱指标 | **无** | 有 |
| `trace_json` / 会话文件名 | **无** | 有（`<pre>` 转义，默认折叠） |
| `contract_violation=1` 标记 | 无 | 有 |
| 原始错误 | 无 | 有（默认折叠） |

### 9.7 备选路线区块（为 T2.4 预留，契约先定）

`_visitor_body.html` 接收可选 `alternatives`（list），每项契约：

```text
{alt_id, source_doc_id, source_title, node_names: [str],
 status: "verified"|"partial", reason: str,
 segments: [{from_name, to_name, source_doc_ids: [str]}]}
```

- 为空 / 未传：**整块不渲染**，不做假数据占位；
- 非空：渲染最多 3 张卡片，含来源标题、来源 doc_id、节点链、状态、
  逐段来源折叠区，以及 GET 链接 `?view=<当前视图>&alt=<alt_id>`；
- `alt` 参数当前只用于模板高亮（`alt-card--selected` + “当前高亮”），
  结果页持久化由 T2.4 接入；不引入 JS。

### 9.8 T3.3 / T3.4 占位（不放假数据）

| 任务 | 占位位置 | class / data 属性 | 页面上可见文案 |
|---|---|---|---|
| T3.4 证据卡 | 行程每个 `.period` 内、条件建议卡片内 | `details.evidence-slot` | “查看来源（T3.4 接入证据卡）”“查看完整证据（T3.4 接入证据卡）” |
| T3.3 路线示意图 | 路线顺序区块内、`proposal` 之后 | `details.diagram-slot` | “查看路线示意（图谱顺序，不是地图）” |
| T2.4 备选路线 | 路线顺序之后、地点列表之前 | `section` + `article.card.alt-card` / `.alt-card--selected` | “备选路线”（仅 alternatives 非空时出现） |

占位块只说明“将由哪个任务接入”，不含示例节点、示例来源或编造数字。

### 9.9 隐私

- 访客视图不显示 `trace_file` 的绝对路径；评审视图只显示文件名；
- 用户原话由 Jinja 自动转义（需要时显式 `|e`）；
- 页面不加载第三方资源，不写 cookie 之外的分析脚本（本项目没有脚本）。

## 10. 本地校验

### 10.1 服务端渲染（Flask 测试客户端，不启动服务）

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$py = ".\.venv\Scripts\python.exe"

& $py -c "import sys; sys.path.insert(0, 'analysis/p07_agent/src'); import web_app; app = web_app.app; app.config['TESTING'] = True; c = app.test_client(); r = c.get('/'); print('GET', r.status_code); print('has_form', b'<form' in r.data); print('doc32', '32'.encode() in r.data)"
```

期望：`GET 200`、`has_form True`、`doc32 True`。

### 10.2 状态与双视图（fixture，不调模型）

用 `unittest.mock.patch.object(web_app, 'run_agent', return_value=fixture)` 后
`client.post('/', data={'query': '...', 'view': 'visitor'})`，即可渲染四种状态；
检查点：

1. 访客页不含 `intent_json` / `trace_json` / `tool_decisions` / `route.metrics` /
   `路线结构：` / `工具调用` / `图谱指标`；
2. 评审页含 intent JSON、`tool_decisions`、逐段来源、`route.metrics`、trace；
3. `status="working"` / `None` 渲染成 `data-status="error"`，页面不出现原值；
4. 免责句只在 `verified` / `partial` 出现。

### 10.3 零外部资源 / 无脚本

```powershell
& $py -c "import pathlib,re; bad=[str(p) for p in pathlib.Path('analysis/p07_agent').rglob('*') if p.suffix in ('.html','.css','.js','.svg') and re.search(r'https?://', p.read_text(encoding='utf-8', errors='ignore'))]; print('external_refs', bad); print('script_tags', [str(p) for p in pathlib.Path('analysis/p07_agent/web').rglob('*.html') if ('<' + 'script') in p.read_text(encoding='utf-8').lower()])"
```

期望两个列表都为空。

### 10.4 项目自检与测试

```powershell
& $py checks\check_agent.py analysis\p07_agent
& $py -m unittest discover -s analysis\p07_agent\tests -q
```

T3.2 完成时：check 通过，121 条测试 OK。

## 11. 截图复现（T3.2）

三张截图都由**真实 Flask 模板**渲染，不是手工 HTML；fixture 数据不调用模型：

| 文件 | 视口 | 尺寸 | 说明 |
|---|---|---|---|
| `visitor_375.png` | 375 CSS px | 375×3371 | 访客视图整页 |
| `visitor_1280.png` | 1280 CSS px | 1280×2313 | 访客视图整页 |
| `auditor_1280.png` | 1280 CSS px | 1280×4386 | 评审视图整页 |

fixture 的来源（仓库外临时脚本，不提交）：用 `tools.get_route_candidates('长隆')` +
`validate_route()` + `route_metrics()` 得到真实图谱路线（北门 → 小火车游览区 → 青龙山 →
考拉园 → 熊猫乐园 → 熊猫餐厅，单一来源 `CL-O-02`），用 `build_itinerary()` 生成行程，
用 `get_conditions()` / `get_condition_evidence()` 取真实条件建议；
`intent` / `decision` 是展示用 fixture。**截图不代表一次真实 `run_agent` 输出。**

复现步骤：

1. 仓库外临时脚本（示意）用真实模板渲染 fixture：

```python
import sys, threading
sys.path.insert(0, r"analysis/p07_agent/src")
import web_app
from flask import request
from werkzeug.serving import make_server

result = build_fixture()          # 至少含 status / query / route / itinerary / suggestions
app = web_app.app
original_home = app.view_functions["home"]

def demo_home():
    if request.method == "POST":
        return original_home()
    return web_app._render_result(result, web_app._resolve_view(), result["query"])

app.view_functions["home"] = demo_home
server = make_server("127.0.0.1", 0, app)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(server.server_port)
```

2. 用父 Agent 的 CDP 工具（仓库外）真实设置视口并整页截图：

```powershell
$py = ".\.venv\Scripts\python.exe"
$shot = "E:\ProgramProject\travel-agent-run\optimization\state\tools\cdp_shot.py"
$scheme = "http"
$base = "${scheme}://127.0.0.1:<port>"

& $py $shot --url "$base/?view=visitor" --out "analysis\p07_agent\web\preview\visitor_375.png"  --width 375
& $py $shot --url "$base/?view=visitor" --out "analysis\p07_agent\web\preview\visitor_1280.png" --width 1280
& $py $shot --url "$base/?view=auditor" --out "analysis\p07_agent\web\preview\auditor_1280.png" --width 1280
```

3. 每张图必须记录工具原样打印的 `METRICS`。本次实测：

```text
visitor_375.png   METRICS {"innerWidth":375,"scrollWidth":375,"clientWidth":375,"scrollHeight":3371}
visitor_1280.png  METRICS {"innerWidth":1280,"scrollWidth":1280,"clientWidth":1280,"scrollHeight":2313}
auditor_1280.png  METRICS {"innerWidth":1280,"scrollWidth":1280,"clientWidth":1280,"scrollHeight":4386}
```

375px 的 `scrollWidth` 等于 `clientWidth` 等于视口宽度 375，**没有横向滚动**。
工具用 `Emulation.setDeviceMetricsOverride` 真正设置视口，而不是用 500px 布局裁切
（T3.1 §11 记录过本机无头 Chrome 的 500px 下限）。

## 12. 已知限制与后续

- 本任务不实现结果页持久化：视图切换会回到已回填输入框的首屏，再提交渲染另一视图；
  `?alt=` 高亮同理，等 T2.4 提供备选路线与结果缓存后生效。
- 证据卡（T3.4）与路线示意图（T3.3）只有占位，不显示示例来源或示例节点。
- 条件建议的“选择理由”与 `needs_verification` 由后端给出，前端不推断。
- 页面没有实时票价、排队、天气、开放状态，也不提供预订、支付、导航或叫车服务。
