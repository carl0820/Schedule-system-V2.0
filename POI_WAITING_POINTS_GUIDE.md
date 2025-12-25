# POI等待点配置 - 使用指南

## 问题：前端看不到POI等待点配置？

### 可能原因1：需要向下滚动 ⭐ 最常见

POI等待点配置在**死锁配置页面的最底部**，位于所有其他配置项之后。

**解决方法**：
1. 访问 http://localhost:8092/static/deadlock_config.html
2. 登录系统（如果未登录）
3. **向下滚动到页面底部** 📜
4. 在"历史记录参数"区块之后，应该能看到：
   ```
   ┌─────────────────────────────────┐
   │ POI等待点配置                    │
   │ 选择POI点作为限行区域的等待点      │
   │                                 │
   │ ☐ 启用POI等待点                 │
   │                                 │
   │ 选择POI等待点                    │
   │ 从机器人POI中选择等待点（可多选） │
   │ [POI列表显示在这里]              │
   └─────────────────────────────────┘
   ```

### 可能原因2：POI列表加载失败

如果看到"正在加载POI列表..."一直不消失，或显示错误信息。

**检查步骤**：
1. 打开浏览器开发者工具（F12）
2. 切换到"Console"（控制台）选项卡
3. 查看是否有错误信息
4. 切换到"Network"（网络）选项卡
5. 刷新页面，检查 `/api/maps/pois` 请求是否成功（应该返回200状态码）

**可能的错误**：
- ❌ `/api/maps/pois` 返回404 → API端点未注册（检查main.py是否include了maps router）
- ❌ `/api/maps/pois` 返回空数组 → 没有注册的机器人或机器人没有POI
- ❌ JavaScript错误 → 浏览器控制台会显示具体错误

### 可能原因3：没有注册机器人

POI列表从注册的机器人获取，如果没有机器人，列表会是空的。

**解决方法**：
1. 访问 http://localhost:8092/static/robot_list.html
2. 注册至少一个机器人
3. 确保机器人在线并且有POI点
4. 返回死锁配置页面，刷新

### 可能原因4：浏览器缓存

旧版本的HTML文件被缓存了。

**解决方法**：
- **Windows/Linux**: Ctrl + Shift + R（强制刷新）
- **Mac**: Cmd + Shift + R
- 或者：清空浏览器缓存后重新访问

## 验证POI配置是否存在

### 方法1：检查HTML源代码
1. 访问 http://localhost:8092/static/deadlock_config.html
2. 右键 → 查看页面源代码（View Page Source）
3. Ctrl+F 搜索 "POI等待点配置"
4. 应该能找到4处匹配

### 方法2：检查本地文件
```bash
cd d:\chatbot
grep -c "POI等待点配置" static/deadlock_config.html
```
应该返回 `4`

### 方法3：测试API端点
```bash
# 测试POI API
curl http://localhost:8092/api/maps/pois
```
应该返回POI列表的JSON数组

## 完整的配置流程

### 步骤1：注册机器人（如果还没有）
1. 访问 http://localhost:8092/static/robot_list.html
2. 点击"注册机器人"
3. 输入机器人ID和IP地址
4. 确保机器人在线

### 步骤2：访问死锁配置页面
1. 访问 http://localhost:8092/static/deadlock_config.html
2. 如果未登录，会自动跳转到登录页面
3. 登录后返回配置页面

### 步骤3：向下滚动找到POI配置
⚠️ **重要**：POI配置在页面最底部，需要滚动！

页面结构（从上到下）：
1. 死锁检测参数
2. 窄道检测参数
3. 死锁解除参数
4. 后退动作参数
5. 历史记录参数
6. **👉 POI等待点配置** ← 在这里！

### 步骤4：配置POI等待点
1. ☑️ 勾选"启用POI等待点"
2. 从POI列表中选择要用作等待点的POI（可多选）
3. 已选择的POI会显示在下方
4. 点击"保存配置"按钮

### 步骤5：验证配置
1. 重新加载页面
2. 向下滚动到POI配置区块
3. 确认之前选择的POI被正确勾选

## 常见问题 FAQ

### Q1: 为什么看不到POI列表？
A: 检查以下几点：
- 是否已注册机器人？
- 机器人是否在线？
- 机器人上是否有POI点？
- 浏览器控制台是否有错误？

### Q2: POI列表显示"暂无POI点"？
A: 说明当前注册的机器人上没有POI，需要：
1. 在机器人上创建POI点
2. 或者注册其他有POI的机器人

### Q3: 保存后POI配置没有生效？
A: 检查：
1. 浏览器控制台是否有保存成功的提示？
2. `/api/system/config/deadlock` PUT请求是否成功（200状态码）？
3. 重新加载配置，检查POI是否被保存

### Q4: 页面一直显示"正在加载配置..."？
A: 说明配置API加载失败，检查：
1. 服务是否正常运行？
2. `/api/system/config/deadlock` GET请求是否成功？
3. 浏览器控制台的错误信息

## 技术细节

### API端点
- **获取POI列表**: `GET /api/maps/pois`
- **获取死锁配置**: `GET /api/system/config/deadlock`
- **保存死锁配置**: `PUT /api/system/config/deadlock`

### 配置数据结构
```json
{
  "use_poi_waiting_points": true,
  "poi_waiting_points": ["P01", "P02", "P03"]
}
```

### 前端实现位置
- **HTML文件**: `static/deadlock_config.html` (line 421-448)
- **JavaScript逻辑**:
  - 加载POI列表: line 499-527
  - 渲染POI列表: line 530-572
  - 保存配置: line 704-799

---

**最后更新**: 2025-12-25
**相关commit**: 25984a7 (2025-12-22)
