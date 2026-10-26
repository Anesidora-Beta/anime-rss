# 动漫资源 · RSS 增强订阅

把主流动漫资源站的更新统一清洗成干净的 RSS，**每条帖子自动提取磁力链接、种子直链、帖子页和正文外链**，  
丢进任意 RSS 阅读器就能持续追更。支持多站合并、跨站去重、按番剧/字幕组/画质筛选。

两种用法：

| 用法                      | 订阅地址                            | 适合              | 需要什么         |
| ----------------------- | ------------------------------- | --------------- | ------------ |
| **A. GitHub Pages（推荐）** | 公网固定地址，任何网络都能用                  | 手机、平板、公司电脑随处订阅  | 一个 GitHub 账号 |
| **B. 本地服务**             | `http://localhost:8899/rss.xml` | 只在电脑上用；需要临时参数筛选 | 电脑开机         |

A 方案由 GitHub 每 20 分钟自动抓取一次，页面和订阅都是静态文件，**不用开电脑**。  
B 方案实时抓取、支持任意参数组合，但服务关了就停了。两者可以同时用。

## 支持的站点

| 站点                        | 说明           | 提供的下载方式       |
| ------------------------- | ------------ | ------------- |
| **动漫花园** `share.dmhy.org` | 中文资源最全       | 磁力链接          |
| **蜜柑计划** `mikanani.me`    | 番剧订阅为主，字幕组集中 | 种子直链（附文件大小）   |
| **ACG.RIP** `acg.rip`     | WebRip 画质好   | 种子直链（附文件大小）   |
| **Nyaa** `nyaa.si`        | 国际站，RAW 与英译  | 磁力链接（附做种数）    |
| **萌番组** `bangumi.moe`     | 磁力完整         | 磁力链接（附做种数、大小） |

各站给的字段并不一致：只有动漫花园、Nyaa、萌番组带 infoHash（能拼磁力），  
蜜柑计划和 ACG.RIP 只给 `.torrent` 直链。服务会把它们统一成同一套结构，  
有什么给什么，缺的不硬凑。

**为什么蜜柑计划不给磁力**：它的 Episode hash 看起来像 infoHash，实测却和它自己种子的真实  
infohash 不一致（它重新打包过），硬拼出来的磁力会下不动。所以只给可靠的 `.torrent` 直链。

**跨站去重为什么能对上**：动漫花园用 base32 表示 infohash（32 位），蜜柑/Nyaa/萌番组用 hex（40 位）。  
服务内部统一转成 hex 再比较，所以同一种子在不同站能认出来是同一个。

---

# A. 部署到 GitHub Pages（公网订阅）

> **本仓库已部署完成**，直接用下面的地址即可，不需要再走一遍流程：
>
> | 用途          | 地址                                                    |
> | ----------- | ----------------------------------------------------- |
> | **订阅源（推荐）** | `https://anesidora-beta.github.io/anime-rss/feed.xml` |
> | 可视面板        | `https://anesidora-beta.github.io/anime-rss/`         |
>
> 当前状态：5 个源全部正常，共 278 条，零错误；每 20 分钟自动更新。
>
> 下面 1~5 节保留为「换一个仓库重新部署」时的步骤说明。

## 1. 新建仓库

打开 <https://github.com/new>，填一个仓库名（比如 `anime-rss`），  
**Visibility 选 Public**（Private 仓库的 Pages 需要付费计划），不要勾选任何初始化文件。

## 2. 推送代码

在命令行里执行（把 `你的用户名` 换成实际用户名，仓库名同理）：

```bash
cd 你存放项目的目录\dmhy-rss
git remote add origin https://github.com/你的用户名/anime-rss.git
git push -u origin main
```

