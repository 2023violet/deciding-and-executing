# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。本文件是本仓库**版本、验证结果与测试数量的唯一权威位置**，README 与教程只链接到这里。

## [6.0.0] - 2026-11-19（本地候选）

- deciding-and-executing 6.0.0；closing-out 2.3.0。
- 一句话：减重。减掉的是 Agent 要读的文字、用户要填的内容和说话方式里的"流程表演"；证据链、确认机制和高风险档的要求不变。依据与每项的衡量、回退条件见 [docs/proposals/2026-11-19-skills-v6-slimming.md](docs/proposals/2026-11-19-skills-v6-slimming.md)。

### 不兼容变更
- **标准档决策卡只要求三节**：目标、编号的成功标准、止损。非目标和关键假设改为选填；写了关键假设仍要按 A1、A2 编号。高风险档仍五节必填。确认哈希没有变，旧工作区的确认保持有效。
- **参考文档重组**：`stage-1-direction.md` … `stage-5-closeout.md` 合并为 `direction.md`（定方向）、`plan-and-execute.md`（计划与执行）、`review-and-close.md`（审查、复盘与收尾）；命令表、证据规则、代码指纹等脚本细节移到 `script.md`。

### 减重
- SKILL.md 从约 1.0 万字符、150 行减到约 5,100 字符、69 行，只留：判断事情有多大（带例子，拿不准选轻的一档）、三条硬规则（照 `next` 走、预览先给用户看、不能验证的写"未验证"）、三行流程表、怎么调用脚本、容易出错的地方。
- 一次标准流程 Agent 读入的技能文字从 24,499 字符（7 个文件）降到约 13,900 字符（4 个文件），**约 −43%**；SKILL.md 里的术语（闸门、证据、指纹、两步确认、token 等）从 54 次降到 12 次。测量脚本：`dev/measure_skill_weight.py`，前后数据在 `dev/eval-runs/v6-baseline/`。

### 新增
- `de.py prove [--shell] -- <命令>`：不需要工作区，运行一条命令并绑定当前代码指纹，输出已验证 / 未通过 / 未验证（非 git）；不写任何文件，并写明"只证明这条命令通过，不等于需求满足"。
- `check plan` 为没有验证命令的步骤推荐仓库里已有的入口（package.json 脚本并按 lock 文件选包管理器、pytest、Makefile、justfile、cargo、go），只建议不改计划；`verify_cmd` 用了只在 Unix 下能用的写法时给警告。
- 独立复核模板与审查文档写明"没发现问题是合法结果，每个问题都要附复现方式"。
- 独立提示词开头加一句话版：8 个常见时刻各一句可以直接复制的话；完整版保留，提问方式与定方向文档一致。
- 触发用例新增 6 条"用词很大、其实是小事"的近似反例。

### 验证
- 环境：Windows 10 + Python 3.13 + Git for Windows（2026-11-20）。`dev/release_check.py` 全部通过，回归测试 195 项（2 项符号链接用例在 Windows 上跳过）。
- 触发评测（`dev/eval-runs/trigger-2026-11-19-v6/`；描述与 5.0.0 最终版相同；本机约 150 个技能同时在场；每条 3 次；额度中断后用 `--resume` 补齐，最终没有出错的运行）：
  - **deciding-and-executing 39/41**：正例 16/18，与 5.0.0 持平；反例 23/23，其中 6 条新增的"用词很大、其实是小事"近似反例全部没有误触发。
  - **closing-out 28/28**：正例 13/13，反例 15/15。
  - 仍未触发的两条与 5.0.0 相同："做着做着偏了"（3 次都直接作答）、英文"部署失败三次"（1/3）。

### 未验证
- 用真实任务测量"读入文字、确认次数、到第一步的时间、小任务是否被误拉进流程"（S0 后半部分）还没做，需要指定任务。
- 真实 Agent 的行为对照（R1）、宿主上的 `allowed-tools` 与会话钩子、macOS，仍未验证。

