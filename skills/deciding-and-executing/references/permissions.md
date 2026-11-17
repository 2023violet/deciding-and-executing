# 宿主配置：审批规则与可选的会话钩子

`de.py` 的两步确认只能保证"内容展示过且没变"，不能保证"是人点了同意"。脚本分辨不了按回车的是人还是 Agent。唯一能让真人介入的，是运行 Agent 的宿主（Claude Code、Codex）在执行命令前弹出的审批。

**高风险档位必须配置；标准档位建议至少配置 purge。**

## 需要人工审批的命令

| 命令 | 为什么 |
|---|---|
| `de.py purge --confirm …` | 删除工作区 |
| `de.py step … --confirm …` | 开始一个标记为不可逆的步骤 |
| `de.py replan … --waive …` | 不改计划就继续一个反复失败的步骤 |
| `de.py gate … --confirm …` | 确认方向或计划（计划里含将要执行的验证命令） |
| `de.py review … --confirm …` | 确认交付结论 |

只读命令（`status`、`status --brief`、`check`、`show`、`list`、`preflight`、`coverage`、`handoff`）和不带 `--confirm` 的预览不需要审批。

## Claude Code

在项目的 `.claude/settings.json`（团队共享）或 `~/.claude/settings.json`（个人）里加入：

```json
{
  "permissions": {
    "ask": [
      "Bash(*de.py purge --confirm*)",
      "Bash(*de.py step * --confirm*)",
      "Bash(*de.py replan * --waive*)",
      "Bash(*de.py gate * --confirm*)",
      "Bash(*de.py review * --confirm*)"
    ]
  }
}
```

要点（来自 Claude Code 权限文档）：
- 规则按 deny → ask → allow 的顺序匹配，匹配到 ask 就会弹出审批，即使有更具体的 allow 规则。
- ask 规则对复合命令里的子命令同样生效，自动模式下也会弹出审批。
- `bypassPermissions` 模式会跳过所有审批，在这种模式下以上规则无效。
- 规则匹配的是命令文本，换一种写法（例如 `sh -c "…"`）可能匹配不到。所以它是**防止 Agent 照常调用时绕过人**的机制，不是安全边界。

## Codex

在 `~/.codex/rules/default.rules`（个人）或受信任项目的 `<repo>/.codex/rules/` 里加入。Codex 按参数列表做**前缀精确匹配**，所以要写出脚本的实际路径（把下面的路径换成你的安装位置）：

```
prefix_rule(
    pattern = ["python3", "/Users/you/.agents/skills/deciding-and-executing/scripts/de.py", ["purge", "replan", "gate", "review", "step"]],
    decision = "prompt",
    justification = "de.py 的确认类命令需要人工审批",
)
```

要点（来自 Codex rules 文档）：
- 多条规则同时匹配时取最严格的决定：forbidden > prompt > allow。
- 可以用 `codex execpolicy check --pretty --rules <文件> -- <命令>` 检查规则是否生效。
- rules 功能标注为实验性；文档没有说明在 never 审批策略下 prompt 是否仍然生效，请在你的配置下实测。
- 上面的前缀会让这几个子命令的预览调用也弹出审批。嫌打扰的话，只保留 `purge`。
- 前缀里的解释器名必须和实际调用一致：Windows 上通常是 `python` 或 `py`，需要为实际使用的写法各加一条规则。

## 可选：新会话开始时自动显示状态

"新会话先运行 `status`"是最容易被跳过的一步。`de.py status --brief` 专为会话开始钩子设计：
- 输出不超过 15 行的纯文本：阶段、闸门、当前步骤、升级、下一步命令、其他工作区；
- 没有工作区时什么都不输出；
- 任何错误最多输出一行，永远退出 0，不会打断会话。

钩子命令因此不需要 `test -f` 之类的判断，Windows 和 macOS 的写法只差解释器名。

**Claude Code**：在 `.claude/settings.json`（项目）或 `~/.claude/settings.json`（个人）里加入。路径换成你的安装位置；Windows 上用 `python`，macOS / Linux 用 `python3`。

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/deciding-and-executing/scripts/de.py status --brief"
          }
        ]
      }
    ]
  }
}
```

`compact` 让上下文被压缩后重新注入一次状态。Claude Code 会把钩子的标准输出放进上下文，单次上限约 10,000 字符，`--brief` 远低于这个上限。

**Codex**：在 `~/.codex/hooks.json`（个人）或受信任项目的 `<repo>/.codex/hooks.json` 里加入同样结构的配置。Codex 的 SessionStart matcher 与 Claude Code 相同，默认注入上限约 2,500 token。

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          { "type": "command", "command": "python3 /Users/you/.agents/skills/deciding-and-executing/scripts/de.py status --brief" }
        ]
      }
    ]
  }
}
```

配好后开一个新会话，确认 `[de] …` 这几行出现在上下文里。没有出现就不要依赖它，仍按 SKILL.md 先手动运行 `status`。本技能没有在真实宿主上验证过这两份配置。

## 配好之后怎么验证

以下针对审批规则：

1. 在一个测试仓库里走到 purge 预览，让 Agent 带 `--confirm` 执行。
2. 应该看到宿主弹出审批；拒绝后命令不执行，`.decision/` 仍然存在。
3. 没有弹出审批，说明规则没有生效，不要依赖它。
