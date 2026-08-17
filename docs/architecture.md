# 提取方案与访问边界

## 1. 公开频道与评论的实际测试

### 通知频道 `@pokemon521`

频道历史使用普通 HTTPS GET：

```text
https://t.me/s/pokemon521
https://t.me/s/pokemon521?before=<最老帖子编号>
```

公开 HTML 中可以稳定观察到：

- `data-post="pokemon521/<id>"`
- `<time datetime="...">`
- `.tgme_widget_message_text`
- `.tgme_widget_message_photo_wrap` 的公开图片 URL
- 某些消息的反应数和浏览数

2026-08-17 的一次扫描取得 85 条可见帖子和 5 个历史分页窗口。

### 活动帖 Discussion Widget

频道正文的普通 `t.me/s` 页面不直接嵌入评论，但活动帖的公开 Discussion Widget 可以通过以下形式访问：

```text
https://t.me/pokemon521/395?embed=1&discussion=1&comments_limit=50
```

页面会公开返回：

- 评论总数；
- 首页评论 HTML；
- `peer`、`top_msg_id`、`discussion_hash` 等分页字段；
- Discussion Widget 的公开 `api_url`。

随后以普通 HTTPS POST 调用公开的 `loadComments` 分页方法，读取更早评论。这个过程：

- 不使用 Telegram 登录；
- 不使用 Bot Token、API ID/API Hash、Cookie 或 Session；
- 不加入群组；
- 不发送评论、消息或任何写操作；
- 不调用需要认证的 Telegram MTProto/Bot API。

2026-08-17 对帖子 395 的真实结果：

```text
总评论：286
分页：6 页
匹配“飞天螳螂”：55 条
带公开用户链接的不同支持者下限：25 人
```

“公开用户链接下限”是保守指标：只有 Discussion Widget 明确暴露公开资料链接的评论者才计入不同作者。没有公开链接的评论仍可计入匹配评论数，但不会被冒充成可验证的不同用户。

仓库不保存评论全文、用户名或用户 ID，只保存聚合数量和少量评论 ID 样本以便定位公开证据。

### 交流群 `@pokemon_love`

以下两个公开 URL 能返回 HTTP 200：

```text
https://t.me/pokemon_love
https://t.me/s/pokemon_love
```

但后者会回到群组简介页；两者都没有 `data-post` 消息节点。它们能提供群名、成员数、在线人数和关联频道等简介信息，不能提供可分页的聊天历史。

因此当前边界是：

```text
通知频道正文：匿名公开历史可读
通知帖评论：匿名公开 Discussion Widget 可读
Pokemon Love 群：匿名简介可读，匿名聊天历史不可用
```

## 2. 数据处理链路

```text
公开频道 HTML
  -> 帖子 ID / 时间 / 正文 / 图片 URL
  -> 兑换码标签正则 + 活动图片线索
  -> 当前月份筛选
  -> 活动帖 Discussion Widget 分页
  -> 评论文本规范化
  -> 宝可梦中文名称词表过滤
  -> 至少 3 条评论 + 至少 3 个公开用户链接
  -> comment_consensus 候选
  -> 3 次独立运行状态锁
  -> latest.json + history.jsonl + state.json
```

### 为什么需要宝可梦名称词表

评论区里可能有大量“官网”“兑换成功”“谢谢”等高频普通词。如果只按频次统计，普通词会压过真正答案。当前链路使用静态中文宝可梦名称集合，只允许名称本身或短的猜测前后缀进入共识统计。

词表来源：公开项目 [`42arch/pokemon-dataset-zh`](https://github.com/42arch/pokemon-dataset-zh) 的 national 数据；运行时已固化为 `data/pokemon_names_zh.json`，不需要在线调用该项目。

## 3. 共识与状态锁

单次运行只产生候选，不立即锁定：

```text
第 1 次：comment_candidates，observations = 1
第 2 次：comment_candidates，observations = 2
第 3 次：locked，observations = 3
```

`data/state.json` 保存每个月的：

- 候选名称；
- 观察次数；
- 最近一次评论匹配数量；
- 可验证的不同作者数量下限；
- 活动帖 ID；
- 最近几次独立运行摘要。

锁定后，`monitor.py` 在执行网络请求之前检查当前月份状态并直接退出；`--ignore-lock` 仅供本地排障或重新验证使用。GitHub Actions 的并发策略为不取消正在执行的运行，避免两次运行同时更新状态时丢失计数。

如果候选发生冲突或没有达到作者门槛，则不会锁定；图片线索会保持 `media_needs_manual_review`，而不是猜测一个兑换码。

## 4. 调度与成本控制

GitHub Actions 的 cron 使用 UTC：

```text
17 0,4,8,12,16,20 1-7 * *
```

即每月 1～7 日每天 6 次，其他日期不自动运行；保留手动触发。锁定后即使触发也不会再访问 Telegram。

这比全年每 6 小时运行更符合活动发布窗口，也避免在已经确认后继续产生网络请求和提交。

## 5. 规则链路与图片边界

规则链路适合：

1. 频道正文明确写出 `兑换码：xxx`；
2. 公开评论中出现可识别的宝可梦名称；
3. 多个公开来源重复出现同一候选；
4. 帖子时间与当前月份关联。

它不做：

- 从模糊图片直接猜字；
- 把 OCR 单次结果当作确定码；
- 把一个高频评论或同一用户重复评论当作多人共识；
- 调用官网试码来反推答案；
- 自动兑换。

图片活动在正文层仍会保留 `media_clue` 证据；如果公开评论共识已经解决该活动，则不会再把同一线索放进 `manual_review`。

## 6. Session 备用方案

`@pokemon_love` 的完整群聊历史不能从匿名公开预览取得。如果未来确实需要读取那里，应单独运行私有读取器，并明确：

- Session 由用户在真实终端登录产生；
- 不在聊天中粘贴 Secret；
- 不上传 GitHub 或公共 Actions；
- 不把群友用户名、用户 ID 或全文同步到公开仓库；
- 只把经过规则过滤的聚合证据传给公共项目，或者保持私有输出。

当前活动帖公开评论已经足够支持主链路，因此没有启用 Session。

## 7. 为什么暂不接入 AI

AI 只能改善已经抓到的正文、评论或图片的解释，不能解决访问权限。它还会增加：

- 模型 API Key 或本地模型安装；
- 调用费用、限流和重试；
- 非确定性和幻觉候选；
- 将 Telegram 文本或图片发送给第三方的隐私和平台条款风险；
- 输出 JSON 校验、模型漂移和供应商故障处理。

只有当公开评论无法形成稳定共识、且存在大量可复现的真实漏检样本时，才值得把视觉/OCR 或模型适配器作为独立可选步骤加入；它不能替代公开评论访问。
