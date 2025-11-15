"""
只测试语法，不测试导入
"""
import ast
import os

def test_syntax(file_path):
    """测试Python文件语法"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code, filename=file_path)
        print(f"[OK] {file_path}")
        return True
    except SyntaxError as e:
        print(f"[ERROR] {file_path}: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] {file_path}: {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 60)
    print("语法测试（不测试导入）")
    print("=" * 60)
    
    # 获取项目根目录（test目录的父目录）
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    files_to_test = [
        "config.py",
        "main.py",
        "app/models/robot.py",
        "app/models/task.py",
        "app/services/robot_agent.py",
        "app/services/map_manager.py",
        "app/services/path_planner.py",
        "app/services/robot_manager.py",
        "app/services/task_scheduler.py",
        "app/api/robots.py",
        "app/api/tasks.py",
        "app/api/maps.py",
        "app/api/system.py",
    ]
    
    success_count = 0
    total_count = len(files_to_test)
    
    for file_name in files_to_test:
        file_path = os.path.join(base_dir, file_name)
        if os.path.exists(file_path):
            if test_syntax(file_path):
                success_count += 1
        else:
            print(f"[MISS] {file_path}: 文件不存在")
    
    print("\n" + "=" * 60)
    print(f"测试完成: {success_count}/{total_count} 文件语法正确")
    print("=" * 60)
    print("\n注意：此测试只检查语法，不检查导入依赖")
    print("如果所有文件语法正确，可以尝试安装依赖后再测试")
    print("=" * 60)

if __name__ == "__main__":
    main()

