# 服务重启指南

## 问题说明

由于Python字节码缓存问题，代码修改可能不会立即生效。需要完全重启服务。

## 重启步骤

### 方法1：手动重启（推荐）

1. **停止当前服务**
   - 在运行`python main.py`的终端按 **Ctrl+C**
   - 或者关闭运行服务的终端窗口

2. **清理Python缓存**（可选但推荐）
   ```powershell
   # 在chatbot目录执行
   Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
   ```

3. **重新启动服务**
   ```bash
   cd d:\chatbot
   python main.py
   ```

4. **验证启动成功**
   - 应该看到："Periodic task update loop started"
   - **5秒后**应该看到：`[PERIODIC] Loop 10: Found X executing/assigned tasks`
   - 之后每5秒应该看到 `[PERIODIC] Loop 20`, `Loop 30` 等

### 方法2：使用PowerShell脚本

```powershell
# 完全停止所有Python进程
Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force

# 等待3秒
Start-Sleep -Seconds 3

# 清理缓存
cd d:\chatbot
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 启动服务
python main.py
```

## 验证代码修改已生效

启动后，监控日志应该看到新的心跳格式：

```bash
# 在另一个终端运行
tail -f logs/app.log | findstr "\[PERIODIC\]"
```

**预期输出**（新格式）：
```
[PERIODIC] Loop 10: Found 0 executing/assigned tasks (total tasks: 25)
[PERIODIC] Loop 20: Found 0 executing/assigned tasks (total tasks: 25)
[PERIODIC] Loop 30: Found 0 executing/assigned tasks (total tasks: 25)
```

如果看到这种格式，说明代码修改已生效！

## 运行测试

服务启动成功后：

```bash
python quick_test.py
```

**预期结果**：
```
✓ 任务创建成功: <task_id>
  状态: pending
  动作数: 3

监控任务执行（30秒）...
[0s] 动作索引: 0, 状态: executing   # 第一个动作
[Xs] 动作索引: 1, 状态: executing   # 等待动作
[X+2s] 动作索引: 2, 状态: executing # 第二个动作
[Ys] 动作索引: 2, 状态: COMPLETED   # 完成
```

## 故障排除

### 问题1：仍然看到旧格式的日志

**原因**：Python使用了缓存的字节码

**解决**：
1. 完全停止服务
2. 删除所有 `__pycache__` 目录
3. 删除所有 `.pyc` 文件
4. 重新启动

### 问题2：定期循环停止

**症状**：`[PERIODIC]` 日志在某个时间后停止输出

**原因**：`_update_executing_tasks()` 内部异常导致循环终止

**解决**：新的代码修复已经解决此问题，确保：
1. 使用最新代码（包含【修复】标记）
2. 完全重启服务
3. 检查日志中是否有 `[PERIODIC] Error in _update_executing_tasks` 错误

### 问题3：任务卡在第一个动作

**症状**：`current_action_index` 一直是 0

**可能原因**：
1. 定期循环没有运行（检查 `[PERIODIC]` 日志）
2. 机器人未真正执行动作（检查机器人连接）
3. Action状态查询失败（检查网络）

**解决**：确保定期循环持续输出日志

## 已修复的BUG列表

1. ✅ WAIT动作异常处理
2. ✅ 动作完成逻辑修复
3. ✅ 语法错误修复
4. ✅ 定期循环增强（更好的异常处理和日志）

## 需要帮助？

查看完整修复总结：`BUG_FIX_SUMMARY.md`
