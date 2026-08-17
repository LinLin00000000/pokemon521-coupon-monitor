# 宝可梦 521 兑换码监测器

一个尽量小的、只读的 GitHub Actions 项目：读取公开 Telegram 通知频道 `@pokemon521`，并在活动帖启用公开 Discussion Widget 时统计评论共识，提取当月兑换码候选。

它不会登录 Telegram、加入交流群、创建机器人、使用 Telegram API 凭据、保存 Cookie/Session，也不会调用官网优惠码接口或自动兑换。

## 当前验证结果

2026-08-17 对活动帖 [`pokemon521/395`](https://t.me/pokemon521/395) 做了真实匿名 HTTPS 测试：

| 数据 | 实际结果 | 结论 |
|---|---:|---|
| 通知频道公开历史 | 85 条可见帖子，5 个 `?before=` 页面 | 可以匿名读取 |
| 帖子 395 的公开 Discussion Widget | 286 条评论，6 页 | 可以匿名读取评论 |
| 规范化后完全/语义简化为“飞天螳螂”的答案 | 55 条 | 形成强候选 |
| 带公开用户链接的不同评论者下限 | 25 人 | 超过 3 人共识门槛 |
| `@pokemon_love` 公开预览 | 只有群简介，没有聊天历史 | 不作为匿名历史源 |

评论读取使用的是 Telegram 网页公开的 Discussion Widget：先 GET 活动帖的 `?embed=1&discussion=1` 页面，再使用页面公开返回的 `loadComments` 分页参数读取更早评论。这里没有 Telegram 登录态、Bot Token、API ID/API Hash、Cookie 或 Session。

当前运行结果不会把用户名、评论全文或个人资料写入仓库，只保存评论总数、匹配数量、公开用户链接支持数下限和少量公开评论 ID 作为审计线索。

## 自动确认策略

当前默认门槛是：

1. 活动帖属于当前月份，并且是图片猜码/兑换码活动；
2. 只从评论中提取已知宝可梦中文名称，避免把“官网”等普通高频词误判为答案；
3. 至少 3 条匹配评论；
4. 至少 3 个带公开资料链接的不同评论者支持；
5. 同一候选在 3 次独立监测运行中保持一致后，写入 `data/state.json` 并锁定；
6. 锁定后后续定时运行直接跳过 Telegram 抓取，避免全年重复请求。

因此，第一次看到强共识时状态是 `comment_candidates`，不是立即宣称最终确认。状态锁达到 3 次后才是 `locked`。

## 调度

GitHub Actions 使用 UTC：

```text
每月 1～7 日：00:17、04:17、08:17、12:17、16:17、20:17 UTC
```

每天 6 次只发生在月初 7 天；其余日期不按 cron 运行。仍保留 `workflow_dispatch` 供手动触发。并发运行不会互相取消，避免状态锁计数丢失。

## 状态含义

`data/latest.json` 的 `status`：

- `comment_candidates`：公开评论已形成符合门槛的候选，但尚未完成 3 次独立运行锁定。
- `locked`：当前月份候选已通过状态锁；后续运行会跳过抓取。
- `text_candidates`：本月公开正文中发现明确兑换码候选，但尚未完成锁定；不代表官网有效。
- `media_needs_manual_review`：发现图片活动，但目前没有足够的公开评论共识或明文候选。
- `historical_only`：只发现旧月份信号，不把旧码放入当前候选。
- `no_relevant_posts`：扫描窗口内没有相关信号。

当前示例数据是 2026 年 8 月活动帖 395 的 `comment_candidates`，候选为 `飞天螳螂`，状态锁为第 1/3 次观察。它不是官网接口验证结果；用户仍然人工登录兑换。

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

## `@pokemon_love` 与 Session

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
