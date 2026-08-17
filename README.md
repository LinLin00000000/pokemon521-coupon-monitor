# 宝可梦 521 兑换码监测器

一个尽量小的、只读的 GitHub Actions 项目：读取公开 Telegram 通知频道 `@pokemon521`，并在活动帖启用公开 Discussion Widget 时统计评论共识，提取当月兑换码候选。

它不会登录 Telegram、加入交流群、创建机器人、使用 Telegram API 凭据、保存 Cookie/Session，也不会调用官网优惠码接口或自动兑换。

## 最新兑换码

> **飞天螳螂**
>
> 当前状态：`locked`（3/3 次独立运行一致）
>
> 活动帖：<https://t.me/pokemon521/395>
>
> 证据摘要：286 条公开评论中有 55 条匹配，至少 25 个公开用户链接支持。
>
> 这表示它是公开评论共识锁定的当月候选，不是官网接口验证结果，也不是自动兑换结果；兑换仍由用户人工完成。以后每月请以机器可读接口中的 `status` 和 `candidates` 为准，不要把 README 这一行当作永久静态值。

### 机器可读接口

```text
https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json
```

备用读取地址：

```text
https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/refs/heads/main/data/latest.json
https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/contents/data/latest.json?ref=main
```

### 解析方式

接入方应按下面的确定性规则读取：

1. 获取 `latest.json`；
2. 只有 `status == "locked"` 才把结果作为已锁定兑换码；
3. 遍历 `candidates[]`，筛选 `freshness == "current_month"`、`needs_manual_review == false` 且 `code` 为非空字符串的候选；
4. 读取候选的 `code` 字段；不要从 `evidence`、评论最高频普通词或图片 URL 推断兑换码；
5. 没有符合条件的候选时返回“暂未锁定”，不要自动尝试其他候选。

简化后的响应结构如下：

```json
{
  "status": "locked",
  "candidates": [
    {
      "code": "飞天螳螂",
      "freshness": "current_month",
      "needs_manual_review": false,
      "kind": "comment_consensus"
    }
  ],
  "lock": {
    "observations": 3,
    "required_observations": 3
  }
}
```

### API 接入示例：curl + jq

```bash
curl --fail --silent --show-error \\
  'https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json' \\
| jq -er '
    if .status != "locked" then
      error("coupon is not locked")
    else
      [.candidates[]
       | select(.freshness == "current_month")
       | select(.needs_manual_review == false)
       | .code
       | select(type == "string" and length > 0)]
      | if length == 0 then error("no current locked candidate") else .[0] end
    end
  '
```

成功时输出：

```text
飞天螳螂
```

### API 接入示例：Python（含 429 回退）

下面的示例先读取 raw，遇到 `429` 或临时 5xx 时尝试 `refs` raw，再回退到 GitHub Contents API。Contents API 的 `content` 字段需要 Base64 解码。三个地址都不需要 Telegram Session；GitHub 匿名 API 仍有自己的请求限额，生产环境应缓存结果。

```python
import base64
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

URLS = [
    "https://raw.githubusercontent.com/LinLin00000000/"
    "pokemon521-coupon-monitor/main/data/latest.json",
    "https://raw.githubusercontent.com/LinLin00000000/"
    "pokemon521-coupon-monitor/refs/heads/main/data/latest.json",
]
CONTENTS_URL = (
    "https://api.github.com/repos/LinLin00000000/"
    "pokemon521-coupon-monitor/contents/data/latest.json?ref=main"
)


def get_json(url):
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def load_latest():
    for url in URLS:
        try:
            return get_json(url)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                raise

    envelope = get_json(CONTENTS_URL)
    content = "".join(envelope["content"].split())
    return json.loads(base64.b64decode(content).decode("utf-8"))


def latest_locked_code(payload):
    if payload.get("status") != "locked":
        return None
    for candidate in payload.get("candidates", []):
        if (
            candidate.get("freshness") == "current_month"
            and candidate.get("needs_manual_review") is False
            and isinstance(candidate.get("code"), str)
            and candidate["code"]
        ):
            return candidate["code"]
    return None


payload = load_latest()
code = latest_locked_code(payload)
print(code if code is not None else "暂未锁定")
```

## 当前验证结果

