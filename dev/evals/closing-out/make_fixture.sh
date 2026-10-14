#!/usr/bin/env bash
# 生成 closing-out 评测用的示例仓库：故意埋入改名残留、失效路径与命令、规则文件分离、残留文件。
# 用法: bash dev/evals/closing-out/make_fixture.sh <目标目录>
set -euo pipefail
D="${1:?用法: $0 <目标目录>}"
rm -rf "$D" && mkdir -p "$D/docs" "$D/src" && cd "$D"
git init -q && git config user.email eval@example.com && git config user.name eval

cat > package.json <<'EOF'
{"name": "demo", "scripts": {"dev": "vite", "test": "vitest"}}
EOF
cat > AGENTS.md <<'EOF'
# 项目规则
- 启动：`npm run dev`
- 测试：`npm run e2e`
- 用户相关逻辑在 `src/legacy/user.ts`，不要直接改
EOF
cat > CLAUDE.md <<'EOF'
# Claude 规则
- 启动：`npm run dev`
- 改 src/ 前先用 plan mode
EOF
cat > README.md <<'EOF'
# Demo

调用 `getUser(id)` 获取用户信息。

## 运行
- 开发：`npm run dev`
- 测试：`npm run e2e`

部署流程的完整说明见 [架构文档](docs/arch.md)，接口说明见 [API](docs/api.md)。
EOF
cat > docs/arch.md <<'EOF'
# 架构
src/legacy/ 存放旧的用户模块；新代码在 src/app.ts。
EOF
echo 'export function fetchUser(id: string) { return id }' > src/app.ts
echo '- [x] 把 getUser 改名\n- [x] 删除 legacy' > PLAN.md
git add -A && git commit -qm "fixture: state after rename and legacy removal"
echo 'console.log(1)' > debug_rename.js
echo "fixture ready: $D"