## [5.0.0] - 2026-11-17（本地候选）

- deciding-and-executing 5.0.0；closing-out 2.2.0。
- 一句话：把"下一步该做什么"从参考文档挪进脚本输出，堵上最后一条靠 Agent 自报的绕过路径（失败计数），给新会话与交接一个由脚本推出的状态视图，并把独立复核做成审查阶段的正式一步。依据与取舍见 [docs/proposals/2026-11-17-skills-optimization-v3.md](docs/proposals/2026-11-17-skills-optimization-v3.md)。

### 不兼容变更
- **`next` 从字符串改为对象** `{cmd, why[, needs_user]}`，并且所有 JSON 输出（成功与拒绝）都有。`cmd` 是可直接运行的 `de.py …` 命令，`null` 表示下一步是人或 Agent 的工作；`needs_user` 表示要先把 preview 给用户看。
- **`status` 的 `current_step` 语义变化**：按 进行中 > 已实现待验证 > 依赖已满足的待做（尚未开工时优先 `first_step`）> 阻塞 > 依赖未满足的待做 选取；不再指向依赖未完成的步骤。
- **验证命令的失败自动计数**（见下）。以前只靠手动 `fail` 的步骤可能更早触发一级升级。

### 新增
- `next` 由脚本从状态推出：标准档且计划无错时建议 `gate AB`；被升级的步骤改过之后先 `replan` 再 `gate B`；到达止损期限交给用户决定；执行期不因证据过期改道，审查期命令证据过期建议 `verify --all`、文件证据过期建议 `reopen`；复盘未写完先写复盘；装了 closing-out 时建议 `closeout`。非默认工作区（包括来自 `DE_WORKSPACE` 的）自动带 `--dir`，路径相对当前目录。
- **失败自动计数**：同一个验证命令上次失败、这次改了代码（指纹不同）仍失败，计一次修复失败。第一次失败是基线；代码没变的重跑、执行期间代码被改动的运行、todo / done 状态的步骤、非 git 项目都不计；通过只重置基线不清零失败次数（`replan --waive` 的"再失败一次就升级"仍成立）；手动 `fail` 与自动计数双向去重。新增的运行时字段只在 `state.json`，计划与闸门哈希不变。
- `status --brief`：给会话开始钩子用的纯文本（≤15 行、约 1,500 字符）。没有工作区时不输出，任何错误最多一行，永远退出 0；执行期不算代码指纹。
- `handoff [--json]`：只读交接摘要。步骤的证据新鲜度由脚本推出（新鲜 / 已过期 / 未验证 / 最近一次失败），另含升级、假设状态与检验步骤、成功标准覆盖、最近 5 条事件、下一步与相关文件路径（只给路径不复制内容）。
- 独立复核：stage-4 把"派一个没有执行上下文的子代理（或新会话 / 其他模型）逐条复核成功标准"定为正式一步（高风险档必须，标准档建议），新增中英文报告模板 `assets/independent-review.md`；`review --independent-report` 记下报告哈希，报告事后被改动或删除则审查结论失效，决策记录写明报告路径。只防事后篡改，不能证明复核者真的独立。
- 新输出（`next.why`、`--brief`、`handoff`）按工作区语言输出中文或英文；旧的拒绝原因仍是中文。
- stage-1 改为"按轮提问"：每轮只问当前就能回答的问题，编号并附推荐答案，用户答"是"即采纳；事实由 Agent 自己查。
- 复盘模板加可选小节"环境改进"（查找、自动检查、工具）。
- 两个技能的 description 加英文触发句；SKILL.md 的 `allowed-tools` 列出只读的 de.py 命令（Claude Code 在调用技能的那一轮内免审批）。
- Claude Code 插件：`.claude-plugin/plugin.json` 与 `marketplace.json`（`claude plugin validate` 通过）；README 增加插件与 `npx skills add` 两种安装方式。
- 会话钩子改为 `de.py status --brief`，matcher `startup|resume|clear|compact`，另给 Codex 版配置；closing-out 轻量档建议附上 `handoff` 输出。
- 触发评测改用 `dev/run_trigger_eval.py`（替代 `run_trigger_eval.sh`，跨平台、不需要 jq、不需要把技能装到全局）：做法沿用官方 skill-creator 的 run_eval——临时命令文件承载被测描述，从 `claude -p` 的流式输出判断是否调用；记录本机全局技能与插件等运行环境。触发用例补充英文正例与近似反例（deciding-and-executing 35 条、closing-out 28 条）。

