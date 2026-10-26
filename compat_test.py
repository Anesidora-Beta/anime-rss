#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 feedparser（Feedly / Inoreader / 各类客户端底层同款库）验证订阅源的兼容性。

标准库 ElementTree 只能证明 XML 合法，无法证明真实阅读器能正确解读。
这个脚本检查的是「阅读器眼里的样子」：条目数、日期能否解析、磁力是否被识别为附件、
摘要 HTML 是否可渲染、GUID 是否唯一。
"""

import sys
import time
import urllib.request

import feedparser

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://anesidora-beta.github.io/anime-rss"
FEEDS = ["feed.xml", "all.xml", "1080p.xml", "magnet.xml",
         "dmhy.xml", "mikan.xml", "nyaa.xml", "bangumi.xml", "acgrip.xml"]
UA = "anime-rss-selftest/1.0"

fails = warns = 0


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()


print("=" * 76)
print("feedparser 兼容性测试（模拟真实阅读器）")
print("=" * 76)

for name in FEEDS:
    raw = get(f"{BASE}/{name}")
    d = feedparser.parse(raw)

    issues, notes = [], []

    if d.get("bozo"):
        exc = d.get("bozo_exception")
        # 有些客户端对 XML 声明/DOM 问题敏感，这里视为必须关注的信号
        issues.append(f"解析告警 {type(exc).__name__}: {str(exc)[:60]}")

    if not d.feed.get("title"):
        issues.append("feed.title 为空")
    entries = d.entries
    if not entries:
        issues.append("没有解析出任何条目")

    no_date = no_link = no_id = 0
    mag = 0
    dup_ids = {}
    for e in entries:
        if not e.get("published_parsed") and not e.get("updated_parsed"):
            no_date += 1
        if not e.get("link"):
            no_link += 1
        if not e.get("id"):
            no_id += 1
        for enc in e.get("enclosures", []):
            href = enc.get("href", "")
            if href.startswith("magnet:") or href.endswith(".torrent"):
                mag += 1
                break
        dup_ids[e.get("id")] = dup_ids.get(e.get("id"), 0) + 1

    if no_date:
        issues.append(f"{no_date} 条日期无法解析")
    if no_link:
        issues.append(f"{no_link} 条缺 link")
    if no_id:
        warns += 1
        notes.append(f"{no_id} 条无 id")
    dup = sum(v - 1 for v in dup_ids.values() if v > 1)
    if dup:
        issues.append(f"{dup} 条 id 重复")

    # 摘要应该是可渲染的 HTML，且能被阅读器取到文本
    sample = entries[0]
    summary = sample.get("summary", "")
    if not summary:
        warns += 1
        notes.append("首条无 summary")
    elif "<" not in summary:
        warns += 1
        notes.append("首条 summary 无 HTML 结构")
    else:
        notes.append(f"summary {len(summary)}B")

    note = f"{len(entries)} 条｜识别到附件 {mag}｜" + "；".join(notes)
    if issues:
        fails += 1
        print(f"  FAIL  {name:<12} {note}")
        for i in issues:
            print(f"          ✗ {i}")
    else:
        print(f"  ok    {name:<12} {note}")

print()
print("-" * 76)
print("首条在阅读器中的呈现")
print("-" * 76)
d = feedparser.parse(get(f"{BASE}/feed.xml"))
e = d.entries[0]
print(f"  title    : {e.get('title', '')[:70]}")
print(f"  link     : {e.get('link', '')[:70]}")
p = e.get("published_parsed")
print(f"  published: {time.strftime('%Y-%m-%d %H:%M:%S', p) if p else '(解析失败)'}")
print(f"  id       : {e.get('id', '')[:60]}")
for enc in e.get("enclosures", []):
    print(f"  enclosure: type={enc.get('type', '?')[:36]}  {enc.get('href', '')[:56]}")
print(f"  summary  : {len(e.get('summary', ''))} 字节 HTML")

# 检查摘要里能否提取出可点击的磁力链接
import re
hrefs = re.findall(r'href="([^"]+)"', e.get("summary", ""))
mag_hrefs = [h for h in hrefs if h.startswith("magnet:")]
print(f"  摘要内链接: {len(hrefs)} 个，其中磁力 {len(mag_hrefs)} 个")

print()
print("=" * 76)
print(f"结果：失败 {fails}，警告 {warns}")
print("=" * 76)
sys.exit(0 if fails == 0 else 1)
