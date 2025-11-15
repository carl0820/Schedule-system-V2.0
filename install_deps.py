"""
依赖安装脚本 - 分步安装，避免批量安装失败
"""
import subprocess
import sys

# 检测 Python 版本
PYTHON_VERSION = sys.version_info
IS_PYTHON_313 = PYTHON_VERSION.major == 3 and PYTHON_VERSION.minor >= 13

# 核心依赖（必需）
CORE_DEPS = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "httpx==0.25.2",
    "pydantic==2.5.0",
    "pydantic-settings==2.1.0",
    "websockets==12.0",
    "python-multipart==0.0.6",
]

# 可选依赖（根据 Python 版本选择兼容版本）
if IS_PYTHON_313:
    # Python 3.13 需要更新的版本
    OPTIONAL_DEPS = [
        "redis>=5.0.1",
        "psycopg2-binary>=2.9.10",  # Python 3.13 需要 >= 2.9.10
        "numpy>=1.26.0,<2.0",  # Python 3.13 需要 >= 1.26.0
        "python-jose[cryptography]==3.3.0",
        "passlib[bcrypt]==1.7.4",
        "psutil>=5.9.6",
    ]
else:
    # Python 3.11 和 3.12 使用原始版本
    OPTIONAL_DEPS = [
        "redis==5.0.1",
        "psycopg2-binary>=2.9.9,<3.0",
        "numpy>=1.24.3,<2.0",
        "python-jose[cryptography]==3.3.0",
        "passlib[bcrypt]==1.7.4",
        "psutil==5.9.6",
    ]

# 镜像源列表（按优先级）
MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://mirrors.cloud.tencent.com/pypi/simple",
    "https://pypi.douban.com/simple",
    None  # 官方源
]

def install_package(package, mirror=None, allow_failure=False):
    """安装单个包"""
    cmd = [sys.executable, "-m", "pip", "install", package, "--no-proxy"]
    
    if mirror:
        cmd.extend(["-i", mirror])
        # 添加信任主机
        if "tuna.tsinghua" in mirror or "aliyun" in mirror or "tencent" in mirror or "douban" in mirror:
            cmd.extend(["--trusted-host", mirror.split("://")[1].split("/")[0]])
    
    print(f"\n正在安装: {package}")
    print(f"命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"[OK] {package} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        if allow_failure:
            print(f"[WARN] {package} 安装失败（允许跳过）: {e.stderr[:200]}")
            return False
        else:
            print(f"[ERROR] {package} 安装失败: {e.stderr[:200]}")
            return False

def install_with_fallback(package, allow_failure=False):
    """使用多个镜像源尝试安装"""
    for mirror in MIRRORS:
        if install_package(package, mirror, allow_failure=allow_failure):
            return True
    return False

def main():
    """主函数"""
    print("=" * 60)
    print("依赖安装脚本")
    print("=" * 60)
    print(f"\nPython 版本: {PYTHON_VERSION.major}.{PYTHON_VERSION.minor}.{PYTHON_VERSION.micro}")
    if IS_PYTHON_313:
        print("[INFO] 检测到 Python 3.13，将使用兼容版本")
    print("\n这个脚本会逐个安装依赖包，避免批量安装失败")
    print("=" * 60)
    
    # 安装核心依赖
    print("\n" + "=" * 60)
    print("安装核心依赖...")
    print("=" * 60)
    
    failed_core = []
    for dep in CORE_DEPS:
        if not install_with_fallback(dep):
            failed_core.append(dep)
    
    # 安装可选依赖
    print("\n" + "=" * 60)
    print("安装可选依赖...")
    print("=" * 60)
    
    failed_optional = []
    for dep in OPTIONAL_DEPS:
        # 对于可选依赖，允许失败
        if not install_with_fallback(dep, allow_failure=True):
            failed_optional.append(dep)
    
    # 总结
    print("\n" + "=" * 60)
    print("安装总结")
    print("=" * 60)
    
    if failed_core:
        print(f"\n[ERROR] 核心依赖安装失败 ({len(failed_core)}/{len(CORE_DEPS)}):")
        for dep in failed_core:
            print(f"  - {dep}")
        print("\n请手动安装这些依赖，或检查网络连接")
    else:
        print(f"\n[OK] 所有核心依赖安装成功 ({len(CORE_DEPS)}/{len(CORE_DEPS)})")
    
    if failed_optional:
        print(f"\n[WARN] 可选依赖安装失败 ({len(failed_optional)}/{len(OPTIONAL_DEPS)}):")
        for dep in failed_optional:
            print(f"  - {dep}")
        print("\n这些依赖是可选的，不影响基本功能")
    else:
        print(f"\n[OK] 所有可选依赖安装成功 ({len(OPTIONAL_DEPS)}/{len(OPTIONAL_DEPS)})")
    
    print("\n" + "=" * 60)
    
    if failed_core:
        print("\n[ERROR] 核心依赖未完全安装，请手动解决")
        sys.exit(1)
    else:
        print("\n[SUCCESS] 依赖安装完成！")
        print("\n可以运行测试: python test/quick_test.py")
        print("=" * 60)

if __name__ == "__main__":
    main()

