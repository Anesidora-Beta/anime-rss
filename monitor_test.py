#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长周期监控：按固定间隔采样，观察跨定时任务边界时的表现。

关注三件事：
  1. 每次采样是否都可访问（不因重新部署而出现 404/503）；
  2. feed.xml 与 feed.json 是否为同一版本（避免 CDN 半更新状态）；
  3. 内容是否在部署时间点后确实变了（说明定时任务真的在跑）。
"""

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://anesidora-beta.github.io/anime-rss"
UA = "anime-rss-monitor/1.0"


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, {}, b"", time.time() - t0
    except Exception as e:
        return None, {"err": str(e)}, b"", time.time() - t0


def snapshot():
    """一次完整采样"""
    s = {"t": time.strftime("%H:%M:%S")}

    st, hd, body, el = get(f"{BASE}/feed.xml")
    s["xml_status"] = st
    s["xml_size"] = len(body)
    s["xml_sec"] = el
    s["lm"] = hd.get("last-modified", "-")
    s["xml_sha"] = hashlib.sha256(body).hexdigest()[:10] if body else "-"
    s["xml_items"] = 0
    s["xml_latest"] = "-"
    # 内容完整性：与 Content-Length 比对
    cl = hd.get("content-length")
    s["len_ok"] = (int(cl) == len(body)) if (cl and body) else None
    if body:
        try:
            ch = ET.fromstring(body).find("channel")
            its = ch.findall("item")
            s["xml_items"] = len(its)
            if its:
                s["xml_latest"] = (its[0].findtext("pubDate") or "-")[:25]
        except Exception as e:
            s["xml_items"] = f"解析失败:{e}"

    st2, hd2, body2, _ = get(f"{BASE}/feed.json")
    s["json_status"] = st2
    s["json_count"] = 0
    s["json_latest"] = "-"
    s["mag_ok"] = "-"
    if body2:
        try:
            d = json.loads(body2)
            s["json_count"] = d.get("count", 0)
            items = d.get("items") or []
            if items:
                s["json_latest"] = (items[0].get("pubdate") or "-")[:25]
            mag = [i for i in items if i.get("magnet")]
            if mag:
                hex40 = sum(1 for i in mag if re.search(r"btih:[0-9a-f]{40}", i["magnet"]))
                dn = sum(1 for i in mag if re.search(r"&dn=[^&]+", i["magnet"]))
                s["mag_ok"] = f"{hex40}/{len(mag)}hex,{dn}dn"
        except Exception as e:
            s["json_count"] = f"解析失败:{e}"

    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--gap", type=int, default=45)
    a = ap.parse_args()

    print("=" * 96)
    print(f"长周期监控：{a.rounds} 轮 × {a.gap}s ≈ {a.rounds * a.gap // 60} 分钟")
    print("=" * 96)
    print(f"{'时间':<9}{'XML':<6}{'条数':<6}{'体积':<9}{'耗时':<7}{'JSON':<6}{'总条':<6}"
          f"{'最新条目':<26}{'磁力质量':<14}{'部署时间(UTC)'}")
    print("-" * 96)

    rows = []
    for i in range(a.rounds):
        s = snapshot()
        rows.append(s)
        print(f"{s['t']:<9}{str(s['xml_status']):<6}{str(s['xml_items']):<6}"
              f"{s['xml_size'] // 1024:>6}KB  {s['xml_sec']:<6.2f}{str(s['json_status']):<6}"
              f"{str(s['json_count']):<6}{s['xml_latest']:<26}{s['mag_ok']:<14}"
              f"{s['lm'].replace('GMT', '').strip()}")
        if i < a.rounds - 1:
            time.sleep(a.gap)

    print("-" * 96)
    ok = sum(1 for s in rows if s["xml_status"] == 200 and s["json_status"] == 200)
    print(f"可访问: {ok}/{len(rows)}")

    shas = {s["xml_sha"] for s in rows}
    print(f"内容版本: {len(shas)} 种 {'（稳定，未跨过更新）' if len(shas) == 1 else '（发生了更新，符合预期）'}")

    lms = {s["lm"] for s in rows}
    print(f"部署时间: {len(lms)} 次变化 -> {sorted(lms)}")

    # XML 与 JSON 版本一致性
    mismatch = [s for s in rows if s["xml_latest"] != s["json_latest"] and
                s["xml_latest"] != "-" and s["json_latest"] != "-"]
    if mismatch:
        print(f"⚠ XML/JSON 版本不一致 {len(mismatch)} 次:")
        for s in mismatch[:3]:
            print(f"    {s['t']}  xml={s['xml_latest']}  json={s['json_latest']}")
    else:
        print("XML 与 JSON 版本: 一致")

    len_bad = [s for s in rows if s["len_ok"] is False]
    print(f"下载完整性: {'全部完整' if not len_bad else f'{len_bad} 长度不符'}")

    mag_vals = {s["mag_ok"] for s in rows}
    print(f"磁力质量: {mag_vals}")
    print("=" * 96)


if __name__ == "__main__":
    main()
