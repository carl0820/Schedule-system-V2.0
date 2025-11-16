# GitHub Release 创建指南

## 已完成的步骤

✅ 代码已推送到 GitHub  
✅ 版本标签 v1.1.0 已创建并推送  
✅ Release Notes 已准备 (`RELEASE_NOTES.md`)

## 在 GitHub 上创建 Release

### 方法1: 通过 GitHub Web 界面（推荐）

1. **访问仓库**: https://github.com/carl0820/schedule-system-based-on-REST

2. **进入 Releases 页面**:
   - 点击仓库页面右侧的 "Releases" 链接
   - 或直接访问: https://github.com/carl0820/schedule-system-based-on-REST/releases

3. **创建新 Release**:
   - 点击 "Draft a new release" 或 "Create a new release" 按钮

4. **填写 Release 信息**:
   - **Tag**: 选择 `v1.1.0`（应该已经存在）
   - **Title**: `v1.1.0 - Deadlock Detection Fixes and UI Improvements`
   - **Description**: 复制 `RELEASE_NOTES.md` 的内容

5. **发布 Release**:
   - 点击 "Publish release" 按钮

### 方法2: 使用 GitHub CLI（如果已安装）

```bash
# 安装 GitHub CLI (如果未安装)
# Windows: winget install GitHub.cli
# 或访问: https://cli.github.com/

# 创建 release
gh release create v1.1.0 \
  --title "v1.1.0 - Deadlock Detection Fixes and UI Improvements" \
  --notes-file RELEASE_NOTES.md
```

### 方法3: 使用 API（需要 Personal Access Token）

```powershell
# 需要设置环境变量 GITHUB_TOKEN
$token = "your_github_token"
$headers = @{
    "Authorization" = "token $token"
    "Accept" = "application/vnd.github.v3+json"
}

$body = @{
    tag_name = "v1.1.0"
    name = "v1.1.0 - Deadlock Detection Fixes and UI Improvements"
    body = Get-Content RELEASE_NOTES.md -Raw
    draft = $false
    prerelease = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://api.github.com/repos/carl0820/schedule-system-based-on-REST/releases" `
    -Method Post -Headers $headers -Body $body
```

## Release Notes 内容

Release Notes 已保存在 `RELEASE_NOTES.md` 文件中，包含：

- 🐛 Bug Fixes（死锁检测启动问题、时间筛选问题）
- ✨ New Features（机器人管理UI增强）
- 📚 Documentation（新增技术文档）
- 🔧 Technical Improvements（代码优化）
- 📊 Statistics（统计数据）

## 验证 Release

创建 Release 后，可以：

1. 访问 Releases 页面查看: https://github.com/carl0820/schedule-system-based-on-REST/releases
2. 检查 Release 是否包含所有必要信息
3. 验证下载链接是否正常工作

## 下一步

Release 创建后，用户可以：
- 查看详细的更新说明
- 下载特定版本的代码
- 了解新功能和修复的问题

