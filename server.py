#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多站动漫资源 RSS 增强订阅服务

支持 动漫花园 / 蜜柑计划 / ACG.RIP / Nyaa / 萌番组 五个源，
统一清洗成干净 RSS，每条帖子自动提取：磁力链接、种子直链、帖子页、正文外链。
支持多源合并、跨站去重、关键词与标签过滤。

用法:
    python server.py                # 默认 0.0.0.0:8899
    PORT=9000 python server.py

订阅:
    http://<host>:8899/rss.xml
    http://<host>:8899/rss.xml?src=dmhy,mikan&keyword=青之箱&limit=30
"""

import gzip
import html
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sources as S

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# 部分云环境只解析到 IPv6 会导致 [Errno 101] Network is unreachable，
# 这里把 getaddrinfo 收敛到 IPv4 优先。
def _force_ipv4():
    _orig = socket.getaddrinfo

    def _v4(host, port, family=0, type=0, proto=0, flags=0):
        try:
            res = _orig(host, port, socket.AF_INET, type, proto, flags)
            if res:
                return res
        except socket.gaierror:
            pass
        return _orig(host, port, family, type, proto, flags)

    socket.getaddrinfo = _v4


try:
    _force_ipv4()
except Exception:
    pass

CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))
PORT = int(os.environ.get("PORT", "8899"))
HOST = os.environ.get("HOST", "0.0.0.0")
SITE_TITLE = "动漫资源 · 增强订阅"
MAX_MERGE = 800  # 合并后参与排序的上限, 防止多源过大

# ---------------------------------------------------------------- 文本清洗

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img[^>]*>", re.I)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
BARE_URL_RE = re.compile(r"""https?://[^\s<>"']+""")

SKIP_HOST_PARTS = (
    "tracker.", "t.acg.rip", "open.acgtracker", "nyaa.tracker",
    "tr.bangumi.moe", "bangumi.moe/tracker", "google-analytics", "googletagmanager",
)
SKIP_EXT = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico",
    ".css", ".js", ".woff", ".woff2",
)
SITE_HOSTS = ("share.dmhy.org", "mikanani.me", "acg.rip", "nyaa.si", "bangumi.moe")


def clean_text(s, limit=None):
    """HTML -> 可读纯文本"""
    if not s:
        return ""
    s = IMG_RE.sub(" ", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|tr|h\d)>", "\n", s, flags=re.I)
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    s = TAG_RE.sub("", s)
    s = re.sub(r"<[^>]*$", "", s)   # 源站正文被截断时残留的半截标签
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def extract_links(desc_html):
    """从正文里抽出有意义的外链（去重、去噪）"""
    if not desc_html:
        return []
    raw = HREF_RE.findall(desc_html) + BARE_URL_RE.findall(desc_html)
    out, seen = [], set()
    for h in raw:
        h = html.unescape(h).strip().rstrip(").,;）】")
        if not h.lower().startswith(("http://", "https://")):
            continue
        m = re.match(r"https?://([^/?#]+)", h)
        if not m:
            continue
        host = m.group(1).lower()
        if any(host.endswith(x) for x in SITE_HOSTS):
            continue
        if any(p in host for p in SKIP_HOST_PARTS):
            continue
        if h.lower().split("?")[0].endswith(SKIP_EXT):
            continue
        key = h.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out[:12]


def slim_magnet(url, title="", keep_tr=3):
    """磁力规整：btih 统一成 40 位 hex、补上显示名称、只留前几个 tracker。

    源站给的磁力有两个毛病，直接转发会明显影响可用性：
      1. 动漫花园用 base32 编码 btih（32 位），部分下载器只认 hex，统一转换；
      2. dn 参数经常缺失或为空串，下载器里就只剩一串哈希，看不出是什么番。
         用条目标题补上（urlencode，标题里的 & 和 # 不会破坏结构）。
    """
    if not url or not url.startswith("magnet:"):
        return url or ""
    m = re.search(r"btih:([0-9a-zA-Z]{32,40})", url, flags=re.I)
    if not m:
        return url
    ih = S.norm_infohash(m.group(1))
    if not ih or len(ih) != 40:
        return url

    dn = ""
    dm = re.search(r"[&?]dn=([^&]*)", url)
    if dm:
        dn = urllib.parse.unquote(dm.group(1)).strip()
    if not dn and title:
        dn = title.strip()

    parts = [f"magnet:?xt=urn:btih:{ih}"]
    if dn:
        parts.append("dn=" + urllib.parse.quote(dn, safe=""))
    for i, t in enumerate(re.findall(r"[&?]tr=([^&]*)", url)):
        if i >= keep_tr:
            break
        parts.append("tr=" + t)
    return "&".join(parts)


