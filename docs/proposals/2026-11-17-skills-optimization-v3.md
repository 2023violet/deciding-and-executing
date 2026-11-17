# 两个 skill 的优化方案 v3（核实与评审后）

> 2026-11-17。依据：另一个 Agent 写的《优化思路方案 v2》和《生态调研报告·第二轮》。
> 基线：分支 `review-fixes-p0-p2`（v4.2.0 / closing-out 2.1.0，PR #1 未合并；`main` 仍是 4.1.0）。
> 用法：按编号批准。标【行为变更】的会改变用户可见的行为，需要你先拍板；其余可以直接做。

---

## 〇、结论

1. **数字基本属实，推论有一处不对。** 报告里的 star、安装量、建库日期和 GSD 归档，我都逐条查过，基本对得上。但从"mattpocock 单点技能装得多"推出"把我们拆成五个单点技能"，这一步不成立，理由见第二节。
2. **v2 有两个前提已经过时。** 一是"用户要背五阶段命令"：命令一直是 Agent 在跑，用户一条都不用敲。二是"标准档约 5 次确认"：v4.2 有了 `gate AB` 之后，标准档只剩 3 次（AB、审查通过、可选的清理），加上不可逆步骤。
3. **v2 说的"3 条已知绕过路径"是真的，今天全部复现了。** 详见第三节。这是最该先修的。
4. **建议的形态：** 不拆成五个技能，引擎和两个现有技能保持不变。从生态里借三样核实过的东西：
   - 每条命令都给出"下一个合法动作"；
   - 验收时用一个看不到执行过程的复核者；
   - 方向阶段用"一轮一组编号问题，每题附推荐答案"的提问格式。
   等 R1 评测有了数据，再决定要不要加一个单独的"验收"技能。

---

## 一、调研核实（2026-11-17 实查）

| 报告里的说法 | 核实结果 | 怎么查的 |
|---|---|---|
| mattpocock/skills，2026-02 建库，约 32.6 万 star | ✅ 326,211 star，2026-02-03 建库 | `gh api repos/...` |
| grill-me 安装 1.6M、triage 1.1M、claude-handoff 487K、retro 368K | ✅ 一致；另外 handoff 有 1.1M | skills.sh 各技能页 |
| "grill-me 的 SKILL.md 只有三句话" | ⚠️ 不准确。grill-me 只有一行"调用 grilling"，是给用户手动调用的入口；真正干活的是 `grilling`，约 25 行 | 读原文 |
| README 点名反对 GSD/BMAD/Spec-Kit | ✅ 原话说它们 "take away your control" | README |
| mattpocock 全是互不相干的单点技能 | ❌ 漏了关键一半。他也有编排型技能：`implement`（串起 tdd 和 code-review）、`implement-spec`、`wayfinder`（用 issue 跟踪器规划多会话的大工作）。核心设计是"用户调用的编排技能 + 模型自动调用的纪律技能"，而且编排技能不能互相调用 | README 的 Reference 一节、各 SKILL.md |
| handoff 比我们的 state.json 弱 | ⚠️ 两者目标不同。他的 handoff 故意写到系统临时目录，只引用已有产物、不另存状态，卖点是零配置。不能拿来比谁强 | handoff/SKILL.md |
| addyosmani 约 11.8 万 star；`/build auto` 批准一次就跑完 | ✅ 118,460 star。原话是批准一次计划后自动跑完，但每个任务仍要过测试，遇到失败或高风险步骤会暂停 | README |
| superpowers 约 31.9 万 star，靠 SessionStart 注入 | ✅ 318,853 star；钩子匹配 `startup\|clear\|compact`，也就是新会话、清屏、上下文压缩之后都会重新注入 | hooks/hooks.json |
| superpowers 的差评是"token ×10""启动预载 22k" | ❌ 没找到依据。查到的实测（12 个会话、自测）：简单任务大约多用 8% token，中等和复杂任务反而更省。"23k/会话"是对技能整体的统计，不针对 superpowers | 第三方博客，样本小 |
| verification-before-completion 28 万安装 | ✅ 279.8K；而且它全靠提示词（Iron Law 加合理化借口表），没有任何脚本强制 | skills.sh、原文 |
| Cloudflare security-audit 约 7.4 万 star；发现者和验证者分开；三态判定；schema 校验 | ✅ 74,211 star。三态是 `confirmed / needs_validation / rejected`，还有零依赖的校验脚本，多次运行结果可以累加 | README |
| 同一功能实测：OpenSpec 4.00、Spec-Kit 2.77、BMAD 体验 2 分、6 天 / $200 | ✅ 13 个维度。总分 OpenSpec 4.00、BMAD 3.65、Spec-Kit 2.77；开发体验 BMAD 只有 2。"$200"是规划 $50 加实现 $150 自己相加得出的 | ranthebuilder.cloud，2026-04 |
| GSD 已归档 | ✅ 2026-06-26 归档。它不是停更，而是搬到了 open-gsd/gsd-core | 仓库页 |
| task-master 停更 | ⚠️ 只能确认最后一次推送是 2026-04-28，"转商业"没核实 | GitHub API |
| ECC 约 30.5 万 star | ✅ 现在叫 affaan-m/ECC，304,862 star | GitHub API |
| impeccable 41 万安装 | ✅ impeccable 这一个技能 413.8K，整个仓库合计 1.9M | skills.sh |
| "主动送审，拿安全徽章" | ⚠️ skills.sh 的页面上自动显示 Gen Agent Trust Hub、Socket、Snyk 三家的审计结果，没看到"申请送审"的流程。要上榜，靠的是有人用 `npx skills add` 安装后产生的统计 | skills.sh 页面、FAQ |

