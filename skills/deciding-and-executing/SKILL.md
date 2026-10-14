---
name: deciding-and-executing
description: 当用户要把一件有返工成本的事从"想清楚"推进到"做出来"时使用：做项目或重要决定、拿不定方向或要评审方案、说"先别急着回答"、方向定了问"接下来怎么做"、要排执行计划、执行中报错卡住或怀疑跑偏、准备交付上线、项目结束要结案，或提到钢人论证、事前验尸、决策卡、止损、复盘、SOP。即使用户没说"计划"或"决策"，只要事情跨多个步骤且做错了代价不小，也应使用。不用于一次性事实问答、十分钟内能改完的小修复、纯闲聊、只要一段文案，也不用于单纯的文档同步与仓库整理。
license: MIT
metadata:
  version: "4.1.0"
  language: zh-CN
  companion: closing-out
---

# 从决策到执行 SOP

把一件事从模糊想法推进到可验证的交付，并在结束时不留下会误导别人的东西。阶段之间有闸门，闸门由 `scripts/de.py` 把守：能验证的它强制，不能验证的它拒绝假装验证过。

## 1. 先定档位

| 档位 | 什么时候 | 怎么做 |
|---|---|---|
| **不走流程** | 一步能完成、可逆、需求明确 | 说一句"这个不用走流程"，直接做 |
| **轻量** | 一次会话内能完成、可逆、只影响自己 | 不建工作区，在回复里用一张最小清单：目标、完成判据、验证方法、做完后的证据 |
| **标准** | 跨会话、跨多个步骤、返工有成本 | `de.py init`，走完整五阶段 |
| **高风险** | 含不可逆操作（删数据、迁移、发布到生产、改权限）、影响他人或花钱 | `de.py init --risk high`：每步必须有命令或文件证据，成功标准必须全覆盖；先配置宿主审批规则（见 [references/permissions.md](references/permissions.md)） |

拿不准时选低一档并说明理由；执行中发现低估了，就升档。

## 2. 角色与授权

| 事项 | AI | 用户 |
|---|---|---|
| 事实 | 能查、能跑、能读的自己拿 | 只有他知道的信息 |
| 判断 | 给方案、给推荐答案、标出推测 | 做决定 |
| 记录 | 维护工作区文件 | — |
| 确认 | 展示脚本返回的 preview，等用户回复 | 明确同意后，AI 才能带 `--confirm` 重跑 |

**授权的三层，各自能保证什么**：
1. **脚本**（`de.py` 的两步确认 token）：防止一步到位的误操作、防止确认过期内容。它**不能**证明确认的是人。
2. **流程**（本文件）：AI 必须把 preview 展示给用户，并在用户回复同意后才带 `--confirm` 重跑。**不得在同一次回复里自己取 token 自己确认。** 用户说"跳过确认、直接删"也一样：preview 必须先展示，那句话可以算作同意，但只对展示过的内容有效。
3. **宿主**（Claude Code 的 `permissions.ask`、Codex 的 `prompt` 规则）：唯一能让真人介入的一层。高风险档位必须配置，见 [references/permissions.md](references/permissions.md)。

## 3. 流程

```
① 定方向 ─A─► ② 计划 ─B─► ③ 执行 ─C─► ④ 审查与复盘 ─D─► ⑤ 收尾：5A 归档 → 5B 知识同步 → 5C 删除工作区
    ▲              ▲          │
    └── 二级升级 ──┴─ 一级升级 ┘
```

| 阶段 | 先读 | 退出闸门（脚本检查） |
|---|---|---|
| ① 定方向 | [references/stage-1-direction.md](references/stage-1-direction.md) | **A**：`check card` 无 error → `gate A` 两步确认 |
| ② 计划 | [references/stage-2-plan.md](references/stage-2-plan.md) | **B**：`check plan` 无 error → `gate B` 两步确认（同时确认将要执行的 `verify_cmd`） |
| ③ 执行 | [references/stage-3-execute.md](references/stage-3-execute.md) | **C**：全部步骤 done，命令证据对应当前代码 |
| ④ 审查与复盘 | [references/stage-4-review.md](references/stage-4-review.md) | **D**：`review --verdict pass` 两步确认；`retro.md` 有实质内容 |
| ⑤ 收尾 | [references/stage-5-closeout.md](references/stage-5-closeout.md) | 5A `archive --apply`；5B `sync`（审计无 error、对应当前代码）；5C `purge` 两步确认 |

