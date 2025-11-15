#!/bin/bash
# 快速保存版本并推送到 GitHub
# 使用方法: ./save_version.sh "提交信息"

if [ -z "$1" ]; then
    echo "错误: 请提供提交信息"
    echo "使用方法: ./save_version.sh \"提交信息\""
    exit 1
fi

MESSAGE="$1"

echo "正在保存版本..."

# 添加所有更改
git add -A

# 检查是否有更改
if [ -z "$(git status --porcelain)" ]; then
    echo "没有需要提交的更改"
    exit 0
fi

# 提交更改
echo "提交更改: $MESSAGE"
git commit -m "$MESSAGE"

if [ $? -ne 0 ]; then
    echo "提交失败！"
    exit 1
fi

# 推送到 GitHub
echo "推送到 GitHub..."
git push origin main

if [ $? -eq 0 ]; then
    echo "✓ 版本已成功保存并推送到 GitHub！"
else
    echo "✗ 推送失败！"
    exit 1
fi

