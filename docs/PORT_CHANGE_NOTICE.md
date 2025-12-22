# 端口变更通知

## 重要变更

**默认端口已从 8000 更改为 8092**

## 原因

Windows 系统保留了端口范围 **7992-8091**，导致端口 8000 无法绑定，出现错误：
```
ERROR: [Errno 13] error while attempting to bind on address ('0.0.0.0', 8000): 
[winerror 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

## 解决方案

已将默认端口改为 **8092**（在保留范围之外），确保服务可以在任何 Windows 网络环境下正常启动。

## 访问地址

- **主页**: http://localhost:8092/
- **API 文档**: http://localhost:8092/docs
- **健康检查**: http://localhost:8092/health

## 自定义端口

如果需要使用其他端口，可以：

1. **方法1：修改 config.py**
   ```python
   PORT: int = 8092  # 改为你想要的端口号
   ```

2. **方法2：使用环境变量**
   创建 `.env` 文件：
   ```
   PORT=8092
   ```

3. **方法3：命令行参数**
   ```powershell
   .\venv\bin\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8092
   ```

## 检查 Windows 保留端口

如果需要检查 Windows 保留的端口范围：
```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

## 注意事项

- 所有启动脚本（`start_service.ps1`, `stop_service.ps1`, `restart_service.ps1`, `check_service.ps1`）已自动从 `config.py` 读取端口配置
- 如果修改了端口，请确保防火墙允许该端口
- 确保新端口不在 Windows 保留范围内

