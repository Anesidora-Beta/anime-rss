#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态构建：抓取全部源 -> 生成 docs/ 下的 RSS、JSON 与页面。

由 GitHub Actions 定时调用，产物直接由 GitHub Pages 托管，
所以能拿到一个任何网络下都能订阅的公网地址。

用法:
    python build_feed.py
    python build_feed.py --site https://yourname.github.io/rss

产物（docs/ 目录）:
    feed.xml          主订阅源（feeds.json 里 primary 那一条）
    <id>.xml          feeds.json 里定义的其它订阅源
    <sid>.xml         按单一站点拆分的订阅源（dmhy / mikan / acgrip / nyaa / bangumi）
    feed.json         页面用的数据
    status.json       本次构建的状态（时间、各源条数、失败信息）
    index.html        公开的订阅面板
"""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.parse

import server as core
import sources as S

HERE = os.path.dirname(os.path.abspath(__file__))
RETENTION_DAYS = 7      # 历史条目滚动保留天数（站点临时不可用时不至于掉空）
MAX_KEEP = 500          # 合并后最多保留的条目
PER_SOURCE = 150        # 单个源最多保留的条目，避免大站把小站挤掉


# ------------------------------------------------------------------ 配置

def load_feeds():
    """读取 feeds.json；缺省给一条「全部更新」"""
    p = os.path.join(HERE, "feeds.json")
    default = [{"id": "all", "title": "全部更新", "primary": True, "limit": 200}]
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"! feeds.json 解析失败，改用默认配置: {e}")
        return default
    feeds = cfg.get("feeds") if isinstance(cfg, dict) else cfg
    feeds = [f for f in (feeds or []) if isinstance(f, dict) and f.get("id")]
    return feeds or default


def as_list(v):
    """支持 "a,b" 字符串或 ["a","b"] 数组两种写法"""
    if not v:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def describe(spec):
    """把过滤条件描述成频道名后缀"""
    bits = []
    for key, label in (("keyword", "关键词"), ("include", "含"),
                       ("exclude", "排除"), ("cat", "分类")):
        v = as_list(spec.get(key))
        if v:
            bits.append(f"{label} {'/'.join(v)}")
    return (" · " + "，".join(bits)) if bits else ""


def match(it, spec):
    low = (it.get("title") or "").lower()
    kw = as_list(spec.get("keyword"))
    if kw and not any(w.lower() in low for w in kw):
        return False
    inc = as_list(spec.get("include"))
    if inc and not any(w.lower() in low for w in inc):
        return False
    exc = as_list(spec.get("exclude"))
    if exc and any(w.lower() in low for w in exc):
        return False
    cats = as_list(spec.get("cat"))
    if cats and it["source"] == "dmhy" and it["category"] not in cats:
        return False
    return True


# ------------------------------------------------------------------ 历史合并

def load_previous(path):
    """读取上一轮的结果，用于在某个源临时失败时保住已有条目"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return []
    out = []
    for x in (d.get("items") or []):
        if not isinstance(x, dict) or not x.get("title"):
            continue
        out.append({
            "source": x.get("source", ""),
            "title": x.get("title", ""),
            "link": x.get("link", ""),
            "magnet": x.get("magnet", ""),
            "torrent": x.get("torrent", ""),
            "infohash": x.get("infohash", ""),
            "size": x.get("size", ""),
            "seeders": x.get("seeders"),
            "pubdate": x.get("pubdate", ""),
            "category": x.get("category", ""),
            "author": x.get("author", ""),
            "summary": x.get("summary", ""),
            "links": x.get("links") or [],
            "desc_html": "",
        })
    return out


def prune(items):
    cutoff = time.time() - RETENTION_DAYS * 86400
    out = []
    for it in items:
        ts = core.ts_of(it)
        if ts and ts < cutoff:      # ts 为 0 表示时间解析失败，保留
            continue
        out.append(it)
    return out


