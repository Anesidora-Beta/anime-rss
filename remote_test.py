#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公网订阅的多轮可靠性测试。

用法：
    python remote_test.py                 # 默认测试线上地址
    python remote_test.py --rounds 3      # 稳定性测试轮数
    python remote_test.py --base <url>    # 换地址

只依赖标准库。
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import timezone


def parse_date(s):
    """把 RSS 时间统一成带时区的 datetime；无时区的按 UTC 处理，避免比较时报错"""
    dt = parsedate_to_datetime((s or "").strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

DEFAULT_BASE = "https://anesidora-beta.github.io/anime-rss"
UA = "anime-rss-selftest/1.0 (+github pages)"

ATOM = "{http://www.w3.org/2005/Atom}"
TORRENT_NS = "{https://github.com/nyaadevs/nyaa}"
MK_NS = "{https://mikanani.me}"

FEEDS = ["feed.xml", "all.xml", "1080p.xml", "magnet.xml",
         "dmhy.xml", "mikan.xml", "nyaa.xml", "bangumi.xml", "acgrip.xml"]

BTIH_HEX = re.compile(r"^[0-9a-fA-F]{40}$")
MAGNET_RE = re.compile(r"^magnet:\?xt=urn:btih:([0-9a-zA-Z]{32,40})(&|$)")

# ---------------------------------------------------------------- 结果收集

class Report:
    def __init__(self):
        self.rows = []          # (组, 名称, 状态, 详情)
        self.fails = 0
        self.warns = 0

    def ok(self, group, name, detail=""):
        self.rows.append((group, name, "PASS", detail))

    def warn(self, group, name, detail=""):
        self.rows.append((group, name, "WARN", detail))
        self.warns += 1

    def fail(self, group, name, detail=""):
        self.rows.append((group, name, "FAIL", detail))
        self.fails += 1

    def dump(self):
        cur = None
        for group, name, status, detail in self.rows:
            if group != cur:
                print(f"\n[{group}]")
                cur = group
            mark = {"PASS": "  ok  ", "WARN": " warn ", "FAIL": " FAIL "}[status]
            print(f"{mark} {name:<34} {detail}")


R = Report()


# ---------------------------------------------------------------- HTTP

def fetch(url, timeout=40, extra_headers=None, method="GET"):
    """返回 (status, headers, body_bytes, elapsed_sec)"""
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept-Encoding", "gzip")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            if hdrs.get("content-encoding") == "gzip":
                import gzip as _gz
                body = _gz.decompress(body)
            return resp.status, hdrs, body, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b"", time.time() - t0
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}, b"", time.time() - t0


# ---------------------------------------------------------------- T1 可用性

def t1_availability(base):
    """每个入口连续请求 3 次，检查状态码 / 耗时 / 体积稳定性"""
    cache = {}
    for name in FEEDS + ["feed.json", "index.html"]:
        url = f"{base}/{name}"
        codes, times, sizes, bodies = [], [], [], []
        for _ in range(3):
            st, hd, body, el = fetch(url)
            codes.append(st)
            times.append(el)
            sizes.append(len(body))
            bodies.append(hashlib.sha256(body).hexdigest())

        if all(c == 200 for c in codes):
            stable = len(set(sizes)) == 1
            note = f"{times[-1]:.2f}s  {sizes[-1] // 1024}KB"
            if not stable:
                note += f"  ⚠体积抖动 {sizes}"
                R.warn("T1 可用性", name, note)
            elif times[-1] > 5:
                R.warn("T1 可用性", name, note + "  ⚠偏慢")
            else:
                R.ok("T1 可用性", name, note)
            cache[name] = {"size": sizes[-1], "hash": bodies[-1]}
        else:
            err = hd.get("error") if isinstance(hd, dict) else ""
            R.fail("T1 可用性", name, f"状态码 {codes} {err or ''}")
    return cache


# ---------------------------------------------------------------- T2 结构

def parse_feed(body, name):
    """解析 XML，返回 (channel, items) 或抛异常"""
    root = ET.fromstring(body)
    if root.tag != "rss":
        raise ValueError(f"根元素不是 rss 而是 {root.tag}")
    ch = root.find("channel")
    if ch is None:
        raise ValueError("缺少 channel")
    return ch, ch.findall("item")


