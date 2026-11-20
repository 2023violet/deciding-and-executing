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

# 从决策到执行

把一件跨会话、返工代价高的事，从模糊想法推进到可验证的交付，结束时不留下会误导别人的东西。`scripts/de.py` 负责记状态和核对证据：能验证的它强制，不能验证的它不假装验证过。

## 1. 先判断这件事有多大

第一步永远是这个判断。看的是这件事本身，不是用户的用词："帮我想清楚""能上线吗"这类话也常用在小事上。

| 档位 | 什么时候 | 例子 | 怎么做 |
|---|---|---|---|
| **不走流程** | 一步能完成、可逆、需求明确 | 变量起名、改一个 if、修一行正则 | 说一句"这个不用走流程"，直接做 |
| **轻量** | 一次会话内能完成、可逆、只影响自己 | 加一个接口参数并补测试 | 不建工作区，在回复里列出：目标、怎么算完成、怎么验证、验证结果 |
| **标准** | 跨会话、跨多个步骤、返工有成本 | 多日的数据库迁移、重写一个模块 | `de.py init`，按下面的流程走 |
| **高风险** | 不可逆（删数据、迁移生产库、发布、改权限）、影响他人或花钱 | 迁移几百万行生产数据 | `de.py init --risk high`：每步必须有命令或文件证据，成功标准必须全覆盖；先配置宿主审批规则（[permissions.md](references/permissions.md)） |

**拿不准就选轻的一档**，并说明理由；执行中发现低估了再升档。升档便宜，被流程拖累不便宜。

## 2. 三条硬规则

1. **照 `next` 走**。每条命令的 JSON 都带 `next = {cmd, why}`：`cmd` 是下一个合法动作，照抄运行（`<…>` 换成真实内容）；`cmd` 为 null 时，下一步是你或用户的工作，`why` 说明是什么。有 `.decision/` 时先运行 `status`。
2. **预览先给用户看**。带 `needs_user: true` 的命令（确认方向和计划、不可逆步骤、审查结论、删除工作区）要先把 preview 给用户看，等用户回复同意后，才带 `--confirm` 重跑；不要在同一次回复里自己确认。用户说"别问了直接做"，也要先展示，那句话只对展示过的内容算数。脚本分辨不了确认的是人还是 Agent，真人审批靠宿主规则（[permissions.md](references/permissions.md)）。
3. **不能验证的写"未验证"**。有验证命令的步骤，只有脚本当场跑通才算完成；没有命令的，用文件或文字证据，文字证据记为未验证。不要说"应该没问题"。

## 3. 流程

| 阶段 | 什么时候 | 读 |
|---|---|---|
| 定方向 | 方向未定、方案拿不定、关键假设被推翻 | [direction.md](references/direction.md) |
| 计划与执行 | 方向已定；执行中；失败到上限要改计划 | [plan-and-execute.md](references/plan-and-execute.md) |
| 审查、复盘与收尾 | 全部步骤完成、问"能上线吗"、项目结束 | [review-and-close.md](references/review-and-close.md) |

只读当前阶段需要的那份。方向已清楚时，标准档可以用 `gate AB` 一次确认决策卡和计划；收尾用 `closeout` 一步完成归档与同步。用户跳过前面的阶段时不拒绝：从对话里提炼最小的决策卡或计划，推测项标"假设"，请用户一次确认。

确认之后改了方向（目标、成功标准、非目标、关键假设、止损、结论、失败次数上限）或计划结构，确认会失效，执行类命令会被拒绝，直到重新确认。这是有意的：改了就要让用户重新看过。

**什么时候退回去**：同一步失败到上限（默认 2 次；验证命令"改了代码仍失败"由脚本自动计数）或投入超过预计一倍 → 回到计划，只改出问题的那一步。止损期限到了、关键假设被推翻、出现明显更好的方案 → 回到定方向，只重审被推翻的那条假设。

## 4. 怎么调用脚本

文档里的 `de.py …` 是 `python <本技能目录>/scripts/de.py …` 的简写，在项目里任何目录运行都会找到同一个工作区（git 仓库根目录的 `.decision/`）。
- Claude Code：`python "${CLAUDE_SKILL_DIR}/scripts/de.py" status`（照这个写法，只读命令在本轮可免审批）；变量没被替换时用绝对路径，如 `~/.claude/skills/deciding-and-executing/scripts/de.py`。
- 其他宿主用绝对路径，如 `~/.agents/skills/deciding-and-executing/scripts/de.py`。macOS / Linux 用 `python3`，Windows 用 `python` 或 `py -3`。
- `audit.py` 指 closing-out 技能目录下的 `scripts/audit.py`。

开工前可以用 `preflight` 只读检查分支和将要执行的命令；审查时用 `coverage` 逐条核对成功标准的证据。命令表、证据规则、代码指纹等细节见 [script.md](references/script.md)，按交付类型选验证手段见 [references/verification-strategy.md](references/verification-strategy.md)。

## 5. 容易出错的地方

- **把活动当步骤**："研究竞品"不是步骤，"列出 5 个竞品的价格对比表"才是。写不出完成判据，说明还没拆好。
- **能写验证命令却不写**：命令证据是唯一能被脚本复核的证据。测试、构建、lint、`curl -f` 检查都写成 `verify_argv`。
- **用旧证据交付**：代码改过之后旧的命令证据就失效了，审查前先 `verify --all`。
- **为了过确认而改标准**：改成功标准、放宽判据、删测试都会让确认失效，要告诉用户为什么改。
- **最危险的假设排在最后**：先做能推翻方向的那一步。
- **新会话凭记忆续做**：先 `status`；交接给别的会话时附上 `handoff` 的输出。
- **项目结束不结案**：留下的 `.decision/` 会被下一个 Agent 当成现行目标。

说话时区分事实、推断和猜测，不确定就说不确定。阶段变化或被拒绝时，在回复末尾说明现在在哪、下一步是什么；其余时候不必每次重复。

## 6. 与 closing-out 的分工，以及其他资料

本技能管"这件事"；closing-out 管"整个仓库的文档"。收尾时的知识同步交给 closing-out 的完整档；会话结束但项目没完，交给它的轻量档。

- [worked-example.md](references/worked-example.md)：第一次使用时读（一项多日的开发任务）
- [example-decision.md](references/example-decision.md)：用户在做非代码的重要决定时读
- [prompts-standalone.md](references/prompts-standalone.md)：用户要在没装技能的 AI 里用时读
- [evidence.md](references/evidence.md)：用户问"为什么这样设计"时读
- `assets/`：决策卡、计划、进度日志、复盘、独立复核报告模板
