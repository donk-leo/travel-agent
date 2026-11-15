# -*- coding: utf-8 -*-
"""白云山采集脚本：按 ``data/raw/sources.csv`` 抓取原始页面并维护采集清单。

用法（在仓库根执行）::

    python scenic/baiyunshan/src/collect.py --dry-run
    python scenic/baiyunshan/src/collect.py
    python scenic/baiyunshan/src/collect.py --only BYS-O-01 BYS-O-02
    python scenic/baiyunshan/src/collect.py --force

设计要点：

1. 只用标准库（``urllib`` / ``csv`` / ``hashlib`` …），干净 clone + Python 3.11
   即可重放，不依赖 requests/bs4 等第三方包；
2. 每个站点抓取前先读 ``robots.txt``，结论写入 manifest 的 ``robots`` 列；
   ``disallowed`` 的 URL 不发起页面请求，直接记入 ``sources_rejected.csv``；
3. 请求间隔 ≥2 秒、超时 30 秒、最多重试 3 次（403/404/410 不重试）；
4. 小红书 3 条只做一次**无 cookie** 普通 GET，观察是否登录墙/空壳；被拦即记
   ``requires_login`` / ``login_wall``，不加载登录态、不模拟登录、不破解验证码；
5. 写盘纪律：``sha256`` 是落盘 HTML 文本（UTF-8）的 SHA256，``content_bytes``
   是传输解压后的响应体字节数，``raw_file`` 是相对仓库根的 posix 路径；
6. 硬护栏：脚本只写 ``data/raw/``，永不写 ``data/processed/``，不改 ``sources.csv``。

退出码：0 = 脚本跑完（个别页面失败看 manifest，不代表脚本失败）；
        1 = 环境/护栏/自身一致性错误；2 = 参数错误。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import http.client
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

log = logging.getLogger("baiyunshan.collect")

# ---------------------------------------------------------------------------
# 路径：src/ -> baiyunshan/ -> scenic/ -> 仓库根
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent
AREA_DIR = SRC_DIR.parent
REPO_ROOT = AREA_DIR.parent.parent
DATA_DIR = AREA_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_HTML_DIR = RAW_DIR / "html"
SOURCE_CSV = RAW_DIR / "sources.csv"
MANIFEST_CSV = RAW_DIR / "manifest.csv"
REJECTED_CSV = RAW_DIR / "sources_rejected.csv"
PROCESSED_DIR = DATA_DIR / "processed"  # 冻结数据目录：只用于护栏校验，永不写入

# ---------------------------------------------------------------------------
# 采集参数
# ---------------------------------------------------------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}
REQUEST_INTERVAL = 2.0          # 秒，任意两次 HTTP 请求之间的最小间隔
TIMEOUT = 30                    # 秒
RETRIES = 3                     # 最多尝试次数（含首次）
NO_RETRY_STATUS = {403, 404, 410}
TIME_FMT = "%Y-%m-%d %H:%M:%S"

MANIFEST_FIELDS = [
    "doc_id", "scenic_area", "doc_type", "title", "source_site", "source_url",
    "http_status", "content_bytes", "charset", "fetch_time", "sha256",
    "raw_file", "status", "error", "robots",
]
REJECTED_FIELDS = [
    "doc_id", "source_url", "source_site", "http_status", "reason", "detail",
    "attempted_at",
]
STATUS_ENUM = ("ok", "cached", "failed", "rejected")
ROBOTS_LABEL_RE = re.compile(r"^(allowed|disallowed|no_robots_txt|unavailable:\d{3})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# 小红书登录墙 / 空壳判定用标记（只在“页面不含笔记 ID”时才作为证据）
XHS_LOGIN_MARKERS = (
    "登录后查看", "请先登录", "请登录", "扫码登录", "手机号登录", "密码登录",
    "登录/注册", "立即登录", "login-container", "website-login", "login-box",
)

_last_request_at = 0.0
_robots_cache: dict[str, "RobotsInfo"] = {}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    """统一日志格式；Windows 控制台强制 UTF-8，避免中文乱码。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - 老环境兜底
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _now() -> str:
    return datetime.now().strftime(TIME_FMT)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel_repo(path: Path) -> str:
    """相对仓库根的 posix 路径；脚本被移动时退回绝对路径，便于排查。"""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _check_write_path(path: Path) -> None:
    """硬护栏：只允许写 data/raw/，且绝不写 sources.csv / data/processed/。"""
    resolved = path.resolve()
    if resolved == SOURCE_CSV.resolve():
        raise SystemExit(f"[护栏] 拒绝写入采集输入清单：{resolved}")
    processed = PROCESSED_DIR.resolve()
    if resolved == processed or processed in resolved.parents:
        raise SystemExit(f"[护栏] 拒绝写入冻结数据目录 data/processed：{resolved}")
    raw = RAW_DIR.resolve()
    if resolved != raw and raw not in resolved.parents:
        raise SystemExit(f"[护栏] 拒绝写入 data/raw 之外的路径：{resolved}")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """写 UTF-8-SIG CSV；即使 rows 为空也写表头（拒采清单需要空表头）。"""
    _check_write_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _read_sources() -> list[dict]:
    """读取采集清单（utf-8-sig，兼容 Excel 另存）。"""
    with open(SOURCE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"[错误] 采集清单为空：{SOURCE_CSV}")
    required = {"doc_id", "scenic_area", "doc_type", "title", "source_site", "source_url"}
    missing = required - set(rows[0].keys())
    if missing:
        raise SystemExit(f"[错误] sources.csv 缺少必需列：{sorted(missing)}")
    return rows


