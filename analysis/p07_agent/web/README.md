# P7 前端：设计系统与双视图（T3.1 + T3.2 + T3.3 + T3.4）

T3.1 交付可复用的设计系统（调色板、四状态徽标、响应式样式表、基础模板）；
**T3.2 已接线**：`analysis/p07_agent/src/web_app.py` 不再使用 `render_template_string`，
改为渲染 `web/templates/` 下的 Jinja2 模板，提供访客视图与评审视图；
**T3.4 已接线**：每个停留点与每个路线段都有证据入口，卡片内容全部来自 T1.6
`evidence` 模块的原文切片（`doc_meta()` / `quote_sentence_for()` /
`segment_evidence()`），缺失逐字显示「未找到来源」；
**T3.3 已接线**：路线顺序下方渲染**顺序示意图**（服务端内联 SVG，数据 = P7 路线顺序 +
P6 `rel=NEXT` 边，零坐标、无地图瓦片），页面逐字写明「这是顺序示意图，不是地图」。

- 访客视图：`web/templates/result.html`（正文抽到 `_visitor_body.html`，与评审视图共用）
- 评审视图：`web/templates/auditor.html`（在访客内容之后追加 `<details>` 评审面板）
- 首屏查询页：`web/templates/index.html`（GET `/`）
- 证据卡宏：`web/templates/_evidence_card.html`（T3.4，访客/评审共用）
- 路线示意图宏：`web/templates/_route_diagram.html`（T3.3，访客/评审共用）
- 设计口径：`docs/optimization/PRODUCT_SPEC.md` §4.1 / §5 / §6 / §7 / §9

页面默认**无 JS、零外部资源**：所有内容服务端渲染，图标是 Unicode 字符，
字体只用系统栈，断网也能打开已返回的结果。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `static/style.css` | 唯一样式表：`:root` 调色板、移动优先、`@media` 断点、T3.2 双视图样式、T3.4 证据卡样式、T3.3 示意图样式（第 23 节） |
| `web/templates/base.html` | 基础模板：页头、动态覆盖篇数、视图切换、状态徽标区、免责句区、页脚限制 |
| `web/templates/_status_badge.html` | 四状态徽标宏（图标 + 文字 + 颜色三重编码），未知状态回退 `error` |
| `web/templates/_evidence_card.html` | T3.4 证据卡宏：标题 / `source_url` 新窗口链接 / 发布日期 / 摘句 / 评审字符区间 |
| `web/templates/_route_diagram.html` | T3.3 路线示意图宏：服务端内联 SVG，按天分色，箭头方向 = 图谱 `NEXT`，零坐标 |
| `web/templates/index.html` | 首屏查询页（T3.2）：表单 + 3 个示例 + 提交；无结果时渲染 |
| `web/templates/result.html` | 访客视图结果页（T3.2），`extends "base.html"` |
| `web/templates/auditor.html` | 评审视图结果页（T3.2），`extends "base.html"`；T3.4 追加摘句字符区间 |
| `web/templates/_visitor_body.html` | 两个结果页共用的访客正文，避免双视图内容漂移；T3.4 证据入口、T3.3 示意图入口在此 |
| `web/preview/result_preview.html` | T3.1 静态预览页（引用 `../../static/style.css`），数据全部标注为示例 |
| `web/preview/screenshot_375.png`、`screenshot_1280.png` | T3.1 静态预览截图 |
| `web/preview/visitor_375.png`、`visitor_1280.png` | T3.2 访客视图真实模板渲染截图（fixture 数据） |
| `web/preview/auditor_1280.png` | T3.2 评审视图真实模板渲染截图（fixture 数据） |
| `web/preview/evidence_375.png`、`evidence_1280.png` | T3.4 证据卡真实模板渲染截图（含「未找到来源」卡片，见 §11） |
| `web/preview/diagram_375.png`、`diagram_1280.png` | T3.3 路线示意图真实模板渲染截图（白云山 BYS-T-02 链，见 §11） |
| `web/README.md` | 本文件：调色板、对比度、接线说明、状态映射、证据卡、示意图、截图复现 |

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
的色对，因此下表的 22 对仍然逐对成立；T3.3 追加的示意图样式（第 23 节）只用
`fill` / `stroke` 与一个不配 `color` 的 `background-color`，同样不新增色对
（复算脚本仍只打印 22 条）。

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
| 证据卡缺失态（`.evidence-card__missing`，卡片白底） | `#8A5A00` | `#FFFFFF` | 5.93:1 |
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
- 全表扫描：`style.css` 中唯一的 px 宽度是 `.visually-hidden` 的 `1px`（另有断点
  `@media (max-width: 480px)` 与 `border-width: 2px`，都不是元素宽度），其余宽度均为 `%` 或 `rem`；
