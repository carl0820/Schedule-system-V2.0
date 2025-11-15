"""
基础测试脚本 - 测试代码结构和语法
"""
import sys
import importlib.util
import os

def test_import(module_path, module_name):
    """测试模块导入"""
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None:
            print(f"[X] {module_name}: 无法找到模块规范")
            return False
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        print(f"[OK] {module_name}: 导入成功")
        return True
    except SyntaxError as e:
        print(f"[ERROR] {module_name}: 语法错误 - {e}")
        return False
    except Exception as e:
        # 如果是缺少依赖导致的导入错误，这是正常的
        if "No module named" in str(e):
            print(f"[WARN] {module_name}: 缺少依赖 - {e}")
            return True  # 语法没问题，只是缺少依赖
        else:
            print(f"[ERROR] {module_name}: 导入错误 - {e}")
            return False

def test_syntax(module_path):
    """测试语法"""
    try:
        with open(module_path, 'r', encoding='utf-8') as f:
            code = f.read()
        compile(code, module_path, 'exec')
        return True
    except SyntaxError as e:
        print(f"[ERROR] {module_path}: 语法错误 - {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 60)
    print("基础代码测试")
    print("=" * 60)
    
    # 获取项目根目录（test目录的父目录）
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 测试配置文件
    print("\n[1] 测试配置文件...")
    test_syntax(os.path.join(base_dir, "config.py"))
    test_import(os.path.join(base_dir, "config.py"), "config")
    
    # 测试模型
    print("\n[2] 测试数据模型...")
    test_import(os.path.join(base_dir, "app", "models", "robot.py"), "app.models.robot")
    test_import(os.path.join(base_dir, "app", "models", "task.py"), "app.models.task")
    
    # 测试服务
    print("\n[3] 测试服务模块...")
    test_import(os.path.join(base_dir, "app", "services", "robot_agent.py"), "app.services.robot_agent")
    test_import(os.path.join(base_dir, "app", "services", "map_manager.py"), "app.services.map_manager")
    test_import(os.path.join(base_dir, "app", "services", "path_planner.py"), "app.services.path_planner")
    test_import(os.path.join(base_dir, "app", "services", "robot_manager.py"), "app.services.robot_manager")
    test_import(os.path.join(base_dir, "app", "services", "task_scheduler.py"), "app.services.task_scheduler")
    
    # 测试API
    print("\n[4] 测试API路由...")
    test_import(os.path.join(base_dir, "app", "api", "robots.py"), "app.api.robots")
    test_import(os.path.join(base_dir, "app", "api", "tasks.py"), "app.api.tasks")
    test_import(os.path.join(base_dir, "app", "api", "maps.py"), "app.api.maps")
    test_import(os.path.join(base_dir, "app", "api", "system.py"), "app.api.system")
    
    # 测试主应用
    print("\n[5] 测试主应用...")
    test_import(os.path.join(base_dir, "main.py"), "main")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    print("\n注意：如果看到 '[WARN] 缺少依赖' 的提示，这是正常的，")
    print("需要先安装依赖：pip install -r requirements.txt")
    print("=" * 60)

if __name__ == "__main__":
    main()