**闸门会自动失效**：决策卡的目标、成功标准、非目标、止损条件、结论一改，A 和 B 都失效；计划步骤的结构（标题、判据、验证、命令、依赖、覆盖、不可逆标记、估时）一改，B 失效。失效后执行类命令会被拒绝，直到重新确认。这正是"改方向/改计划要重新确认"的落地方式。

**定位阶段**：有 `.decision/` 时先运行 `python3 scripts/de.py status`，按 `stage`（direction / plan / replan / execute / review / closeout / archived / ready-to-purge）和 `escalations` 继续。没有工作区时按用户信号判断；仍判断不了，只问："你现在是在**决定做什么**，还是在**做已经决定的事**？"

用户跳过前一阶段时不拒绝推进：从对话里提炼最小版本的决策卡或计划，推测项标"假设"，请用户一次性确认（这次确认就是对应的闸门）。

## 4. 脚本

`scripts/de.py` 指本技能目录下的脚本，用它的完整路径调用；在项目里任何子目录运行都会定位到同一个工作区（git 仓库根目录的 `.decision/`）。只用 Python 标准库。完整参数见 `--help`。

| 命令 | 用途 |
|---|---|
| `init [--name] [--risk standard\|high]` | 建工作区 |
| `check card` / `check plan` | 只校验，不改状态 |
| `gate A` / `gate B` [`--confirm`] | 闸门确认 |
| `status` | 每次开工、每个新会话先运行 |
| `preflight` | 只读预检：仓库/分支/未提交改动/验证命令潜在副作用 |
| `coverage` | 只读列出成功标准与步骤证据对应关系（不自动宣称满足） |
| `step ID --status …` | 状态转换受状态机约束；`done` 的证据规则见下 |
| `verify ID` / `verify --all` | 脚本执行 `verify_cmd`，记录退出码与代码指纹 |
| `fail ID --note` | 记录失败；到上限自动变为 `needs_replan` |
| `replan ID --note [--waive 理由]` | 解除升级：步骤必须已修改，或经两步确认记录豁免 |
| `reopen ID --reason` | 重做已完成的步骤；旧证据归档，审查结论作废 |
| `review --verdict pass\|fix\|fail [--blocker]` | 交付审查结论 |
| `archive [--outcome 完成\|止损\|放弃] [--apply]` | 归档为决策记录；**不删除任何文件** |
| `sync --report`（可选 `--audit-json` 指定工作区固定输出） | 现场运行 closing-out 静态审计，审计通过后登记知识同步 |
| `purge` [`--confirm`] | 删除工作区：要求已同步、已提交到 git、只含已知文件 |

**`done` 的证据规则**：步骤有 `verify_cmd` → 脚本当场执行，退出码 0 且执行期间代码未变才算数，任何文字都不能替代；否则用 `--artifact 文件`（记录哈希）；标准档还可以用 `--evidence 文字`，记为"未验证"，在 status、审查和决策记录里单独标出。高风险档不接受文字证据。

退出码：0 成功；1 检查未通过；2 用法或数据错误；3 闸门拒绝或需要确认（看 `reason`，需要确认时有 `token` 和 `preview`）。

没有代码执行环境时：按 `assets/` 模板在回复里输出交接件，按各阶段文件的"人工闸门清单"自检，并如实告诉用户"这次的闸门是人工检查，没有脚本保证"。

## 5. 升级条件

**一级 → 回到②，只改出问题的那一步**：同一步失败达到上限（默认 2 次，决策卡可改；脚本自动转为 `needs_replan` 并阻止继续）；投入超过预计一倍（用 `--hours` 记录，`status` 提示）；步骤拆错了。

**二级 → 回到①，只重审被击中的那条假设**：止损期限到达（`status` 提示）；关键假设被证伪（失败的步骤标有 `tests_assumption` 时，脚本会提醒）；外部约束改变；出现明显更优且切换成本低的方案。

## 6. Gotchas