def pretty_time(pubdate):
    try:
        return parsedate_to_datetime(pubdate).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return (pubdate or "")[:25]


# ---------------------------------------------------------------- 抓取与缓存

_cache = {}
_cache_lock = threading.Lock()


def fetch_raw(url):
    """带 TTL 缓存抓取; 失败时回退到过期缓存"""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit["ts"] < CACHE_TTL:
            return hit["data"], "hit"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/xml, application/json, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = r.read()
        with _cache_lock:
            _cache[url] = {"ts": now, "data": data}
        return data, "fresh"
    except Exception:
        with _cache_lock:
            hit = _cache.get(url)
            if hit:
                return hit["data"], "stale"
        raise


def normalize(items):
    """补齐派生字段：正文外链、摘要、磁力瘦身"""
    for it in items:
        html_src = it.get("desc_html") or ""
        it["links"] = extract_links(html_src)
        it["summary"] = clean_text(html_src, 420)
        it["magnet"] = slim_magnet(it.get("magnet") or "", it.get("title") or "")
        if not it.get("infohash") and it["magnet"]:
            it["infohash"] = S.infohash_of(it["magnet"])
    return items


def gather(sids, params):
    """并发抓取多个源, 返回 (items, errors)"""
    jobs = []
    for sid in sids:
        for u in S.fetch_urls(sid, params):
            jobs.append((sid, u))

    items, errors = [], []

    def run(sid, url):
        raw, _how = fetch_raw(url)
        return normalize(S.parse_items(sid, raw, params))

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as ex:
        futs = {ex.submit(run, sid, u): (sid, u) for sid, u in jobs}
        for f in as_completed(futs):
            sid, _u = futs[f]
            try:
                items.extend(f.result())
            except Exception as e:
                errors.append(f"{S.BY_ID[sid]['name']}: {e.__class__.__name__} {e}")
    return items, errors


# ---------------------------------------------------------------- 归一化

def norm_title(t):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (t or "").lower())


def quality(it):
    s = 0
    if it["magnet"]:
        s += 4
    if it["torrent"]:
        s += 2
    if it["size"]:
        s += 1
    if it["seeders"] is not None:
        s += 1
    return s


def dedupe(items):
    """双键去重：infohash 相同（跨语言同种子）或标题相同（同语言重复发布）
    都视为同一条，合并时保留信息最全的，并把互补字段补进去。"""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_hash, by_title = {}, {}
    for i, it in enumerate(items):
        h = (it.get("infohash") or "").lower()
        if h:
            if h in by_hash:
                union(by_hash[h], i)
            else:
                by_hash[h] = i
        t = norm_title(it.get("title") or "")
        if t:
            if t in by_title:
                union(by_title[t], i)
            else:
                by_title[t] = i

    groups, order = {}, []
    for i, it in enumerate(items):
        r = find(i)
        if r not in groups:
            groups[r] = it
            order.append(r)
            continue
        a, b = groups[r], it
        keep, drop = (a, b) if quality(a) >= quality(b) else (b, a)
        for f in ("size", "torrent", "seeders", "category"):
            if not keep.get(f) and drop.get(f):
                keep[f] = drop[f]
        # 磁力与 infohash 必须成对补齐，避免显示错误的 btih
        if not keep.get("magnet") and drop.get("magnet"):
            keep["magnet"] = drop["magnet"]
            keep["infohash"] = drop.get("infohash") or keep.get("infohash")
        groups[r] = keep

    return [groups[r] for r in order]


def ts_of(it):
    try:
        return parsedate_to_datetime(it["pubdate"]).timestamp()
    except Exception:
        return 0