### 仓库卫生
- `experimental/independent-verification/R1_SMOKE_OPERATOR.md` 删除了被提交进仓库的操作者分组映射表；映射只放在已忽略的私有文件里。旧的 9 个 Trial 分组已在 git 历史中暴露，正式运行前必须重新随机（未改写 git 历史）。
- `release_check.py` 新增两项：会被打包的文件里不得出现评测私有材料；`plugin.json` 版本与技能版本一致。

### 验证
- 环境：Windows 10 + Python 3.13 + Git for Windows（2026-11-17）。
- `dev/release_check.py --outer-zip <临时目录>/deciding-and-executing-v5.0.0.zip` 全部通过：两个技能结构校验、CHANGELOG 版本、`dist/*.skill` 与源码逐文件一致、插件版本一致、无评测私有材料、回归与对抗测试 174 项通过（2 项符号链接用例因权限跳过，约 320 秒）、自审计 error 0 / warn 0、外层 ZIP 解压后 124 个文件逐一比对且静态审计 error 0。
- 新增 65 项测试：`test_v5_next`（含一条照着 `next.cmd` 从 `gate AB` 走到 `purge` 的全流程）、`test_v5_autofail`、`test_v5_brief_handoff`（含进程内统计代码指纹调用次数）、`test_v5_review_report`。失败计数的三个关键条件（同指纹不计、手动去重、基线）和 4.2 的两条绕过修复都做了变异检查：改回去，对应测试会失败。
- `claude plugin validate`（Claude Code 2.1.283）对 `marketplace.json` 与 `plugin.json` 均通过。

### 未验证
- 宿主上的 `allowed-tools` 免审批、SessionStart 钩子注入（Claude Code 与 Codex）、插件与 `npx skills add` 在干净环境的安装、macOS。
- 真实 Agent 的行为对照（R1）仍未运行。
- **触发评测（2026-11-17～18，Claude Code 2.1.283，默认模型，本机约 150 个技能与 19 个插件同时在场，每条 3 次，阈值 0.5）**：原始数据与每次运行的工具调用顺序在 `dev/eval-runs/trigger-2026-11-17/`。
  - **基线（4.2 风格描述）**：反例全部正确（deciding-and-executing 17/17，closing-out 15/15）；正例偏弱（8/18、6/13）。
  - **迭代 1（本版最终描述）**：把触发时机写成"在回答或动手之前先调用本技能，不要直接给建议或直接开始改"，补用户原话（"帮我理一理""从头到尾检查一遍还有什么坑""查还有哪些文档提到被删的东西"），closing-out 写明与通用整理做法的区别（只读审计脚本）。结果：**deciding-and-executing 33/35（正例 16/18，反例 17/17）；closing-out 28/28（正例 13/13，反例 15/15）**，没有新增误触发。数据在 `dev/eval-runs/trigger-2026-11-18-iter1/`。
  - 迭代 1 仍未触发：deciding-and-executing 的"做着做着偏了"（3 次都直接作答）和英文的"部署失败三次"（1/3）。
  - 注意：用例是写描述时就能看到的同一批，没有按 6:4 分训练集与验证集，存在过拟合风险；正例提升应在新用例上复核。
  - 以下是基线一轮的失败分析：
  - deciding-and-executing 没触发时，模型多半直接作答（方向类问题）或直接动手（Glob / Read / PowerShell，执行类问题），只有 1 次被别的技能（superpowers:systematic-debugging）抢走。
  - closing-out 没触发时，约一半输给本机已装的同类技能 `neat-freak`，其余是模型直接 Grep / Glob 开始改。
  - 前两轮作废并归档：`run1-detection-bug/`（运行器把"先调用别的技能再作答"记成了不明结果），`run2-quota-exhausted/`（额度用尽后的错误结果被当成未触发）。运行器现已记录完整调用顺序、把出错运行排除在触发率之外、连续出错时停止，并支持 `--resume` 只补测缺的部分。
  - 已确认的环境问题：本机约 150 个技能超出技能列表预算，新技能只显示名字、不显示描述。运行器默认把子进程的 `SLASH_COMMAND_TOOL_CHAR_BUDGET` 放大到 200000，`--listing-chars 0` 可测默认预算下的真实表现。从桌面应用里启动时，运行器会去掉应用传下来的 `CLAUDE_CODE_*` / `ANTHROPIC_BASE_URL`，否则子进程报 "Not logged in"。

