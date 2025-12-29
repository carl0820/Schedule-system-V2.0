# 更新日志 / Changelog

本文档记录多机器人调度系统的版本更新历史。

---

## [2.0.1-rc1] - 2025-12-29

### 🐛 Bug 修复 / Bug Fixes

#### 任务调度系统
- **修复 GO_HOME 任务完成检测问题** ([38891e2](https://github.com/carl0820/Schedule-system-V2.0/commit/38891e2))
  - 问题：机器人返回充电桩后，任务状态停留在"执行中"，导致任务无法完成
  - 原因：`get_current_action()` API 失败时（404/400错误）没有 fallback 逻辑
  - 修复：添加异常处理，当机器人在充电桩且空闲时自动标记 GO_HOME 完成
  - 文件：`app/services/task_scheduler.py` (lines 3801-3824)

#### 前端界面
- **修复任务列表时间筛选统计数字不更新问题** ([0fff160](https://github.com/carl0820/Schedule-system-V2.0/commit/0fff160))
  - 问题：使用时间筛选后，顶部统计数字仍显示全局统计
  - 原因：API 计算统计时未考虑 `start_date` 和 `end_date` 筛选条件
  - 修复：有时间筛选时基于筛选结果计算统计，无筛选时查询数据库
  - 文件：`app/api/tasks.py` (lines 494-529)

### 🔧 Windows 部署改进 / Windows Deployment Improvements

#### 端口配置优化
- **服务端口从 8092 更改为 9092** ([6792100](https://github.com/carl0820/Schedule-system-V2.0/commit/6792100))
  - 原因：端口 8092 在 Windows 保留端口范围（8052-8151）内
  - 影响：Windows 系统无法绑定该端口（WinError 10013）
  - 解决方案：更改为 9092，避免端口冲突
  - 新增诊断工具：`check_port_reservation.ps1`
  - 文件：`config.py`, `start.ps1`, `start_safe.ps1`, `diagnose.ps1`

#### 启动脚本优化
- **修复启动脚本编码问题** ([25345ca](https://github.com/carl0820/Schedule-system-V2.0/commit/25345ca))
  - 问题：PowerShell 脚本显示乱码（繁体字/garbled text）
  - 修复：所有脚本改为纯英文，避免编码问题
  - 文件：`start_service.ps1`, `start.ps1`

- **增强 restart_service.ps1 可靠性** ([3d58a48](https://github.com/carl0820/Schedule-system-V2.0/commit/3d58a48))
  - 添加 3 秒等待确保端口释放
  - 添加最终端口检查
  - 改为前台运行（blocking mode）
  - 文件：`restart_service.ps1`

#### 新增诊断工具
- **新增端口诊断和安全启动脚本** ([a2aa742](https://github.com/carl0820/Schedule-system-V2.0/commit/a2aa742), [d8fa275](https://github.com/carl0820/Schedule-system-V2.0/commit/d8fa275))
  - `start_safe.ps1`：自动检测并终止占用端口的进程（3次重试）
  - `diagnose.ps1`：5项诊断测试（端口占用、Python进程、绑定测试、防火墙、Python版本）
  - `STARTUP_GUIDE.md`：完整的 Windows 启动指南
  - `check_port_reservation.ps1`：检查 Windows 端口保留范围
  - `PORT_CHANGE_NOTE.md`：端口更改说明文档

### 📚 文档更新 / Documentation Updates

- **新增 Windows 启动指南** ([d8fa275](https://github.com/carl0820/Schedule-system-V2.0/commit/d8fa275))
  - 5种启动脚本对比和使用场景
  - 5个常见问题和解决方案
  - 推荐工作流程
  - 完整故障排查指南

- **更新启动指南端口信息** ([acfc7c2](https://github.com/carl0820/Schedule-system-V2.0/commit/acfc7c2))
  - 所有文档中的 8092 更新为 9092

### 🔄 其他改进 / Other Improvements

- 优化启动脚本执行方式，改为前台运行以便实时查看日志
- 统一所有启动脚本的端口配置
- 添加详细的调试日志，便于问题排查

---

## [1.5.0] - 2025-12-28 及之前

之前版本的功能和改进（详细信息请查看 git 历史记录）

### 主要功能
- 多机器人任务调度系统
- 任务优先级管理
- 多动作任务支持（MOVE_TO, WAIT, GO_HOME）
- POI 点管理
- 实时任务监控
- Web 管理界面

---

## 版本命名规范

- **Major.Minor.Patch[-rc|beta|alpha]**
  - Major: 重大架构变更或不兼容更新
  - Minor: 新功能或重要改进
  - Patch: Bug 修复和小改进
  - rc: Release Candidate（发布候选）
  - beta: 测试版
  - alpha: 内部测试版

---

## 升级指南

### 从 1.5.0 升级到 2.0.1-rc1

1. **拉取最新代码**
   ```bash
   git pull origin main
   ```

2. **注意端口变更**
   - 服务端口从 8092 更改为 9092
   - 所有访问 URL 需要更新端口号
   - 示例：http://localhost:9092

3. **重启服务**
   ```powershell
   .\restart_service.ps1
   ```

4. **验证**
   - 访问 http://localhost:9092 确认服务正常
   - 测试任务列表时间筛选功能
   - 测试 GO_HOME 任务完成检测

---

## 已知问题 / Known Issues

- 无

---

## 贡献者 / Contributors

- Claude Sonnet 4.5 - 代码生成和优化
- Lemon Li - 项目维护和测试

---

**完整更新历史请查看**: https://github.com/carl0820/Schedule-system-V2.0/commits/main
