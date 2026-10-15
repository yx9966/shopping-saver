# Shopping Saver · 中国购物省钱助手

用于 Hermes 等支持 Agent Skills 的智能体。在中国购物时，查询京东、淘宝／天猫商品和优惠券，比较严格同款的最低到手总价、拆单与凑单方案。

仅查询、核验与计算，不领券、加购、提交订单或支付。

## 安装到 Hermes

```sh
hermes skills install https://github.com/yx9966/shopping-saver
```

在 Hermes 新会话中使用：

> 用 shopping-saver 查渴望原味鸡猫粮 5.4kg 一袋，优先官方店，比较京东和天猫最低到手价，附商品和优惠券链接。不额外买凑单商品。

收货地区、规格、数量、店铺要求和已有会员资格会影响结果。智能体会按已有信息查询，只补问必要条件。

其他支持 Agent Skills 的工具可加载仓库根目录的 [SKILL.md](SKILL.md)。技能执行环境需要 Python 3.10+；查询与算价脚本只用标准库。页面核验需要宿主提供网页或浏览器工具，登录、验证码由用户本人完成。

## 比价逻辑

**最低到手总价 = 商品金额（含全部凑单品）− 确认可叠加的即时优惠 + 运费 + 必须支付的其他费用。**

1. 固定同款、规格、数量、配送地区及店铺条件，避免混用小包装起步价或临期价。
2. 查找候选商品、券和活动，再按官方规则及当前账号核验资格、门槛、有效期和叠加顺序。
3. 比较单买、同店合单、跨店满减及跨平台拆单；一张一次性券不能重复用于多个订单。
4. 只有用户允许时才凑单，全部额外支出纳入计算，并与无凑单方案比较。
5. 区分“候选中的估算最低价”和“结算页已核验最低价”，给出链接、使用条件与查询时间。

算价器输出：

| 字段 | 含义 |
|---|---|
| `lowest_total` | 可行候选中买齐需求的最低总支出，可能含估算 |
| `lowest_verified` | 每单均有一致结算页金额的最低总支出；无完整核验方案时为空 |
| `without_filler` | 不买额外商品的最低总支出 |
| `fewest_orders` | 优先少拆单，再比较总支出 |

“最低”只覆盖本次提供的候选，不承诺全网最低。脚本不会自行抓取结算页或验证优惠资格；这些证据由智能体收集。返佣、未来返现和礼品估值不扣减本次付款，新会员费等额外付费条件单独说明。

## 直接使用脚本

查询候选：

```sh
python3 scripts/maishou.py search --source 1 --keyword '渴望 原味鸡 5.4kg'
python3 scripts/maishou.py search --source 2 --keyword '渴望 原味鸡 5.4kg'
```

`1` 为淘宝／天猫，`2` 为京东。详情、优惠入口及第三方服务配置见 [买手查询说明](references/maishou.md)。返回的接口参考价不等于当前账号结算价，不能把券再机械扣一次。

按 [输入格式](references/input-format.md) 提供候选订单：

```sh
python3 scripts/compare.py input.json --output result.json
```

金额均为整数人民币分，支持有明确参与范围的满减、每满减、顺序门槛、一次性权益、运费及必要费用。复杂折扣可录入该确切组合的已核验结算差额；不自动推演未知活动。

运行虚构验算示例：

```sh
python3 scripts/compare.py references/example.json --at 2026-10-13T12:00:00+08:00
```

该示例的无凑单总额为 270 元，允许购买 5 元纸巾后总额为 253 元。它仅供算法验算，不是实时商品报价；`--at` 用于历史回放，不能用于声称已过期的券仍然有效。

## 数据来源与限制

查询脚本使用第三方买手服务发现候选，再由智能体读取官方页面核验。第三方服务的可用性、免费额度及商用政策不作保证；失败时技能回退网页查询，不把接口错误当成没有商品。

默认查询身份和推广归属沿用公开上游配置，可通过 `MAISHOU_OPENID`、`MAISHOU_INVITE_CODE` 使用自己合法取得的配置。推广链接必须标注，返佣不作为用户即时优惠，也不影响推荐排序。脚本不读取电商 Cookie，不向该服务发送用户的详细地址或手机号。

## 开发与测试

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

Windows 使用 `.venv\Scripts\python.exe`。测试覆盖优惠门槛、分摊、互斥券、凑单预算、数量、时效、必要费用、核验价格及服务错误处理；不需要真实网络或电商账号。

## 许可与致谢

本项目采用 [MIT License](LICENSE)。买手接口调用逻辑改编自 [aahl/skills 的 maishou](https://github.com/aahl/skills/tree/e11555d09013379c8013e77f568ee25909a72890/skills/maishou)，保留了 [上游许可和改编说明](references/maishou-license.txt)。本项目不隶属于京东、淘宝、天猫或买手服务。