## [4.2.0] - 2026-11-16（本地候选）

- deciding-and-executing 4.2.0；closing-out 2.1.0。
- 一句话：按一次全面评审的结论分三轮整改——P0 修掉会让人第一次上手就卡住的问题，P1 提高可信度并减少确认次数，P2 收拾表达与维护成本。工作区格式有变化（新增 `state.json`），旧工作区自动迁移。

### P0：落地阻断项
- 统一脚本调用说明：文档里的 `de.py …` / `audit.py …` 是简写，SKILL.md 写明 Claude Code（`${CLAUDE_SKILL_DIR}`）、其他宿主与 Windows（`python` / `py -3`）下的实际写法；原先 14 处 `python3 scripts/de.py` 在项目根目录执行会找不到脚本。
- 占位符改为白名单识别：只有模板里原样出现的 `[…]` 才算"未填写"。此前任何含方括号的内容都会被当成占位符——成功标准"返回 [400]"被静默丢弃、步骤标题"修复 [P1] …"被判缺少标题。
- 新增 `verify_argv`（参数数组，不经 shell 直接执行，按 PATH/PATHEXT 查找程序），与 `verify_cmd` 二选一；找不到程序记为退出码 127 而不是崩溃。gate B 预览用 `verify_command` / `runs_via_shell` 展示命令。旧计划不含该字段时批准哈希不变。
- `verify --all` 在步骤之间复用代码指纹，少算一半指纹。

### P1：可信度与易用性
- **运行时状态与计划分离**：`plan.json` 只放 Agent 编写的计划结构；状态、证据、闸门、审查结论移到只由脚本写入的 `state.json`，每次写入的摘要记在 `events.jsonl`。`plan.json` 里的运行时字段被忽略并在 `status` 中提示；`state.json` 在脚本之外被修改时 `status` 报警。旧工作区在下一次写入命令时自动迁移，已有的闸门批准保持有效。README 的"不能保证"表补上"不防有意同时伪造两份文件"。
- **收窄触发、减少确认**：description 改为面向跨会话、返工代价高、需要交付证据的开发任务，排除一次会话内能做完的普通开发；标准档新增 `gate AB`（一次确认决策卡与计划，高风险档拒绝）；新增 `closeout`（archive + sync 一步完成，先预览后 `--apply`）。
- **以开发任务为主线**：新的端到端示例改为"订单服务从 SQLite 迁到 PostgreSQL"（`verify_argv`、`gate AB`、一级升级、不可逆步骤、`coverage`、`closeout`）；原"辞职做点单小程序"示例改名为 `example-decision.md`，用于非代码的重要决定。
- **英文支持**：`init --lang en` 生成英文模板；决策卡与复盘的章节、字段、结论（go / go with changes / drop）、归档结局（done / stopped / abandoned）接受英文；英文工作区生成英文决策记录。脚本提示信息仍是中文。
- **多工作区**：新增 `list`；`--dir` 可由环境变量 `DE_WORKSPACE` 提供；`status` 列出其他工作区；代码指纹排除所有工作区（与 `audit.py` 一致），并行的两件事互不让对方的证据过期。
- `audit.py` 从 `state.json` 读取步骤进度（兼容旧工作区）。
- **未完成**：真实 Agent 的触发与行为评测仍未运行——它需要把技能安装到全局目录并发起上百次 Claude Code 调用，留给维护者决定何时运行（`dev/run_trigger_eval.sh`）。

