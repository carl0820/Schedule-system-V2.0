# 依赖安装指南

## 问题诊断

如果遇到代理错误（如 `ProxyError: Cannot connect to proxy`），这通常是因为：
1. 系统配置了代理，但代理服务器不可用
2. 网络连接问题
3. 镜像源连接问题

## 解决方案

### 方案1：禁用代理（推荐）

在Windows PowerShell中：

```powershell
# 取消代理设置
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:http_proxy=""
$env:https_proxy=""

# 然后安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 方案2：使用其他镜像源

```bash
# 阿里云镜像
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 腾讯云镜像
pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple

# 豆瓣镜像
pip install -r requirements.txt -i https://pypi.douban.com/simple/

# 官方源（如果网络允许）
pip install -r requirements.txt
```

### 方案3：使用 --no-proxy 选项

```bash
pip install --no-proxy -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 方案4：配置pip永久使用镜像（不通过代理）

编辑或创建 `%APPDATA%\pip\pip.ini` 文件：

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
```

或者创建 `%USERPROFILE%\pip\pip.ini`：

```ini
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
```

然后直接运行：

```bash
pip install -r requirements.txt
```

### 方案5：分步安装（逐个安装）

如果批量安装失败，可以逐个安装核心依赖：

```bash
# 核心依赖
pip install fastapi==0.104.1 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install uvicorn[standard]==0.24.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install httpx==0.25.2 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install pydantic==2.5.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install pydantic-settings==2.1.0 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 可选依赖（如果不需要可以跳过）
pip install redis==5.0.1 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install psycopg2-binary==2.9.9 -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install numpy==1.24.3 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 方案6：使用conda（如果已安装）

```bash
conda install fastapi uvicorn httpx pydantic numpy
pip install pydantic-settings websockets redis psycopg2-binary python-multipart python-jose[cryptography] passlib[bcrypt] psutil
```

## 快速测试

安装完成后，运行：

```bash
python test/quick_test.py
```

如果看到所有模块导入成功，说明安装正确。

## 常见错误解决

### 错误1: SSL证书问题

```bash
pip install --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 错误2: 超时问题

```bash
pip install --default-timeout=100 -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 错误3: 权限问题（Windows）

```powershell
# 以管理员身份运行PowerShell
pip install --user -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 错误4: Python 3.13 兼容性问题（metadata-generation-failed）

如果使用 Python 3.13，某些旧版本的包可能不支持。**已修复：`requirements.txt` 现在使用版本范围，会自动选择兼容版本。**

**推荐方案：直接使用修复后的 requirements.txt**

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

修复后的 `requirements.txt` 会自动选择兼容版本：
- `psycopg2-binary>=2.9.9,<3.0` - 在 Python 3.13 下会自动选择 >=2.9.10
- `numpy>=1.24.3,<2.0` - 在 Python 3.13 下会自动选择 >=1.26.0

**方案A：使用 Python 3.13 专用版本（如果自动选择仍有问题）**

使用 `requirements-py313.txt` 文件，明确指定更新的版本：

```bash
pip install -r requirements-py313.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**方案B：使用安装脚本（自动检测版本）**

```bash
python install_deps.py
```

脚本会自动检测 Python 版本，对于 Python 3.13 使用兼容版本。

**方案C：使用Python 3.11或3.12（最稳定）**

Python 3.11和3.12与所有依赖包兼容性最好：

```bash
# 使用pyenv或conda切换到Python 3.11或3.12
conda create -n robot_env python=3.11
conda activate robot_env
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**方案D：跳过可选依赖（如果仍有问题）**

如果某些可选依赖安装失败，可以先跳过（不影响基本功能）：

```bash
# 安装核心依赖
pip install fastapi==0.104.1 uvicorn[standard]==0.24.0 httpx==0.25.2 pydantic==2.5.0 pydantic-settings==2.1.0 websockets==12.0 python-multipart==0.0.6 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 可选依赖（如果失败不影响基本功能）
pip install "psycopg2-binary>=2.9.10" -i https://pypi.tuna.tsinghua.edu.cn/simple || echo "psycopg2-binary安装失败，跳过"
pip install "numpy>=1.26.0" -i https://pypi.tuna.tsinghua.edu.cn/simple || echo "numpy安装失败，跳过"
```

## 最小依赖安装

如果只需要基本功能，可以只安装核心依赖：

```bash
pip install fastapi uvicorn httpx pydantic pydantic-settings -i https://pypi.tuna.tsinghua.edu.cn/simple
```

这样可以运行基本API，但Redis、PostgreSQL等功能将不可用。