def _load_csv_index(path: Path) -> dict[str, dict]:
    """按 doc_id 建索引；文件不存在返回空表（首次采集）。"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return {row["doc_id"]: row for row in csv.DictReader(f) if row.get("doc_id")}


# ---------------------------------------------------------------------------
# HTTP 与解码
# ---------------------------------------------------------------------------
class FetchError(RuntimeError):
    """抓取失败；status 为真实 HTTP 状态码（网络层失败时为 None）。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _throttle() -> None:
    """保证任意两次请求间隔 ≥ REQUEST_INTERVAL 秒（礼貌采集）。"""
    global _last_request_at
    wait = REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _http_get(url: str) -> tuple[bytes, int, object, str]:
    """单次 GET，返回 (响应体字节, HTTP 状态, 响应头, 最终 URL)。

    只做传输层解压；不解码、不跟随非 HTTP 重定向（urllib 默认跟随 3xx）。
    """
    _throttle()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 0) or 0)
            headers = resp.headers
            final_url = resp.geturl()
    except urllib.error.HTTPError as exc:
        try:
            exc.read(4096)  # 丢弃错误页，仅用于释放连接
        except Exception:
            pass
        raise FetchError(f"HTTP {exc.code} {exc.reason}", status=int(exc.code))
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"{type(exc).__name__}: {reason}")

    encoding = (headers.get("Content-Encoding") or "").lower().strip()
    if encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise FetchError(f"gzip 解压失败：{exc}", status=status)
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw, status, headers, final_url


def _fetch_page(url: str) -> tuple[bytes, int, object, str]:
    """带重试的页面抓取；403/404/410 不重试。"""
    last: FetchError | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            return _http_get(url)
        except FetchError as exc:
            last = exc
            log.warning("抓取失败（第 %d/%d 次）：%s -> %s", attempt, RETRIES, url, exc)
            if exc.status in NO_RETRY_STATUS:
                break
    assert last is not None
    raise last