### P2：表达与可维护性
- 用户可见的文档去掉研发阶段代号（R1/R2/R3）；README 不再复制命令表，统一链接到 SKILL.md 第 4 节（单一权威位置）。
- 版本号只写在各 SKILL.md 的 `metadata.version`：`de.py` 运行时读取，`build_release.py` / `release_check.py` 由它推出发布包名，不再在三处硬编码。
- 历次评审与验收记录移到 `docs/history/`，`docs/` 只留教程与演进路线；README.en 的版本徽章（原为 4.0.1）与中文版一致。
- `audit.py` 的命令检查改为可扩展的 `RUNNERS` 表，新增 `just` 配方检查。
- 可选的 Claude Code SessionStart 钩子：新会话开始时自动运行 `status`（`references/permissions.md`）。
- 工作区查找结果在一次命令内缓存，`status` 少跑一次 git。
- 未做：实验性技能 `experimental/` 是否拆到独立仓库、`dist/*.skill` 是否改为只随发布提供，留给维护者决定。

### 绕过修复（2026-11-17 复现后修复）
- 不可逆步骤先标为 `blocked` 再进入 `in_progress` 可以跳过确认；现在从 `todo` 或 `blocked` 进入执行都要两步确认。
- 闸门通过后在决策卡里调高"修复失败次数上限"，闸门不失效，升级也不再触发；现在上限进入闸门 A 的哈希（取默认值 2 时不进入，沿用默认值的旧工作区闸门不受影响），gate A 预览会显示上限。重新确认之前，`fail` 按已确认的上限与卡片当前值中较严的一个判断是否升级，放宽不能先用后批。
- SKILL.md 补一句：非 git 项目可用，但证据无法绑定当前代码，`purge` 会拒绝删除。

### 仓库一致性清理（不改变工作流契约）
- `de.py review --verdict pass` 把同一批过期证据重复报告两次。
- `de.py archive` 完成后的提示仍要求手动保存审计 JSON（v4.0.1 起 `sync` 会现场重跑审计）；`worked-example.md` 同样已更正。
- `de.py preflight` 把重命名项的旧路径当成一条额外改动（且路径被截断）。
- `audit.py`、`de.py` 读取 `ARCHIVED` / `plan.json` 时未关闭文件句柄；`ARCHIVED` 不是对象时会抛异常。
- `release_check.py` 的外层 ZIP 比对把 `.git/` 也算进"应有文件"，在 git 检出里必然失败；现与 `build_release.py` 共用同一套排除规则。
- `score_paired.py`（实验性）：清单为空时误报 `PAIRED_EXPLORATORY_RESULTS`；读取 JSON 未指定 UTF-8。
- `make_fixture.sh` 生成的 `PLAN.md` 含字面 `\n`；`run_trigger_eval.sh` 不再依赖 `bc`。
- `validate_skill.py` 兼容 CRLF 换行；用法示例改为正确的 `skills/<名称>` 路径。
- 新增 `.gitattributes`（LF 检出、`.skill` 按二进制处理），避免 Windows 克隆后 dist 与源码按字节比对失败。
- 测试在 Windows 上的 3 处可移植性问题：只读 `.git` 对象无法删除、文件名含双引号、无权限创建符号链接（改为跳过）。

- 把 SKILL.md、stage-2/stage-4、README 中以"v4.0.1 补充""R2 补充"追加在文末的段落并入正文对应位置（closing-out 自己的规则：就地改写，不追加"更新"段落）；README 命令表补上 `preflight`、`coverage`；闸门失效条件补上关键假设、计划名称、`first_step`、`if_then`。
- 重新打包 `dist/deciding-and-executing.skill` 与 `dist/closing-out.skill`。