**口径提醒：** skills.sh 的"Installs"来自 CLI 匿名统计，FAQ 没说是否去重，用户也可以关掉统计。它只能说明有多少人装过，不能说明技能有效。

---

## 二、评审：两份文档对在哪、错在哪

### 对的部分（采纳）

- **验收是最热、也最不容易因为模型变强而贬值的环节。** verification-before-completion 只靠提示词就有 28 万安装，Cloudflare 用发现者和验证者分开、三态判定、schema 校验做出了标杆。我们的 de.py 会真跑验证命令、把证据和代码指纹绑在一起。这是生态里很少见的硬差异，应该继续往这里投入。
- **模型自动调用和用户手动调用要分开设计。** 这是 mattpocock 最值得学的机制。
- **"可以随时查询状态 + 告诉下一步该做什么"让体验变轻。** OpenSpec 和 task-master 都证明了这一点。de.py 有 `status`，但"下一步"的输出还没有覆盖所有命令。
- **R1 行为评测仍是 P0。** 社区证据全都是"长任务值得、小任务亏"这类有条件的判断，分界线在哪，只能我们自己测。
- **灵魂保护条款四条判据**（假完成测试、确认刻度尺、用数据裁决、不能验证的必须标出来）：保留，作为本方案每一项的审查标准。

### 错的部分（不采纳或修正）

1. **"单点技能赢了，所以拆成五个"：因果推断不成立。**
   - mattpocock 的安装量混杂了作者本身的影响力：他的通讯有约 6 万订阅者，还有 Total TypeScript 的受众。安装量证明不了"单点"这个形态本身更好。
   - 他自己就有编排型技能和多会话规划（wayfinder），所以他的经验是"小而可组合的纪律单元，加上很薄的编排层"，不是"只要单点"。
   - 我们拆出来的"方向拷问"和"复盘"，要和 1.6M 安装的 grill-me、368K 的 retro 正面竞争，却没有差异：这两件事都不需要脚本强制。
   - 每多一个技能，它的描述就常驻上下文。Claude Code 给技能列表的预算是上下文的 1%，超出时最少被用到的技能描述会被丢掉。技能多了还更容易互相抢触发：你本机就装着 superpowers，它的 brainstorming 写着 "You MUST use this before any creative work"。
   - **结论：** 只有"验收"值得考虑单独拆出来，而且要等 R1 数据。见 P2-1。
2. **"用户要背五阶段命令"：与事实不符。** SKILL.md 一直写的是由 Agent 运行 de.py，用户只在闸门处拍板。真正的负担是预览要读多少字、要确认几次，不是命令。所以 v2 的指标"用户命令数 = 0"本来就已经达成，应该换成"确认次数"和"预览长度"。
3. **"标准档约 5 次确认"：v4.2 之后已经过时。** 标准档现在是 `gate AB`、审查通过、可选的清理，各一次，加上每个不可逆步骤一次。v2 的 X2 大部分已经落地了。
4. **"superpowers 的最大差评是 token ×10"：没有依据。** 应该引用实测："简单任务多约 8%，复杂任务更省。"这反倒说明给小任务分流，比砍流程更关键。
5. **v2 的 X3"在技能内部加小任务快车道"：和现在的定位冲突。** v4.2 的描述已经明确排除"十分钟内的小修复"。小任务应该交给别的技能或者干脆不用技能，而不是在这个重技能里再开一条快车道。