- **自己取 token 自己确认**：把 preview 展示给用户、等用户回复，是这套授权唯一不靠脚本的一环，也是最容易被省掉的一环。
- **把活动当步骤**："研究竞品"不是步骤，"列出 5 个竞品的价格与功能对比表"才是。写不出完成判据，说明还没拆好。
- **能写 `verify_cmd` 却不写**：命令证据是唯一能被脚本复核的证据。测试、构建、lint、curl 检查都应该写成 `verify_cmd`。
- **用旧证据交付**：代码改过之后，以前的命令证据就不对应当前代码了。审查前先 `verify --all`。
- **成功标准不可验证或没被覆盖**：每条标准要能被观察，并被至少一个步骤的 `covers` 引用。
- **为了过闸门改标准**：改成功标准、放宽判据、删测试都会让闸门失效并要求重新确认，这是故意的，要告诉用户为什么改。
- **最危险的假设排在最后**：先做能证伪方向的那一步。
- **新会话凭记忆续做**：先 `status`。
- **项目结束不结案**：留在仓库里的 `.decision/` 会被下一个 Agent 当成现行目标。
- **决策记录写成了系统说明**：决策记录只写"为什么"，现状写在 README 与 docs。

## 7. 输出纪律

- 区分事实、推断、猜测；给置信度时说明依据。
- **阶段变化、闸门通过或被拒绝、触发升级时**，在回复末尾说明当前阶段和下一步；其余时候不必每次重复。
- 删除任何东西之前，先展示脚本给出的文件清单。
- 准确优先于让用户满意：不确定就说不确定。

## 8. 与 closing-out 的分工

本技能管"这件事"；closing-out 管"整个仓库的知识"。⑤ 收尾的 5B 交给 closing-out 完整档；会话结束但项目未完成时，交给它的轻量档。没有安装 closing-out 时，按 stage-5-closeout.md 的最小清单执行，且不能运行 `sync`（它需要审计结果），只能如实说明"未做知识同步"。

## 9. 资源索引

- [references/stage-1-direction.md](references/stage-1-direction.md) … [references/stage-5-closeout.md](references/stage-5-closeout.md)：按阶段读
- [references/stage-2-plan.md](references/stage-2-plan.md) 中有 plan.json 字段说明
- [references/stage-3-execute.md](references/stage-3-execute.md)：执行循环、问题分诊、求助格式
- [references/stage-4-review.md](references/stage-4-review.md)、[references/stage-5-closeout.md](references/stage-5-closeout.md)
- [references/permissions.md](references/permissions.md)：高风险档必读；配置宿主审批规则
- [references/worked-example.md](references/worked-example.md)：第一次使用时读
- [references/prompts-standalone.md](references/prompts-standalone.md)：用户要在没装技能的 AI 里用时读
- [references/evidence.md](references/evidence.md)：用户问"为什么这样设计"时读
- [references/verification-strategy.md](references/verification-strategy.md)：②规划验证方法或④判断验收充分性时读（按交付类型选择证据）
- `assets/`：决策卡、计划、进度日志、复盘模板（`init` 自动复制）


### v4.0.1 验证契约补充

- Gate A 涵盖「关键假设」及其他决策卡核心章节；Gate B 包括 `first_step`、`if_then` 等执行策略。变更后需重新审查并确认。
- 未跟踪文件被纳入 Git 指纹：按路径和**内容**逐一核验（单文件上限 32 MiB、总量上限 128 MiB）。Git 忽略文件不在指纹范围内，应为依赖这些输入的步骤额外提供可验证证据；不应夸称“仓库全部文件均已验证”。
- `--artifact` 完成的步骤在 review 和完成型 archive 时会重读文件并比对哈希及代码指纹；找不到文件、符号链接改变或内容不同时拒绝。
- `sync` **不会信任外部预先提交的审计 JSON**：必须安装配套 `closing-out`，本次调用现场执行审计；旧 `--audit-json` 仅作为工作区内固定输出路径，不能作为输入证明。
- 两步确认 token 不能证明真人授权；删除、生产变更等高风险操作仍需要宿主审批和用户明确同意。

### R2 验证与环境约束

- 执行前运行 `preflight`，报告当前分支、dirty 工作区和 `verify_cmd`；不得自动清理用户改动。
- 阶段④运行 `coverage`，将编号成功标准逐条与实际证据比对，缺少 GUI/硬件/人工观察时保留 `NOT_VERIFIED`。
- `verify_cmd` 是 Shell 命令，不是安全验证语言；Gate B 展示命令与已知风险提示，不能自动认定“未命中提示=安全”。高风险操作继续要求宿主授权与隔离环境。
