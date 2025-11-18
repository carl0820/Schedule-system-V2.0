# 🚀 快速开始指南

> 5分钟快速部署多机器人调度系统

## 📌 选择你的平台

- **Windows 用户**: 继续阅读本文档
- **Mac/Linux 用户**: 请查看 [QUICK_START_MAC_LINUX.md](QUICK_START_MAC_LINUX.md)

---

## 第一步：下载代码

从GitHub下载或克隆代码到本地：

```powershell
# 方法1: 下载ZIP并解压
# 访问: https://github.com/carl0820/schedule-system-based-on-REST
# 点击 "Code" → "Download ZIP"

# 方法2: 使用Git克隆
git clone https://github.com/carl0820/schedule-system-based-on-REST.git
cd schedule-system-based-on-REST
```

## 第二步：安装依赖

打开PowerShell，进入项目目录，运行：

```powershell
# 推荐：使用Python安装脚本（跨平台，自动处理网络问题）
python install_deps.py
```

如果Python脚本不可用，使用PowerShell脚本：

```powershell
# 方法2: 使用PowerShell脚本（Windows）
.\install_deps_simple.ps1
```

如果脚本都不可用，手动安装：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 第三步：启动服务

```powershell
# 使用启动脚本
.\start_service.ps1

# 或直接运行
python main.py
```

## 第四步：访问系统

打开浏览器访问：
- **首页**: http://localhost:8000
- **API文档**: http://localhost:8000/docs

## 完成！

现在你可以：
1. 注册机器人（点击"机器人管理"）
2. 加载地图（点击"地图管理"）
3. 创建任务（在首页选择POI点或输入坐标）

---

## 需要帮助？

- **详细文档**: 查看 `docs/QUICK_START_GUIDE.md`
- **常见问题**: 查看 `docs/QUICK_START_GUIDE.md` 的"常见问题"部分
- **API文档**: http://localhost:8000/docs

---

**系统要求**: 
- **Windows**: Windows 10/11, Python 3.8-3.13, 4GB+ RAM
- **Mac/Linux**: macOS 10.14+ / Linux (Ubuntu 18.04+, CentOS 7+), Python 3.8-3.13, 4GB+ RAM