---

## 三、对照代码核实（今天在分支上复现）

复现脚本：`C:\Users\16429\AppData\Local\Temp\claude\f85c154014502679\fd0ddf1d-878c-40b1-af57-f17e0484737f\scratchpad\repro_bypass.py`，3 条全部复现。

| 编号 | 绕过路径 | 复现结果 | 位置 |
|---|---|---|---|
| B1 | 不可逆步骤先改成 `blocked` 再改成 `in_progress`，可以跳过确认 | 退出码 0，没有要求确认 | `de.py` 的 `cmd_step`：只在 `old == "todo"` 时要求确认 |
| B2 | 闸门通过后，把决策卡里的"修复失败次数上限"改成 99，闸门不失效，升级也不再触发 | 失败 3 次后 `escalate: False`，`max_fails: 99`，状态里没有任何闸门警告 | `card_info` 从卡片全文解析上限，但 `gate_a_hash` 只哈希 5 个章节和结论 |
| B4 | 验证命令连续失败，失败次数不会自动增加，可以无限重试 | `step done` 失败 4 次后，`fails: 0` | 失败只在 Agent 主动运行 `fail` 时才计数 |

B3（非 git 项目）：README 第 276 行已经写明这类项目能力降级，status 也会给警告，不算缺陷，只需要在 SKILL.md 里补一句。
B5（SKILL.md 第 52 行措辞）：修完 B2 以后，要把"升级阈值"加进闸门失效的列表。

---

## 四、设计原则（来自官方规范和核实过的证据）

1. **SKILL.md 只放每条路径都要用的内容，只有部分路径用到的放进 references。** 官方要求正文少于 500 行，引用只链一层。现状是 155 行和 120 行，已经达标，不需要为了瘦身而瘦身。
2. **描述写"做什么 + 什么时候用 + 不用于什么"**，不超过 1024 字符。触发词要覆盖技能实际支持的语言。
3. **容易出错的环节交给脚本，开放性的环节讲清楚原因。** 这就是官方说的"自由度"：独木桥要装护栏，开阔地只需指方向。证据绑定、闸门、删除都属于独木桥，保留脚本。
4. **先评测，再扩张。** 先有不用技能时的基线，至少 3 个场景，再改文档。
5. **每加一个技能，都要说清楚它和已有技能比差在哪。** 说不清就不加。
6. **用正面指令写行为，少用禁令。** 这是 mattpocock 的 writing-for-agents 给的规则：禁令会把被禁止的行为带进上下文。改 SKILL.md 时按这一条顺手修。

---

## 五、优化方案

### P0：修补绕过路径和明显缺口（小改动，可以直接做，除了标注的一项）

> 进度（2026-11-17）：
> - 4.2 分支：P0-1、P0-2 已完成（含 B3 文档、B5），并补上一个残余漏洞：闸门失效期间，`fail` 按已确认的上限判断是否升级。
> - 5.0.0（分支 `v5-major-update`）：P0-3（失败自动计数，按"改了代码仍失败才计"）、P0-4（英文触发词）、P0-5 中的 R1_SMOKE 映射表处理、P1-1 至 P1-7、P2-2（插件清单与 README 安装方式）已实现，测试 174 项通过；P3-2 触发评测随本版运行，结果见 CHANGELOG。
> - 未做：P2-1（等 R1 数据）、P2-3（等实测数字）、P3-1、P3-3；P1-5 / P1-6 未在真实宿主上验证。

**P0-1 修 B1：不可逆步骤的确认不能绕过**
- 改法：`cmd_step` 中，从 `todo` 或 `blocked` 进入 `in_progress` 时都要求确认。确认内容里已经带着代码指纹，所以重新进入时会自然要求重新确认。
- 验收：新增回归测试（`todo → blocked → in_progress` 必须拿到退出码 3），再做一个变异测试：把条件改回去，测试必须失败。

**P0-2 修 B2 和 B5：升级阈值纳入闸门 A**
- 改法：`gate_a_hash` 加入 `max_fails`，"升级阈值"章节也进入哈希。SKILL.md 第 52 行和 `stage-1-direction.md` 的失效列表同步更新。
- 注意：旧工作区升级后，闸门 A 会失效一次。要在 CHANGELOG 和 status 的提示里说明"重新确认一次即可"。