def t2_structure(base):
    feeds = {}
    for name in FEEDS:
        st, _, body, _ = fetch(f"{base}/{name}")
        if st != 200:
            R.fail("T2 结构", name, f"HTTP {st}")
            continue
        try:
            ch, items = parse_feed(body, name)
        except Exception as e:
            R.fail("T2 结构", name, f"解析失败: {e}")
            continue

        problems = []
        # channel 必需项
        for tag in ("title", "link", "description", "language"):
            if not (ch.findtext(tag) or "").strip():
                problems.append(f"channel/{tag} 为空")
        # atom:self
        self_link = ch.find(ATOM + "link")
        if self_link is None or not self_link.get("href"):
            problems.append("缺少 atom:self")
        elif not self_link.get("href").startswith("https://anesidora-beta.github.io/"):
            problems.append(f"self 地址异常 {self_link.get('href')[:50]}")
        # 条目字段
        bad_guid = bad_date = bad_link = 0
        for it in items:
            if not (it.findtext("title") or "").strip():
                problems.append("存在空 title")
                break
            g = (it.findtext("guid") or "").strip()
            if not g:
                bad_guid += 1
            if not (it.findtext("pubDate") or "").strip():
                bad_date += 1
            else:
                try:
                    parse_date(it.findtext("pubDate"))
                except Exception:
                    bad_date += 1
            if not (it.findtext("link") or "").strip():
                bad_link += 1
        if bad_guid:
            problems.append(f"{bad_guid} 条缺 guid")
        if bad_date:
            problems.append(f"{bad_date} 条时间格式错")
        if bad_link:
            problems.append(f"{bad_link} 条缺 link")

        if problems:
            R.fail("T2 结构", name, "；".join(problems))
        else:
            R.ok("T2 结构", name, f"{len(items)} 条，字段齐全")
        feeds[name] = {"channel": ch, "items": items, "self": self_link.get("href") if self_link is not None else ""}
    return feeds


# ---------------------------------------------------------------- T3 内容

def t3_content(feeds):
    for name, f in feeds.items():
        items = f["items"]
        if not items:
            R.warn("T3 内容", name, "0 条")
            continue

        mag = tor = ext = 0
        bad_mag = []
        guids = {}
        dup_guid = 0
        times = []

        for it in items:
            # 磁力
            enc = it.find("enclosure")
            url = (enc.get("url") or "") if enc is not None else ""
            if url.startswith("magnet:"):
                mag += 1
                m = MAGNET_RE.match(url)
                if not m:
                    bad_mag.append(url[:40])
                elif not BTIH_HEX.match(m.group(1)):
                    # base32 形式也算可接受，但要能解码
                    try:
                        import base64
                        base64.b32decode(m.group(1).upper())
                    except Exception:
                        bad_mag.append(url[:40])
            elif url.endswith(".torrent"):
                tor += 1

            desc = it.findtext("description") or ""
            if "正文链接" in desc:
                ext += 1

            g = (it.findtext("guid") or "").strip()
            if g:
                guids[g] = guids.get(g, 0) + 1
                if guids[g] > 1:
                    dup_guid += 1

            try:
                times.append(parse_date(it.findtext("pubDate")))
            except Exception:
                pass

        issues = []
        if bad_mag:
            issues.append(f"{len(bad_mag)} 个磁力格式异常，如 {bad_mag[0]}")
        if dup_guid:
            issues.append(f"{dup_guid} 条 guid 重复")
        # 时间必须递减（允许相等，只统计明显逆序，避免时区标记差异造成误报）
        if len(times) > 1:
            inversions = sum(1 for a, b in zip(times, times[1:]) if (b - a).total_seconds() > 1)
            if inversions:
                issues.append(f"{inversions} 处时间逆序")
        # 条目里不应该残留未转义的 HTML 片段
        raw = ET.tostring(f["channel"], encoding="unicode")
        if re.search(r"<[a-zA-Z][^>]*\$\s*$", raw):
            issues.append("存在截断标签")

        note = f"{len(items)} 条｜磁力 {mag}｜种子 {tor}｜外链 {ext}"
        if issues:
            R.fail("T3 内容", name, note + "｜" + "；".join(issues))
        else:
            R.ok("T3 内容", name, note)


# ---------------------------------------------------------------- T4 一致性

