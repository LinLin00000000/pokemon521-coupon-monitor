# 宝可梦 521 兑换码监测器

一个尽量小的、只读的 GitHub Actions 项目：定时读取公开 Telegram 通知频道 `@pokemon521`，提取明文兑换码；如果兑换码只出现在图片中，则保存图片链接和帖子证据，标记为人工复核。

它**不会**登录 Telegram、加入交流群、调用 Telegram API、调用官网优惠码接口，也不会自动兑换。

## 当前验证结果

本项目在 2026-08-06 用匿名公开网页测试过两个入口：

| 入口 | 匿名结果 | 结论 |
|---|---|---|
| [`t.me/s/pokemon521`](https://t.me/s/pokemon521) | HTTP 200；页面包含 `data-post`、`<time datetime>`、帖子正文和公开图片 URL；`?before=<id>` 可以读取更早窗口 | **可以无 Token 读取频道历史** |
| [`t.me/pokemon_love`](https://t.me/pokemon_love) | HTTP 200，但只是群组简介/成员信息 | **可以无 Token 读取简介，不能从公开预览读取聊天历史** |
| [`t.me/s/pokemon_love`](https://t.me/s/pokemon_love) | HTTP 200 后解析到 `t.me/pokemon_love`，没有帖子记录 | 不作为匿名聊天记录源 |

频道公开预览中，当前活动帖子会提供“兑换码藏在图片中”的说明和图片，但测试页面没有公开评论记录链接。因此 v1 不假设能从网页读取频道评论，也不尝试绕过 Telegram 的访问边界。

## 为什么 v1 选择规则匹配

| 方案 | 优点 | 局限 | 本项目决定 |
|---|---|---|---|
| 字符串/规则匹配 | 无 AI Token；无第三方数据外传；确定性强；Actions 轻量；容易审计和去重 | 只能可靠提取正文中明确写出的码；图片中的码只能标记 | **默认主链路** |
| 近百条记录 + AI 小模型 | 能理解上下文、处理一些不规则表达；未来可辅助 OCR 结果筛选 | 不能解决交流群匿名不可见的问题；需要模型 API Key 或把模型装进 Runner；有成本、延迟、幻觉和数据外传风险 | **暂不启用，保留未来适配点** |

近百条消息的抓取仍然保留在 v1：每次最多分页抓取 100 条公开频道帖子，但只把“候选码”和“需要人工复核的图片线索”写入数据，不保存完整聊天记录。

## 仓库结构

```text
.
├── monitor.py                    # 标准库实现的抓取、解析、规则提取
├── sources.json                  # 公开源配置，不含凭据
├── data/
│   ├── latest.json               # 当前月份候选/图片线索，固定 raw URL
│   └── history.jsonl             # 去重后的历史信号，保留来源证据
├── tests/test_monitor.py         # 离线解析、提取、分页和幂等测试
└── .github/workflows/monitor.yml # 每 6 小时运行，只有数据变化才提交
```

## 使用

本地运行不需要任何 Python 第三方依赖：

```bash
python3 -m unittest discover -s tests -v
python3 monitor.py --max-messages 100 --max-pages 8
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

仓库发布后，机器可读的当前结果是：

```text
https://raw.githubusercontent.com/<owner>/pokemon521-coupon-monitor/main/data/latest.json
```

历史记录是：

```text
https://raw.githubusercontent.com/<owner>/pokemon521-coupon-monitor/main/data/history.jsonl
```

`latest.json` 的 `status` 含义：

- `text_candidates`：本月公开正文中发现了明确兑换码候选；仍不代表官网有效。
- `media_needs_manual_review`：本月发现活动图片线索，但没有猜码或 OCR；打开 `manual_review` 中的帖子/图片人工判断。
- `historical_only`：只发现旧月份信号，不把旧码放入当前候选。
- `no_relevant_posts`：扫描窗口内没有相关信号。

当前真实扫描结果是 `media_needs_manual_review`：帖子 [`pokemon521/395`](https://t.me/pokemon521/395) 被识别为本月图片线索；交流群探测结果为 `profile_only`。历史文件中的旧码不能视为当前有效码。

## 安全边界

- 不保存 Telegram Bot Token、API ID/API Hash、登录 Session、Cookie 或官网凭据。
- 不加入 `@pokemon_love`，不启动机器人，不读取私有消息。
- 不调用官网的优惠码校验、订单创建、支付或兑换接口。
- 不自动 OCR、猜测图片文字或批量尝试宝可梦名称。
- GitHub Actions 只提交 `data/latest.json` 和 `data/history.jsonl` 的内容变化。

如果以后确实需要 AI，建议作为单独的可选步骤：先由规则链路筛出少量相关帖子，再把最小化文本窗口送到明确配置的模型适配器；不要默认把近百条原始消息和图片发送到第三方服务。AI 也不能替代交流群的访问权限。

## License

MIT