- 示意图是唯一的例外：`_route_diagram.html` 给 `svg` 写死 `width` 属性（访客 480px、
  评审 640px），靠 `.diagram__scroll { max-width: 100%; overflow-x: auto }` 在**容器内**
  横向滚动，`documentElement.scrollWidth` 仍是视口宽度（见 §9.11 与 §11 的 METRICS）；
- 实测（CDP `Emulation.setDeviceMetricsOverride`，`visitor_375.png`）：
  `window.innerWidth = 375`、`documentElement.scrollWidth = 375`、`clientWidth = 375`，
  即 **scrollWidth 等于视口宽度，没有横向滚动**；整页 `scrollHeight = 3371`。
  1280 视口同理（访客页 `scrollWidth = 1280`、`scrollHeight = 2313`；
  评审页 `scrollWidth = 1280`、`scrollHeight = 4386`）；
- T3.3 加入示意图后复测（`diagram_375.png` / `diagram_1280.png`，示意图已展开）：
  375 视口 `scrollWidth = 375`、`scrollHeight = 3591`；1280 视口 `scrollWidth = 1280`、
  `scrollHeight = 2663`。**图内可横向滚动，页面本身仍不横向滚动。**

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

### 9.8 T3.3 / T3.4 均已交付（不放假数据）

| 任务 | 状态 | 位置 | class / data 属性 |
|---|---|---|---|
| T3.4 证据卡 | **已交付**（详见 §9.10） | 行程每个 `.period` 内、路线每段 `.segment` 内 | `details.evidence` + `.evidence-card` |
| T3.3 路线示意图 | **已交付**（详见 §9.11） | 路线顺序区块内、`proposal` 之后 | `details.diagram-block` + `figure.diagram` + 内联 `svg` |
| T2.4 备选路线 | 契约已定，未接入 | 路线顺序之后、地点列表之前 | `section` + `article.card.alt-card` / `.alt-card--selected` |

原先的占位块 `.diagram-slot` 已随占位一起删除（`style.css` 中对应的两条选择器
也一并移除），不再留“待接入”文案。T3.4 交付时同样删除了 `.evidence-slot` 占位；
条件建议的完整卡片按 PRODUCT_SPEC §6.4 等来源过滤（T2.5）后再接入。

### 9.9 隐私

- 访客视图不显示 `trace_file` 的绝对路径；评审视图只显示文件名；
- 用户原话由 Jinja 自动转义（需要时显式 `|e`）；
- 页面不加载第三方资源，不写 cookie 之外的分析脚本（本项目没有脚本）。

### 9.10 T3.4 证据卡（每个停留点 / 每个路线段）

**数据来源（只读，单一实现）**

`web_app.py` 只调用 T1.6 的 `analysis/p07_agent/src/evidence.py`，不读 guides CSV、
不拼句子、不补 URL/日期：

| 上下文变量 | 构建函数 | 内容 |
|---|---|---|
| `point_evidence` | `_build_point_evidence(route)` | `node_id → [card]`；每个停留点最多 **2 张卡**，来源取 `graph_nodes.source_doc_ids` 前 2 篇 |
| `segment_evidence_list` | `_build_segment_evidence(route)` | 每段 `{from_name, to_name, source_doc_ids, cards, found_count}`，直接调用 `segment_evidence(segment)` |
| `itinerary` | `_attach_point_evidence(...)` | 复制一份分时行程，给每个 `.period` 挂 `point_nodes`（按时段文案里出现的停留点分组，长名优先，避免「熊猫乐园」误吃「熊猫乐园站」） |