### 验证
- 环境：Windows 10 + Python 3.13 + Git for Windows（2026-11-16）。
- 整改前基线：`python -m unittest discover -s dev/tests` 83 项、3 项报错（均为测试在 Windows 上的可移植性问题）。
- 整改后：`dev/release_check.py --outer-zip <临时目录>/deciding-and-executing-v4.2.0.zip` 全部通过——两个技能结构校验、CHANGELOG 版本、`dist/*.skill` 与源码逐文件一致、回归与对抗测试 109 项通过（1 项符号链接用例因权限跳过，约 150–200 秒）、自审计 error 0 / warn 0、外层 ZIP 解压后 116 个文件逐一比对且静态审计 error 0（2026-11-17 绕过修复后重跑）。这是外层 ZIP 检查第一次在 git 检出里跑通（此前它把 `.git/` 算进应有文件，必然失败）。
- 新增测试覆盖：方括号内容、`verify_argv`（含找不到程序、与 `verify_cmd` 冲突、旧计划批准不失效）、`state.json` 拆分（伪造字段被忽略、手改被发现、旧工作区迁移）、`gate AB`、`closeout`、多工作区指纹、`DE_WORKSPACE`、英文决策卡全流程、`just` 配方检查、两条绕过路径（经 `blocked` 跳过不可逆确认、事后放宽失败上限）。这两条修复各做了变异检查：把修复改回去，对应测试会失败。
- 实验性技能：`test_review_checks` 与 `test_v02_contract` 30 项通过（2 项符号链接用例跳过）；`test_paired_eval` 仍需操作者提供私有金标。
- 未运行：macOS；Claude Code / Codex 上的真实触发与行为评测；宿主审批规则与 SessionStart 钩子的实机验证。

## [4.1.0] - 2026-10-14（R1→R2→R3 本地候选）

- deciding-and-executing 4.1.0；closing-out 2.0.1 不变。
- R1：保留 v4.0.1 三组实验合同和结果边界；只允许真实 Agent 日志进入比较统计。
- R2：增加只读 `preflight` 和 `coverage` 命令；闸门 B 展示验证命令的已知风险提示；修复阶段②字段说明不一致。
- R3：添加对新命令的对抗/边界回归及评测使用指南，维持简洁主 Skill 和现有 SOP。
- 验证：83 项回归在 Linux 上通过（见 [R1-R2-R3 验收报告](docs/history/R1-R2-R3-验收报告.md)）。
- 限制：尚无真实 Agent 三组实验成绩；新命令不能证明 shell 命令安全，也不能推断验收已充分。

## [4.0.1] - 2026-10-13（本地候选，待独立复审）

- deciding-and-executing 4.0.1；closing-out 2.0.1。
- WP-01：Git 指纹加入未跟踪文件的真实内容；超大未跟踪文件（大于 32 MiB）拒绝当作可验证指纹；明确 Git 忽略文件不在覆盖范围。
- WP-02：Gate A 将关键假设的实质内容纳入确认哈希，动态状态列不触发重新审批。
- WP-03：Gate B 包括 `first_step`、`if_then`、计划名称等审批相关设置。
- WP-04：review 与完成型 archive 重新验证文件证据的内容和路径状态，status 报告过期文件证据。
- WP-05：`sync` 本次现场运行 closing-out/audit.py；预写 JSON 不再可信，也不能直接指定任意输出路径。
- WP-06：独立的构建/发布检查检查外层 ZIP 的 Unicode 文件名、干净解压和 Markdown 链接；安装包核对源码。
- 验证证据：见 [docs/history/v4.0.1-独立验收记录.md](docs/history/v4.0.1-独立验收记录.md)；本条不预先宣称测试通过。

## [4.0.0] - 2026-10-12

