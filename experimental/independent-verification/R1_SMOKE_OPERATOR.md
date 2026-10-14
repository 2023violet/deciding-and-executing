# R1｜3 案例 × 3 组真实 Agent 首轮烟测（执行准备）

**状态：READY_TO_RUN / NOT_RUN。** 本环境无 `claude` 或 `codex` CLI，未执行任何 Agent Trial；不得把本文件视为实验成绩。

## 实验版本与边界

- 继续使用已有 `Deciding-Executing-R1-Prepared-Trials.zip` 以及 `Deciding-Executing-R1-Evaluation-Kit.zip`。**不重建**冻结案例、任务合同、私有 oracle 和预注册阈值。
- 固定版本是 R1 原协议使用的 `deciding-and-executing v4.0.1 / closing-out v2.0.1`；不要将 v4.1.0、新的 independent-verification 原型安装进这些试验，避免破坏干预条件。
- 选定开发集 **T01（低风险快速修复）**、**T06（安全路径穿越）**、**T11（文档事实漂移）**。UI 试验不在冻结的 R1 15 案例中，不把本次原型 UI 夹具加入 R1 分母。
- 对应三组各 3 条，总共 **9 Trial**；从 `manifest.json` 原顺序过滤，不能改变每条 Trial 原有的编号、分组或原始任务文本。操作者自己留存分组映射，盲审者不得看到。

## 操作者私有映射（不要暴露给 Agent / 盲审评分人）

| 原顺序 | Case | Trial ID | Arm |
|---:|---|---|---|
| 4 | T01 | R004-fbce898758 | skills |
| 5 | T06 | R005-da73edfac4 | skills |
| 7 | T01 | R007-f7d27caf83 | native |
| 9 | T11 | R009-f63b522161 | contract |
| 10 | T06 | R010-693093d45c | native |
| 21 | T06 | R021-d7de47f984 | contract |
| 26 | T01 | R026-17fe7448d6 | contract |
| 40 | T11 | R040-4aa635abf8 | skills |
| 42 | T11 | R042-8c382883e2 | native |

**防泄漏：** 只有当前 Trial 的 `workspace` 和 `task.md` 暴露给执行 Agent；`private_evaluator/`、`manifest.json`、本映射、所有其他 Trial 与标准答案绝不能挂入执行 Agent 的可读目录。现有 R1 预置试验包含 Git 仓库，仅在可信隔离 VM/容器中使用。不要把整个 ZIP 当作 Agent 工作目录。

## 执行与评分

1. 预先记录同一模型/宿主版本、权限、操作系统、时间预算、上下文配置和是否启用全局 Skills（必须隔离全局配置）。
2. 依上表的**原随机顺序**逐一打开隔离 Trial 工作区。传入原 `task.md`，不得改写；从全新会话执行。
3. 记录完整工具调用/命令轨迹、实际耗时、人工干预、成本和是否宣称完成。写入相应的 `run_metadata.json` 与 `transcript.txt`；必要人工复核填 `review.json`。
4. 在隔离的评分环境依原版 `OPERATOR_GUIDE.md` 运行 `r1_eval.py grade`、`summary`。无安全沙箱时不加 `--allow-exec`，功能检查保留 `NOT_VERIFIED`。
5. 报告配对的 C-B 与 B-A 结果。9 条试验只构成流程烟测，**不能代替原预注册的 15 案例结论门槛**。如某条执行失败，不得替换案例凑成功率。

## 预检发现

- 预置 `results.json` 中 45 条均是 `NOT_RUN`，`summary.json` 为 `INSUFFICIENT_PAIRED_DATA`。
- 本运行环境 `claude`、`codex` 未安装，因此本轮真实 Agent 执行进度 **0/9**。
