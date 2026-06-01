#!/bin/sh
# 车机大模型服务代理 - adb shell 测试脚本
#
# 用法:
#   sh test_llm_proxy.sh <base_url>
#
# 示例:
#   sh test_llm_proxy.sh https://can-rolls-reid-event.trycloudflare.com
#   sh test_llm_proxy.sh http://localhost:8900

BASE_URL="${1:-http://localhost:8900}"

# https 地址需要 -k 跳过SSL校验（车机时间不准导致）
SSL_FLAG=""
echo "${BASE_URL}" | grep -q "^https" && SSL_FLAG="-k"

echo "===================================="
echo "  车机大模型服务代理 - 测试脚本"
echo "  base_url: ${BASE_URL}"
echo "===================================="
echo ""

echo "--- 测试 /v1/chat/completions (非流式) ---"
curl ${SSL_FLAG} -s "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"bailian/glm-5","messages":[{"role":"user","content":"你好"}]}'
echo ""
echo ""

echo "--- 测试 /v1/chat/completions (流式) ---"
curl ${SSL_FLAG} -s "${BASE_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"bailian/glm-5","messages":[{"role":"user","content":"1+1等于几"}],"stream":true}'
echo ""
echo ""

echo "===================================="
echo "  测试完成"
echo "===================================="