一句话：回应外部工程评审（结论 REWORK REQUIRED）。保留架构，把"文档要求 Agent 这样做"改成"脚本能验证就强制、不能验证就明说"。逐条回应见 [docs/history/内审报告-v4.0.0.md](docs/history/内审报告-v4.0.0.md)。

- deciding-and-executing 4.0.0
- closing-out 2.0.0

### 安全修复
- **P0：`archive --remove-workspace` 可删除项目根目录（含 .git）。** 复现确认后移除该参数。删除改为独立的 `purge`，前提依次为：工作区位于项目内且不是项目根、不是符号链接、带 `.de-workspace` 标记、只含已知文件、已归档、已同步、已提交到 git（可恢复），并经两步确认（token 绑定文件清单）。
- `ARCHIVED` 标记里的路径不再被信任：必须是项目内、工作区外、由 de.py 生成的决策记录。
- `--docs-dir` 限制在项目内；`--dir` 必须是项目根之下的子目录。
- 在子目录运行不再另建工作区（统一定位到 git 仓库根）。

### 新增
- 风险档位：不走流程 / 轻量（不建工作区）/ 标准 / 高风险。
- 闸门 A、B 改为两步确认并记录内容哈希；决策卡核心内容或计划结构改动后自动失效，执行类命令被拒绝。
- 步骤状态机与合法转换；`needs_replan` 状态；`replan`（要求步骤已修改，或两步确认记录豁免）；`reopen`（旧证据归档、审查作废）。
- 证据分为命令 / 文件 / 文字三类：有 `verify_cmd` 的步骤由脚本当场执行；命令证据绑定代码指纹，代码变化即过期；高风险档拒绝文字证据。
- `verify --all`、`review`（审查结论绑定代码与计划）、`sync`（核对审计无 error、完整、对应当前代码）。
- 计划字段 `verify_cmd`、`depends_on`、`covers`、`irreversible`、`spent_h`；成功标准覆盖检查、依赖成环检查、类型校验。
- 结构化止损条件（触发状态 / 期限 / 动作）；结论按枚举解析。
- 事件日志 `events.jsonl`：先写事件再写计划，中断可被 `status` 发现。
- `references/permissions.md`：Claude Code 与 Codex 的宿主审批规则。
- audit.py：`complete`、`evidence_level`、`limits`、`fingerprint` 字段；按目录计算有效规则链；`--exclude`；git 输出按 NUL 分隔解析。
- closing-out 报告按证据层级（静态审计 / 变更影响分析 / 源码事实核查 / 运行验证）分别写结论。
- `dev/release_check.py`：结构、测试、dist 与源码一致性、CHANGELOG、自审计一次跑完。

### 修复（自审发现，评审未列出）
- 新名字是旧名字前缀时（fetchUserData→fetchUser）旧名残留漏报。
- 规则路径检查用 `lstrip("./")` 会把 `.github` 变成 `github`。
- 测试未与使用者 git 全局配置隔离：开启提交签名时 32 项中 12 项报错。
- 截断测试缺乏区分度（变异测试发现），已重写。

### 不兼容变更
- 移除 `archive --remove-workspace`；决策卡格式（结论、编号标准、止损三行）与计划字段有变化。迁移步骤见 README"从 3.x 升级"。

### 验证
- 结构校验：两个技能通过 `dev/validate_skill.py`（PyYAML 解析）与 skill-creator `quick_validate`。
- 回归与对抗测试：63 项全部通过（test_de 42 项、test_audit 21 项），本机约 37 秒；已与 git 全局配置隔离。
- 变异测试：对 8 处关键约束逐一注入缺陷，全部被测试发现（详见内审报告）。
- 端到端：在隔离仓库中走完 init → gate A/B → step/verify → review → archive → audit → sync → purge。
- 发布检查：`dev/release_check.py` 全部通过（结构、CHANGELOG、dist 与源码逐文件一致、测试、自审计 error 0 / warn 0）。
- **未完成**：Agent 行为评测（dev/evals 中 15 个用例）与触发率测试未在真实 Agent 上运行；Windows / macOS 未测试。

