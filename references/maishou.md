# 买手候选查询

通过 `maishou88.com` 搜索淘宝／天猫和京东商品，查询券及活动，按需生成推广链接。脚本仅用 Python 标准库，不安装上游 Skill，不读取浏览器登录信息，也不领券、加购或下单。

## 调用

将 `<skill-directory>` 替换为当前 Skill 目录。搜索每个平台，初次各取一页；覆盖不足时再调整关键词或翻页。已有商品链接仍应保留为比较基准，搜索结果不保证包含该商品。

```sh
python3 <skill-directory>/scripts/maishou.py search --source 1 --keyword '渴望 原味鸡 5.4kg'
python3 <skill-directory>/scripts/maishou.py search --source 2 --keyword '渴望 原味鸡 5.4kg'
python3 <skill-directory>/scripts/maishou.py detail --source 1 --id '<goodsId>'
python3 <skill-directory>/scripts/maishou.py link --source 1 --id '<goodsId>'
```

`--source 1` 为淘宝／天猫，`2` 为京东。`search` 支持 `--page 2`；详情与转链可传返回记录中的 `--activity-id` 和 `--supplier-code`。所有命令支持 `--timeout`，默认 25 秒，无自动重试。将 JSON 输出重定向到任务文件可保留证据。

先按用户要求筛选候选，通常只查最相关的 1–3 个详情。需要打开商品／领券入口时才调用 `link`；返回链接由浏览器访问，不通过脚本抓取登录页面。`goodsId` 是买手的标识，不能拼成京东 SKU 或淘宝商品链接；详情有时会返回新标识，继续操作时使用最新记录中的标识与平台。

## 输出如何使用

输出包含来源接口、UTC 查询时间、平台、原始商品字段与 `checkout_verified: false`。搜索保留价格、券门槛、有效期、活动标签等字段，详情保留服务原始数据。金额沿用服务返回形式，不在查询脚本中运算。

- `actualPrice` 是接口参考价。可能已经包含券、88VIP或补贴，也可能没有扣券；不要自动再减 `couponPrice`。
- `couponConditions` 与 `tagList` 曾出现门槛冲突，原样保留并通过官方券页核对。日期不带时区或时分时，不自行补成已核验的精确到期时间。
- `commission`、返利和邀请奖励不是即时抵扣，不能从付款金额中减掉。
- 标题可能混有多种规格或临期商品；搜索标题、最低价和店名不能单独证明选中规格、效期或品牌授权。
- API 报价不能直接写入算价器的 `checkout_total_cents`。核对商品、资格、适用范围及叠加规则后，按 `input-format.md` 构造候选；缺少证据的优惠保留为待确认机会。

推广链接在用户可见结果中标明“推广链接”，说明使用上游默认或自配推广归属，不把佣金声称为用户所得。不要按佣金排序推荐。

## 配置与失败处理

默认沿用公开上游的身份标识和邀请码，以支持本地原型。`MAISHOU_OPENID` 和 `MAISHOU_INVITE_CODE` 可使用自己合法取得的配置覆盖；不打印身份值，不向此服务发送用户的电商 Cookie、地址或手机号。仅关键词等本次查询参数会发往第三方服务。

目前实测默认配置可查询，但没有确认服务方的长期免费额度、稳定性或商用接入政策。输出中的 `identity_config`、`referral_config` 显示使用默认还是自配配置。

HTTP 错误、超时、业务 401、异常 JSON 或响应结构变化均以非零退出码和 JSON 错误返回；不能解释成“无商品”或“无优惠券”。成功返回空列表才表示该次查询无结果。失败时保留错误并回到网页／浏览器查询，不循环试身份，不让用户反复登录淘宝来修复买手服务的鉴权问题。

## 来源

接口调用逻辑改编自 [aahl/skills 的 maishou](https://github.com/aahl/skills/tree/e11555d09013379c8013e77f568ee25909a72890/skills/maishou)，保留 [MIT 许可与归属](maishou-license.txt)。本地改动包括无依赖 HTTP、单独转链命令、业务错误识别及带来源时间的 JSON 输出。