def _decode(raw: bytes, content_type: str) -> tuple[str, str]:
    """解码 HTML，返回 (文本, 编码名)。

    判定顺序：
    1. 整页是**合法 UTF-8** 且含汉字 -> 直接按 UTF-8（GBK/Big5 中文几乎不可能整页
       都是合法 UTF-8，这个信号比响应头可信）；
    2. 响应头 / meta 声明的编码严格解码成功 -> 采用（跳过 latin-1 这类“什么都能解”的
       编码，因为它会把 GBK 解成乱码）；
    3. 以上都不行时，把所有候选编码试一遍，用“汉字数 - 乱码数”打分取最高。
    """
    declared: list[str] = []
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if match:
        declared.append(match.group(1).lower())
    for meta in re.finditer(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:8192], re.I):
        declared.append(meta.group(1).decode("ascii", "ignore").lower())

    def score(text: str) -> int:
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        bad = text.count("\ufffd")
        mojibake = len(re.findall(r"[\u00c0-\u00ff]", text))
        return cjk * 2 - bad * 50 - mojibake * 3

    # 1) 合法 UTF-8 优先
    try:
        utf8_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        if not utf8_text.strip():
            return utf8_text, "utf-8"
        if re.search(r"[\u4e00-\u9fff]", utf8_text) or not re.search(r"[^\x00-\x7f]", utf8_text):
            return utf8_text, "utf-8"

    # 2) 声明编码严格解码
    loose = {"latin-1", "latin1", "iso-8859-1", "windows-1252", "ascii", "us-ascii"}
    for enc in declared:
        if enc in loose:
            continue
        try:
            text = raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
        if score(text) > 0:
            return text, enc

    # 3) 打分兜底
    candidates = declared + ["utf-8", "gb18030", "gbk", "big5", "latin-1"]
    best: tuple[int, str, str] | None = None
    seen: set[str] = set()
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            text = raw.decode(enc)
        except LookupError:
            continue
        except UnicodeDecodeError:
            text = raw.decode(enc, "replace")
            if text.count("\ufffd") > len(text) * 0.01:
                continue
        value = score(text)
        if best is None or value > best[0]:
            best = (value, text, enc)
    if best is None:
        return raw.decode("utf-8", "replace"), "utf-8(replace)"
    return best[1], best[2]


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------
class RobotsInfo:
    """某站点的 robots 结论；label 为 ok 时按规则对具体 URL 判定。"""

    def __init__(self, label: str, rules: list[tuple[bool, str]] | None = None):
        self.label = label
        self.rules = rules or []

    def verdict(self, url: str) -> str:
        if self.label != "ok":
            return self.label
        parts = urllib.parse.urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        return "allowed" if _robots_allows(self.rules, target) else "disallowed"


def _robots_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def parse_robots(text: str) -> list[tuple[bool, str]]:
    """解析 robots.txt 中 ``User-agent: *`` 组的 Allow/Disallow 规则。"""
    groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if rules:  # 上一条规则属于上一组，收尾
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif field in ("allow", "disallow") and agents and value:
            rules.append((field == "allow", value))
    if agents:
        groups.append((agents, rules))

    merged: list[tuple[bool, str]] = []
    for group_agents, group_rules in groups:
        if "*" in group_agents:
            merged.extend(group_rules)
    return merged


def _robots_pattern_match(pattern: str, target: str) -> bool:
    if "*" not in pattern and not pattern.endswith("$"):
        return target.startswith(pattern)
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "^" + ".*".join(re.escape(part) for part in body.split("*"))
    if anchored:
        regex += "$"
    return re.match(regex, target) is not None


def _robots_allows(rules: list[tuple[bool, str]], target: str) -> bool:
    """最长匹配优先；同长度时 Allow 优先；无命中视为允许。"""
    best_len = -1
    best_allow = True
    for allow, pattern in rules:
        if _robots_pattern_match(pattern, target):
            specificity = len(pattern.replace("*", "").rstrip("$"))
            if specificity > best_len or (specificity == best_len and allow):
                best_len = specificity
                best_allow = allow
    return best_allow if best_len >= 0 else True


def _load_robots(url: str) -> RobotsInfo:
    """取一次站点 robots.txt 并在本次运行内缓存（按 origin）。"""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin in _robots_cache:
        return _robots_cache[origin]

    robots_url = _robots_url(url)
    info: RobotsInfo
    try:
        raw, status, _headers, _final = _http_get(robots_url)
    except FetchError as exc:
        label = "no_robots_txt" if exc.status in (404, 410) else f"unavailable:{exc.status or 0:03d}"
        info = RobotsInfo(label)
        log.info("robots.txt 不可用：%s -> %s（%s）", robots_url, label, exc)
    else:
        if status == 200:
            text = raw.decode("utf-8", "replace")
            if not text.strip():
                info = RobotsInfo("no_robots_txt")
                log.info("robots.txt 为空文件：%s -> no_robots_txt", robots_url)
            else:
                info = RobotsInfo("ok", parse_robots(text))
                log.info("robots.txt 已读取：%s（%d 条规则）", robots_url, len(info.rules))
        else:
            info = RobotsInfo(f"unavailable:{status:03d}")
            log.info("robots.txt 返回 HTTP %s：%s", status, robots_url)
    _robots_cache[origin] = info
    return info


