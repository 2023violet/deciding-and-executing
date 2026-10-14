# 示例：一次完整档收尾

## 场景
本次会话把 `getUser` 改名为 `fetchUser`，删除了 `src/legacy/`，并把测试命令从 `npm run e2e` 合并进 `npm test`。用户说："今天先到这，收个尾。"

改了名字、删了模块 → 用完整档。

## 1 审计

```
python3 scripts/audit.py --rename getUser=fetchUser
```

主要发现：
- error `stale-names`：README.md 第 2 行仍写 getUser
- error `rule-refs`：AGENTS.md 第 2 行引用 `npm run e2e`，package.json 里已没有
- error `dead-links`：README.md 链接 docs/api.md 不存在
- warn `rule-refs`：AGENTS.md 第 3 行提到 `src/legacy/old.ts`，路径已不存在
- warn `rules-chain`：CLAUDE.md 与 AGENTS.md 同时存在，CLAUDE.md 没有导入 AGENTS.md
- warn `residue`：PLAN.md、debug_x.py、src/app_old.ts
- info `duplicate-lines`：部署说明同一句话出现在 README.md 和 docs/arch.md

## 2 事实差异表

| 事实来源 | 过时位置 | 改法 | 验证 |
|---|---|---|---|
| src/app.ts 导出 fetchUser | README.md:2 | 改为 fetchUser | 再跑审计 stale-names 为 info |
| package.json 的 scripts 只有 dev、test | AGENTS.md:2 | 测试命令改为 `npm test` | 运行 `npm test` 通过 |
| src/legacy/ 已删除 | AGENTS.md:3 | 删除这条规则 | rule-refs 无此项 |
| docs/api.md 从未创建 | README.md:2 | 删除该链接（API 说明在 docs/arch.md） | dead-links 清零 |
| — | CLAUDE.md 与 AGENTS.md 分离 | CLAUDE.md 首行加 `@AGENTS.md`，删去与 AGENTS.md 重复的内容 | rules-chain 无警告 |
| docs/arch.md 是部署说明的权威位置 | README.md 第 3 行 | README 改为一句链接 | duplicate-lines 无此项 |

## 3 路由补查
"删除模块"一类还要查 README 的功能列表与目录结构图：结构图里仍有 `src/legacy/`，一并删除（审计查不到这一处，是按路由表手动搜到的）。

## 6 报告（节选）

> **一句话结论**：README 和规则文件已与 fetchUser 改名、legacy 删除、测试命令合并对齐；下一个 Agent 不会再去跑不存在的 `npm run e2e`。
>
> **删除候选（确认前不会删除）**
> | 路径 | 理由 | 有用内容是否已并入 |
> |---|---|---|
> | PLAN.md | 本次会话的计划草稿，步骤已全部完成 | 是：剩余的一条待办已写进 README "现状与下一步" |
> | debug_x.py | 调试脚本，未被引用 | 不适用 |
> | src/app_old.ts | 改名前的副本，无任何引用 | 不适用 |
>
> **遗留**：Agent 记忆中有一条"测试用 npm run e2e"，与现状矛盾；记忆默认只读，是否更新请你决定。

## 7 清理
用户回复"删吧"后删除三个文件，再跑一次审计：error 0，warn 0。在报告末尾补"清理结果"。
