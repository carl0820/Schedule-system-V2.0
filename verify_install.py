#!/usr/bin/env python3
"""验证依赖安装"""

import sys

print("="*60)
print("验证依赖安装")
print("="*60)
print(f"\nPython版本: {sys.version}")
print(f"Python路径: {sys.executable}")
print()

packages = {
    "pydantic": "核心依赖",
    "fastapi": "核心依赖",
    "uvicorn": "核心依赖",
    "httpx": "核心依赖",
    "requests": "核心依赖",
    "numpy": "可选依赖",
}

results = {}
for package, desc in packages.items():
    try:
        module = __import__(package)
        version = getattr(module, '__version__', 'unknown')
        print(f"[OK] {package:15} ({desc}): {version}")
        results[package] = True
    except ImportError:
        print(f"[MISSING] {package:15} ({desc}): 未安装")
        results[package] = False

print()
print("="*60)
print("安装结果汇总")
print("="*60)

core_deps = ["pydantic", "fastapi", "uvicorn", "httpx", "requests"]
core_ok = all(results.get(dep, False) for dep in core_deps)

if core_ok:
    print("\n[SUCCESS] 所有核心依赖安装成功！")
    print("\n可以运行以下命令启动服务：")
    print(f"  {sys.executable} main.py")
    print("\n访问以下地址：")
    print("  主页面: http://localhost:8092")
    print("  API文档: http://localhost:8092/docs")
else:
    print("\n[ERROR] 部分核心依赖未安装")
    print("\n请安装缺失的依赖")