# ---------------------------------------------------------------------------
# 小红书判定（只观察，不绕登录）
# ---------------------------------------------------------------------------
def _is_xiaohongshu(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host.endswith("xiaohongshu.com")


def _xhs_note_id(url: str) -> str:
    match = re.search(r"/explore/([0-9A-Za-z]+)", urllib.parse.urlsplit(url).path)
    return match.group(1) if match else ""


def _xhs_block_reason(
    src_url: str, final_url: str, status: int, text: str, expected_title: str = ""
) -> tuple[str, str] | None:
    """判断小红书是否被登录墙/空壳拦住；返回 (reason, detail) 或 None。

    只有同时满足「HTML 含笔记 ID」+「含笔记标题或笔记状态对象」才算拿到正文；
    仅凭 URL/ID 出现（可能在 canonical、脚本配置里）不算，避免把空壳当成功。
    """
    if status in (401, 403, 461):
        return "requires_login", f"HTTP {status}：未登录请求被拒，未加载任何登录态"
    final = urllib.parse.urlsplit(final_url)
    if "login" in final.netloc.lower() or "login" in final.path.lower() or "passport" in final.netloc.lower():
        return "login_wall", f"被重定向到登录页：{final_url}"

    note_id = _xhs_note_id(src_url)
    id_present = bool(note_id) and note_id in text
    title_core = expected_title.split(" - ")[0].strip() if expected_title else ""
    title_present = bool(title_core) and title_core in text
    state_present = any(key in text for key in ('"noteId"', "noteDetailMap", '"noteDetail"'))
    has_content = id_present and (title_present or state_present)
    markers = [marker for marker in XHS_LOGIN_MARKERS if marker in text]
    if markers and not has_content:
        return "login_wall", (
            f"页面出现登录提示 {markers[:3]} 且未包含笔记正文（笔记 ID {note_id or '(未知)'}）；"
            "按约定不加载登录态/cookie"
        )
    if not has_content:
        return "requires_login", (
            f"无 cookie 只拿到不含笔记正文的空壳页（{len(text)} 字符，"
            f"未命中笔记 ID/标题/状态对象：{note_id or '(未知)'}）；"
            "按约定不加载登录态/cookie"
        )
    return None


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def _validate_manifest(rows: list[dict], sources: list[dict], require_all: bool) -> list[str]:
    """校验 manifest 自洽，返回错误信息列表（空 = 通过）。

    ``require_all=True`` 时要求覆盖 sources.csv 全部 doc_id；``--only`` 增量采集时
    允许只含部分行，但顺序仍必须与 sources.csv 一致。
    """
    problems: list[str] = []
    expected_all = [src["doc_id"] for src in sources]
    got = [row.get("doc_id", "") for row in rows]
    expected = [doc_id for doc_id in expected_all if doc_id in set(got)]
    if require_all and set(got) != set(expected_all):
        missing = sorted(set(expected_all) - set(got))
        problems.append(f"manifest 未覆盖全部 doc_id，缺少：{missing}")
    if got != expected:
        problems.append(f"doc_id 顺序/覆盖不符：期望 {expected}，实际 {got}")
    for row in rows:
        doc_id = row.get("doc_id", "?")
        status = row.get("status", "")
        if status not in STATUS_ENUM:
            problems.append(f"{doc_id}: status 非法 {status!r}")
        robots = row.get("robots", "")
        if not ROBOTS_LABEL_RE.match(robots or ""):
            problems.append(f"{doc_id}: robots 非法 {robots!r}")
        if status in ("ok", "cached"):
            try:
                http_status = int(row.get("http_status", ""))
            except (TypeError, ValueError):
                problems.append(f"{doc_id}: http_status 不是数字 {row.get('http_status')!r}")
                http_status = 0
            if http_status <= 0:
                problems.append(f"{doc_id}: http_status 应为真实正数")
            try:
                nbytes = int(row.get("content_bytes", ""))
            except (TypeError, ValueError):
                problems.append(f"{doc_id}: content_bytes 不是数字 {row.get('content_bytes')!r}")
                nbytes = 0
            if nbytes <= 0:
                problems.append(f"{doc_id}: content_bytes 应 > 0")
            if not SHA256_RE.match(row.get("sha256", "")):
                problems.append(f"{doc_id}: sha256 不是 64 位小写 hex")
            try:
                datetime.strptime(row.get("fetch_time", ""), TIME_FMT)
            except (TypeError, ValueError):
                problems.append(f"{doc_id}: fetch_time 无法按 {TIME_FMT} 解析")
            if not row.get("raw_file", ""):
                problems.append(f"{doc_id}: raw_file 为空")
        elif status in ("failed", "rejected"):
            if not row.get("error", ""):
                problems.append(f"{doc_id}: 失败/拒采行 error 为空")
    return problems


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _dry_run(sources: list[dict]) -> int:
    print(f"[dry-run] sources.csv = {_rel_repo(SOURCE_CSV)}（{len(sources)} 条）")
    print("[dry-run] 不发起任何网络请求、不写任何文件；robots.txt 将在正式采集前逐站读取。")
    for index, src in enumerate(sources, 1):
        doc_id = src["doc_id"]
        url = src["source_url"]
        target = _rel_repo(RAW_HTML_DIR / f"{doc_id}.html")
        exists = "已存在" if (RAW_HTML_DIR / f"{doc_id}.html").exists() else "待抓取"
        login = "需登录态（仅尝试一次无 cookie GET）" if _is_xiaohongshu(url) else "否"
        print(f"  {index}/{len(sources)}  {doc_id}  {url}")
        print(f"        -> {target}  [{exists}]  login={login}")
    xhs = sum(1 for src in sources if _is_xiaohongshu(src["source_url"]))
    print(f"[dry-run] 共 {len(sources)} 条（其中小红书 {xhs} 条）；未写文件、未发请求，退出 0。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="白云山采集：按 data/raw/sources.csv 抓取原始页并维护 manifest.csv",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印采集计划，不发请求、不写文件")
    parser.add_argument("--only", nargs="*", default=None, help="只采集指定 doc_id（可多个）")
    parser.add_argument("--force", action="store_true", help="已有原始 HTML 时仍重新抓取")
    args = parser.parse_args(argv)

    setup_logging()
    if not SOURCE_CSV.exists():
        log.error("采集清单不存在：%s", SOURCE_CSV)
        return 1

    all_sources = _read_sources()
    ids = [src["doc_id"] for src in all_sources]
    if args.only:
        unknown = sorted(set(args.only) - set(ids))
        if unknown:
            log.error("--only 指定了 sources.csv 中不存在的 doc_id：%s", unknown)
            return 2
        selected_ids = set(args.only)
        sources = [src for src in all_sources if src["doc_id"] in selected_ids]
    else:
        sources = all_sources

    if args.dry_run:
        return _dry_run(sources)

    # 正式采集：先记录输入清单摘要，结束时复验未被改动
    digest_before = _sha256_bytes(SOURCE_CSV.read_bytes())
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)

    previous = _load_csv_index(MANIFEST_CSV)
    previous_rejected = _load_csv_index(REJECTED_CSV)
    log.info("待采集 %d / %d 条；已有 manifest 行 %d", len(sources), len(all_sources), len(previous))

    rows: list[dict] = []
    new_rejected: dict[str, dict] = {}

    for index, src in enumerate(sources, 1):
        doc_id = src["doc_id"]
        url = src["source_url"]
        out_file = RAW_HTML_DIR / f"{doc_id}.html"
        attempted_at = _now()
        base = {
            "doc_id": doc_id,
            "scenic_area": src["scenic_area"],
            "doc_type": src["doc_type"],
            "title": src["title"],
            "source_site": src["source_site"],
            "source_url": url,
        }

        # 已有快照且未要求 --force：直接复用，不发请求。
        # 必须同时有上次 manifest 的真实 http_status，避免在清单丢失时凭空补状态码。
        old = previous.get(doc_id, {})
        if out_file.exists() and not args.force and old.get("http_status"):
            raw = out_file.read_bytes()
            log.info("[%d/%d] 已存在，复用 %s", index, len(sources), doc_id)
            rows.append({
                **base,
                "http_status": old.get("http_status", ""),
                "content_bytes": old.get("content_bytes") or len(raw),
                "charset": old.get("charset") or "utf-8",
                "fetch_time": old.get("fetch_time")
                or datetime.fromtimestamp(out_file.stat().st_mtime).strftime(TIME_FMT),
                "sha256": _sha256_bytes(raw),
                "raw_file": _rel_repo(out_file),
                "status": "cached",
                "error": "",
                "robots": old.get("robots") or "unavailable:000",
            })
            continue

        # 1) robots
        robots_info = _load_robots(url)
        robots_label = robots_info.verdict(url)
        if robots_label == "disallowed":
            detail = (
                f"robots.txt（{_robots_url(url)}，HTTP 200）对目标路径 Disallow；"
                "按约定不发起页面请求"
            )
            log.warning("[%d/%d] 拒采（robots）：%s", index, len(sources), doc_id)
            rows.append({
                **base,
                "http_status": "",
                "content_bytes": 0,
                "charset": "",
                "fetch_time": attempted_at,
                "sha256": "",
                "raw_file": "",
                "status": "rejected",
                "error": f"robots_disallowed: {detail}"[:300],
                "robots": robots_label,
            })
            new_rejected[doc_id] = {
                "doc_id": doc_id,
                "source_url": url,
                "source_site": src["source_site"],
                "http_status": "",
                "reason": "robots_disallowed",
                "detail": detail[:300],
                "attempted_at": attempted_at,
            }
            continue

        # 2) 页面抓取
        try:
            raw, http_status, headers, final_url = _fetch_page(url)
        except FetchError as exc:
            reason = "http_error" if exc.status else "network_error"
            detail = str(exc)[:300]
            log.error("[%d/%d] 失败 %s -> %s", index, len(sources), doc_id, detail)
            rows.append({
                **base,
                "http_status": exc.status if exc.status else "",
                "content_bytes": 0,
                "charset": "",
                "fetch_time": attempted_at,
                "sha256": "",
                "raw_file": "",
                "status": "failed",
                "error": f"{reason}: {detail}"[:300],
                "robots": robots_label,
            })
            new_rejected[doc_id] = {
                "doc_id": doc_id,
                "source_url": url,
                "source_site": src["source_site"],
                "http_status": exc.status if exc.status else "",
                "reason": reason,
                "detail": detail,
                "attempted_at": attempted_at,
            }
            continue

        content_type = headers.get("Content-Type", "") if headers is not None else ""
        text, charset = _decode(raw, content_type)
        nbytes = len(raw)

        # 3) 小红书：只观察，不绕登录
        if _is_xiaohongshu(url):
            blocked = _xhs_block_reason(url, final_url, http_status, text, src.get("title", ""))
            if blocked is not None:
                reason, detail = blocked
                log.warning("[%d/%d] 拒采（小红书 %s）：%s", index, len(sources), reason, doc_id)
                rows.append({
                    **base,
                    "http_status": http_status,
                    "content_bytes": nbytes,
                    "charset": charset,
                    "fetch_time": attempted_at,
                    "sha256": "",
                    "raw_file": "",
                    "status": "rejected",
                    "error": f"{reason}: {detail}"[:300],
                    "robots": robots_label,
                })
                new_rejected[doc_id] = {
                    "doc_id": doc_id,
                    "source_url": url,
                    "source_site": src["source_site"],
                    "http_status": http_status,
                    "reason": reason,
                    "detail": detail[:300],
                    "attempted_at": attempted_at,
                }
                continue

        # 4) 落盘（UTF-8 字节，避免 Windows 文本模式改写换行导致 sha256 与落盘不一致）
        if nbytes == 0 or not text.strip():
            detail = f"HTTP {http_status} 但响应体为空（{nbytes} bytes）"
            log.error("[%d/%d] 失败 %s -> %s", index, len(sources), doc_id, detail)
            rows.append({
                **base,
                "http_status": http_status,
                "content_bytes": nbytes,
                "charset": charset,
                "fetch_time": attempted_at,
                "sha256": "",
                "raw_file": "",
                "status": "failed",
                "error": f"empty_response: {detail}"[:300],
                "robots": robots_label,
            })
            new_rejected[doc_id] = {
                "doc_id": doc_id,
                "source_url": url,
                "source_site": src["source_site"],
                "http_status": http_status,
                "reason": "empty_response",
                "detail": detail,
                "attempted_at": attempted_at,
            }
            continue

        _check_write_path(out_file)
        out_file.write_bytes(text.encode("utf-8"))
        sha = _sha256_bytes(out_file.read_bytes())
        log.info(
            "[%d/%d] OK %s  HTTP %s  %d bytes  %s  笔记ID=%s",
            index, len(sources), doc_id, http_status, nbytes, charset,
            _xhs_note_id(url) or "-",
        )
        rows.append({
            **base,
            "http_status": http_status,
            "content_bytes": nbytes,
            "charset": charset,
            "fetch_time": attempted_at,
            "sha256": sha,
            "raw_file": _rel_repo(out_file),
            "status": "ok",
            "error": "",
            "robots": robots_label,
        })

    # 5) 增量合并：按 doc_id 合并旧 manifest，输出仍按 sources.csv 顺序
    merged = {**previous, **{row["doc_id"]: row for row in rows}}
    ordered = [merged[src["doc_id"]] for src in all_sources if src["doc_id"] in merged]

    problems = _validate_manifest(ordered, all_sources, require_all=not args.only)
    if problems:
        for problem in problems:
            log.error("[自检] %s", problem)
        log.error("manifest 自检未通过，未写入清单；请修复后重跑。")
        return 1

    # 6) 拒采清单：只保留当前 manifest 中 failed/rejected 的行
    rejected_map = {**previous_rejected, **new_rejected}
    rejected_rows: list[dict] = []
    for src in all_sources:
        doc_id = src["doc_id"]
        row = merged.get(doc_id)
        if not row or row.get("status") not in ("failed", "rejected"):
            continue
        record = rejected_map.get(doc_id)
        if record is None:
            record = {
                "doc_id": doc_id,
                "source_url": src["source_url"],
                "source_site": src["source_site"],
                "http_status": row.get("http_status", ""),
                "reason": "unknown",
                "detail": row.get("error", "")[:300],
                "attempted_at": row.get("fetch_time", ""),
            }
        rejected_rows.append(record)

    _write_csv(MANIFEST_CSV, ordered, MANIFEST_FIELDS)
    _write_csv(REJECTED_CSV, rejected_rows, REJECTED_FIELDS)

    # 7) 输入清单未被改动
    digest_after = _sha256_bytes(SOURCE_CSV.read_bytes())
    if digest_before != digest_after:
        log.error("sources.csv 在采集过程中被改动（sha256 不一致），请立即检查！")
        return 1

    ok = sum(1 for row in ordered if row["status"] in ("ok", "cached"))
    ok_new = sum(1 for row in ordered if row["status"] == "ok")
    ok_cached = sum(1 for row in ordered if row["status"] == "cached")
    failed = sum(1 for row in ordered if row["status"] == "failed")
    rejected = sum(1 for row in ordered if row["status"] == "rejected")
    log.info(
        "采集结束：成功 %d / %d（ok %d，cached %d），失败 %d，拒采 %d",
        ok, len(ordered), ok_new, ok_cached, failed, rejected,
    )
    log.info("清单 -> %s；拒采 -> %s", _rel_repo(MANIFEST_CSV), _rel_repo(REJECTED_CSV))
    if failed or rejected:
        log.warning("存在失败/拒采条目，详见 sources_rejected.csv；不伪造任何状态码或正文。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