def keep_item(it, include, exclude, cats, keyword):
    low = (it["title"] or "").lower()
    if include and not any(w.lower() in low for w in include):
        return False
    if exclude and any(w.lower() in low for w in exclude):
        return False
    # 分类筛选只对动漫花园生效（其它站的分类体系不同）
    if cats and it["source"] == "dmhy" and it["category"] not in cats:
        return False
    # 萌番组没有搜索接口，关键词在本地过滤
    if keyword and it["source"] == "bangumi" and keyword.lower() not in low:
        return False
    return True


# ---------------------------------------------------------------- RSS 构建

ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
ET.register_namespace("nyaa", "https://nyaa.si/xmlns/nyaa")


def build_description(it):
    """渲染成"链接清单"式 HTML"""
    esc = html.escape
    src = S.BY_ID.get(it["source"], {"name": it["source"]})
    magnet = slim_magnet(it["magnet"], it.get("title") or "")
    torrent = it["torrent"]
    page = it["link"]
    links = it["links"]
    body = it["summary"]
    ih = it["infohash"]

    h = ['<div style="font:14px/1.65 -apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Arial,sans-serif;color:#1f2328">']

    meta = [f'<b style="color:#0969da">{esc(src["name"])}</b>']
    if it["category"]:
        meta.append(esc(it["category"]))
    if it["pubdate"]:
        meta.append(esc(pretty_time(it["pubdate"])))
    if it["size"]:
        meta.append(esc(it["size"]))
    if it["seeders"] is not None:
        meta.append(f"做种 {it['seeders']}")
    if it["author"]:
        meta.append("发布者 " + esc(it["author"]))
    h.append(f'<p style="margin:0 0 10px;color:#57606a;font-size:13px">{" · ".join(meta)}</p>')

    if magnet:
        h.append('<p style="margin:0 0 3px;font-size:13px"><b>磁力链接</b>')
        if ih:
            h.append(f'<span style="color:#8b949e"> btih {esc(ih)}</span>')
        h.append("</p>")
        h.append(
            f'<p style="margin:0 0 5px;font-size:13px">'
            f'<a href="{esc(magnet, quote=True)}" style="color:#0969da">▶ 点此打开磁力链接</a></p>'
            f'<p style="margin:0 0 12px;word-break:break-all;color:#57606a;font-size:11.5px;line-height:1.5">'
            f"{esc(magnet)}</p>"
        )

    if torrent:
        h.append(
            f'<p style="margin:0 0 12px;font-size:13px"><b>种子文件</b> '
            f'<a href="{esc(torrent, quote=True)}" style="color:#0969da">下载 .torrent</a></p>'
        )

    if page:
        short = re.sub(r"^https?://", "", page)
        h.append(
            f'<p style="margin:0 0 12px;font-size:13px"><b>帖子页</b> '
            f'<a href="{esc(page, quote=True)}" style="color:#0969da;word-break:break-all">{esc(short)}</a></p>'
        )

    if links:
        h.append(f'<p style="margin:0 0 5px;font-size:13px"><b>正文链接 · {len(links)}</b></p>')
        h.append('<ul style="margin:0 0 10px;padding-left:19px">')
        for u in links:
            shown = re.sub(r"^https?://", "", u)
            if len(shown) > 62:
                shown = shown[:59] + "…"
            h.append(
                f'<li style="margin:0 0 3px;font-size:13px"><a href="{esc(u, quote=True)}" '
                f'style="color:#0969da;word-break:break-all">{esc(shown)}</a></li>'
            )
        h.append("</ul>")

    if body:
        h.append(
            '<details style="margin-top:8px;border-top:1px solid #eaeef2;padding-top:8px">'
            '<summary style="cursor:pointer;color:#8b949e;font-size:12px">展开正文摘要</summary>'
            f'<p style="margin:8px 0 0;color:#57606a;font-size:12.5px;white-space:pre-wrap">{esc(body)}</p>'
            "</details>"
        )

    h.append("</div>")
    return "".join(h)


def _parse_filters(params):
    include = [w.strip() for w in (params.get("include") or "").split(",") if w.strip()]
    exclude = [w.strip() for w in (params.get("exclude") or "").split(",") if w.strip()]
    cats = [w.strip() for w in (params.get("cat") or "").split(",") if w.strip()]
    keyword = (params.get("keyword") or "").strip()
    try:
        limit = int(params.get("limit") or 50)
    except ValueError:
        limit = 50
    return include, exclude, cats, keyword, max(1, min(limit, 500))


