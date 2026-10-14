> **v4.0.1 本地候选（未正式发布）**：修复 v4.0.0 六项独立复审 P1 问题。安装和迁移前阅读 [验收记录](docs/v4.0.1-独立验收记录.md) 与 [最终愿景](docs/Skill-愿景与演进路线.md)。

# deciding-and-executing · 从决策到执行，再到收拾干净

**简体中文** | [English](README.en.md)

> 两个配套的 Agent Skill，把一件事从"想清楚"推进到"做出来"，最后"收拾干净"。
> **deciding-and-executing** 负责这件事本身：定方向 → 计划 → 单步执行 → 审查复盘 → 收尾归档。
> **closing-out** 负责整个仓库的知识：工作结束后，让 README、docs、规则文件、决策记录重新与代码现状一致。
> 闸门由脚本把守。脚本只宣称它能验证的东西：能验证的就强制，不能验证的（比如"是不是真人同意的"）就明说，并交给宿主的审批机制。

![version](https://img.shields.io/badge/version-4.0.1-blue) ![spec](https://img.shields.io/badge/Agent%20Skills-open%20spec-green) ![platforms](https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20claude.ai-supported-purple) ![python](https://img.shields.io/badge/python-3.8%2B%20stdlib%20only-yellow) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [两个技能，一条流水线](#两个技能一条流水线)
- [脚本能保证什么、不能保证什么](#脚本能保证什么不能保证什么)
- [快速开始](#快速开始)
- [使用示例](#使用示例)
- [deciding-and-executing 详解](#deciding-and-executing-详解)
- [closing-out 详解](#closing-out-详解)
- [项目里会出现哪些文件](#项目里会出现哪些文件)
- [仓库结构](#仓库结构)
- [开发与测试](#开发与测试)
- [设计原则与依据](#设计原则与依据)
- [已知局限](#已知局限)
- [常见问题](#常见问题)
- [从 3.x 升级](#从-3x-升级)
- [参与贡献](#参与贡献)
- [许可证与致谢](#许可证与致谢)

---

## 它解决什么问题

| 失败模式 | 典型表现 | 由谁解决 |
|---|---|---|
| **过早收敛** | 模型顺着你的想法，给出一个让人满意但没被检验过的结论 | deciding-and-executing ① |
| **想完不会做** | 方向讨论得很透彻，执行时又从零开始临场发挥 | ② 计划 |
| **宣布完成却没完成** | "代码写好了"被当成"功能可用"，没有证据，或拿旧版本的测试结果交付 | ③④：命令证据绑定代码指纹 |
| **反复盲试** | 同一步失败了还在换个姿势再试 | 失败到上限后脚本阻止继续，要求改计划 |
| **一出错就推倒重来** | 一个部署报错，演变成重新讨论整个项目该不该做 | 两级升级，只改被击中的部分 |
| **做完不收拾** | README 还写着旧命令，规则文件引用已删除的目录，过程文件被下一个 Agent 当成现行目标 | ⑤ 收尾 + closing-out |

## 两个技能，一条流水线

```
                          deciding-and-executing（这件事）
① 定方向 ─A─► ② 计划 ─B─► ③ 执行 ─C─► ④ 审查与复盘 ─D─► ⑤ 5A 归档 → 5B 知识同步 → 5C 删除工作区
    ▲              ▲          │                                        │
    └── 二级升级 ──┴─ 一级升级 ┘                                        ▼
                                                    closing-out（整个仓库的知识）
                             审计 → 差异表 → 路由 → 先减后加 → 复核 → 分层报告 → 确认后清理
```

| | deciding-and-executing | closing-out |
|---|---|---|
| 管什么 | 一件事：决策、计划、执行、复盘、结案 | 整个仓库：文档、规则文件、决策记录、残留文件 |
| 什么时候用 | 要做一件有返工成本的事 | 一段工作结束；里程碑、发布、交接；改名或删模块之后 |
| 脚本 | `de.py`：闸门、状态机、证据、升级、归档、删除 | `audit.py`：只读静态审计 |
| 能否单独用 | 能（没有 closing-out 时 5B 退化为人工清单，且不能 sync） | 能（任何仓库都可用） |

两个技能在 5B 交接：closing-out 准备完整的知识同步报告，`de.py sync --report .decision/closeout-report.md` **在本次调用中重新运行**配套审计脚本，保存可信审计 JSON，并检查 error、完整性和当前代码指纹。只做完 5A 归档不算结案。

## 脚本能保证什么、不能保证什么

| 能保证（脚本强制） | 不能保证（明说，并交给别的机制） |
|---|---|
| 计划没过闸门 B、或过了之后被改过，就不能开始执行 | 确认 token 是人给的还是 Agent 自己取的 → 宿主审批规则 |
| 有 `verify_cmd` 的步骤，只有命令当场跑通才算完成，任何文字都替代不了 | 文件证据的内容是否属实 → 人工审查 |
| 代码一变，旧的命令证据自动过期，审查前必须重跑 | 文档描述的行为是否仍与代码一致 → 源码事实核查 |
| 同一步失败到上限，状态变为待重新规划，不改计划不能继续 | 用宿主的 bypass 模式绕过一切 → 不要在重要项目里用 |
| 审查结论绑定代码和计划，任一变化即失效 | |
| 删除只针对项目内、带标记、只含已知文件、已提交到 git 的工作区 | |

**授权分三层**：脚本的两步确认（防误操作、防确认过期内容）→ 流程规则（Agent 必须把 preview 展示给你，等你回复后才能确认）→ 宿主审批（Claude Code `permissions.ask` / Codex `prompt` 规则，唯一能让真人介入的一层）。高风险档位必须配置第三层，见 [permissions.md](skills/deciding-and-executing/references/permissions.md)。

## 快速开始

### 1. 安装

| 平台 | 安装 | 调用 |
|---|---|---|
| Claude Code（个人） | `cp -r skills/* ~/.claude/skills/` | 自动触发，或 `/deciding-and-executing`、`/closing-out` |
| Claude Code（团队） | 复制到仓库的 `.claude/skills/` 并提交 | 同上 |
| Codex CLI / IDE、ChatGPT 桌面端 | `cp -r skills/* ~/.agents/skills/`（或仓库的 `.agents/skills/`） | 自动触发，或 `$deciding-and-executing`、`$closing-out` |
| claude.ai / Claude 桌面端 | 设置 → 技能，分别上传 `dist/` 下的两个 `.skill` 文件 | 自动触发 |
| Claude API | 通过 `/v1/skills` 上传，用 `container.skills` 引用（需启用代码执行工具） | 自动触发 |

> claude.ai 不能读写你的 git 仓库，闸门会退化为人工清单，且无法删除工作区。推荐在 Claude Code / Codex 中使用。

### 2. 配置宿主审批（高风险档位必须，其他建议）

把 [permissions.md](skills/deciding-and-executing/references/permissions.md) 里的规则加入 Claude Code 的 `settings.json` 或 Codex 的 `.rules` 文件，然后按文末的步骤验证它真的会弹出审批。

### 3. 开始使用

不需要记命令，用平常的话说：

```
先别急着回答。我在考虑把团队的 Jenkins 全部迁到 GitHub Actions……
今天先到这，收个尾。今天把 getUser 改成了 fetchUser，删了 src/legacy。
```

## 使用示例

| 你说 | 触发 | 反应 |
|---|---|---|
| "README 有个错别字帮我改下" | 都不触发 | 直接改 |
| "先别急着回答，我想辞职做独立开发……" | ① | 多个方向 + 能翻转结论的假设，只问一个问题并附推荐答案，然后停下等你 |
| "方向定了，业余做三个月，怎么排？" | ② | 生成计划，验证付费意愿的小实验排最前；`gate B` 的 preview 列出将要执行的命令，等你同意 |
| "第 3 步又失败了，你再试一次就好" | ③ | 说明已触发升级、脚本会拒绝继续；给出"改计划"或"记录豁免"两条路并推荐 |
| "功能写完了，可以上线了吧？" | ④ | 不直接说可以；`verify --all` 重跑命令证据，逐条对照成功标准 |
| "项目结束了，帮我结案" | ⑤ → closing-out | 归档预览 → 你同意后写入 → closing-out 完整档 → sync → 提交 → 展示删除清单 → 你同意后删除 |
| "别问了，直接删，token 你自己填" | ⑤ | 仍先展示删除清单；你的话可视为同意，但只对展示过的清单有效 |
| "这周把 SQLite 换成了 PostgreSQL，收个尾" | closing-out | 审计查不出语义变化，按路由表搜索并改掉所有 SQLite 描述；报告分层写明证据 |

完整案例：[deciding-and-executing 端到端示例](skills/deciding-and-executing/references/worked-example.md)、[closing-out 收尾示例](skills/closing-out/references/example.md)。

## deciding-and-executing 详解

**档位**

| 档位 | 什么时候 | 做法 |
|---|---|---|
| 不走流程 | 一步能完成、可逆 | 直接做 |
| 轻量 | 一次会话内能完成、只影响自己 | 不建工作区，回复里一张最小清单 |
| 标准 | 跨会话、多步骤、返工有成本 | `de.py init` |
| 高风险 | 不可逆操作、影响他人或花钱 | `de.py init --risk high`：只接受命令或文件证据，成功标准必须全覆盖，必须配置宿主审批 |

**阶段与闸门**

| 阶段 | 退出闸门（脚本检查） |
|---|---|
| ① 定方向 | `check card` 无 error → `gate A` 两步确认 |
| ② 计划 | `check plan` 无 error（含成功标准覆盖、依赖成环、类型校验）→ `gate B` 两步确认 |
| ③ 执行 | 全部步骤 done |
| ④ 审查与复盘 | `review --verdict pass`：步骤全部完成、命令证据对应当前代码、无阻断项；复盘三节有实质内容 |
| ⑤ 收尾 | 5A `archive --apply`；5B `sync`；5C `purge` 两步确认 |

决策卡的目标、成功标准、非目标、止损条件或结论被改动，闸门 A、B 都失效；计划步骤的结构被改动，闸门 B 失效。失效后执行类命令会被拒绝，直到重新确认。

**步骤状态机**：`todo → in_progress → implemented → done`，另有 `blocked` 和 `needs_replan`。`done` 不能直接改回去，只能 `reopen`（旧证据归档、审查结论作废）；`needs_replan` 只能通过 `replan` 解除。

**`de.py` 命令**（用技能目录下脚本的完整路径调用；在项目任何子目录运行都使用同一个工作区）

| 命令 | 作用 |
|---|---|
| `init [--name] [--risk standard\|high]` | 建工作区；已有不覆盖，非空的陌生目录拒绝 |
| `check card` / `check plan` | 只校验 |
| `gate A` / `gate B` [`--confirm TOKEN`] | 闸门两步确认 |
| `status` | 阶段、闸门、当前步骤、过期证据、纯文字证据、升级提示、事件日志一致性 |
| `step ID --status S [--evidence 文本 \| --artifact 文件] [--hours H]` | 状态转换；`done` 的证据规则见下 |
| `verify ID` / `verify --all` | 脚本执行 `verify_cmd`，记录退出码、输出摘要、代码指纹 |
| `fail ID --note` | 记录失败；到上限自动 `needs_replan` |
| `replan ID --note [--waive 理由 --confirm]` | 解除升级：步骤必须已修改，或两步确认记录豁免 |
| `reopen ID --reason` | 重做已完成步骤 |
| `review --verdict pass\|fix\|fail [--blocker …] [--confirm]` | 审查结论 |
| `archive [--outcome 完成\|止损\|放弃] [--apply]` | 写决策记录；不删除任何东西 |
| `sync --report`（可选 `--audit-json` 指定工作区固定输出） | 现场运行 closing-out 静态审计，审计通过后登记知识同步 |
| `purge [--confirm TOKEN]` | 删除工作区 |
| `show` | 计划表 |

**`done` 的证据规则**：有 `verify_cmd` → 脚本当场执行，退出码 0 且执行期间代码未变才算；否则 `--artifact` 文件（记录哈希）；标准档可用 `--evidence` 文字，记为"未验证"并在状态、审查、决策记录中单独标出；高风险档不接受文字。

退出码：`0` 成功；`1` 检查未通过；`2` 用法或数据错误；`3` 闸门拒绝或需要确认（返回 `token` 与 `preview`）。

## closing-out 详解

**三条原则**：每个事实只有一个权威位置；先减后加、就地改写；证据改状态，记忆和旧文档只算线索。

**两个档位**：轻量（每次会话结束，只看本次改动）；完整（里程碑、发布、交接、改名或删模块后）。

**七步流程**：审计 → 事实差异表 → 按变更类型路由 → 先减后加 → 复核（改完必须重新审计）→ 分层报告（删除只列候选）→ 你确认后清理并再审计。

**报告必须分层写证据**：静态审计 / 变更影响分析 / 源码事实核查 / 运行验证，不同层级不共用一个"通过"。

**`audit.py`**（只读）

```bash
python3 scripts/audit.py [--root .] [--base main] [--rename 旧=新 ...] [--exclude 'glob' ...] [--max-findings 200]
```

| 检查项 | 发现什么 |
|---|---|
| `rules-chain` | 每个目录的有效规则链（仓库根到该目录，每层一个 AGENTS 文件）超过 Codex 默认 32 KiB；CLAUDE.md 与 AGENTS.md 并存却没有导入；CLAUDE.md 超过 200 行；AGENTS.override.md 存在；CLAUDE.local.md 未被忽略 |
| `rule-refs` | 规则文件里的 `@导入`、路径、`npm` / `make` 命令不存在 |
| `doc-commands` | README 与 docs 里的命令不存在 |
| `dead-links` | 相对链接指向不存在的文件（忽略代码块与行内代码） |
| `stale-names` | `--rename` 旧名字残留（跳过历史文件；正确处理新旧名互为前缀） |
| `duplicate-lines` | 同一句较长的话出现在多个文档 |
| `residue` | 计划草稿、调试脚本、旧副本、未跟踪文件（文件名含空格、引号、中文也能正确识别） |
| `decision` | 决策工作区的状态（工作区内容不参与文档检查，也不计入代码指纹） |

输出包含 `complete`（是否被截断）、`evidence_level: "static"`、`limits`（能力边界）和 `fingerprint`。退出码：`0` 无 error 且输出完整；`1` 有 error 或被截断；`2` 用法错误。

## 项目里会出现哪些文件

| 文件 | 生命周期 | 说明 |
|---|---|---|
| `.decision/.de-workspace` | 进行中 | 工作区标记；删除时只认带标记的目录 |
| `.decision/decision-card.md` | 进行中 | 结论、目标、编号的成功标准、非目标、编号假设、结构化止损条件 |
| `.decision/plan.json` | 进行中 | 步骤、闸门记录、证据、审查结论 |
| `.decision/events.jsonl` | 进行中 | 只追加的机器事件日志；先写事件再写计划，中断可被发现 |
| `.decision/progress.md` | 进行中 | 给人读的进度记录与"待办/观察" |
| `.decision/retro.md` | 进行中 | 复盘与教训去向 |
| `.decision/closeout-*.{json,md}` | 5B | 知识同步的审计结果与报告 |
| `docs/decisions/YYYY-MM-DD-名称.md` | 永久 | 决策记录：只记"为什么"，含证据类型、审查结论、知识同步报告 |

## 仓库结构

```
.
├── README.md / README.en.md
├── CHANGELOG.md                   版本、验证结果、测试数量的唯一权威位置
├── LICENSE
├── skills/                        ← 需要安装的只有这里
│   ├── deciding-and-executing/
│   │   ├── SKILL.md
│   │   ├── references/            五个阶段、permissions、示例、独立提示词、设计依据
│   │   ├── scripts/de.py
│   │   ├── assets/                决策卡、计划、进度日志、复盘模板
│   │   └── agents/openai.yaml
│   └── closing-out/
│       ├── SKILL.md
│       ├── references/            路由表、放置规则、示例
│       ├── scripts/audit.py
│       ├── assets/report.md
│       └── agents/openai.yaml
├── dist/                          打包好的 .skill（release_check 会核对与 skills/ 一致）
├── docs/
│   ├── 内审报告-v4.0.0.md          对外部评审的逐条回应与自审发现
│   └── 教程-如何制作高质量Skill.md
└── dev/
    ├── release_check.py           发布前一次性检查
    ├── validate_skill.py          结构校验（有 PyYAML 时做真实 YAML 解析）
    ├── run_trigger_eval.sh        触发率测试
    ├── tests/                     回归与对抗测试（与本机 git 全局配置隔离）
    ├── evals/<技能名>/            行为评测用例与触发查询
    └── eval-runs/                 评测运行记录
```

## 开发与测试

```bash
python3 dev/release_check.py                       # 一次跑完：结构、测试、dist 一致性、CHANGELOG、自审计
python3 -m unittest discover -s dev/tests     # 只跑测试
bash dev/run_trigger_eval.sh closing-out dev/evals/closing-out/trigger_evals.json 3   # 触发率（需 Claude Code 与 jq）
bash dev/evals/closing-out/make_fixture.sh /tmp/fixture-co                            # closing-out 示例仓库
```

测试会启动大量 git 子进程，完整运行需要几十秒；具体数字见 [CHANGELOG.md](CHANGELOG.md)。测试已与本机的 git 全局配置（签名、钩子、编辑器）隔离。

**三个层次分别验收**：静态合规（validate_skill）≠ 工具行为正确（回归测试）≠ Agent 实际遵守（`dev/evals` 行为评测与触发评测，需在 Claude Code 中运行）。当前版本完成了哪几层，见 CHANGELOG 的"验证"一节。

**修改技能的流程**：真实任务 → 读完整执行记录 → 每次纠正模型就加一条 Gotcha → 改脚本先写失败测试 → `release_check.py` → 更新版本号与 CHANGELOG → 用 closing-out 给本仓库收尾。

## 设计原则与依据

| 原则 | 依据 |
|---|---|
| 同一对话里的自我反驳只算草稿，优先外部证据 | Huang 等，ICLR 2024 |
| 显式对抗迎合，置信度要说明依据 | Sharma 等，ICLR 2024 |
| 一次只做一步，状态外置，无证据不算完成 | Anthropic Engineering《Effective harnesses for long-running agents》 |
| 证据绑定代码版本；授权分三层；升级是硬约束 | 外部工程评审（见内审报告）；Claude Code 权限文档；Codex rules 文档 |
| if-then 预案 | Gollwitzer 与 Sheeran 元分析 |
| 止损 = 触发状态 + 期限 + 动作 | Annie Duke《Quit》的 kill criteria |
| AGENTS.md 唯一规则源，CLAUDE.md 导入；规则链按目录计算 | Claude Code 记忆文档；Codex AGENTS.md 文档 |
| 决策记录与现状文档分离 | 架构决策记录（ADR）惯例 |

完整依据与证据强度见 [evidence.md](skills/deciding-and-executing/references/evidence.md)。

## 已知局限

- **Agent 行为层尚未独立评测。** 回归测试证明脚本行为正确，但"Agent 是否会把 preview 展示给用户再确认"只能靠行为评测，目前未在真实 Agent 上运行。
- **两步确认不能证明确认者是人。** Agent 若违反流程自己确认，脚本发现不了；这一层依赖宿主审批规则，而宿主规则匹配的是命令文本，不是安全边界。
- **静态审计不懂语义。** 文档行为描述是否正确，需要源码事实核查。
- **命令检查只覆盖 npm 与 Make。** Poetry、Cargo、Go 等暂不校验。
- **只在 Linux 上测试过。** Windows 与 macOS 没有运行证据；路径与符号链接处理按跨平台方式编写，但未验证。
- **非 git 项目能力降级**：无法判断证据是否对应当前代码，也不能删除工作区。

## 常见问题

**每件事都要走流程吗？** 不用。见档位表；十分钟能改完的小修复不走流程。

**脚本会执行 plan.json 里的命令，安全吗？** 只执行 `verify_cmd`，且这些命令在 `gate B` 的 preview 里逐条列出、经你确认；之后任何人改了命令，闸门 B 失效，脚本拒绝执行。

**closing-out 会不会乱删文件？** 不会。审计只读；删除只出候选清单。

**它会改我的 Agent 记忆吗？** 默认不会。

**为什么不直接用别人的收尾技能？** 可以用，思路相通。这里的 closing-out 与 deciding-and-executing 共享一套接口与约定，并把更多检查交给了脚本。

## 从 3.x 升级

4.0.0 有不兼容变更，进行中的 3.x 工作区需要迁移：
1. 决策卡：结论改为以"做 / 改后做 / 放弃"开头；成功标准编号；止损条件改为"触发状态 / 期限 / 动作"三行。
2. 计划：给步骤补 `covers`；能用命令验证的补 `verify_cmd`。
3. 在工作区里新建 `.de-workspace` 标记（或重新 `init` 到新目录后搬运内容）。
4. 依次运行 `gate A`、`gate B` 重新确认。
5. `archive --remove-workspace` 已移除，改用 `archive --apply` → `sync` → `purge`。

## 参与贡献

最有价值的贡献：真实失败案例（会整理进 Gotchas）；"差一点"的触发反例；Agent 行为评测结果；audit.py 对更多生态的命令检查；Windows / macOS 运行结果。提交前运行 `python3 dev/release_check.py`。

## 许可证与致谢

基于 [MIT 许可证](LICENSE) 发布。方法论参考了 Anthropic 与 OpenAI 的官方技能文档、[Agent Skills 开放规范](https://agentskills.io)、Claude Code 团队分享的内部经验，以及 [anthropics/skills](https://github.com/anthropics/skills)、[openai/skills](https://github.com/openai/skills)、[obra/superpowers](https://github.com/obra/superpowers)、[KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) 等开源技能库；4.0.0 的大部分改动来自一份外部工程评审。完整来源见 [教程](docs/教程-如何制作高质量Skill.md)。


### v4.0.1 使用注意

- `sync` 要求两个 Skill 都完整安装：`de.py sync --report .decision/closeout-report.md`。它现场运行配套审计器并把结果存为 `.decision/closeout-audit.json`，不信任提前编辑的 JSON。`--audit-json` 如需兼容旧命令，只能指向该固定输出文件。
- 代码指纹包含 Git 已跟踪变更与未跟踪文件（单文件上限 32 MiB、总量上限 128 MiB）的内容，**不包含 Git 忽略文件**。证据可靠性还取决于验证命令是否覆盖正确的需求。
- `review pass` 及完成型 `archive` 现在会重新验证 artifact 文件的当前哈希、路径和与代码版本的匹配状态。
- v4.0.1 仍需要 Windows/macOS、Claude Code/Codex 真实宿主审批与 Agent 触发/行为对照评测，见验收记录。