2026-08-17 对活动帖 [`pokemon521/395`](https://t.me/pokemon521/395) 做了真实匿名 HTTPS 测试：

| 数据 | 实际结果 | 结论 |
|---|---:|---|
| 通知频道公开历史 | 85 条可见帖子，5 个 `?before=` 页面 | 可以匿名读取 |
| 帖子 395 的公开 Discussion Widget | 286 条评论，6 页 | 可以匿名读取评论 |
| 规范化后完全/语义简化为“飞天螳螂”的答案 | 55 条 | 形成强候选 |
| 带公开用户链接的不同评论者下限 | 25 人 | 超过 3 人共识门槛 |
| `@pokemon_love` 公开预览 | 只有群简介，没有聊天历史 | 不作为匿名历史源 |

评论读取使用的是 Telegram 网页公开的 Discussion Widget：先 GET 活动帖的 `?embed=1&discussion=1` 页面，再从页面公开返回的分页字段和动态 `api_url` 调用 `loadComments`，读取更早评论。这里没有 Telegram 登录态、Bot Token、API ID/API Hash、Cookie 或 Session。

## 公开端点清单与实现边界

这里要区分“端点类型”和“具体分页 URL”：`?before=<post_id>` 是一个分页模板，不会因为每个消息 ID 不同就算成新的端点。按当前代码统计，Telegram 来源共有 **8 类公共端点：7 个匿名 GET 入口/模板 + 1 个由页面动态给出的匿名 POST 入口**。

以下是本次测试使用的完整 URL（UTC：2026-08-17 14:34）：

| # | 完整 URL | 方法 | 用途 | 测试结果 |
|---:|---|---|---|---|
| 1 | <https://t.me/pokemon521> | GET | 通知频道简介 | HTTP 200 |
| 2 | <https://t.me/s/pokemon521> | GET | 通知频道公开历史 | HTTP 200 |
| 3 | <https://t.me/s/pokemon521?before=395> | GET | 历史分页示例；代码实际会把 `395` 换成当前页面最旧帖子 ID | HTTP 200 |
| 4 | <https://t.me/pokemon521/395> | GET | 2026-08 活动帖永久链接 | HTTP 200 |
| 5 | <https://t.me/pokemon521/395?embed=1&discussion=1&comments_limit=50> | GET | 活动帖公开 Discussion Widget 首页 | HTTP 200；286 条评论、首页 50 条 |
| 6 | <https://t.me/api/method?api_hash=1f4736830bf40aa915> | POST | Widget 返回的 `loadComments` 公共分页入口 | 当前可用；必须 POST，表单字段每次从第 5 个页面读取，不能硬编码 |
| 7 | <https://t.me/pokemon_love> | GET | `@pokemon_love` 群公开简介 | HTTP 200 |
| 8 | <https://t.me/s/pokemon_love> | GET | 群历史匿名探测 | HTTP 200，但重定向到群简介、消息数 0 |

第 6 个 URL 中的 `api_hash` 是 Telegram 网页 Widget 自己公开提供的前端参数，不是本项目的登录凭据；`peer`、`top_msg_id`、`discussion_hash` 和 `before_id` 不写入仓库，而是从当前 Widget 响应中临时读取。当前一次真实分页结果是 6 页、286 条评论、没有截断。

### 发布数据的公共读取 URL

仓库数据不是 Telegram 端点。当前按 4 个公开文件、3 种读取方式展开，共有 **12 个数据 URL**：

| 文件 | GitHub raw（用户给出的形式） | raw 的 `refs` 形式 | GitHub Contents API |
|---|---|---|---|
| 当前结果 | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json> | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/refs/heads/main/data/latest.json> | <https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/contents/data/latest.json?ref=main> |
| 历史记录 | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/history.jsonl> | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/refs/heads/main/data/history.jsonl> | <https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/contents/data/history.jsonl?ref=main> |
| 状态锁 | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/state.json> | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/refs/heads/main/data/state.json> | <https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/contents/data/state.json?ref=main> |
| 中文名称表 | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/pokemon_names_zh.json> | <https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/refs/heads/main/data/pokemon_names_zh.json> | <https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/contents/data/pokemon_names_zh.json?ref=main> |

Contents API 返回的是带 metadata 的 JSON 包装，文件正文在 `content` 字段中并以 Base64 编码；它适合程序化回退，不是直接展示 `latest.json` 正文的等价链接。raw 入口适合直接显示 JSON，但 GitHub 会按访问者出口 IP、时间和缓存路径限流。

**数量口径：** Telegram 运行时是 8 类端点；仓库数据读取是 12 个具体 URL；因此如果把两部分合并并按上表展开，是 20 个可测试 URL，不包括 GitHub 仓库首页和每一个动态 `before_id` 分页实例。


## 自动确认策略

当前默认门槛是：

1. 活动帖属于当前月份，并且是图片猜码/兑换码活动；
2. 只从评论中提取已知宝可梦中文名称，避免把“官网”等普通高频词误判为答案；
3. 至少 3 条匹配评论；
4. 至少 3 个带公开资料链接的不同评论者支持；
5. 同一候选在 3 次独立监测运行中保持一致后，写入 `data/state.json` 并锁定；
6. 锁定后后续定时运行直接跳过 Telegram 抓取，避免全年重复请求。

因此，第一次看到强共识时状态是 `comment_candidates`，不是立即宣称最终确认。状态锁达到 3 次后才是 `locked`。

## 宝可梦中文名称表：完整性与维护策略

当前 `data/pokemon_names_zh.json` 有 **1,025 个唯一的简体中文 canonical 名称**，其中包括 `飞天螳螂`。这个数量与：

- [PokeAPI 的 `pokemon-species` 列表](https://pokeapi.co/api/v2/pokemon-species?limit=2000) 返回的 1,025 个物种；
- [神奇宝贝百科的全国图鉴列表](https://wiki.52poke.com/zh/%E5%AE%9D%E5%8F%AF%E6%A2%A6%E5%88%97%E8%A1%A8%EF%BC%88%E6%8C%89%E5%85%A8%E5%9B%BD%E5%9B%BE%E9%89%B4%E7%BC%96%E5%8F%B7%EF%BC%89) 所述的 1,025 种；
- [名称表上游数据集](https://github.com/42arch/pokemon-dataset-zh) 的 1～9 世代范围

一致。因此，**作为“第 1～9 世代、每个基础物种一个简体中文官方/主流名称”的过滤表，它目前是完整的**。这不等于覆盖所有评论写法：

| 范围 | 当前覆盖 | 说明 |
|---|---|---|
| 1,025 个基础物种的简体中文名称 | 是 | 这是当前自动确认的正向白名单 |
| 地区形态、Mega/极巨化、不同形态的独立叫法 | 不单独保证 | 图鉴页面的物种数和形态数不是同一口径；兑换码答案通常还是基础名称 |
| 繁体字、旧译名、港台译名 | 否 | 例如不自动把繁体写法当成简体 canonical 名称 |
| 英文、日文、罗马字、玩家昵称、缩写 | 否 | 避免把普通英文/昵称误判为答案 |
| 错别字、谐音、口语简称 | 否 | 需要有证据后单独加入 alias 表，不能自动扩张 |

### 为什么不采用“全量词频 + 黑名单”作为主算法

把“官网”加入黑名单是有用的**第二层防线**，但不能替代白名单：

1. 黑名单只能排除已经知道的词；新的普通词、活动套话、昵称和错别字仍会漏进来。
2. “官网”“答案”“兑换成功”等词可能因为讨论语境而非常高频；高频不代表兑换码。
3. 正确答案本身也可能是高频词。2026-08 活动中“飞天螳螂”出现 55 次，不能因为它频率高就认为它是噪声。
4. 复制答案会让评论数膨胀；真正有价值的是不同公开用户、不同时间和同一活动帖绑定，而不是词频本身。
5. 仅靠全量分词还会受到中文分词、短词包含关系和评论中同时提到多个宝可梦的影响。

所以当前采用：

```text
正向 canonical 白名单
  + 少量已知非答案黑名单（辅助）
  + 最长名称匹配
  + 两个不相关名称同时出现则拒绝
  + 不同公开用户数 / 评论数 / 时间分布 / 活动帖关联
  + 跨运行状态锁
```

代码已经处理了“地鼠”是“三地鼠”子串这一类情况：`我猜是三地鼠吧` 会选择唯一的最长 canonical 名称；`三地鼠和飞天螳螂` 会因为出现两个不相关候选而拒绝，不会强行选最高频的一个。

### 如果以后发现遗漏，处理方式

不直接把陌生高频词自动加入白名单，而是走一个小的 alias 维护流程：

1. 记录未匹配文本的匿名聚合统计，不把评论全文、用户名或用户 ID 发布到仓库；
2. 检查它是否是 canonical 名称的繁体、旧译名、常见简称、错别字，还是普通语境词；
3. 至少找到一条官方/图鉴映射或多次独立活动证据；
4. 把确认后的写法放入单独的 alias 文件，保留 `alias -> canonical`、来源 URL、确认日期和备注；
5. 为 alias 增加测试，并继续要求评论共识与状态锁；
6. 如果只是一次拼写或单个用户的自造昵称，保持未确认，不进入自动锁定路径。

这样即使名称表将来扩充，也不会因为一个评论区高频噪声把“官网”或其他普通词误升级为兑换码。


GitHub Actions 使用 UTC：

```text
每月 1～7 日：00:17、04:17、08:17、12:17、16:17、20:17 UTC
```

每天 6 次只发生在月初 7 天；其余日期不按 cron 运行。仍保留 `workflow_dispatch` 供手动触发。并发运行不会互相取消，避免状态锁计数丢失。

## 实际实现流程

```text
1. 读取 sources.json；只使用公开 URL
2. GET https://t.me/s/pokemon521
3. 按页面最旧帖子 ID 生成 ?before=<id>，去重并分页
4. 从帖子 HTML 提取 ID、时间、正文、图片和评论入口
5. 用规则提取正文明确兑换码；图片只记录为 media_clue，不 OCR、不猜码
6. 只保留当前月份的活动帖作为评论读取目标
7. GET 活动帖 Discussion Widget，读取评论总数和第一页
8. 从 Widget 读取动态 api_url 与分页字段，POST loadComments 直到完成或达到上限
9. 规范化评论文本，只匹配 canonical 宝可梦名称；处理最长名称和多候选冲突
10. 按候选统计评论数和公开用户链接下限，排除普通高频词
11. 连续 3 次独立运行同一候选后写入 state.json 并锁定
12. 输出 latest.json、history.jsonl、state.json；锁定后下一次运行直接跳过网络抓取
```

评论正文不会完整写入公开仓库；当前只保留评论总数、匹配数量、公开用户链接支持数下限和少量评论 ID 样本。`@pokemon_love` 只做简介/历史可见性探测，不作为当前匿名答案源。


`data/latest.json` 的 `status`：

- `comment_candidates`：公开评论已形成符合门槛的候选，但尚未完成 3 次独立运行锁定。
- `locked`：当前月份候选已通过状态锁；后续运行会跳过抓取。
- `text_candidates`：本月公开正文中发现明确兑换码候选，但尚未完成锁定；不代表官网有效。
- `media_needs_manual_review`：发现图片活动，但目前没有足够的公开评论共识或明文候选。
- `historical_only`：只发现旧月份信号，不把旧码放入当前候选。
- `no_relevant_posts`：扫描窗口内没有相关信号。

`data/latest.json` 会反映最近一次已发布运行：可能是 `comment_candidates`，也可能在完成 3 次观察后变成 `locked`。候选 `飞天螳螂` 只代表公开评论共识，不是官网接口验证结果；用户仍然人工登录兑换。

## 仓库结构

```text
.
├── monitor.py                         # 频道抓取、规则提取、状态锁、输出
├── discussion.py                      # 匿名 Discussion Widget 分页与评论共识
├── sources.json                       # 公开源配置，不含凭据
├── data/
│   ├── latest.json                    # 当前机器可读结果
│   ├── history.jsonl                  # 去重后的历史信号
│   ├── state.json                     # 月份候选的跨运行锁状态
│   └── pokemon_names_zh.json          # 静态宝可梦中文名称集合
├── tests/test_monitor.py              # 频道解析、规则、分页和幂等测试
├── tests/test_discussion.py           # 评论解析、名称过滤和作者下限测试
└── .github/workflows/monitor.yml      # 月初 7 天高频运行
```

`pokemon_names_zh.json` 的名称集合来自公开项目 [`42arch/pokemon-dataset-zh`](https://github.com/42arch/pokemon-dataset-zh)，仅作为本地候选过滤词表；运行时不依赖该项目的在线 API。

## 使用

本地运行不需要 Python 第三方依赖：

```bash
python3 -m unittest discover -s tests -v
python3 monitor.py --max-messages 100 --max-pages 8 \
  --max-discussion-posts 3 --max-comments 500 --lock-observations 3
```

如果当前网络需要代理，在命令前设置标准环境变量即可：

```bash
HTTPS_PROXY=http://<your-proxy-host>:<port> \\
HTTP_PROXY=http://<your-proxy-host>:<port> \\
python3 monitor.py
```

GitHub Actions 使用公开 Runner 的网络，不需要设置 Telegram Secret。工作流只授予：

```yaml
permissions:
  contents: write
```

提交身份固定为 `github-actions[bot]`，不会使用本机 Git 用户名或邮箱。

这意味着：

- 定时扫描产生的数据提交显示为 `github-actions[bot]`，这是有意保留的自动化来源标记，不是你的个人 GitHub 登录账号；
- 当前早期的功能提交也曾在本地使用同一个通用 bot 身份创建，因此提交历史里的 `feat:`、`merge:` 和 `chore:` 都可能显示为 bot；
- 如果以后要区分“用户手工修改”和“Actions 数据更新”，推荐手工修改使用你的 GitHub 账号，定时数据继续使用 bot；
- 不应为了改显示名称而重写已经公开的历史或强制推送。若要改未来提交身份，需要明确指定已验证的 GitHub noreply 邮箱，并重新认证 push。

## 固定资源 URL

仓库地址：

```text
https://github.com/LinLin00000000/pokemon521-coupon-monitor
```

当前机器可读结果：

```text
https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json
```

历史记录：

```text
https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/history.jsonl
```

## GitHub raw 的 429 与“无法检索最新提交”

如果浏览器打开 raw URL 显示：

```text
429: Too Many Requests
```

这通常表示当前访问者的出口 IP、GitHub raw 边缘缓存或 GitHub 当时的服务状态触发了限流/错误率保护，不表示 JSON 文件不存在或格式损坏。不要连续刷新或并发重试；先等待一段时间，再减少读取频率。

本次排查时，GitHub Status 页面报告了 GitHub.com 部分故障，并明确提到 raw repository content downloads 处于较高错误率；同一时间 GitHub Contents API、仓库 `main` ref、commit 列表和 tree API 均可正常返回。因此：

- 直接 raw URL 仍保留为最简固定链接，但不承诺任何访问者、任何时刻都能绕过 GitHub 限流；
- 程序化回退使用上面的 [Contents API](https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/contents/data/latest.json?ref=main)，读取其 `content` Base64 字段；
- `raw` 的 `refs/heads/main` 形式可作为第二个测试表示，但仍然属于 GitHub raw 内容服务，不能视为独立 CDN；
- GitHub Pages 当前没有启用，不能直接假定 `*.github.io` URL 可用；如果以后需要长期稳定的无包装 JSON URL，应单独启用 Pages 或受控 CDN，而不是反复撞 raw 端点。

仓库首页偶尔显示“无法检索最新的提交”时，先用以下两个只读 API 验证仓库是否真的异常：

```text
https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/commits?per_page=1
https://api.github.com/repos/LinLin00000000/pokemon521-coupon-monitor/git/ref/heads/main
```

只要它们能返回最新 commit 和 `main` 的 commit SHA，通常就是 GitHub 网页层/缓存/服务降级，而不是提交对象丢失。不要因为这个提示就重建仓库或强制推送。


当前主链路不需要 Session：通知群活动帖的公开评论已经能提供足够强的兑换码共识。

`@pokemon_love` 仍然只有公开简介入口，不能通过匿名 `t.me/s` 页面取得完整聊天历史。如果未来要利用那里更早或更分散的兑换码线索，应做成单独的本地/私有读取器：Session 只能由用户在真实终端登录后产生，不能提交到 GitHub、不能写入公开数据，也不能放进公共 Actions。它是备用增强路径，不是当前自动确认的前置条件。

## 安全边界

- 不保存 Telegram Bot Token、API ID/API Hash、登录 Session、Cookie 或官网凭据。
- 不加入 `@pokemon_love`，不启动机器人，不读取未公开消息。
- 只调用公开网页和公开 Discussion Widget，不调用需要认证的 Telegram MTProto/Bot API。
- 不调用官网优惠码校验、订单创建、支付或兑换接口。
- 不自动 OCR、猜测图片文字或批量尝试兑换码。
- 评论证据只保存聚合统计，不保存评论全文、用户名或用户 ID。
- GitHub Actions 只提交 `data/latest.json`、`data/history.jsonl` 和 `data/state.json` 的内容变化。

## License

MIT