每张卡的字段（`_card_from_meta()` / `segment_evidence()`）：

```text
{doc_id, title, source_url, publish_date, source_site, quote, found}
quote = {text, char_start, char_end[, anchor_start, anchor_end]}
```

`quote.text` 是 `clean_content[char_start:char_end]` 的原始连续子串（T1.6 保证），
模板只转义与排版，不改写、不截断、不拼接。页面上的外部链接只有
`source_url`（新窗口 + `rel="noopener noreferrer"`），没有外部 CSS/JS/字体/图片。

**缺失态（逐字固定文案）**

| 情况 | 页面显示 |
|---|---|
| `found=False` 或 `quote` 为空 | 卡片摘句位置逐字 **「未找到来源」** |
| 某个停留点 0 张有摘句的卡 | 该停留点标题下逐字 **「未找到来源」**（入口摘要同时显示「未找到来源 N 处」） |
| 某段没有卡 / 卡都没有摘句 | 该段入口摘要与正文逐字 **「未找到来源」** |
| 标题 / `source_url` / `publish_date` 为空 | 按 PRODUCT_SPEC §6.2 的固定文案：`来源标题缺失（doc_id: …）` / `原文链接缺失（数据缺口）` / `发布日期未记录`；**不补造** |

任何证据构建异常都会被 `_build_*` 捕获并降级成空卡（模板显示「未找到来源」），
页面不会 500；`_render_result()` 仍保留模板异常的兜底 error 页。

**默认折叠 / 无 JS**

每个证据入口是原生 `<details class="evidence">`，默认**不展开**；`<summary>` 里给出
停留点数 / 来源条数 / 未找到来源处数，键盘可直接操作，不需要任何脚本。
模板中没有任何 `<script>` 标签。

**双视图差异**

| 内容 | 访客 | 评审 |
|---|---|---|
| 停留点 / 路线段证据入口与卡片 | 有 | 有（同一份 `_visitor_body.html`） |
| `doc_id`（等宽小字） | 有（PRODUCT_SPEC §6.1 要求） | 有 |
| 摘句 `char_start` / `char_end`（含 anchor 位置） | 无 | 有（卡片内 + §「逐段证据」表格） |
| intent / trace / `tool_decisions` / 图谱指标 | 无 | 有 |

**fixture 渲染计数**（Flask test client，真实图谱连接，不调模型）

```text
periods=3  point_blocks=6（5 个唯一节点，云台花园在上午/中午各出现一次）
segments=4  cards=16（有摘句 14 / 未找到来源 2）  empty_evidence_bodies=0
periods_without_evidence=0  segments_without_evidence=0  details_open=0
```

其中 `白云山南门`（T1.6 `scan_coverage()` 报告的 `missing_quote` 节点，
来源 BYS-T-02/BYS-T-03 都定位不到节点名）在页面上显示两张「未找到来源」卡
+ 停留点级「未找到来源」，满足“缺失示例真实出现在页面”的要求。

### 9.11 T3.3 路线示意图（顺序图，不是地图）

**一句话口径**：图里只有「按资料先后顺序排列的节点」和「图谱 `NEXT` 边的方向」；
页面逐字写明 **「这是顺序示意图，不是地图」**，也没有纬度、经度、坐标、
距离或步行时间。

**数据来源（只读，单一实现）**

| 上下文变量 | 构建函数 | 内容 |
|---|---|---|
| `diagram` | `web_app._build_diagram(route)` | `{days: [{day, nodes: [{node_id, name, in_graph}]}], edges: [{from_id, to_id, from_name, to_name, doc_ids}], missing: [{from_id, to_id, from_name, to_name}]}` |

