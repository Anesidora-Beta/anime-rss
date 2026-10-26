#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽检订阅里的实际链接：磁力格式、种子直链是否真能下载、帖子页是否可达。

阅读器点开就是这些链接，格式对但链接死掉等于没用，所以单独验证。
"""

import json
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import unquote

BASE = "https://anesidora-beta.github.io/anime-rss"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

req = urllib.request.Request(f"{BASE}/feed.json", headers={"User-Agent": UA})
with urllib.request.urlopen(req, timeout=40) as r:
    data = json.load(r)

items = data["items"]
print("=" * 76)
print(f"链接抽检  共 {len(items)} 条，总错误 {len(data.get('errors') or [])}")
print("=" * 76)

# ---------- 1. 磁力链接结构 ----------
print("\n[1] 磁力链接结构")
mag_items = [i for i in items if i.get("magnet")]
print(f"  带磁力 {len(mag_items)} 条，抽检前 6 条")
bad = 0
for it in mag_items[:6]:
    m = re.match(r"magnet:\?xt=urn:btih:([0-9a-zA-Z]{32,40})", it["magnet"])
    trackers = len(re.findall(r"&tr=", it["magnet"]))
    name = unquote(re.search(r"&dn=([^&]*)", it["magnet"]).group(1)) if "&dn=" in it["magnet"] else ""
    if not m:
        bad += 1
        print(f"    ✗ 格式异常 {it['magnet'][:60]}")
    else:
        ih = m.group(1)
        kind = "hex40" if len(ih) == 40 else f"base32({len(ih)})"
        print(f"    ok  {kind:<10} tracker={trackers}  {name[:44]}")
print(f"  结果：{'全部合规' if bad == 0 else f'{bad} 条异常'}")

# ---------- 2. 种子直链能否下载 ----------
print("\n[2] 种子直链可用性")
tor_items = [i for i in items if i.get("torrent")]
print(f"  带种子直链 {len(tor_items)} 条，抽检 4 条")
ok_n = 0
for it in tor_items[:4]:
    url = it["torrent"]
    try:
        rq = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(rq, timeout=30) as resp:
            head = resp.read(64)
            code = resp.status
        # bencode 字典以 b'd' 开头
        is_torrent = head[:1] == b"d"
        if code == 200 and is_torrent:
            ok_n += 1
            print(f"    ok  {code}  合法 torrent 头 {head[:16]!r}  {url[:52]}")
        else:
            print(f"    ✗  {code}  非 torrent 内容 {head[:24]!r}  {url[:52]}")
    except urllib.error.HTTPError as e:
        print(f"    ✗  HTTP {e.code}  {url[:60]}")
    except Exception as e:
        print(f"    ✗  {type(e).__name__}  {url[:60]}")
print(f"  结果：{ok_n}/{min(4, len(tor_items))} 可正常下载")

# ---------- 3. 帖子页可达性 ----------
print("\n[3] 帖子页可达性（仅供参考，站点可能有反爬）")
link_items = [i for i in items if i.get("link")]
reach = 0
for it in link_items[:5]:
    url = it["link"]
    host = re.sub(r"^https?://([^/]+).*", r"\1", url)
    try:
        rq = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(rq, timeout=25) as resp:
            reach += 1
            print(f"    ok  {resp.status}  {host:<18} {url[:50]}")
    except urllib.error.HTTPError as e:
        print(f"    !   {e.code}  {host:<18} {url[:50]}")
    except Exception as e:
        print(f"    !   {type(e).__name__}  {host:<18} {url[:50]}")
print(f"  结果：{reach}/5 直接可达")

# ---------- 4. 源分布 ----------
print("\n[4] 各源健康状况")
for s in data["sources"]:
    mark = "ok  " if s["ok"] else "FAIL"
    print(f"    {mark} {s['name']:<10} {s['count']:>4} 条")

print("\n" + "=" * 76)
