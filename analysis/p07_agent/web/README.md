# P7 前端设计系统（T3.1）

T3.2 双视图（访客视图 / 评审视图）复用的设计系统、Jinja2 基础模板与响应式样式表。
本任务**不接线**：`analysis/p07_agent/src/web_app.py` 仍是旧的 `render_template_string` 页面，
模板与静态文件由 T3.2 接入。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `static/style.css` | 唯一样式表：`:root` 调色板、移动优先、`@media (max-width: 480px)` 断点 |
| `web/templates/base.html` | 基础模板：页头、状态徽标区、免责句区、`{% block content %}`、页脚限制 |
| `web/templates/_status_badge.html` | 四状态徽标宏（图标 + 文字 + 颜色三重编码），未知状态回退 `error` |
| `web/preview/result_preview.html` | 静态预览页（引用 `../../static/style.css`），全部数据标注为示例 |
| `web/preview/screenshot_375.png` | 375 CSS px 视口、整页截图（375×4295） |
| `web/preview/screenshot_1280.png` | 1280 CSS px 视口、整页截图（1280×3003） |
| `web/README.md` | 本文件：调色板、对比度复算、断点、T3.2 接线 |

## 2. 设计口径（先读）

- 文案与配色依据 `docs/optimization/PRODUCT_SPEC.md`：§5.2 固定免责句、§5.3 四状态配色、
  §5.6 连接核验与行程可行分开、§9 N3/N4/N5/N6/N7。
- **四状态色值与 §5.3 逐字一致，未做任何微调**（因此没有“原值/新值”差异需要记录）。
- **访客优先（Q1 已签字）**：`base.html` 不放 intent JSON、trace、图谱指标；
  这些只允许出现在 T3.2 评审视图的子模板里。
- **零外部资源**：样式表不引用任何外部字体、图标、脚本、CDN；
  图标全部是 Unicode 字符（✅ ⚠️ ❓ ❌ ✔ ▶ ○），字体只用系统栈。
- **无 JS 也能读**：所有内容都是服务端渲染的静态 HTML；预览页不含任何脚本。

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

未知状态（含 `working`、`reply`、空值、`None`）按 §5.4 **回退为 `error` 样式**，
不会默认成 `verified`。徽标宏的 `data-status` 属性便于 T3.2 定位与验收。

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
| 页面次要文字 `.muted` / `.status-badge__desc` / `.site-tagline` | `#4A5560` | `#F5F7F9` | 7.09:1 |
| 卡片内次要文字 `.muted` / `.day-meta` / `.period__label` | `#4A5560` | `#FFFFFF` | 7.61:1 |
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
| 基础 | 默认（含 375px） | 单列；容器 `width: 100%` + `max-width`；按钮/输入框整宽；证据卡单列 |
| `@media (min-width: 40em)` | ≥640px | 页头改横向两栏；`h1` 1.875rem；表单/卡片加大内边距 |
| `@media (min-width: 64em)` | ≥1024px | 版心 68rem；行程的三个时段改为 3 列 |
| `@media (max-width: 480px)` | ≤480px | 页面内边距收紧；状态徽标紧凑；操作按钮整行 |
| `@media (prefers-reduced-motion: reduce)` | 系统设置 | 关闭全部过渡与动画，`scroll-behavior: auto` |

断点全部用 `em`/`max-width` 表达，没有对页面元素写 `width: <N>px` 的固定宽度。

## 7. 375px 无横向滚动的实现约束

- 容器：`.wrap { width: 100%; max-width: 68rem; }`，内边距用 `padding-inline` + `box-sizing: border-box`；
- 文本：标题/段落 `overflow-wrap: break-word`，长串（`pre`、`code`、引文）`overflow-wrap: anywhere`；
- `pre`：`white-space: pre-wrap` + `overflow-x: auto`，不会撑破页面；
- 表格：`width: 100%`，外层 `.table-scroll` 可横向滚动（T3.2 在评审视图用）；
- 图片：`max-width: 100%; height: auto`（本项目不使用图片）；
- 全表扫描：`style.css` 中唯一的 px 宽度是 `.visually-hidden` 的 `1px`，其余宽度均为 `%` 或 `rem`；
- 实测（CDP `Emulation.setDeviceMetricsOverride` 宽度 375）：
  `window.innerWidth = 375`、`documentElement.scrollWidth = 375`、`clientWidth = 375`，
  即 **scrollWidth 等于视口宽度，没有横向滚动**；整页 `scrollHeight = 4295`。
  1280 视口同理（`scrollWidth = 1280`，`scrollHeight = 3003`）。

## 8. 无障碍

- 焦点：全局 `:focus-visible { outline: 3px solid #0B5FB4; outline-offset: 2px; }`，
  对白底 6.34:1（≥3:1）；跳转链接 `跳到主要内容` 在聚焦时出现；