```text
顺序（分天 / 天内先后）  ← route.proposal.day_plan，缺失或对不上时退回 route.proposal.node_ids
名字                    ← route.proposal.node_names，其次 graph_nodes.csv 的 name
箭头（方向 + 来源）      ← graph_edges.csv 里 rel=NEXT 且 src→dst 与相邻两点**完全一致**的行
```

- 图谱只通过 `tools.load_graph()` 读取（P6 的唯一读取实现），本模块不重写图谱规则、
  不补边、不猜方向；`_graph_index()` 只在第一次渲染时读一次并缓存；
- 同一对 `src→dst` 若有多行 `NEXT` 边，`doc_ids` 去重合并；**反方向的边不算**；
- `doc_ids` 显示在箭头旁（`来源 BYS-T-02、BYS-T-03`），评审视图另有 `<title>`；
- `node_ids` 为空、`day_plan` 与 `node_ids` 对不上、读图谱失败或任何异常 →
  `diagram=None`，页面只渲染文字顺序，**不渲染空图、不报错**。

**缺失段的处理（不伪造方向）**

| 情况 | 页面表现 |
|---|---|
| 相邻两点在图谱里有**同向** `NEXT` 边 | 实线 + 箭头 marker + `data-from` / `data-to` + 来源 `doc_id` |
| 没有这段边（含只有反方向边） | 虚线、**没有箭头**、`data-missing="1"` + `data-missing-from` / `data-missing-to`，并标注「图谱未收录该段」 |
| 节点不在 `graph_nodes.csv` 里 | 虚线框 + 说明「虚线框＝图谱未收录该节点」 |

**布局确定性（x/y 只是排版）**

- 第一天在最上，天内严格按 `node_ids` 顺序，一行一个节点，箭头向下；
- 只按天分组，**跨天之间不画箭头**（避免暗示资料支持跨天连接）；
- 访客 `svg` 480×H、评审 640×H（多出的一列放节点 id），高度由
  `16 + Σ(34 + 52×节点数 + 30×(节点数−1) + 18)` 算出，没有随机量、没有脚本测量；
- 方框的上下位置只表示资料里的先后顺序——**不是方位、不是比例尺**。

**按天配色（≥3 天可区分，不只靠颜色）**

| 天 | 描边 / 箭头 / 天标题 | 天底色 |
|---|---|---|
| 第 1 天 | `#1E6B34`（5.83:1） | `#E8F5EC` |
| 第 2 天 | `#1F5FA8`（5.60:1） | `#E7F0FB` |
| 第 3 天 | `#8A5A00`（5.41:1） | `#FFF4D6` |
| 第 4 天 | `#A12622`（6.52:1） | `#FDECEA` |

第 5 天起循环使用同四组色，但每天都有可见文字「第 N 天 · N 个节点」+ `data-day`，
所以不靠颜色也能分辨；节点名始终是 `#1A2028`（白底 16.39:1）。
四组色值直接取 PRODUCT_SPEC §5.3 的四状态色，不新增色板。

**可点 / 无障碍（无 JS）**

- 每个节点一个 `<g data-node-id="…">`，首个子元素 `<title>` 与 `aria-label`
  都是**节点全名**，节点名包在 `<a href="#stop-<node_id>">` 里；
- `#stop-<node_id>` 锚点落在该停留点的来源卡片区（`_visitor_body.html` 里
  `.point-evidence` 的第一次出现处，用 `namespace` 去重，不会产生重复 id）；
  **如果该停留点没有出现在分时行程里，就暂时没有目标元素**（点击不跳转，
  但不报错）——这是已知限制，见 §12，T3.5 时间线可以复用同一套 `#stop-<id>`；
- 每条箭头是 `<g data-from="<src>" data-to="<dst>">`，可以直接拿回
  `graph_edges.csv` 逐条核对同向 `NEXT` 边；
- 示意图外层是 `<details class="diagram-block">`（访客默认折叠、评审默认展开），
  `summary` 文案「查看路线示意（图谱顺序，不是地图）」；