**P0-3【行为变更】修 B4：脚本亲眼看到的失败自动计数**
- 改法：`step done` 或 `verify` 跑验证命令失败时，如果这次的代码指纹和上一次失败时不同（说明确实改过代码、又试了一次），就自动加一次失败。指纹没变的重复运行不计数，这样 TDD 先看到红灯的过程不会被误伤。`fail` 命令保留，用来记录没有验证命令的失败。
- 理由：现在的计数全靠 Agent 自报，而升级机制要防的恰恰是 Agent 自己"再试一次"的冲动。这个改法用的是脚本观察到的事实，符合"证据优于叙述"。
- 和 v2 的分歧：v2 主张"维持自报，只改措辞"。我认为那样等于默认这条路可以绕过，**需要你选**。

**P0-4 描述补上英文触发词**
- 改法：v4.2 已经支持英文卡片（`init --lang en`），但 deciding-and-executing 的描述里一个英文触发词都没有。补上 "multi-day migration / refactor"、"is this ready to ship"、"decision card"、"pre-mortem"、"steelman" 等，总长控制在 1024 字符以内。closing-out 同样补几个。
- 验收：触发评测里加入英文的正例和近似反例（等 R1 一起跑）。

**P0-5 前置事项（需要你处理）**
- 合并 PR #1：本方案以 v4.2 为基线。
- 处理 `experimental/independent-verification/R1_SMOKE_OPERATOR.md`：这个文件里有分组映射表，评测还没跑就公开，会破坏盲测。

### P1：借鉴核实过的机制，放进现有两个技能（不新增技能）

**P1-1 每条命令都输出"下一个合法动作"**（借鉴 task-master 和 OpenSpec）
- 改法：所有命令的 JSON 都带一个 `next` 字段，给出一条可以直接执行的命令和一句理由。`status` 里的 `next` 根据阶段、升级状态和过期证据推导。
- 价值：断点续做、交接、新会话接手时，Agent 不用读完整份参考文档就知道下一步。
- 验收：每个阶段都有一个测试，断言 `next` 不为空，而且照着执行会被接受。

**P1-2 新增只读命令 `de.py handoff`**（借鉴 mattpocock 的 handoff，但证据状态由脚本推导）
- 输出：阶段、完成了哪些步骤以及每步的证据类型（命令 / 文件 / 未验证文字）、过期证据、升级、未决假设、下一步。
- 原则：只引用文件路径，不复制内容；不新增状态，只写到标准输出。
- 差异点：他的交接摘要是 Agent 自己写的叙述，我们的是脚本从 events 和 state 推导出来的，哪一步没验证一眼就能看到。

**P1-3 方向阶段改用"按轮次提问"**（借鉴 mattpocock 的 grilling）
- 改法：`stage-1-direction.md` 的提问部分改成：
  - 每轮只问当前就能回答的问题，编号排列，每题附推荐答案，用户答"是"就等于接受推荐；
  - 需要查的事实由 Agent 自己去查，不问用户；
  - 用户的回答会解锁下一轮问题。
- 价值：减轻用户负担，又不削弱钢人论证和事前验尸。这件事不需要单独拆成技能。

**P1-4 审查阶段加可选的独立复核者**（借鉴 Cloudflare 和 superpowers 的 requesting-code-review）
- 改法：宿主支持子代理时，`stage-4-review.md` 建议派一个没有执行上下文的子代理复核。它只拿到 diff、决策卡和计划，对每条成功标准给出 `verified / needs_validation / rejected` 三态判定。
- 边界：闸门 D 仍以脚本证据为准，复核意见只记成审查材料。可复用的部分从实验区挑，实验区本身仍然封存。
- 依据：`evidence.md` 引用的研究本来就是"自我修正无效"，这一条是把项目自己的主张落到流程结构上。

**P1-5 SessionStart 钩子改成"只注入状态"**
- 改法：`permissions.md` 里的可选钩子只在存在 `.decision/` 时运行 `de.py status`，输出控制在 15 行左右（新增 `--brief` 选项）。匹配 `startup|clear|compact`，让压缩上下文之后也能重新注入。
- 不做：不注入"总调度"提示词。那会和用户已经装的 superpowers 等技能抢优先级，而且每个会话都要付这部分 token。
- 验收：实测注入的字数；在真实宿主上验证一次（与 X10 合并做）。