def dump_item(it):
    return {
        "source": it["source"],
        "sourceName": S.BY_ID.get(it["source"], {}).get("name", it["source"]),
        "title": it["title"],
        "link": it["link"],
        "magnet": it["magnet"],
        "torrent": it["torrent"],
        "infohash": it["infohash"],
        "size": it["size"],
        "seeders": it["seeders"],
        "pubdate": it["pubdate"],
        "category": it["category"],
        "author": it["author"],
        "summary": it["summary"],
        "links": it["links"],
    }


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "docs"))
    ap.add_argument("--site", default=os.environ.get("SITE_URL", ""))
    args = ap.parse_args()

    out = args.out
    # 域名统一小写：GitHub 的 GITHUB_REPOSITORY 保留原始大小写，
    # 但 Pages 实际域名是全小写，少数严格的阅读器会因为大小写不一致拒绝。
    site = (args.site or "").rstrip("/")
    if site:
        _p = urllib.parse.urlsplit(site)
        site = urllib.parse.urlunsplit((_p.scheme.lower(), _p.netloc.lower(), _p.path, "", ""))
    os.makedirs(out, exist_ok=True)

    t0 = time.time()
    print(f"开始抓取: {' / '.join(s['name'] for s in S.SOURCES)}")

    fetched, errors = core.gather(S.DEFAULT_IDS, {})
    prev = load_previous(os.path.join(out, "feed.json"))

    for e in errors:
        print("  ! " + e)

    if not fetched:
        # 全部源都失败时不要用空结果覆盖线上订阅
        print("所有源都抓取失败，保留上一版订阅不动。")
        return 1

    # 新抓的在前，保证去重时优先保留新数据
    # 先规整再合并：磁力格式修正、dmhy 分类过滤都要覆盖到历史条目，
    # 否则旧数据会把 already fixed 的问题重新带回订阅里。
    items = core.normalize_items(fetched + prev)
    items = core.dedupe(items)
    items = prune(items)
    items.sort(key=core.ts_of, reverse=True)

    # 先按源限流，避免大站（动漫花园）把小站挤出榜单
    by_src = {}
    for it in items:
        by_src.setdefault(it["source"], []).append(it)
    items = []
    for _sid, lst in by_src.items():
        items.extend(lst[:PER_SOURCE])
    items.sort(key=core.ts_of, reverse=True)
    items = items[:MAX_KEEP]

    raw_count = {}
    for it in fetched:
        raw_count[it["source"]] = raw_count.get(it["source"], 0) + 1
    print("新抓 " + " / ".join(f"{S.BY_ID[k]['name']} {v}" for k, v in raw_count.items()))
    print(f"合并后 {len(items)} 条 · 错误 {len(errors)} 个 · 用时 {time.time() - t0:.1f}s")

    per_source = {}
    for it in items:
        per_source[it["source"]] = per_source.get(it["source"], 0) + 1

    feeds_meta = []
    ids_taken = set(S.BY_ID)

    def emit(fid, title, sel, limit, primary=False, meta=True):
        sel = sel[:limit]
        params = {"limit": str(limit)}
        url = f"{site}/{fid}.xml" if site else None
        xml, n = core.build_rss(
            sel, params, url, errors,
            pre_filtered=True, title_override=title,
        )
        write_text(os.path.join(out, f"{fid}.xml"), xml.decode("utf-8"))
        if primary:
            # 主订阅单独再生成一次，让 atom:self 指向 feed.xml 而不是 <id>.xml
            x2, _ = core.build_rss(
                sel, params, f"{site}/feed.xml" if site else None, errors,
                pre_filtered=True, title_override=title,
            )
            write_text(os.path.join(out, "feed.xml"), x2.decode("utf-8"))
        if meta:
            feeds_meta.append({"id": fid, "title": title, "file": f"{fid}.xml", "count": n,
                               "primary": primary})
        print(f"  {fid}.xml  {n} 条  ·  {title}")
        return n

    # 1) feeds.json 定义的自定义订阅
    specs = load_feeds()
    if specs and not any(bool(s.get("primary")) for s in specs):
        specs[0]["primary"] = True      # 没指定就让第一条当主订阅
    primary_done = False
    for spec in specs:
        fid = str(spec["id"]).strip()
        if not fid.isalnum() and not all(c.isalnum() or c in "-_" for c in fid):
            print(f"  ! 跳过非法 id: {fid}")
            continue
        if fid in ids_taken:
            print(f"  ! id 与站点冲突，跳过: {fid}")
            continue
        ids_taken.add(fid)
        sids = S.resolve_ids(spec.get("src"))
        limit = max(1, min(int(spec.get("limit") or 150), 500))
        sel = [it for it in items if it["source"] in sids and match(it, spec)]
        title = (spec.get("title") or fid) + describe(spec)
        primary = bool(spec.get("primary")) and not primary_done
        emit(fid, title, sel, limit, primary=primary)
        primary_done = primary_done or primary

    # 2) 按单一站点拆分的订阅（页面从 sources 里单独渲染，不进 feeds 列表）
    for s in S.SOURCES:
        sid = s["id"]
        sel = [it for it in items if it["source"] == sid]
        emit(sid, f"{core.SITE_TITLE} · {s['name']}", sel, 120, meta=False)

    if not primary_done and feeds_meta:
        # 没有标记 primary 时，把第一条当作主订阅
        first = feeds_meta[0]
        src = os.path.join(out, first["file"])
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out, "feed.xml"))
            first["primary"] = True

    # 3) 页面数据
    payload = {
        "ok": True,
        "site": site,
        "builtAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "builtAtUtc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "count": len(items),
        "errors": errors,
        "feeds": feeds_meta,
        "sources": [
            {"id": s["id"], "name": s["name"], "home": s["home"], "note": s["note"],
             "count": per_source.get(s["id"], 0),
             "ok": per_source.get(s["id"], 0) > 0}
            for s in S.SOURCES
        ],
        "items": [dump_item(it) for it in items],
    }
    write_text(os.path.join(out, "feed.json"),
               json.dumps(payload, ensure_ascii=False, indent=1))
    write_text(os.path.join(out, "status.json"),
               json.dumps({k: v for k, v in payload.items() if k != "items"},
                          ensure_ascii=False, indent=1))

    # 4) 页面与 .nojekyll
    tpl = os.path.join(HERE, "web", "index.html")
    if os.path.exists(tpl):
        shutil.copyfile(tpl, os.path.join(out, "index.html"))
    write_text(os.path.join(out, ".nojekyll"), "")

    print(f"完成，产物在 {out}（用时 {time.time() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