- 滚动容器 `role="region"` + `tabindex="0"`，键盘可横向滚动；
- 模板里没有任何脚本标签、没有外部图片/字体/瓦片，断网也能看。

**复现验证（Flask test client + 真实图谱，不调模型）**

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$py = ".\.venv\Scripts\python.exe"
& $py -c "import sys; sys.path.insert(0, 'analysis/p07_agent/src'); import web_app; print('doc', web_app.DOC_COUNT)"
```

断言要点（父 Agent 可独立复算）：箭头数 = 相邻对数；每条 `data-from/data-to`
都能在 `graph_edges.csv` 找到 `rel=NEXT` 且 `src/data-from、dst/data-to` 一致的行；
故意插入一段图谱里没有的相邻点后，页面**不出现该段的箭头**、只出现
`data-missing` 与「图谱未收录该段」。

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

T3.4 完成时：check 通过，137 条测试 OK（T3.2 完成时为 121 条）。
T3.3 完成时同样是 check 通过 + **137 条测试 OK**（只新增模板与渲染接线，没改测试）。

## 11. 截图复现（T3.2 / T3.4 / T3.3）

七张截图都由**真实 Flask 模板**渲染，不是手工 HTML；fixture 数据不调用模型：

| 文件 | 视口 | 尺寸 | 说明 |
|---|---|---|---|
| `visitor_375.png` | 375 CSS px | 375×3371 | T3.2 访客视图整页 |
| `visitor_1280.png` | 1280 CSS px | 1280×2313 | T3.2 访客视图整页 |
| `auditor_1280.png` | 1280 CSS px | 1280×4386 | T3.2 评审视图整页 |
| `evidence_375.png` | 375 CSS px | 375×8610 | T3.4 访客视图：证据卡展开态（含「未找到来源」卡） |
| `evidence_1280.png` | 1280 CSS px | 1280×5400 | T3.4 访客视图：证据卡展开态（含「未找到来源」卡） |
| `diagram_375.png` | 375 CSS px | 375×3591 | T3.3 访客视图：路线示意图展开态（白云山 BYS-T-02 链） |
| `diagram_1280.png` | 1280 CSS px | 1280×2663 | T3.3 访客视图：路线示意图展开态（白云山 BYS-T-02 链） |

T3.4 两张图的 fixture：`tools.get_route_candidates('广州白云山')` 的真实 NEXT 连接
（白云山南门 → 云台花园 → 缆车上山 → 山顶广场 → 摩星岭，来源 `BYS-T-02`）+
`validate_route()` + `route_metrics()` + `build_itinerary()`；其中 **白云山南门** 是
T1.6 `scan_coverage()` 报告的 `missing_quote` 节点（BYS-T-02 / BYS-T-03 都定位不到节点名），
用来展示「未找到来源」。**截图不代表一次真实 `run_agent` 输出。**

T3.3 两张图用的是同一条链（与任务书的 fixture 一致：
`POI|广州白云山|白云山南门` → `POI|广州白云山|云台花园` → `ACTIVITY|缆车上山` →
`POI|广州白云山|山顶广场` → `POI|广州白云山|摩星岭`），四段**都**能在
`graph_edges.csv` 找到同向 `NEXT` 边（前三段 `BYS-T-02`，最后一段 `BYS-T-02` + `BYS-T-03`），
所以图上 4 条箭头全是真实连接、没有一段是虚构的。
**截图不代表一次真实 `run_agent` 输出。**

> 证据入口默认折叠（§9.10）。为了在静态截图里看到卡片内容，T3.4 的截图脚本在
> **已渲染 HTML** 上给 `<details class="evidence">` 加 `open` 属性（等同用户手动展开，
> 不改内容、数据或样式；模板默认仍是折叠，测试断言 `details_open=0`）。
>
> T3.3 同理：示意图访客默认折叠，`diagram_375/1280.png` 由临时脚本在**已渲染 HTML** 上
> 给 `<details class="diagram-block">` 加 `open`（等同用户点开「查看路线示意」），
> 模板默认仍是折叠（评审视图默认展开，见 §9.11）。

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

# T3.4 证据卡（fixture 用白云山路线，并在响应里给 details.evidence 加 open 以便静态图看到卡片）
& $py $shot --url "$base/?view=visitor" --out "analysis\p07_agent\web\preview\evidence_375.png"  --width 375
& $py $shot --url "$base/?view=visitor" --out "analysis\p07_agent\web\preview\evidence_1280.png" --width 1280

# T3.3 路线示意图（fixture 用白云山 BYS-T-02 链，并在响应里给 details.diagram-block 加 open）
& $py $shot --url "$base/?view=visitor" --out "analysis\p07_agent\web\preview\diagram_375.png"  --width 375
& $py $shot --url "$base/?view=visitor" --out "analysis\p07_agent\web\preview\diagram_1280.png" --width 1280
```

