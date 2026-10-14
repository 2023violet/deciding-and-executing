# Deciding & Executing｜完整统一交付说明

**状态：本地候选，未正式发布（LOCAL_CANDIDATE_READY_FOR_EXTERNAL_AGENT_EVALUATION）。**

本目录是**可以独立导入 GitHub 的统一源码仓库**，不是多个历史 ZIP 的嵌套集合。它完整保留最新两项核心能力，并提供一个**可选的实验性第三 Skill**。

## 版本矩阵

| 组件 | 版本 | 定位 | 路径 |
|---|---|---|---|
| deciding-and-executing | 4.1.0 | 核心候选 | `skills/deciding-and-executing/` |
| closing-out | 2.0.1 | 核心候选 | `skills/closing-out/` |
| independent-verification | 0.2.0 | **实验候选，非默认安装** | `experimental/independent-verification/skill/independent-verification/` |

**只想安装正式核心组合：**只使用 `skills/` 的两个目录，或 `dist/` 内对应的两个 `.skill`。

**试用独立审查：**单独安装 `dist/experimental/independent-verification-v0.2.0-CANDIDATE.skill`，不要在冻结的 R1 对照试验中安装它。

## 安装

从此仓库根目录在 PowerShell 中操作（替换 `$target` 的值）：

```powershell
$target = 'D:\your-project\.agents\skills'  # Codex；Claude Code 改为 .claude\skills
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item -Recurse -Force './skills/deciding-and-executing' $target
Copy-Item -Recurse -Force './skills/closing-out' $target
```

日常明确调用：Codex 使用 `$deciding-and-executing` / `$closing-out`；Claude Code 使用 `/deciding-and-executing` / `/closing-out`。安装前先阅读 [权限边界](skills/deciding-and-executing/references/permissions.md)。

## 项目结构

- `README.md` / `README.en.md`：原 v4.1.0 核心系统使用手册，**原文保留**。
- `skills/`：两个主 Skill 的全部源文件、脚本、参考和资源。
- `dist/`：与源码一致的安装包；`experimental/` 内文件不是稳定发布。
- `experimental/independent-verification/`：v0.2.0 源码、三类案例、检查器、测试和六次配对试验协议；不含评分金标。
- `dev/`：核心回归、打包检查、既有触发评测与历史自评。
- `docs/`：原有说明与验收记录。
- `dev/verify_integrated_delivery.py`：统一包完整性检查（不修改代码或 Git）。

**重要：**R1 冻结的 45 个试验工作区和两组评测金标在总交付 ZIP 的 `operator-private/`，不属于此 GitHub 源码仓库。原来 `R1` 的所有 Agent 运行仍为 `NOT_RUN`。第三 Skill 的 Stage 4 配对试验也仍为 `NOT_RUN`。

## 验证

```bash
python dev/verify_integrated_delivery.py
python -m unittest discover -s dev/tests -q
```

独立验证组件的测试需要操作者另行提供 `EVALUATION/operator_only/` 金标数据；请参阅总包 `README-交付入口.md` 的恢复方式。公开 GitHub 仓库不应包含金标，否则会污染盲评。

## 验收含义

- 核心 83 项历史回归以及第三 Skill 35 项回归已有本地实测记录，本次统一封装**不宣称其通过了真实 Agent 对照试验**。
- `review` / `coverage` 等工具只验证自己能观测到的事实；它们不替代用户批准、真实设备或浏览器测试。
- `verify_cmd` 可能有 Shell 副作用，不能将“校验命令”自动理解为“只读命令”。

**禁止：**未经明确授权，删除现有工作区、推送或发布；也不要将第三 Skill 的实验结果描述为比 Stage 4 更优。