**P1-6 Claude Code 专属增强：只读命令免确认**
- 改法：SKILL.md 的 frontmatter 加 `allowed-tools`，只放只读命令：`status`、`check`、`list`、`show`、`preflight`、`coverage`、`handoff`。官方文档确认其他宿主会忽略不认识的字段。
- 风险：必须核实免确认只对这几个子命令生效，不能连带放行 `gate`、`purge`。要在真实宿主上测。

**P1-7 复盘加一节"环境改进"（可选）**
- 改法：`retro.md` 模板加一小节，借鉴 mattpocock 的 retro 分类：下次能不能更快找到文件？能不能加一个自动检查来防住这次的错？
- 作用：复盘要能产出具体的行动，而不只是记录。

### P2：要不要加新入口，用数据决定

**P2-1 单独的验收技能（候选名 `verifying-completion`），R1 有正面数据才做**
- 形态：模型自动调用；不需要 `.decision/` 工作区，任务大小不限。
- 做法：宣布完成之前，用脚本跑验证命令，把结果和代码指纹绑定，输出三态判定。实现上复用 de.py，加一个不依赖工作区的 `prove` 子命令。
- 差异点：superpowers 的同类技能全靠提示词，这个是脚本真跑。
- 上线门槛：
  - R1 里对比"不用技能"和"superpowers 同类技能"两组，假完成率明显更低；
  - token 和耗时增加不超过 30%；
  - 和 superpowers 同时装时，抢触发的情况可以接受。
- 达不到门槛就不发布。

**P2-2 分发渠道**
- 现在的 `skills/<名称>/SKILL.md` 目录结构就是 `npx skills add` 认的标准布局。先在干净环境实测 `npx skills add 2023violet/deciding-and-executing` 能不能装上并触发。
- 再加 `.claude-plugin/marketplace.json`，支持插件方式安装。
- `dist/*.skill` 和 zip 保留。

**P2-3 README 以痛点开头**
- 开头三个卖点："宣布完成前必须有现场证据""计划挺过会话中断""收尾时文档自动对齐"。
- 具体数字等 R1 出来再填，不填估算值。

### P3：评测与实机验证（证据层）

**P3-1 R1 行为对照（P0 级别的优先级，但要花钱，需要你批预算）**
- 分组：不用技能 / superpowers 的 verification-before-completion / 本技能标准档 / 本技能严格档。
- 场景：至少 3 个，长任务和小任务各一部分。
- 指标：假完成率、token、耗时、用户确认次数、预览字数。
- 先预注册停止规则：收益分辨不出来，或者 token / 耗时增幅超过 30%，就冻结扩张。

**P3-2 触发评测**：中英文正例加近似反例，每条跑 3 次。

**P3-3 实机验证**：宿主审批规则（P1-6）、钩子（P1-5）、macOS 补测。

---

## 六、v2 的 X1–X17 逐项裁定

| v2 编号 | 裁定 | 落在本方案哪里 |
|---|---|---|
| X1 总调度加自动触发 | **修改**：只注入状态，不注入调度提示词，并且用户自愿开启 | P1-5 |
| X2 确认收敛为两次 | **大部分已经实现**（gate AB）；剩下审查通过和清理，属于人该拍板的事，保留 | 不需要新工作 |
| X3 技能内部的小任务快车道 | **不采纳**：靠描述的边界把小任务分流出去；需要小任务验收时走 P2-1 | P0-4、P2-1 |
| X4 标准档纪律改成纯提示词 | **暂缓**：等 R1 的"标准档 vs 严格档"数据 | P3-1 |
| X5 独立复核子代理 | **采纳**，作为可选项 | P1-4 |
| X6 描述重写 | **采纳一部分**：补英文触发词，然后用评测选优；现在的写法本身合规 | P0-4、P3-2 |
| X7 正文瘦身 | **不需要**：已经远低于 500 行；"22k 预载"不适用（技能被调用前只加载描述） | — |
| X8 README 和分发 | **采纳** | P2-2、P2-3 |
| X9 R1 | **采纳**，增加 superpowers 对照组 | P3-1 |
| X10–X12 | **采纳** | P3-3 |
| X13（B1） | **采纳**，已复现 | P0-1 |
| X14（B2） | **采纳**，已复现 | P0-2 |
| X15（B3） | 只补一句文档 | P0-2 顺手做 |
| X16（B4） | **修改**：按指纹自动计数，而不是只改措辞 | P0-3（需要你选） |
| X17（B5） | **采纳** | P0-2 |
| 第二轮修正一：拆成五个单点技能 | **不采纳**；只有验收一项，等数据决定 | P2-1 |
| 第二轮修正二：双层触发 | **采纳**的是原理；落地方式是只读命令免确认，加上可选的验收技能 | P1-6、P2-1 |
| 第二轮修正三：状态可查询 | **采纳** | P1-1、P1-2 |
| 第二轮修正四：送审拿徽章 | **修改**：徽章随上榜自动出现，没有送审流程 | P2-2 |