- 表单：预览页的 `<textarea>` 有可见 `<label for>` 与 `aria-describedby` 提示；
- 状态：徽标有可见中文文字 + `visually-hidden` 的“状态：”前缀，图标 `aria-hidden`；
  `.status-area` 带 `aria-live="polite"`；进度区文字随阶段变化，不只靠颜色；
- 触控：按钮、chip、`summary` 的 `min-height: 2.75rem`（44px），输入框字号 16px；
- 对比度：见 §5；`prefers-reduced-motion` 关闭动效；页面不依赖 JS。

固定免责句 `核验通过只证明连接有据，不证明一天走得完` 在 `base.html` 与预览页中都是
**可见正文**（不是 `title`/`aria-label`），字号 1rem（≥14px），与正文同色 `#1A2028`；
仅在 `verified` / `partial` 出现。

## 9. T3.2 如何接线

### 9.1 Flask 的 `template_folder` / `static_folder`

`src/web_app.py` 目前用 `render_template_string`。T3.2 改成：

```python
from pathlib import Path
from flask import Flask, render_template

BASE_DIR = Path(__file__).resolve().parents[1]   # analysis/p07_agent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "web" / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

@app.route("/")
def home():
    return render_template("result.html", status="verified", status_reason="")
```

`base.html` 用 `url_for('static', filename='style.css')` 生成样式表地址；
按上面的写法默认得到 `/static/style.css`，不需要额外路由。
`template_folder` / `static_folder` 用绝对路径，避免 `src/` 与工作目录不一致时找不到文件。

### 9.2 模板约定

- 子模板第一行 `{% extends "base.html" %}`；必需块名照抄：`{% block title %}`、`{% block content %}`。
- 基础模板已渲染：页头、状态徽标区（`{% block status %}`）、免责句区（`{% block disclaimer %}`）、
  页脚限制。子模板只需填 `content`。
- 结果页传入 `status`（四值之一）与可选的 `status_reason`：
  - `verified` / `partial`：徽标 + 免责句自动出现；
  - `clarify` / `error`：只出徽标，不出免责句；
  - 未传或未知：不渲染徽标——T3.2 必须按 §5.4 把缺失值映射成 `error` 再传入。
- 访客视图的 `content` 顺序按 §4.1：查询区 → 进度区 → 人群提示 → 行程可行性 →
  行程卡（`itinerary.days[].periods[]`）→ 证据入口 → 地点列表（`poi_results`）→
  建议（`suggestions`）→ 可修改操作。
- 评审视图新建 `web/templates/auditor.html` 同样 `extends "base.html"`，在 `content` 里放
  `intent_json`、`decision`、`tool_decisions`、逐段核验表、图谱指标、`trace_json`。
  **不要**把这些放进 `base.html`（Q1：访客视图不显示 JSON 与图谱指标）。
- 若要自定义状态区，覆盖 `{% block status %}` / `{% block disclaimer %}`，并在子模板里
  `{% from "_status_badge.html" import status_badge %}` 后调用宏。
- 静态预览页 `web/preview/result_preview.html` 是纯 HTML，可直接对照它搬运 class 与结构；
  它不参与 Flask 渲染，也不含 Jinja 语法。

### 9.3 文件位置速查

```
analysis/p07_agent/
├─ static/style.css
└─ web/
   ├─ templates/base.html
   ├─ templates/_status_badge.html
   └─ preview/result_preview.html
```

## 10. 本地校验

外部资源：按 T3.1 验收口径扫描 `web/` 与 `static/` 下所有 `.html / .css / .md / .js / .svg`，
协议前缀出现次数均为 0；本 README、两个模板、样式表与预览页都不含外部地址
（字体只用系统栈，图标只用 Unicode 字符）。

模板语法与渲染（Flask 测试上下文，不启动服务）：

```powershell
$py = ".\.venv\Scripts\python.exe"

& $py -c "from flask import Flask, render_template; from pathlib import Path; b=Path('analysis/p07_agent'); a=Flask('t', template_folder=str(b/'web/templates'), static_folder=str(b/'static')); c=a.test_request_context('/'); c.push(); print(len(render_template('base.html', status='verified'))); c.pop()"
```

## 11. 截图说明（环境限制，需 T3.8 复核）

- `screenshot_375.png`：375×4295，`screenshot_1280.png`：1280×3003，均为整页截图（PNG，合计约 524 KB）。
- 本机 Chrome 157 的 `--headless=new --window-size=375,900 --screenshot` 在 Windows 上会强制
  最小窗口宽度 500 CSS px：生成的 PNG 宽度是 375，但页面按 500px 布局后被裁切。
  因此这两张图不是在 500px 布局上裁的，而是用 Chrome DevTools Protocol 的
  `Emulation.setDeviceMetricsOverride` 把视口真正设成 375/1280 后、
  再用 `Page.captureScreenshot` 整页捕获的；同一会话里实测 `scrollWidth == clientWidth == 375`。
- 若 T3.8 用命令行 `--window-size=375` 复核，请先确认该环境的 Chrome 是否也有 500px 下限；
  有下限时以 CDP/DevTools 设备模式为准（流程与正文顺序不变）。