## [3.0.0] - 2026-10-12

一句话：从"想清楚 → 做出来"扩展为"想清楚 → 做出来 → 收拾干净"。

### 新增
- **新技能 `closing-out` 1.0**：工作结束后让 README、docs、规则文件、决策记录重新等于代码现状。
  - 轻量档（每次会话结束）与完整档（里程碑、发布、交接、改名或删模块后）。
  - 只读审计脚本 `scripts/audit.py`，检查项：`rules-chain`（CLAUDE.md / AGENTS.md 加载关系与体积上限）、`rule-refs`、`doc-commands`、`dead-links`、`stale-names`、`duplicate-lines`、`residue`、`decision`。
  - 变更类型路由表、知识放置规则、报告模板、完整示例。
  - 删除只出候选清单，用户在看到报告后明确确认才执行。
- **deciding-and-executing ⑤ 收尾归档（闸门 D）**：`de.py archive` 把决策卡、执行摘要、复盘合并为 `docs/decisions/YYYY-MM-DD-名称.md`；默认只预览，`--apply` 写入，`--remove-workspace` 删除工作区（须用户确认）。
- 复盘模板 `assets/retro.md`，新增"教训去向"一栏。
- `de.py status` 新增阶段 `closeout` 与 `archived`。
- 第六段独立提示词 P6：收尾与知识同步。
- 两个 Codex / ChatGPT 配置 `agents/openai.yaml`。

### 变更
- 仓库结构改为 `skills/`（可安装）+ `dev/`（开发测试）+ `docs/` + `dist/`（打包产物）。
- deciding-and-executing 描述增加"项目结束要结案"，并明确排除"单纯的文档同步与仓库整理"，与 closing-out 划清触发边界。
- Gotchas 增加两条：项目结束不结案；决策卡写成系统说明。
- 评测集按技能分目录；触发测试脚本改为 `run_trigger_eval.sh <技能名> <查询文件>`。

### 修复（来自第一轮按技能执行的评测）
- 审计未检查 README / docs 里的 `npm run` / `make` 命令 → 新增 `doc-commands`。
- 残留文件（如 PLAN.md）被同时报为 `stale-names` 错误 → 残留文件只按 `residue` 报告。
- 仓库只有一个提交时 `changed_files` 为空 → 改用 `git diff-tree --root`。

### 验证
- 结构校验：两个技能均通过 `dev/validate_skill.py` 与 skill-creator 的 `quick_validate`。
- 回归测试：`test_de.py` 18 项、`test_audit.py` 14 项，全部通过。
- 按技能执行的评测（作者自评，独立性有限）：closing-out「改名与删模块」6/6；deciding-and-executing「方向→计划」5/5（沿用 2.0 结果）。
- 自我收尾：用 closing-out 审计本仓库自身，结果见 `dev/eval-runs/iteration-1/self-audit.json`。
- **尚未进行**：有/无技能对比评测、触发率测试（需在 Claude Code 中运行，见 README）。

## [2.0.0] - 2026-10-10

### 新增
- 四阶段 SOP（定方向、计划、执行、审查与复盘），每阶段有进入条件、清单、退出闸门、产出。
- 闸门脚本 `de.py`：`init`、`check card|plan`、`status`、`step`（无证据拒绝 done）、`fail`（达到阈值提示升级）、`show`。
- 两级升级：一级回计划，二级回定方向。
- Gotchas 十条、端到端示例、五段独立提示词、设计依据。
- 评测集、触发测试集、结构校验器、脚本回归测试。

### 变更
- 描述只写触发场景与边界，不再概括流程。

### 验证
- `test_de.py` 11 项通过；结构校验通过；「方向→计划」用例自评 5/5。

## [1.0.0] - 2026-10-10

- 初版：按阶段路由的 SKILL.md、四个阶段参考文件、三个交接模板。无脚本、无评测。
