# Windows依赖安装修复脚本
# 使用正确的Python 3.13安装依赖

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Windows依赖安装修复脚本" -ForegroundColor Cyan
Write-Host "Fix Installation Script for Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 指定正确的Python路径
$pythonPath = "C:\Users\lemon.li\AppData\Local\Programs\Python\Python313\python.exe"

# 检查Python是否存在
if (-not (Test-Path $pythonPath)) {
    Write-Host "[ERROR] 未找到Python 3.13: $pythonPath" -ForegroundColor Red
    Write-Host "请检查Python安装路径" -ForegroundColor Yellow
    exit 1
}

Write-Host "[INFO] Python路径: $pythonPath" -ForegroundColor Green
$version = & $pythonPath --version
Write-Host "[INFO] Python版本: $version" -ForegroundColor Green
Write-Host ""

# 禁用代理
Write-Host "[INFO] 禁用代理..." -ForegroundColor Yellow
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
Write-Host "[SUCCESS] 代理已禁用" -ForegroundColor Green
Write-Host ""

# 镜像源列表
$mirrors = @(
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.mirrors.ustc.edu.cn/simple/"
)

# 升级pip
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[STEP 1/4] 升级pip" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$pipUpgraded = $false
foreach ($mirror in $mirrors) {
    Write-Host "[TRY] 使用镜像源: $mirror" -ForegroundColor Yellow

    $result = & $pythonPath -m pip install --upgrade pip -i $mirror 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[SUCCESS] pip升级成功" -ForegroundColor Green
        $pipUpgraded = $true
        break
    }
}

if (-not $pipUpgraded) {
    Write-Host "[WARN] pip升级失败，继续使用当前版本" -ForegroundColor Yellow
}
Write-Host ""

# 安装pydantic
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[STEP 2/4] 安装pydantic" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$pydanticVersions = @(
    "pydantic==2.5.0",
    "pydantic>=2.4.0,<3.0",
    "pydantic"
)

$pydanticInstalled = $false
foreach ($version in $pydanticVersions) {
    Write-Host "[TRY] 尝试安装: $version" -ForegroundColor Yellow

    foreach ($mirror in $mirrors) {
        Write-Host "    使用镜像源: $mirror" -ForegroundColor Gray

        $result = & $pythonPath -m pip install $version -i $mirror --no-cache-dir 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[SUCCESS] pydantic安装成功" -ForegroundColor Green
            $pydanticInstalled = $true
            break
        }
    }

    if ($pydanticInstalled) {
        break
    }
}

if (-not $pydanticInstalled) {
    Write-Host "[ERROR] pydantic安装失败" -ForegroundColor Red
}
Write-Host ""

# 安装numpy
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[STEP 3/4] 安装numpy" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$numpyVersions = @(
    "numpy>=1.26.0,<2.0",
    "numpy>=1.24.0,<2.0",
    "numpy"
)

$numpyInstalled = $false
foreach ($version in $numpyVersions) {
    Write-Host "[TRY] 尝试安装: $version" -ForegroundColor Yellow

    foreach ($mirror in $mirrors) {
        Write-Host "    使用镜像源: $mirror" -ForegroundColor Gray

        $result = & $pythonPath -m pip install $version -i $mirror --no-cache-dir 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[SUCCESS] numpy安装成功" -ForegroundColor Green
            $numpyInstalled = $true
            break
        }
    }

    if ($numpyInstalled) {
        break
    }
}

if (-not $numpyInstalled) {
    Write-Host "[WARN] numpy安装失败（可选依赖，不影响基本功能）" -ForegroundColor Yellow
}
Write-Host ""

# 安装其他依赖
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "[STEP 4/4] 安装其他依赖" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$installed = $false
foreach ($mirror in $mirrors) {
    Write-Host "[TRY] 使用镜像源: $mirror" -ForegroundColor Yellow

    $result = & $pythonPath -m pip install -r requirements.txt -i $mirror --no-cache-dir 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[SUCCESS] 依赖安装成功" -ForegroundColor Green
        $installed = $true
        break
    }
}

if (-not $installed) {
    Write-Host "[WARN] 部分依赖可能未安装成功" -ForegroundColor Yellow
}
Write-Host ""

# 验证安装
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "验证安装" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$packages = @{
    "pydantic" = "核心依赖"
    "fastapi" = "核心依赖"
    "uvicorn" = "核心依赖"
    "httpx" = "核心依赖"
    "numpy" = "可选依赖"
}

$allCoreInstalled = $true

foreach ($package in $packages.Keys) {
    $desc = $packages[$package]
    $checkResult = & $pythonPath -c "import $package; print($package.__version__)" 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] $package ($desc): $checkResult" -ForegroundColor Green
    } else {
        Write-Host "[MISSING] $package ($desc): 未安装" -ForegroundColor Red
        if ($desc -eq "核心依赖") {
            $allCoreInstalled = $false
        }
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "安装结果汇总" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($allCoreInstalled) {
    Write-Host "[SUCCESS] 所有核心依赖安装成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "可以运行以下命令启动服务：" -ForegroundColor Cyan
    Write-Host "  $pythonPath main.py" -ForegroundColor Yellow
    Write-Host "或" -ForegroundColor Cyan
    Write-Host "  .\start_service.ps1" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "访问以下地址：" -ForegroundColor Cyan
    Write-Host "  主页面: http://localhost:8092" -ForegroundColor Yellow
    Write-Host "  API文档: http://localhost:8092/docs" -ForegroundColor Yellow
} else {
    Write-Host "[ERROR] 核心依赖未完全安装" -ForegroundColor Red
    Write-Host ""
    Write-Host "请尝试以下方法：" -ForegroundColor Yellow
    Write-Host "1. 以管理员权限运行此脚本" -ForegroundColor White
    Write-Host "2. 临时禁用防火墙/杀毒软件" -ForegroundColor White
    Write-Host "3. 检查网络连接" -ForegroundColor White
    Write-Host "4. 手动安装失败的依赖：" -ForegroundColor White
    Write-Host "   $pythonPath -m pip install pydantic fastapi uvicorn httpx -i https://pypi.tuna.tsinghua.edu.cn/simple" -ForegroundColor Gray
}

Write-Host ""
