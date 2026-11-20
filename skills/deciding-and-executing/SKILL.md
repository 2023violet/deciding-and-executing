---
name: deciding-and-executing
description: 跨会话、返工代价高的工作的决策与执行流程，由脚本强制要求可复核的完成证据。遇到以下情况，在回答或动手之前先调用本技能，不要直接给建议或直接开始改：拿不定要不要做一件多日的事（迁移、重构、新系统、上线发布、改生产数据），或用户说"先别急着回答""帮我想清楚""帮我理一理"；方向已定、要拆计划、排每天做什么、定每步怎么算完成；执行中同一步反复失败、怀疑方案本身有问题或做着做着跑偏；问"可以上线了吗""从头到尾检查一遍还有什么坑"；接着上次做、仓库里有 .decision 目录、项目做完要结案；或明确要决策卡、SOP、钢人论证、事前验尸、止损、复盘。非代码的重要决定（辞职、开店、创业）同样适用。不用于一次会话能做完的小修复、单纯解释概念、写邮件或文案，也不用于文档同步与仓库整理（那是 closing-out）。Use this skill before answering or editing anything when a multi-day effort is being decided, planned, debugged after repeated failures, checked before shipping ("is this ready to ship?"), resumed from a .decision folder or closed out, or when a decision card, steelman, pre-mortem or retro is asked for. Not for quick fixes, concept questions or plain writing.
license: MIT
allowed-tools:
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" status *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" handoff *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" check *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" list *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" show *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" preflight *)
  - Bash(python "${CLAUDE_SKILL_DIR}/scripts/de.py" coverage *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" status *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" handoff *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" check *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" list *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" show *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" preflight *)
  - Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/de.py" coverage *)
metadata:
  version: "5.0.0"
  language: zh-CN
  companion: closing-out
---

# 从决策到执行 SOP

把一件事从模糊想法推进到可验证的交付，并在结束时不留下会误导别人的东西。阶段之间有闸门，闸门由 `scripts/de.py` 把守：能验证的它强制，不能验证的它拒绝假装验证过。

## 1. 先判断这件事有多大

第一步永远是这个判断。看的是这件事本身，不是用户的用词："帮我想清楚""能上线吗"这类话也常用在小事上。

| 档位 | 什么时候 | 例子 | 怎么做 |
|---|---|---|---|
| **不走流程** | 一步能完成、可逆、需求明确 | 变量起名、改一个 if、修一行正则 | 说一句"这个不用走流程"，直接做 |
| **轻量** | 一次会话内能完成、可逆、只影响自己 | 加一个接口参数并补测试 | 不建工作区，在回复里列出：目标、怎么算完成、怎么验证、验证结果 |
| **标准** | 跨会话、跨多个步骤、返工有成本 | 多日的数据库迁移、重写一个模块 | `de.py init`，走完整流程；方向已清楚时可用 `gate AB` 一次确认决策卡与计划，收尾用 `closeout` |
| **高风险** | 含不可逆操作（删数据、迁移生产库、发布、改权限）、影响他人或花钱 | 迁移几百万行生产数据 | `de.py init --risk high`：每步必须有命令或文件证据，成功标准必须全覆盖；先配置宿主审批规则（见 [references/permissions.md](references/permissions.md)） |

**拿不准就选轻的一档**，并说明理由；执行中发现低估了再升档。升档便宜，被流程拖累不便宜。

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
| ② 计划 | [references/stage-2-plan.md](references/stage-2-plan.md) | **B**：`check plan` 无 error → `gate B` 两步确认（同时确认将要执行的验证命令）；标准档可用 `gate AB` 与 A 一次确认 |
| ③ 执行 | [references/stage-3-execute.md](references/stage-3-execute.md) | **C**：全部步骤 done，命令证据对应当前代码 |
| ④ 审查与复盘 | [references/stage-4-review.md](references/stage-4-review.md) | **D**：`review --verdict pass` 两步确认；`retro.md` 有实质内容 |
| ⑤ 收尾 | [references/stage-5-closeout.md](references/stage-5-closeout.md) | 5A `archive --apply`；5B `sync`（审计无 error、对应当前代码）——或 `closeout --apply` 一步完成两者；5C `purge` 两步确认 |

**闸门会自动失效**：决策卡的目标、成功标准、非目标、关键假设（只更新"状态"列除外）、止损条件、结论、修复失败次数上限一改，A 和 B 都失效；计划的名称、`first_step`、`if_then` 或步骤结构（标题、判据、验证、命令、依赖、覆盖、验证的假设、不可逆标记、估时）一改，B 失效。失效后执行类命令会被拒绝，直到重新确认。这正是"改方向/改计划要重新确认"的落地方式。

**定位阶段**：有 `.decision/` 时先运行 `de.py status`，按 `stage`（direction / plan / replan / execute / review / closeout / archived / ready-to-purge）、`escalations` 和 `next` 继续。没有工作区时按用户信号判断；仍判断不了，只问："你现在是在**决定做什么**，还是在**做已经决定的事**？"

