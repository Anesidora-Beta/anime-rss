#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slim_magnet 的单元测试：验证磁力规整在各种边界下都正确。"""

import re
import sys
import urllib.parse

import server as core
import sources as S

cases = []


def add(name, got, want_check, detail=""):
    ok, note = want_check(got)
    cases.append((name, ok, note or detail))


def check_hex40_and_dn(got):
    m = re.match(r"magnet:\?xt=urn:btih:([0-9a-f]{40})", got)
    if not m:
        return False, f"btih 非 hex40: {got[:60]}"
    if "&dn=" not in got:
        return False, "缺少 dn"
    dn = urllib.parse.unquote(got.split("&dn=")[1].split("&")[0])
    if not dn.strip():
        return False, "dn 为空"
    return True, dn


# 1. 动漫花园典型：base32 + 空 dn
dmhy = ("magnet:?xt=urn:btih:ET3OE2Y3ZWEQJRSEU5BIWFW6CBXVAP3B&dn="
        "&tr=http%3A%2F%2F104.143.10.61%3A8000%2Fannounce"
        "&tr=http%3A%2F%2Ft.nyaatracker.com%3A80%2Fannounce"
        "&tr=http%3A%2F%2Fopen.acgtracker.com%3A1096%2Fannounce"
        "&tr=http%3A%2F%2Ftr.bangumi.moe%3A6969%2Fannounce")
got = core.slim_magnet(dmhy, "[LoliHouse] 青之箱 / Blue Box - 03 [WebRip 1080p]")
add("dmhy base32 + 空 dn", got, check_hex40_and_dn)
# 期望值独立算一遍，不硬编码，避免把测试写死
import base64
expect_hex = base64.b32decode("ET3OE2Y3ZWEQJRSEU5BIWFW6CBXVAP3B").hex()
if expect_hex in got:
    cases.append(("base32 转换正确", True, expect_hex))
else:
    cases.append(("base32 转换正确", False, f"期望 {expect_hex}，实际 {got[:60]}"))

# 2. Nyaa 典型：无 dn
nyaa = ("magnet:?xt=urn:btih:d1168ab99f5ef54cc361ca00fe53169866b6cbec"
        "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
        "&tr=udp%3A%2F%2Fopen.tracker.cl%3A1337%2Fannounce"
        "&tr=udp%3A%2F%2Ftracker.openbittorrent.com%3A80%2Fannounce"
        "&tr=udp%3A%2F%2Fexodus.desync.com%3A6969%2Fannounce")
got = core.slim_magnet(nyaa, "[Erai-raws] Watashi no Shiawase na Kekkon - 12")
add("nyaa 无 dn", got, check_hex40_and_dn)

# 3. 标题含特殊字符 & # % 空格
tricky = "[Group] Show & Tell #1 100% [1080p]"
got = core.slim_magnet(nyaa, tricky)
ok, dn = check_hex40_and_dn(got)
add("标题含 & # % 特殊字符", got,
    (lambda g: (ok and dn == tricky, f"还原为「{dn}」" if dn else "")))

# 4. tracker 数量限制
add("tracker 截到 3 个", got,
    (lambda g: (g.count("&tr=") == 3, f"实际 {g.count('&tr=')} 个")))

# 5. 幂等性：连续处理两次结果一致
once = core.slim_magnet(nyaa, tricky)
twice = core.slim_magnet(once, tricky)
add("重复处理幂等", twice, (lambda g: (g == once, "两次结果一致" if g == once else f"不一致:\n   {once}\n   {g}")))

# 6. 已有正确 dn 的应保留原值而不是被标题覆盖
withdn = ("magnet:?xt=urn:btih:d1168ab99f5ef54cc361ca00fe53169866b6cbec"
          "&dn=%E5%B7%B2%E6%9C%89%E5%90%8D%E7%A7%B0&tr=udp%3A%2F%2Fx%3A1")
got = core.slim_magnet(withdn, "不该覆盖的标题")
ok, dn = check_hex40_and_dn(got)
add("保留原有 dn", got, (lambda g: (dn == "已有名称", f"dn={dn}")))

# 7. 非磁力输入原样返回
for bad in ["", "https://acg.rip/t/123.torrent", "magnet:?xt=urn:xx"]:
    got = core.slim_magnet(bad, "标题")
    add(f"非标准输入原样返回「{bad[:22]}」", got,
        (lambda g, b=bad: (g == b, "保持原样" if g == b else f"被改动为 {g[:40]}")))

# 8. 缺 title 时不应炸
got = core.slim_magnet(nyaa, "")
add("无标题时降级", got,
    (lambda g: (g.startswith("magnet:?xt=urn:btih:") and "&dn=&" not in g, "未产生空 dn")))

print("=" * 70)
print("磁力规整单元测试")
print("=" * 70)
fails = 0
for name, ok, note in cases:
    if ok:
        print(f"  ok    {name:<28} {note[:60]}")
    else:
        fails += 1
        print(f"  FAIL  {name:<28} {note[:90]}")
print("-" * 70)
print(f"通过 {len(cases) - fails}/{len(cases)}")
print()
print("样例输出：")
print(" ", core.slim_magnet(dmhy, "[LoliHouse] 青之箱 / Blue Box - 03 [WebRip 1080p]"))
sys.exit(0 if fails == 0 else 1)