3. 每张图必须记录工具原样打印的 `METRICS`。本次实测：

```text
visitor_375.png   METRICS {"innerWidth":375,"scrollWidth":375,"clientWidth":375,"scrollHeight":3371}
visitor_1280.png  METRICS {"innerWidth":1280,"scrollWidth":1280,"clientWidth":1280,"scrollHeight":2313}
auditor_1280.png  METRICS {"innerWidth":1280,"scrollWidth":1280,"clientWidth":1280,"scrollHeight":4386}
evidence_375.png  METRICS {"innerWidth":375,"scrollWidth":375,"clientWidth":375,"scrollHeight":8610}
evidence_1280.png METRICS {"innerWidth":1280,"scrollWidth":1280,"clientWidth":1280,"scrollHeight":5400}
diagram_375.png   METRICS {"innerWidth":375,"scrollWidth":375,"clientWidth":375,"scrollHeight":3591}
diagram_1280.png  METRICS {"innerWidth":1280,"scrollWidth":1280,"clientWidth":1280,"scrollHeight":2663}
```

375px 的 `scrollWidth` 等于 `clientWidth` 等于视口宽度 375，**没有横向滚动**
（T3.4 证据卡展开到最长摘句时同样成立；T3.3 示意图把 480px 宽的 `svg` 放进
`overflow-x: auto` 的容器里，页面仍不横向滚动）。
工具用 `Emulation.setDeviceMetricsOverride` 真正设置视口，而不是用 500px 布局裁切
（T3.1 §11 记录过本机无头 Chrome 的 500px 下限）。

## 12. 已知限制与后续

- 本任务不实现结果页持久化：视图切换会回到已回填输入框的首屏，再提交渲染另一视图；
  `?alt=` 高亮同理，等 T2.4 提供备选路线与结果缓存后生效。
- 证据卡（T3.4）只覆盖停留点与路线段：条件建议仍只显示 `doc_id` 列表，
  完整卡片按 PRODUCT_SPEC §6.4 等来源过滤（T2.5）后再接入。
- 分时行程（`itinerary.py`）没有 node_id，停留点按时段文案里出现的节点名做确定性
  匹配分组（长名优先）；因此同一节点在多个时段出现时会各显示一次证据入口。
- 路线示意图（T3.3）覆盖范围：只画 P7 路线里的 `proposal.node_ids`，按 `day_plan`
  分天；**跨天之间不画箭头**；图谱没有 `NEXT` 边的相邻两点只画虚线并标「图谱未收录该段」；
  节点链接 `#stop-<node_id>` 目前落在停留点来源卡片区，**没出现在分时行程里的停留在
  页面上暂时没有目标元素**（点击不跳转，不报错），T3.5 时间线可以复用同一套锚点补全；
  示意图不含纬度、经度、坐标、距离、步行时间，也不接任何地图瓦片。
- 条件建议的“选择理由”与 `needs_verification` 由后端给出，前端不推断。
- 页面没有实时票价、排队、天气、开放状态，也不提供预订、支付、导航或叫车服务。
