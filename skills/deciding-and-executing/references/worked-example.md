# 完整示例：订单服务从 SQLite 迁到 PostgreSQL

一项典型的多日开发任务从头走到尾，用来校准"每个交接件写到什么程度算合格"。非代码的重要决定（例如要不要辞职创业）见 [example-decision.md](example-decision.md)。

## 目录
- 用户的起点与档位
- ① 定方向（简短）
- 决策卡
- ② 计划与 gate AB
- ③ 执行：一次一级升级
- ④ 审查
- ⑤ 收尾

## 用户的起点与档位

> 订单服务要从 SQLite 迁到 PostgreSQL，下周开始做，大概三四天。帮我排一下，别漏东西。

跨多天、多个步骤、有一步动生产数据 → **标准档**，生产切换那一步标为不可逆。没有一步需要别人审批或花钱，所以不用高风险档。

```
$ de.py init --name 订单服务迁移到 PostgreSQL
$ de.py preflight          # 只读：当前分支 main、1 个未提交文件（用户的，不动它）
```

## ① 定方向（简短）

方向基本已定，只做两件事：找出能翻转结论的假设，补齐止损。

- **A1**：ORM 生成的查询在 PostgreSQL 上行为一致。不成立就要先改写 `reports/` 里的原生 SQL，工期翻倍。
- 只问用户一个问题："切换时能接受 10 分钟只读窗口吗？我的推荐答案是能，这样不用做双写。" 用户：能。

## 决策卡

```markdown
# 决策卡：订单服务迁移到 PostgreSQL

- 日期：2026-11-16
- 结论：改后做（先迁读路径，再迁写路径）
- 置信度及依据：中，依据是在生产数据副本上的一次试迁移

## 目标
订单服务在 PostgreSQL 上运行，迁移不丢数据。

## 成功标准
1. 订单相关测试在 PostgreSQL 上全部通过 [CI 任务 pg-tests]
2. 迁移后两库的订单行数与金额合计一致
3. 切换期间只读窗口不超过 10 分钟

## 非目标
- 不改表结构，不顺手做分库

## 关键假设
| # | 假设 | 若不成立的后果 | 状态 |
|---|---|---|---|
| A1 | ORM 查询在 PostgreSQL 上行为一致 | 先改写 reports/ 的原生 SQL，工期翻倍 | 未验证 |

## 止损条件
- 触发状态：试迁移仍有行数不一致，且找不到原因
- 期限：2026-11-27
- 动作：停止迁移，保留 SQLite，把发现写进决策记录
```

成功标准里写了 `[CI 任务 pg-tests]` 这样的方括号也没问题：只有模板里原样的占位符才算"没填"。

## ② 计划与 gate AB

```json
{
  "name": "订单服务迁移到 PostgreSQL",
  "risk": "standard",
  "steps": [
    {"id": 1, "title": "在 PostgreSQL 上跑现有测试", "done_when": "失败用例清单为空或已逐条归因",
     "verify": "pytest 在 PG 测试库上通过", "covers": [1], "tests_assumption": "A1", "estimate_h": 3,
     "verify_argv": ["python", "-m", "pytest", "tests/orders", "--db", "postgres"]},
    {"id": 2, "title": "写迁移脚本并在数据副本上试跑", "done_when": "两库行数与金额合计一致",
     "verify": "核对脚本退出码 0", "covers": [2], "depends_on": [1], "estimate_h": 5,
     "verify_argv": ["python", "scripts/compare_counts.py", "--source", "copy.sqlite"]},
    {"id": 3, "title": "演练切换并计时", "done_when": "演练记录显示只读窗口 ≤ 10 分钟",
     "verify": "演练记录 docs/ops/cutover-rehearsal.md", "covers": [3], "depends_on": [2], "estimate_h": 2},
    {"id": 4, "title": "生产切换", "done_when": "生产流量全部走 PostgreSQL",
     "verify": "切换后核对脚本退出码 0", "covers": [2, 3], "depends_on": [3], "irreversible": true,
     "estimate_h": 2, "verify_argv": ["python", "scripts/compare_counts.py", "--source", "prod-snapshot"]}
  ],
  "if_then": [
    {"if": "某条原生 SQL 在 PG 上报错", "then": "先加一条只覆盖它的测试，再改写，不批量改"},
    {"if": "行数一致但金额合计不一致", "then": "检查 numeric 精度映射，停在步骤 2"}
  ],
  "first_step": 1
}
```

注意四点：
- 验证 A1 的步骤排第一；
- 能用命令证明的都写了 `verify_argv`，不经 shell，换到 Windows 上也能跑；
- 演练记录只能用文件证据（`--artifact`）；
- 生产切换标了 `irreversible`，开始前脚本会要求两步确认。

`check plan` 无 error 后，标准档可以把决策卡和计划一起交给用户确认：`de.py gate AB` 返回的 preview 同时列出结论、成功标准、止损和每条验证命令（`runs_via_shell: false`）。用户回复"可以"后，带 `--confirm` 重跑。高风险档不允许 AB，必须分别 `gate A`、`gate B`。

## ③ 执行：一次一级升级

步骤 2 的核对脚本两次报金额合计不一致：

```
$ de.py fail 2 --note "金额合计差 0.03"
$ de.py fail 2 --note "改了取整方式仍差 0.03"
{"fails": 2, "max_fails": 2, "escalate": true, "status": "needs_replan", ...}
```

停止盲试，回到②只改这一步：查出 SQLite 的 REAL 存储金额，迁移前要先转成 `numeric(12,2)`。在 `plan.json` 把步骤 2 拆成"2a 金额列转换并单测"和"2b 试迁移"，然后 `replan 2 --note "拆出金额转换"`。计划结构变了，gate B 失效，重新 `gate B` 给用户确认。A1 没有被证伪（问题出在数据类型，不在查询），不回到①。

开始步骤 4 时：

```
$ de.py step 4 --status in_progress
{"needs_confirmation": true, "token": "…", "preview": {"步骤": "生产切换", "警告": "这是不可逆操作，开始前需要用户确认"}}
```

把 preview 给用户看，用户同意后再带 `--confirm`。

## ④ 审查

```
$ de.py verify --all        # 代码在步骤 3 之后又改过，旧证据已过期
$ de.py coverage            # 标准 1、2：READY_FOR_INDEPENDENT_REVIEW；标准 3：文件证据，需人工看演练记录
```

`READY_FOR_INDEPENDENT_REVIEW` 不等于通过：逐条对照成功标准，标准 3 打开演练记录确认是 8 分钟。然后 `review --verdict pass`，preview 给用户确认。复盘写进 `retro.md`：估时偏差主要来自数据类型，教训"迁移前先列出所有列在两库中的类型映射"去向是团队规则文件。

## ⑤ 收尾

先按 closing-out 完整档同步文档：README 的本地启动命令、`.env.example` 里的数据库地址、AGENTS.md 里"测试用 SQLite"的规则都要改。报告存为 `.decision/closeout-report.md`。

```
$ de.py closeout --report .decision/closeout-report.md          # 预览：将写入的决策记录、检查结果
$ de.py closeout --report .decision/closeout-report.md --apply  # 用户同意后：写决策记录 + 现场重跑审计
```

审计有 error 时 closeout 只完成归档，并提示修复后运行 `sync --report …`。通过后提交所有改动，`de.py purge` 列出将删除的工作区文件，用户同意后 `purge --confirm`，再提交一次。