**照 `next` 走**：每条命令的 JSON 输出都带 `next = {cmd, why}`。`cmd` 是下一个合法动作（照抄运行，`<…>` 占位要换成真实内容）；`cmd` 为 null 表示下一步是你或用户的工作（改步骤、写复盘、和用户商量），`why` 说明是什么。带 `needs_user: true` 的命令要先把 preview 给用户看、等用户同意后才能运行。

用户跳过前一阶段时不拒绝推进：从对话里提炼最小版本的决策卡或计划，推测项标"假设"，请用户一次性确认（这次确认就是对应的闸门）。

## 4. 脚本

**怎么调用**：本技能所有文档里的 `de.py …` 都是 `python <本技能目录>/scripts/de.py …` 的简写，从项目里任何目录运行，都会定位到同一个工作区（git 仓库根目录的 `.decision/`）。非 git 项目也能用，但证据无法绑定到当前代码，`purge` 也会拒绝删除工作区。
- Claude Code：`python "${CLAUDE_SKILL_DIR}/scripts/de.py" status`（照这个写法调用，只读命令在本轮可免审批）；变量没被替换时，用技能安装位置的绝对路径（如 `~/.claude/skills/deciding-and-executing/scripts/de.py`）。
- 其他宿主：同样用绝对路径（如 `~/.agents/skills/deciding-and-executing/scripts/de.py`）。
- macOS / Linux 用 `python3`，Windows 用 `python` 或 `py -3`。
- 脚本在技能目录里，不在项目里：写 `scripts/de.py` 这样的相对路径会找不到它。
- 文档里的 `audit.py` 指 closing-out 技能目录下的 `scripts/audit.py`（两个技能装在同一目录时，即 `<本技能目录>/../closing-out/scripts/audit.py`）。

只用 Python 标准库（3.8+）。完整参数见 `de.py --help`。

| 命令 | 用途 |
|---|---|
| `init [--name] [--risk standard\|high] [--lang zh\|en]` | 建工作区；`--lang en` 生成英文模板（决策卡、计划、复盘、决策记录） |
| `list` | 列出本仓库所有工作区 |
| `check card` / `check plan` | 只校验，不改状态 |
| `gate A` / `gate B` / `gate AB` [`--confirm`] | 闸门确认；`AB` 一次确认两者，仅标准档 |
| `status` | 每次开工、每个新会话先运行；`--brief` 输出 ≤15 行纯文本，给会话开始钩子用 |
| `handoff` [`--json`] | 只读交接摘要：步骤与证据新鲜度、升级、假设、最近事件、下一步、相关文件路径 |
| `preflight` | 只读预检：仓库/分支/未提交改动/验证命令潜在副作用 |
| `coverage` | 只读列出成功标准与步骤证据对应关系（不自动宣称满足） |
| `step ID --status …` | 状态转换受状态机约束；`done` 的证据规则见下 |
| `verify ID` / `verify --all` | 脚本执行验证命令，记录退出码与代码指纹 |
| `fail ID --note` | 手动记录失败（没有验证命令的步骤）；验证命令的失败由脚本自动计数；到上限自动变为 `needs_replan` |
| `replan ID --note [--waive 理由]` | 解除升级：步骤必须已修改，或经两步确认记录豁免 |
| `reopen ID --reason` | 重做已完成的步骤；旧证据归档，审查结论作废 |
| `review --verdict pass\|fix\|fail [--blocker] [--independent-report]` | 交付审查结论；可关联工作区里的独立复核报告 |
| `archive [--outcome 完成\|止损\|放弃] [--apply]` | 归档为决策记录；**不删除任何文件**（英文工作区可写 `done\|stopped\|abandoned`） |
| `sync --report`（可选 `--audit-json` 指定工作区固定输出） | 现场运行 closing-out 静态审计（不信任任何预先写好的审计 JSON），通过后登记知识同步 |
| `closeout --report 文件 [--outcome] [--apply]` | archive + sync 一步完成：先预览，用户同意后 `--apply` |
| `purge` [`--confirm`] | 删除工作区：要求已同步、已提交到 git、只含已知文件 |

**文件归属**：`plan.json` 是你编写的计划结构；状态、证据、闸门和审查结论在 `state.json`，只由脚本写入，每次写入的摘要记在 `events.jsonl`。`plan.json` 里出现的运行时字段会被忽略，`state.json` 在脚本之外被改动时 `status` 会报警。这能挡住疏忽和随手修改，挡不住有意同时伪造两份文件的人或 Agent。

**一个仓库多件事**：每件事一个工作区（如 `init --dir .decision-<名称>`），之后每条命令都带同一个 `--dir`（或设置环境变量 `DE_WORKSPACE`）；`list` 列出全部。代码指纹排除所有工作区，互不影响。