仓库已经在本地初始化并提交好了，上面两条就能推上去。第一次会要求登录：  
用浏览器授权，或者填一个 [Personal Access Token](https://github.com/settings/tokens) 当密码。

## 3. 打开 Pages（只需一次）

仓库页面 → **Settings** → 左侧 **Pages** → **Build and deployment** →  
**Source 选 `GitHub Actions`**（不要选 Deploy from a branch）。

这一步没法省略：创建 Pages 站点需要仓库管理员权限，而工作流用的 `GITHUB_TOKEN`  
拿不到这个权限（实测报 `Resource not accessible by integration`），所以由本人点一次。  
开好之后工作流就能一直自动发布，不用再管。

## 4. 手动跑一次

如果推送时工作流已经因为 Pages 没开而失败过，去 **Actions** → 左侧「更新资源订阅」→  
右上 **Run workflow** → 绿色按钮重跑一次（不重跑的话，最多等 20 分钟下一次定时任务也会补上）。

等 1 分钟左右跑完，页面上会显示订阅地址。之后每 20 分钟自动更新。

## 5. 订阅地址

```
https://你的用户名.github.io/anime-rss/feed.xml
```

打开 `https://你的用户名.github.io/anime-rss/` 是可视面板：显示每个源的状态、  
所有可用的订阅频道、最新条目（带磁力按钮和一键复制订阅地址）。

## 自定义订阅频道

改 `feeds.json` 再推送，下一次构建就会生成对应的 xml：

```json
{
  "feeds": [
    { "id": "all",  "title": "全部更新", "primary": true, "limit": 200 },
    { "id": "bluebox", "title": "青之箱", "keyword": ["青之箱"], "limit": 80 },
    { "id": "lh",   "title": "LoliHouse 1080p",
      "include": ["LoliHouse", "1080p"], "exclude": ["繁体"], "limit": 100 }
  ]
}
```

| 字段        | 说明                                                     |
| --------- | ------------------------------------------------------ |
| `id`      | 文件名，生成 `docs/<id>.xml`；第一个标 `primary` 的同时作为 `feed.xml` |
| `title`   | 阅读器里显示的频道名                                             |
| `src`     | 限定站点，如 `["dmhy","nyaa"]`，省略为全部                         |
| `keyword` | 标题必须含其中任一关键词                                           |
| `include` | 同 `keyword`，多个词任一命中                                    |
| `exclude` | 标题含任一关键词则排除                                            |
| `cat`     | 分类过滤，**只对动漫花园生效**                                      |
| `limit`   | 该频道最多输出多少条                                             |

除了 `feed.xml`，每个站还有一个独立频道：`dmhy.xml`、`mikan.xml`、`acgrip.xml`、  
`nyaa.xml`、`bangumi.xml`。

**静态方案的边界**：Pages 上是静态文件，不能像本地服务那样用 `?keyword=` 临时筛。  
关键词频道是在最近抓到的约 500 条里过滤，足够覆盖新番追更，但查不到很早以前的老资源。  
要任意条件实时筛，用下面的 B 方案。

## 关于定时任务的两件事

- **会延迟**：GitHub 的 cron 在高峰期可能晚几分钟，属正常；频率也不会快于 5 分钟。
- **60 天不动会暂停**：仓库 60 天没有任何提交时，GitHub 会自动停掉定时任务。  
  去 Actions 页面点一次 Run workflow 就恢复了。

## 滚动保留是怎么实现的

生成的 XML 不提交进仓库（否则每 20 分钟 600KB，一个月能把仓库撑到 1GB），  
所以 Actions 每次都是全新环境。为了让「某个源临时挂掉时条目不会突然消失」，  
构建前会先从**上一次发布到 Pages 的 `feed.json`** 把历史条目取回来，合并后再裁剪到 7 天内：

```yaml
- name: 取回上一轮条目（滚动保留用）
  run: curl -fsS --max-time 30 "${{ steps.site.outputs.url }}/feed.json" -o docs/feed.json || echo "首次运行"
```

取不到就按全新构建处理，不会让流程失败。副作用是构建依赖 Pages 可访问性 ——  
如果站点长期不可用，历史会断档，但新条目照常抓取。

---

# B. 本地运行

双击 **`启动.bat`**（需要 Python 3.9+）。窗口会打开浏览器并保持运行，  
**关掉窗口即停止服务**。

| 场景             | 地址                              |
| -------------- | ------------------------------- |
| 本机阅读器          | `http://localhost:8899/rss.xml` |
| 手机 / 同 WiFi 设备 | 把 `localhost` 换成电脑的局域网地址        |

首页 `http://localhost:8899/` 会自动显示当前可用的局域网地址，并提供一个可视化生成器 ——  
勾选站点和筛选条件后一键复制订阅地址。

## 可用参数

| 参数                    | 说明                  | 示例                  |
| --------------------- | ------------------- | ------------------- |
| `src`                 | 选择站点，逗号分隔，缺省为全部     | `?src=dmhy,mikan`   |
| `keyword`             | 站内搜索关键词             | `?keyword=青之箱`      |
| `include`             | 标题必须含其中任一关键词        | `?include=1080p,4K` |
| `exclude`             | 标题含任一关键词则排除         | `?exclude=繁体,480p`  |
| `limit`               | 合并后返回条数，1–500，默认 50 | `?limit=100`        |
| `cat`                 | 分类过滤，**只对动漫花园生效**   | `?cat=動畫,季度全集`      |
| `sort_id` / `team_id` | 动漫花园的分类 / 字幕组 ID    | `?team_id=407`      |

参数可组合，例如「只订 LoliHouse 的非繁体 1080p，最近 30 条」：

```
http://localhost:8899/rss.xml?include=LoliHouse,1080p&exclude=繁体&limit=30
```

---

# 通用说明

## 它解决了什么

原始 RSS 有三个毛病：

1. 正文是一大坨带内联样式的 HTML，阅读器里几乎没法看；
2. 真正的磁力/种子藏在 `enclosure` 标签里，多数阅读器不显示，复制不出来；
3. 正文里散落的发布页 / TG 群 / 字幕组仓库链接，得点进帖子页才能看到。

服务在服务端把这些问题一次处理掉，并把五个站的内容合并成一份按时间倒序的清单。

## 关于合并与去重

同时选多个站时：

- **并发抓取**，按发布时间倒序合并；
- **双键去重**：infohash 相同（跨语言同一种子）或标题相同（同语言重复发布）都算同一条；
- 保留信息最全的那条，并把其它站独有的字段（大小、种子直链、做种数）补进去。

所以五个站合起来看到的是**一份去重清单**，而不是五份内容重叠的清单。  
单站订阅（`src=dmhy`）不受影响，原样输出。

## 磁力链接做了三层规整

源站给的磁力直接转发会很难用，所以每条都处理过：

| 问题                                     | 处理                                 |
| -------------------------------------- | ---------------------------------- |
| 动漫花园用 base32 编码 btih（32 位），部分下载器只认 hex | 统一转成 40 位 hex，跨站也就能按同一 infohash 去重 |
| `dn`（显示名称）经常缺失，动漫花园的还是空串 `&dn=`        | 用条目标题补上并做 urlencode，下载器里能直接看到番剧名   |
| 原链接挂几十个 tracker，一条几百字节                 | 只保留前 3 个，够用了                       |

标题里的 `&`、`#`、`%` 都正确转义过，不会破坏磁力结构（有单元测试覆盖，见 `test_magnet.py`）。

## 关于动漫花园的分类过滤

动漫花园的 RSS 是**全站流**，实测 500 条的构成是：

```
動畫 364 · 日劇 49 · 季度全集 39 · 音樂 27 · 特攝 8 · 其他 7 · ＲＡＷ 3 · 動漫音樂 2 · 電腦遊戲 1
```

订阅「动漫资源」时只保留 **動畫 / 季度全集 / ＲＡＷ**，其余（日剧、音乐、有声书、游戏）都会被滤掉——  
不然订阅里会混进 `Japanese Audiobooks Archive` 这类完全无关的东西。

想放宽用参数：

| 参数               | 作用         |
| ---------------- | ---------- |
| 默认               | 只要动漫三类     |
| `dmhy_cat=動畫,特攝` | 自己指定要哪些分类  |
| `dmhy_all=1`     | 拿全站，不做分类过滤 |

## 自检脚本

仓库里带了四个测试，改完代码跑一遍能快速发现回归：

```bash
python test_magnet.py                 # 磁力规整的单元测试（离线，11 项）
python remote_test.py --rounds 3      # 线上可用性/结构/内容/一致性/稳定性（48 项）
python monitor_test.py --rounds 9     # 长周期采样，观察跨定时任务边界是否中断
python compat_test.py                 # 用 feedparser 模拟真实阅读器解析（需 pip install feedparser）
```

`remote_test.py` 侧重的是一旦发布出去会不会坏：状态码、字段完整性、时间排序、  
频道间数据一致性、条件请求 304、定时任务是否在跑。`compat_test.py` 验证的是  
「阅读器眼里的样子」——XML 合法不代表客户端能正确解读。`monitor_test.py` 按固定  
间隔采样若干分钟，重点看重新部署的那一瞬间有没有出现 404、XML 和 JSON 会不会  
版本错位。

## 推荐订阅方式

- **只追几部番**：`?keyword=番剧名`，一个番一个源，最清爽。
- **只要磁力**：`?src=dmhy,nyaa,bangumi`，这三个站直接给磁力。
- **只要种子文件**：`?src=mikan,acgrip`。
- **追整个字幕组**：`?include=组名`，标题里的 `[组名]` 会被命中。
- **只想看高画质**：`?include=1080p,2160p&exclude=480p`。
- **全站兜底**：不带参数，五站合并 50 条。

## 常见问题

**部分站点抓取失败**

面板顶部会显示每个源的状态和条数，失败的会标红。GitHub 的服务器在国外，  
个别站（尤其是 Nyaa）有时会拒绝机房 IP；单站失败不影响其它站的条目，  
上一次抓到过的条目也会保留 7 天，不会突然掉空。

**本地服务需要代理时**

服务默认跟随系统代理。若是 Clash 之类只开了端口没设系统代理，启动前设置：

```bat
set HTTPS_PROXY=http://localhost:7890
启动.bat
```

**端口被占用**

```bat
set PORT=9000
启动.bat
```

换端口后订阅地址要一起改，首页会显示新地址。

**数据多久更新一次**

本地服务缓存 5 分钟（`CACHE_TTL` 环境变量可调）；GitHub Actions 每 20 分钟重建一次。

## 自己加站点

编辑 `sources.py`，照着已有站点写两个函数再注册：

```python
def url_mysite(p):
    kw = (p.get("keyword") or "").strip()
    return f"https://example.com/rss?q={quote(kw)}" if kw else "https://example.com/rss"

def parse_mysite(raw, p):
    ch = ET.fromstring(raw).find("channel")
    return [
        item("mysite", it.findtext("title"), it.findtext("link"),
             magnet=(it.find("enclosure").get("url") or ""))
        for it in ch.findall("item")
    ]

# 然后在文件末尾的 SOURCES 列表里加一行
{"id": "mysite", "name": "我的站", "home": "https://example.com",
 "url": url_mysite, "parse": parse_mysite, "note": "备注"}
```

本地服务重启即生效；GitHub 方案推送后会自动重建，新站也会出现在面板和 `src=` 参数里。

## 开机自启（本地服务，可选）

1. `Win + R` 输入 `shell:startup` 回车；
2. 把 `启动.bat` 的快捷方式复制进去。

## 文件说明

| 文件                           | 作用                           |
| ---------------------------- | ---------------------------- |
| `server.py`                  | 本地服务入口（HTTP 接口 + RSS 输出）     |
| `sources.py`                 | 站点适配层，加站改这里                  |
| `build_feed.py`              | 静态构建脚本，GitHub Actions 调用它    |
| `feeds.json`                 | 公网页面的订阅频道定义                  |
| `web/index.html`             | 公网页面的模板，构建时复制到 `docs/`       |
| `index.html`                 | 本地服务的配置面板                    |
| `启动.bat`                     | 本地一键启动                       |
| `.github/workflows/feed.yml` | 定时抓取 + 发布 Pages 的工作流         |
| `docs/`                      | 构建产物（已在 `.gitignore` 里，不进仓库） |

## 技术说明

- 纯 Python 标准库，无第三方依赖；
- 公网方案用 `upload-pages-artifact` + `deploy-pages` 直接发布，**不往仓库提交生成物**，  
  所以仓库体积不会随运行次数增长；
- 已做 gzip 压缩，多源合并 100 条约 300KB → 约 35KB；
- 只做聚合与清洗，不存储、不缓存任何资源文件。
