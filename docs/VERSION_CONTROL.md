# 版本控制使用说明

## 快速保存版本

### Windows (PowerShell)

```powershell
.\save_version.ps1 "你的提交信息"
```

### Linux/Mac (Bash)

```bash
chmod +x save_version.sh
./save_version.sh "你的提交信息"
```

## 手动操作

### 1. 查看当前状态

```bash
git status
```

### 2. 添加所有更改

```bash
git add -A
```

### 3. 提交更改

```bash
git commit -m "你的提交信息"
```

### 4. 推送到 GitHub

```bash
git push origin main
```

## 提交信息规范

建议使用以下格式：

- `Fix: 修复虚拟墙加载问题`
- `Feature: 添加新功能`
- `Update: 更新依赖版本`
- `Refactor: 重构代码`
- `Docs: 更新文档`

## 注意事项

1. **数据文件**: `data/tasks.json` 等数据文件会频繁变化，如果不想提交这些文件，可以：
   - 使用 `git add app/` 只提交代码文件
   - 或者将数据文件添加到 `.gitignore`

2. **日志文件**: `logs/` 目录已在 `.gitignore` 中，不会提交

3. **虚拟环境**: `venv/` 目录已在 `.gitignore` 中，不会提交

## 查看提交历史

```bash
git log --oneline -10  # 查看最近10次提交
```

## 查看远程仓库

```bash
git remote -v  # 查看远程仓库地址
```

## GitHub 仓库地址

https://github.com/carl0820/schedule-system-based-on-REST