**英文用户**：`init --lang en` 生成英文模板；决策卡的章节、字段和结论接受英文写法（Goal、Success criteria、Verdict: go / go with changes / drop 等）。脚本的提示信息仍是中文。

**验证命令**：优先写 `verify_argv`（参数数组，不经 shell，跨平台一致）；需要管道或重定向时才写 `verify_cmd`（交给系统 shell，Windows 上是 cmd.exe）。二者只能写一种。

**`done` 的证据规则**：步骤有验证命令 → 脚本当场执行，退出码 0 且执行期间代码未变才算数，任何文字都不能替代；否则用 `--artifact 文件`（记录哈希；review 和完成型 archive 时会重新核对文件、哈希与代码指纹）；标准档还可以用 `--evidence 文字`，记为"未验证"，在 status、审查和决策记录里单独标出。高风险档不接受文字证据。

**代码指纹覆盖什么**：Git 已跟踪的改动，加上未跟踪文件的路径和内容（单文件 32 MiB、总量 128 MiB 上限，超限拒绝验证）；**不含被 Git 忽略的文件**。步骤依赖忽略文件（本地配置、外部设备、环境变量）时，另给可验证的证据，不要宣称"仓库全部文件均已验证"。

**只读检查**：执行前运行 `preflight`，报告当前分支、未提交改动和将要执行的验证命令，不得自动清理用户改动；④审查时运行 `coverage`，把编号成功标准逐条与实际证据比对，缺少 GUI、硬件或人工观察时保留 `NOT_VERIFIED`。验证命令不是安全的验证语言：gate B 和 `preflight` 的风险提示是非穷尽的模式匹配，没命中不等于安全；高风险操作仍需宿主授权与隔离环境。

退出码：0 成功；1 检查未通过；2 用法或数据错误；3 闸门拒绝或需要确认（看 `reason`，需要确认时有 `token` 和 `preview`）。

没有代码执行环境时：按 `assets/` 模板在回复里输出交接件，按各阶段文件的"人工闸门清单"自检，并如实告诉用户"这次的闸门是人工检查，没有脚本保证"。

## 5. 升级条件

**一级 → 回到②，只改出问题的那一步**：同一步失败达到上限（默认 2 次，决策卡可改；验证命令"改了代码仍失败"由脚本自动计数，规则见 stage-3；到上限自动转为 `needs_replan` 并阻止继续）；投入超过预计一倍（用 `--hours` 记录，`status` 提示）；步骤拆错了。

**二级 → 回到①，只重审被击中的那条假设**：止损期限到达（`status` 提示）；关键假设被证伪（失败的步骤标有 `tests_assumption` 时，脚本会提醒）；外部约束改变；出现明显更优且切换成本低的方案。

## 6. Gotchas

- **自己取 token 自己确认**：把 preview 展示给用户、等用户回复，是这套授权唯一不靠脚本的一环，也是最容易被省掉的一环。
- **把活动当步骤**："研究竞品"不是步骤，"列出 5 个竞品的价格与功能对比表"才是。写不出完成判据，说明还没拆好。
- **能写验证命令却不写**：命令证据是唯一能被脚本复核的证据。测试、构建、lint、curl 检查都应该写成 `verify_argv`。
- **验证命令往项目里写文件**：生成未被 Git 忽略的报告或缓存会改变代码指纹，结果不算数。先确认 `.gitignore` 覆盖了它们。
- **在 `verify_cmd` 里写 POSIX 专用语法**：`test -f`、`> /dev/null`、`&&` 在 Windows 的 cmd.exe 上行为不同或不可用；写成 `verify_argv`。
- **用旧证据交付**：代码改过之后，以前的命令证据就不对应当前代码了。审查前先 `verify --all`。
- **成功标准不可验证或没被覆盖**：每条标准要能被观察，并被至少一个步骤的 `covers` 引用。
- **为了过闸门改标准**：改成功标准、放宽判据、删测试都会让闸门失效并要求重新确认，这是故意的，要告诉用户为什么改。
- **最危险的假设排在最后**：先做能证伪方向的那一步。
- **新会话凭记忆续做**：先 `status`；交接给别的会话或 Agent 时给它 `handoff` 的输出。也可以让宿主在会话开始时自动注入 `status --brief`（见 [references/permissions.md](references/permissions.md)）。
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
- [references/permissions.md](references/permissions.md)：高风险档必读；配置宿主审批规则，以及可选的会话开始钩子
- [references/worked-example.md](references/worked-example.md)：第一次使用时读（一项多日的开发任务）
- [references/example-decision.md](references/example-decision.md)：用户在做非代码的重要决定时读
- [references/prompts-standalone.md](references/prompts-standalone.md)：用户要在没装技能的 AI 里用时读
- [references/evidence.md](references/evidence.md)：用户问"为什么这样设计"时读
- [references/verification-strategy.md](references/verification-strategy.md)：②规划验证方法或④判断验收充分性时读（按交付类型选择证据）
- `assets/`：决策卡、计划、进度日志、复盘模板（`init` 自动复制）