def normalize_items(items, params=None):
    """把条目规整成对外输出的最终形态。

    必须在「新抓的 + 历史读回的」合并之后统一执行一次。
    否则改了规则只对新数据生效，历史条目要等过了保留期才干净——
    实际踩过：磁力规整和分类过滤都只写在解析层，导致旧的 base32 磁力
    和非动漫条目在订阅里又存活了一周。
    """
    params = params or {}
    if str(params.get("dmhy_all") or "") in ("1", "true", "yes"):
        allow = None
    elif (params.get("dmhy_cat") or "").strip():
        allow = {x.strip() for x in params["dmhy_cat"].split(",") if x.strip()}
    elif (params.get("cat") or "").strip():
        allow = None          # 调用方显式指定了分类，交给上层
    else:
        allow = S.DMHY_ANIME_CATS

    out = []
    for it in items:
        if it.get("source") == "dmhy" and allow is not None:
            cat = (it.get("category") or "").strip()
            if cat and cat not in allow:
                continue
        it["magnet"] = slim_magnet(it.get("magnet") or "", it.get("title") or "")
        out.append(it)
    return out


def prepare_items(items, params):
    """规整 -> 过滤 -> 去重 -> 按时间倒序 -> 截断"""
    items = normalize_items(items, params)
    include, exclude, cats, keyword, limit = _parse_filters(params)
    items = [it for it in items if keep_item(it, include, exclude, cats, keyword)]
    items = dedupe(items)
    items.sort(key=ts_of, reverse=True)
    return items[:limit]


def build_rss(items, params, self_url=None, errors=None,
              pre_filtered=False, title_override=None):
    """pre_filtered=True 时跳过内部过滤（静态构建已在外面筛过）"""
    include, exclude, cats, keyword, limit = _parse_filters(params)
    if not pre_filtered:
        items = prepare_items(items, params)

    now = time.strftime("%a, %d %b %Y %H:%M:%S +0800", time.localtime())

    rss = ET.Element("rss", {"version": "2.0"})
    chan = ET.SubElement(rss, "channel")

    sids = S.resolve_ids(params.get("src"))
    src_names = " / ".join(S.BY_ID[x]["name"] for x in sids)
    bits = []
    if keyword:
        bits.append(f"关键词「{keyword}」")
    if cats:
        bits.append("分类 " + "/".join(cats))
    if include:
        bits.append("含 " + "/".join(include))
    if exclude:
        bits.append("排除 " + "/".join(exclude))
    suffix = (" · " + "，".join(bits)) if bits else ""

    ET.SubElement(chan, "title").text = title_override or f"{SITE_TITLE} · {src_names}{suffix}"
    ET.SubElement(chan, "link").text = S.BY_ID[sids[0]]["home"]
    ET.SubElement(chan, "description").text = (
        f"来自 {src_names} 的资源更新，已统一清洗；每条自带磁力链接/种子直链、帖子页与正文外链。{suffix}"
    )
    ET.SubElement(chan, "language").text = "zh-cn"
    ET.SubElement(chan, "lastBuildDate").text = now
    ET.SubElement(chan, "pubDate").text = now
    ET.SubElement(chan, "generator").text = "dmhy-multi-rss"
    ET.SubElement(chan, "ttl").text = "30"
    ET.SubElement(
        chan,
        "{http://www.w3.org/2005/Atom}link",
        {"href": self_url or "", "rel": "self", "type": "application/rss+xml"},
    )
    if errors:
        ET.SubElement(chan, "docs").text = "errors: " + " | ".join(errors[:3])

    for it in items:
        e = ET.SubElement(chan, "item")
        ET.SubElement(e, "title").text = it["title"]
        ET.SubElement(e, "link").text = it["link"]
        ET.SubElement(
            e, "guid", {"isPermaLink": "false"}
        ).text = f"{it['source']}:{it['infohash'] or it['link']}"
        if it["pubdate"]:
            ET.SubElement(e, "pubDate").text = it["pubdate"]
        if it["author"]:
            ET.SubElement(e, "author").text = it["author"]
        cat = it["category"] or S.BY_ID.get(it["source"], {}).get("name", "")
        if cat:
            ET.SubElement(e, "category").text = cat
        ET.SubElement(e, "description").text = build_description(it)
        enc = it["magnet"] or it["torrent"]
        if enc:
            ET.SubElement(
                e, "enclosure",
                {"url": enc, "type": "application/x-bittorrent", "length": "0"},
            )
        if it["infohash"]:
            ET.SubElement(e, "{https://nyaa.si/xmlns/nyaa}infoHash").text = it["infohash"]

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True), len(items)


