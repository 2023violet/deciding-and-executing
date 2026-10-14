## deciding-and-executing 4.1.0（R1→R2→R3 本地候选）

- R1: 保留 v4.0.1 三组实验合同和结果边界；只允许真实 Agent 日志进入比较统计。
- R2: 增加只读 `preflight` 和 `coverage` 命令；闸门 B 展示验证命令的已知风险提示；修复阶段②字段说明不一致。
- R3: 添加对新命令的对抗/边界回归及评测使用指南，维持简洁主 Skill 和现有 SOP。
- 限制：尚无真实 Agent 三组实验成绩；新命令不能证明 shell 命令安全，也不能推断验收已充分。

# 更新日志 / Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。本文件是本仓库**版本、验证结果与测试数量的唯一权威位置**，README 与教程只链接到这里。

## [4.0.1] - 2026-10-13（本地候选，待独立复审）

- deciding-and-executing 4.0.1；closing-out 2.0.1。
- WP-01：Git 指纹加入未跟踪文件的真实内容；超大未跟踪文件（大于 32 MiB）拒绝当作可验证指纹；明确 Git 忽略文件不在覆盖范围。
- WP-02：Gate A 将关键假设的实质内容纳入确认哈希，动态状态列不触发重新审批。
- WP-03：Gate B 包括 `first_step`、`if_then`、计划名称等审批相关设置。
- WP-04：review 与完成型 archive 重新验证文件证据的内容和路径状态，status 报告过期文件证据。
- WP-05：`sync` 本次现场运行 closing-out/audit.py；预写 JSON 不再可信，也不能直接指定任意输出路径。
- WP-06：独立的构建/发布检查检查外层 ZIP 的 Unicode 文件名、干净解压和 Markdown 链接；安装包核对源码。
- 验证证据：见 docs/v4.0.1-独立验收记录.md；本条不预先宣称测试通过。

## [4.0.0] - 2026-10-12

一句话：回应外部工程评审（结论 REWORK REQUIRED）。保留架构，把"文档要求 Agent 这样做"改成"脚本能验证就强制、不能验证就明说"。逐条回应见 [docs/内审报告-v4.0.0.md](docs/内审报告-v4.0.0.md)。

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