def t4_consistency(feeds, feed_json):
    """校验频道之间、JSON 与 XML 之间的数据关系"""
    if "feed.xml" in feeds and "all.xml" in feeds:
        a = [i.findtext("guid") for i in feeds["feed.xml"]["items"]]
        b = [i.findtext("guid") for i in feeds["all.xml"]["items"]]
        if a == b:
            R.ok("T4 一致性", "feed.xml 与 all.xml", f"完全一致（{len(a)} 条）")
        else:
            R.warn("T4 一致性", "feed.xml 与 all.xml", f"不同：{len(a)} vs {len(b)}")

    # 单源频道里的条目，源标记必须正确
    src_tag = {"dmhy.xml": "动漫花园", "mikan.xml": "蜜柑计划", "nyaa.xml": "Nyaa",
               "bangumi.xml": "萌番组", "acgrip.xml": "ACG.RIP"}
    for fname, tag in src_tag.items():
        if fname not in feeds:
            continue
        bad = 0
        for it in feeds[fname]["items"]:
            desc = it.findtext("description") or ""
            if f"[{tag}]" not in desc and tag not in desc[:300]:
                bad += 1
        if bad == 0:
            R.ok("T4 一致性", f"{fname} 源标记", "全部正确")
        else:
            R.fail("T4 一致性", f"{fname} 源标记", f"{bad} 条源标记不符")

    # 1080p 频道
    if "1080p.xml" in feeds:
        its = feeds["1080p.xml"]["items"]
        bad = [i for i in its if "1080" not in (i.findtext("title") or "")]
        if not bad:
            R.ok("T4 一致性", "1080p 频道筛选", f"{len(its)} 条全部含 1080")
        else:
            R.fail("T4 一致性", "1080p 频道筛选", f"{len(bad)} 条不含 1080，如 {(bad[0].findtext('title') or '')[:40]}")

    # feed.json 与 XML 的条目数关系
    if feed_json and "feed.xml" in feeds:
        n_xml = len(feeds["feed.xml"]["items"])
        n_json = feed_json.get("count", 0)
        if n_json >= n_xml:
            R.ok("T4 一致性", "JSON 与 XML 条目数", f"JSON {n_json} ≥ XML {n_xml}")
        else:
            R.fail("T4 一致性", "JSON 与 XML 条目数", f"JSON {n_json} < XML {n_xml}")

        # feed.json 里每条都要有 title，且 json 里列出的频道文件都真实存在
        missing = [f["file"] for f in feed_json.get("feeds", []) if f["file"] not in feeds]
        if missing:
            R.fail("T4 一致性", "频道文件齐全性", f"JSON 声明但缺失：{missing}")
        else:
            R.ok("T4 一致性", "频道文件齐全性", f"{len(feed_json.get('feeds', []))} 个频道全部存在")

        # 源统计与单源频道数量应吻合
        by_id = {s["id"]: s for s in feed_json.get("sources", [])}
        for sid, fname in (("dmhy", "dmhy.xml"), ("mikan", "mikan.xml"), ("nyaa", "nyaa.xml"),
                           ("bangumi", "bangumi.xml"), ("acgrip", "acgrip.xml")):
            if sid in by_id and fname in feeds:
                declared = by_id[sid]["count"]
                actual = len(feeds[fname]["items"])
                # 单源频道有 limit(120) 截断，actual 应 ≤ declared
                if actual <= declared:
                    R.ok("T4 一致性", f"{fname} 数量", f"{actual} ≤ 统计 {declared}")
                else:
                    R.fail("T4 一致性", f"{fname} 数量", f"{actual} > 统计 {declared}")


# ---------------------------------------------------------------- T5 稳定性

def t5_stability(base, rounds=3, gap=15):
    """多轮抓取主订阅，内容在一个 cron 周期内应保持一致"""
    hashes, sizes, codes = [], [], []
    print(f"\n  （稳定性测试：{rounds} 轮，间隔 {gap}s，约需 {rounds * gap}s）")
    for i in range(rounds):
        st, hd, body, el = fetch(f"{base}/feed.xml")
        codes.append(st)
        sizes.append(len(body))
        hashes.append(hashlib.sha256(body).hexdigest()[:12])
        lm = hd.get("last-modified", "-")
        print(f"    第 {i + 1} 轮  status={st}  {len(body) // 1024}KB  {el:.2f}s  LM={lm}")
        if i < rounds - 1:
            time.sleep(gap)

    if not all(c == 200 for c in codes):
        R.fail("T5 稳定性", "多轮可访问性", f"状态码 {codes}")
        return
    R.ok("T5 稳定性", "多轮可访问性", f"{rounds}/{rounds} 次均 200")

    uniq = len(set(hashes))
    if uniq == 1:
        R.ok("T5 稳定性", "内容一致性", f"哈希稳定 {hashes[0]}")
    else:
        # 内容变化可能是定时的 20 分钟更新，不一定是错误
        R.warn("T5 稳定性", "内容一致性", f"{uniq} 种内容（可能正好跨过定时更新）")


