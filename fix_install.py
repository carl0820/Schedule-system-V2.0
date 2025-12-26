#!/usr/bin/env python3
"""
依赖安装修复脚本
解决pydantic和numpy安装失败问题
"""

import subprocess
import sys
import os

def run_command(cmd, description):
    """运行命令并返回结果"""
    print(f"\n{'='*60}")
    print(f"[INFO] {description}")
    print(f"[CMD] {' '.join(cmd)}")
    print('='*60)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            print(f"[SUCCESS] {description}")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print(f"[FAILED] {description}")
            if result.stderr:
                print(f"错误信息:\n{result.stderr}")
            if result.stdout:
                print(f"输出信息:\n{result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] {description} - 超时（5分钟）")
        return False
    except Exception as e:
        print(f"[ERROR] {description} - {e}")
        return False

def check_proxy():
    """检查并禁用代理"""
    print("\n[INFO] 检查代理设置...")

    # 检查环境变量中的代理
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
    has_proxy = False

    for var in proxy_vars:
        if os.environ.get(var):
            print(f"[WARN] 检测到代理设置: {var}={os.environ.get(var)}")
            has_proxy = True

    if has_proxy:
        print("[INFO] 尝试禁用代理...")
        for var in proxy_vars:
            os.environ[var] = ''
        print("[SUCCESS] 已禁用代理")
    else:
        print("[INFO] 未检测到代理设置")

def upgrade_pip():
    """升级pip"""
    print("\n[INFO] 升级pip到最新版本...")
    mirrors = [
        'https://pypi.tuna.tsinghua.edu.cn/simple',
        'https://mirrors.aliyun.com/pypi/simple/',
        'https://pypi.mirrors.ustc.edu.cn/simple/',
    ]

    for mirror in mirrors:
        if run_command(
            [sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip', '-i', mirror],
            f"使用 {mirror} 升级pip"
        ):
            return True

    return False

def install_package(package, mirrors):
    """尝试使用多个镜像源安装包"""
    print(f"\n[INFO] 安装 {package}")

    for mirror in mirrors:
        print(f"\n[TRY] 使用镜像源: {mirror}")

        # 方法1: 使用镜像源直接安装
        if run_command(
            [sys.executable, '-m', 'pip', 'install', package, '-i', mirror, '--no-cache-dir'],
            f"从 {mirror} 安装 {package}"
        ):
            return True

        # 方法2: 使用trusted-host
        if run_command(
            [sys.executable, '-m', 'pip', 'install', package, '-i', mirror,
             '--trusted-host', mirror.split('//')[1].split('/')[0], '--no-cache-dir'],
            f"从 {mirror} 安装 {package} (trusted-host)"
        ):
            return True

    return False

def install_with_compatibility():
    """使用兼容性方法安装"""
    print("\n[INFO] 尝试兼容性安装方案...")

    mirrors = [
        'https://pypi.tuna.tsinghua.edu.cn/simple',
        'https://mirrors.aliyun.com/pypi/simple/',
        'https://pypi.mirrors.ustc.edu.cn/simple/',
        'https://pypi.douban.com/simple/',
    ]

    # 安装pydantic（降低版本要求）
    pydantic_versions = [
        'pydantic==2.5.0',
        'pydantic>=2.4.0,<3.0',
        'pydantic>=2.0.0',
    ]

    print("\n" + "="*60)
    print("[STEP 1/2] 安装 pydantic")
    print("="*60)

    pydantic_installed = False
    for version in pydantic_versions:
        print(f"\n[TRY] 尝试安装: {version}")
        if install_package(version, mirrors):
            pydantic_installed = True
            break

    if not pydantic_installed:
        print("\n[ERROR] pydantic 安装失败，尝试所有版本都不成功")

    # 安装numpy
    numpy_versions = [
        'numpy>=1.26.0,<2.0',
        'numpy>=1.24.0,<2.0',
        'numpy<2.0',
    ]

    print("\n" + "="*60)
    print("[STEP 2/2] 安装 numpy")
    print("="*60)

    numpy_installed = False
    for version in numpy_versions:
        print(f"\n[TRY] 尝试安装: {version}")
        if install_package(version, mirrors):
            numpy_installed = True
            break

    if not numpy_installed:
        print("\n[WARN] numpy 安装失败（这是可选依赖，不影响基本功能）")

    return pydantic_installed, numpy_installed

def verify_installation():
    """验证安装"""
    print("\n" + "="*60)
    print("[VERIFY] 验证安装")
    print("="*60)

    packages = {
        'pydantic': '核心依赖',
        'numpy': '可选依赖',
        'fastapi': '核心依赖',
        'uvicorn': '核心依赖',
        'httpx': '核心依赖',
    }

    results = {}
    for package, desc in packages.items():
        try:
            __import__(package)
            version = __import__(package).__version__
            print(f"[OK] {package} ({desc}): {version}")
            results[package] = True
        except ImportError:
            print(f"[MISSING] {package} ({desc}): 未安装")
            results[package] = False

    return results

def main():
    print("""
╔════════════════════════════════════════════════════════════╗
║         依赖安装修复脚本                                   ║
║         Fix Installation Script                            ║
╚════════════════════════════════════════════════════════════╝
    """)

    # 检查Python版本
    print(f"[INFO] Python版本: {sys.version}")
    print(f"[INFO] Python路径: {sys.executable}")

    # 禁用代理
    check_proxy()

    # 升级pip
    if not upgrade_pip():
        print("\n[WARN] pip升级失败，继续使用当前版本")

    # 安装依赖
    pydantic_ok, numpy_ok = install_with_compatibility()

    # 验证安装
    results = verify_installation()

    # 显示结果
    print("\n" + "="*60)
    print("安装结果汇总")
    print("="*60)

    core_deps_ok = results.get('pydantic', False) and results.get('fastapi', False) and results.get('uvicorn', False)

    if core_deps_ok:
        print("\n[SUCCESS] ✅ 核心依赖安装成功！")
        print("\n可以运行以下命令启动服务：")
        print("  python main.py")
        print("或")
        print("  .\\start_service.ps1")
        return 0
    else:
        print("\n[ERROR] ❌ 核心依赖安装失败")
        print("\n请尝试以下方法：")
        print("1. 检查网络连接")
        print("2. 临时禁用防火墙/杀毒软件")
        print("3. 使用管理员权限运行此脚本")
        print("4. 手动安装失败的依赖：")

        if not results.get('pydantic', False):
            print("\n   pip install pydantic -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir")

        print("\n5. 如果以上都失败，尝试使用虚拟环境：")
        print("   python -m venv venv")
        print("   .\\venv\\Scripts\\activate")
        print("   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple")

        return 1

if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断安装")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[ERROR] 发生未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
