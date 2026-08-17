# 宝可梦 521 兑换码监测器

只读监测 `@pokemon521` 的公开 Telegram 频道和活动帖评论，提取并确认每月兑换码候选。

项目不登录 Telegram、不加入群组、不调用兑换接口，也不自动兑换。

## 最新兑换码

最新结果以 [`data/latest.json`](https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json) 为准：

```text
https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json
```

README 不复制当前兑换码，避免 README 与机器数据出现两个真源。GitHub Actions 只更新数据文件，不需要同步修改文档。

### 接入方式

读取 `latest.json` 后：

1. 确认 `status` 为 `locked`；
2. 从 `candidates` 中选择 `freshness` 为 `current_month`、`needs_manual_review` 为 `false` 的候选；
3. 读取该候选的 `code`；
4. 如果没有符合条件的候选，视为本月尚未确认。

示例：

```bash
curl -fsSL \
  'https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/latest.json' \
| jq -r '
    if .status == "locked" then
      first(.candidates[]
        | select(.freshness == "current_month")
        | select(.needs_manual_review == false)
        | .code) // empty
    else
      empty
    end
  '
```

主要字段：

| 字段 | 含义 |
|---|---|
| `status` | 当前处理状态；只有 `locked` 表示已锁定 |
| `candidates[].code` | 兑换码候选 |
| `candidates[].source_url` | 对应活动帖 |
| `candidates[].kind` | 提取方式，如正文或评论共识 |
| `lock.observations` | 连续一致的独立运行次数 |
| `lock.required_observations` | 锁定所需次数 |

历史信号保存在 [`data/history.jsonl`](https://raw.githubusercontent.com/LinLin00000000/pokemon521-coupon-monitor/main/data/history.jsonl)。

## 工作原理

```text
公开频道历史
  → 识别当月兑换码活动
  → 提取正文中的明确兑换码
  → 读取活动帖的公开评论
  → 使用宝可梦中文名称表过滤候选
  → 统计不同评论者的一致答案
  → 连续多次运行一致后锁定
  → 更新 latest.json、history.jsonl 和 state.json
```

默认确认门槛：

- 候选必须来自当月活动；
- 至少 3 条匹配评论；
- 至少 3 个不同的公开评论者；
- 同一候选连续 3 次独立运行一致。

中文名称表包含 1～9 世代的 1,025 个基础物种名称，来源于 [`42arch/pokemon-dataset-zh`](https://github.com/42arch/pokemon-dataset-zh)。程序使用名称白名单识别答案，并用少量黑名单排除“官网”等普通活动词；不会仅凭全局词频选择兑换码。

## 自动运行

GitHub Actions 在每月 1～7 日运行，每天 6 次：

```text
00:17、04:17、08:17、12:17、16:17、20:17 UTC
```

当月结果锁定后，后续运行会直接退出，减少无效请求。也可以通过 `workflow_dispatch` 手动运行。

## 本地运行

无需第三方 Python 依赖：

```bash
python3 -m unittest discover -s tests -v
python3 monitor.py \
  --max-messages 100 \
  --max-pages 8 \
  --max-discussion-posts 3 \
  --max-comments 500 \
  --lock-observations 3
```

## 项目结构

```text
monitor.py                       频道抓取、规则提取和状态锁
discussion.py                    公开评论分页与共识统计
sources.json                     公开数据源配置
data/latest.json                 当前结果
data/history.jsonl               历史信号
data/state.json                  跨运行锁状态
data/pokemon_names_zh.json       宝可梦中文名称表
.github/workflows/monitor.yml    定时任务
docs/architecture.md            详细实现与访问边界
```

## 边界

- 不保存 Telegram Token、Cookie 或 Session；
- 不加入或读取 `@pokemon_love` 的非公开聊天历史；
- 不对活动图片进行 OCR 或猜码；
- 不调用官网校验、订单或兑换接口；
- 不公开评论全文、用户名或用户 ID；
- 自动提交仅更新数据文件，提交身份为 `github-actions[bot]`。

## License

MIT