---

## 七、明确不做

1. 不拆成"方向拷问""复盘""交接"这些单独的技能：没有差异，还会增加常驻上下文和抢触发。交接做成只读命令（P1-2）。
2. R1 出结果之前，不把任何脚本闸门降级成提示词。
3. 不注入常驻的总调度提示词。
4. 不放宽非 git 项目的限制，不放宽删除白名单。
5. 不往这个技能里加快车道。

## 八、衡量指标（替换 v2 第五节）

| 指标 | 现状 | 目标 | 怎么测 |
|---|---|---|---|
| 已知绕过路径 | 3（今天复现） | 0 | 回归测试加变异测试 |
| 标准档用户确认次数 | AB、审查、清理各 1 次，加不可逆步骤 | 不增加 | 演示任务计数 |
| 每次闸门预览的字数 | 没测过 | 先测出基线，再设上限 | 统计 preview 输出 |
| 钩子注入的大小 | 没有 | ≤ 15 行 | 实测 |
| 断点续做：新会话找到下一步 | 要读参考文档 | `status.next` 直接给出 | P1-1 测试 |
| R1 假完成率的差值 | 没有证据 | 明显为正 | 预注册对照 |
| token / 耗时的差值 | 没有证据 | 增幅 ≤ 30% | 同上 |
| 触发率 / 误触发率（中英文） | 没跑过 | ≥ 0.5 / < 0.5 | 近似反例，每条 3 次 |
| 一条命令安装 | 没测过 | `npx skills add` 能装上并触发 | 干净环境 |

## 九、需要你拍板

1. **P0-3：** 验证失败按代码指纹自动计数，还是维持 Agent 自报？我建议自动计数。
2. **P0-5：** 先合并 PR #1；`R1_SMOKE_OPERATOR.md` 怎么处理：移出仓库，还是换掉映射表重新随机？
3. **P3-1：** R1 的预算和要测哪几个模型。没有这个数据，P2-1 和 X4 都没法定。
4. **P2-1：** 是否接受"数据达标才做验收技能"这个前提。

## 十、诚实边界

- star 和安装量是今天抓取的数字；安装统计的口径（是否去重）官方没有说明。
- superpowers 的 token 数据来自一个 12 个会话的自测博客，只能作为方向参考。
- "单点不一定比套件好"同样是推断，不是实验结论。只有 R1 能给出我们自己任务上的答案。
- P1-6 的免确认范围、P1-5 的钩子行为都还没在真实宿主上验证。
- 本文所有代码结论都基于 `review-fixes-p0-p2` 分支；`main` 上是 4.1.0，差别很大。

## 来源

- GitHub API（2026-11-17）：mattpocock/skills、addyosmani/agent-skills、obra/superpowers、cloudflare/security-audit-skill、Fission-AI/OpenSpec、github/spec-kit、bmad-code-org/BMAD-METHOD、gsd-build/get-shit-done、affaan-m/ECC 等
- [skills.sh](https://skills.sh/)、[skills.sh FAQ](https://skills.sh/docs/faq)、各技能页
- [I Tested Three Spec-Driven AI Tools（ranthebuilder.cloud）](https://ranthebuilder.cloud/blog/i-tested-three-spec-driven-ai-tools-here-s-my-honest-take/)
- [Claude Code Skills 文档](https://code.claude.com/docs/en/skills)
- [Agent Skills authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Superpowers token usage（lzwjava）](https://lzwjava.github.io/superpowers-token-usage-explained-en)、[superpowers review（mejba.me）](https://www.mejba.me/blog/superpowers-plugin-claude-code-review)、[obra/superpowers#832](https://github.com/obra/superpowers/issues/832)
- 同类工具对比汇总：[developertoolkit.ai](https://developertoolkit.ai/en/ecosystem/frameworks/spec-driven-frameworks/)、[uvik.net benchmark](https://uvik.net/blog/spec-driven-development-benchmark/)