# ---------------------------------------------------------------- T6 错误处理

def t6_errors(base):
    st, _, _, _ = fetch(f"{base}/this-does-not-exist.xml")
    if st == 404:
        R.ok("T6 错误处理", "不存在的路径", "正确返回 404")
    else:
        R.fail("T6 错误处理", "不存在的路径", f"返回 {st}，应为 404")

    st, hd, body, _ = fetch(f"{base}/feed.xml")
    etag = hd.get("etag")
    lm = hd.get("last-modified")
    if not etag and not lm:
        R.warn("T6 错误处理", "缓存头", "无 ETag / Last-Modified，阅读器会全量重下")
        return
    cond = {}
    if etag:
        cond["If-None-Match"] = etag
    if lm:
        cond["If-Modified-Since"] = lm
    st2, _, body2, _ = fetch(f"{base}/feed.xml", extra_headers=cond)
    if st2 == 304:
        R.ok("T6 错误处理", "条件请求", "正确返回 304，节省流量")
    elif st2 == 200:
        R.warn("T6 错误处理", "条件请求", f"返回 200 而非 304（ETag={bool(etag)}）")
    else:
        R.warn("T6 错误处理", "条件请求", f"返回 {st2}")


# ---------------------------------------------------------------- T7 定时任务

def t7_schedule(base):
    """检查最近一次部署时间，判断定时任务是否在跑"""
    st, hd, _, _ = fetch(f"{base}/feed.json")
    lm = hd.get("last-modified")
    if not lm:
        R.warn("T7 定时更新", "最近部署时间", "无 Last-Modified 头")
        return
    try:
        dt = parse_date(lm)
        age = time.time() - dt.timestamp()
        mins = age / 60
        note = f"{dt.strftime('%Y-%m-%d %H:%M')} UTC（{mins:.0f} 分钟前）"
        if mins <= 25:
            R.ok("T7 定时更新", "最近部署时间", note + " → 定时任务正常")
        elif mins <= 60:
            R.warn("T7 定时更新", "最近部署时间", note + " → 略超 20 分钟周期")
        else:
            R.fail("T7 定时更新", "最近部署时间", note + " → 超过 1 小时未更新，检查 Actions")
    except Exception as e:
        R.warn("T7 定时更新", "最近部署时间", f"解析失败 {e}")


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--gap", type=int, default=15)
    ap.add_argument("--skip-stability", action="store_true")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("=" * 74)
    print(f"公网订阅可靠性测试  {base}")
    print(f"开始时间 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 74)

    print("\n>>> T1 可用性与性能")
    t1_availability(base)

    print("\n>>> T2 结构完整性")
    feeds = t2_structure(base)

    print("\n>>> T3 内容质量")
    t3_content(feeds)

    print("\n>>> T4 跨频道一致性")
    st, _, jbody, _ = fetch(f"{base}/feed.json")
    try:
        fj = json.loads(jbody.decode("utf-8")) if st == 200 else None
    except Exception:
        fj = None
    if fj is None:
        R.fail("T4 一致性", "feed.json", f"不可用（{st}）")
    t4_consistency(feeds, fj)

    print("\n>>> T6 错误处理与缓存")
    t6_errors(base)

    print("\n>>> T7 定时更新")
    t7_schedule(base)

    if not args.skip_stability:
        print("\n>>> T5 多轮稳定性")
        t5_stability(base, args.rounds, args.gap)

    print("\n" + "=" * 74)
    R.dump()
    print("\n" + "=" * 74)
    total = len(R.rows)
    passed = sum(1 for r in R.rows if r[2] == "PASS")
    print(f"结果：{passed}/{total} 通过   警告 {R.warns}   失败 {R.fails}")
    print("=" * 74)

    if R.fails:
        print("\n需要处理的失败项：")
        for g, n, s, d in R.rows:
            if s == "FAIL":
                print(f"  ✗ [{g}] {n}: {d}")
    if R.warns:
        print("\n需要留意的警告项：")
        for g, n, s, d in R.rows:
            if s == "WARN":
                print(f"  ! [{g}] {n}: {d}")

    return 0 if R.fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