# ---------------------------------------------------------------- HTTP 层

INDEX_HTML = ""


class Handler(BaseHTTPRequestHandler):
    server_version = "multi-rss/2.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, body, ctype, code=200, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        use_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 1024
        if use_gzip:
            body = gzip.compress(body, 6)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=180")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _base(self):
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or f"127.0.0.1:{PORT}"
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        sp = urllib.parse.urlsplit(self.path)
        return f"{proto}://{host}{sp.path or '/rss.xml'}" + (f"?{sp.query}" if sp.query else "")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if path in ("/", "/index.html"):
            page = (
                INDEX_HTML
                .replace("__LAN_RSS__", f"http://{local_ip()}:{PORT}/rss.xml")
                .replace("__SOURCES__", build_source_meta())
            )
            return self._send(page, "text/html; charset=utf-8")

        if path in ("/healthz", "/health"):
            return self._send('{"ok":true,"cache":%d}' % len(_cache), "application/json; charset=utf-8")

        if path == "/api/list":
            sids = S.resolve_ids(params.get("src"))
            try:
                items, errors = gather(sids, params)
                items = prepare_items(items, params)
            except Exception as e:
                return self._send(
                    json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                               ensure_ascii=False),
                    "application/json; charset=utf-8", 502,
                )
            out = []
            for it in items:
                out.append({
                    "source": it["source"],
                    "sourceName": S.BY_ID.get(it["source"], {}).get("name", it["source"]),
                    "title": it["title"],
                    "link": it["link"],
                    "magnet": slim_magnet(it["magnet"], it.get("title") or ""),
                    "torrent": it["torrent"],
                    "size": it["size"],
                    "seeders": it["seeders"],
                    "pubdate": it["pubdate"],
                    "category": it["category"],
                })
            return self._send(
                json.dumps({"ok": True, "count": len(out), "errors": errors, "sources": sids,
                            "items": out}, ensure_ascii=False),
                "application/json; charset=utf-8",
            )

        if path in ("/rss.xml", "/rss", "/feed"):
            sids = S.resolve_ids(params.get("src"))
            try:
                items, errors = gather(sids, params)
                xml_bytes, n = build_rss(items, params, self._base(), errors)
            except Exception as e:
                return self._send(
                    "订阅源暂时不可用: " + html.escape(f"{type(e).__name__}: {e}"),
                    "text/plain; charset=utf-8", 502,
                )
            extra = {
                "X-Items": str(n),
                "X-Sources": ",".join(sids),
                "X-Errors": str(len(errors)),
            }
            return self._send(xml_bytes, "application/rss+xml; charset=utf-8", extra=extra)

        return self._send("Not Found", "text/plain; charset=utf-8", 404)


def build_source_meta():
    import json

    meta = [
        {"id": s["id"], "name": s["name"], "home": s["home"], "note": s["note"]}
        for s in S.SOURCES
    ]
    return json.dumps(meta, ensure_ascii=False)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_index():
    global INDEX_HTML
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "index.html")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            INDEX_HTML = f.read()
    else:
        INDEX_HTML = "<h1>RSS</h1><p>/rss.xml</p>"


def main():
    load_index()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("多站资源 RSS 增强订阅服务已启动")
    print(f"  本机:   http://127.0.0.1:{PORT}/")
    print(f"  局域网: http://{local_ip()}:{PORT}/")
    print(f"  订阅源: http://127.0.0.1:{PORT}/rss.xml")
    print(f"  站点:   {' / '.join(s['name'] for s in S.SOURCES)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
