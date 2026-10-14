#!/usr/bin/env bash
# 触发率测试：每条查询跑 RUNS 次，统计技能被调用的比例。
# 需要 Claude Code（claude CLI）和 jq，且技能已安装到 ~/.claude/skills/ 或项目 .claude/skills/。
# 用法: bash dev/run_trigger_eval.sh <技能名> <trigger_evals.json> [RUNS]
# 例:   bash dev/run_trigger_eval.sh closing-out dev/evals/closing-out/trigger_evals.json 3
# 判定: should_trigger=true 的查询触发率需 >= 0.5；false 的需 < 0.5。
set -euo pipefail
SKILL_NAME="${1:?用法: $0 <技能名> <trigger_evals.json> [RUNS]}"
QUERIES_FILE="${2:?用法: $0 <技能名> <trigger_evals.json> [RUNS]}"
RUNS="${3:-3}"

check_triggered() {
  claude -p "$1" --output-format json 2>/dev/null \
    | jq -e --arg skill "$SKILL_NAME" \
      'any(.. | objects; .type? == "tool_use" and .name? == "Skill" and ((.input.skill? // "") | endswith($skill)))' \
      > /dev/null 2>&1
}

count=$(jq length "$QUERIES_FILE")
pass=0
for i in $(seq 0 $((count - 1))); do
  q=$(jq -r ".[$i].query" "$QUERIES_FILE")
  want=$(jq -r ".[$i].should_trigger" "$QUERIES_FILE")
  hits=0
  for _ in $(seq 1 "$RUNS"); do
    if check_triggered "$q"; then hits=$((hits + 1)); fi
  done
  rate=$(echo "scale=2; $hits / $RUNS" | bc)
  ok=$( { [ "$want" = "true" ] && [ $((hits * 2)) -ge "$RUNS" ]; } || { [ "$want" = "false" ] && [ $((hits * 2)) -lt "$RUNS" ]; } && echo PASS || echo FAIL)
  [ "$ok" = PASS ] && pass=$((pass + 1))
  printf '%s\t%s\t期望=%s\t%s\n' "$ok" "$rate" "$want" "$q"
done
echo "通过 $pass / $count"
