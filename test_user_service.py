"""测试用户服务"""
import sys
import traceback

try:
    print("Importing user_service...")
    from app.services.user_service import get_user_service
    print("UserService imported successfully")
    
    print("Getting user service instance...")
    service = get_user_service()
    print(f"UserService initialized: {service}")
    
    print(f"Users count: {len(service.users)}")
    print(f"Users: {[u.username for u in service.users.values()]}")
    
    # 检查admin用户
    admin_user = service.get_user_by_username("admin")
    if admin_user:
        print(f"Admin user found: {admin_user.username}, role: {admin_user.role}")
    else:
        print("Admin user NOT found!")
        print("Checking if default admin should be created...")
        has_super_admin = any(u.role.value == "super_admin" for u in service.users.values())
        print(f"Has super admin: {has_super_admin}")
    
    # 检查文件
    import os
    from pathlib import Path
    user_file = Path("data/users.json")
    print(f"User file exists: {user_file.exists()}")
    if user_file.exists():
        print(f"User file size: {user_file.stat().st_size} bytes")
        import json
        with open(user_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f"Users in file: {list(data.keys())}")
    
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()

