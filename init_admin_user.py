"""
初始化默认管理员用户
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from passlib.context import CryptContext

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 创建数据目录
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

# 用户文件路径
users_file = data_dir / "users.json"

# 检查是否已存在用户
if users_file.exists():
    with open(users_file, 'r', encoding='utf-8') as f:
        existing_users = json.load(f)
        # 检查是否已有admin用户
        for user_data in existing_users.values():
            if user_data.get('username') == 'admin':
                print("Admin user already exists!")
                exit(0)

# 创建默认管理员用户
user_id = str(uuid.uuid4())
now = datetime.now()

user_data = {
    "user_id": user_id,
    "username": "admin",
    "password_hash": pwd_context.hash("admin123"),
    "role": "super_admin",
    "is_active": True,
    "created_at": now.isoformat(),
    "updated_at": now.isoformat(),
    "last_login": None,
    "email": None
}

# 保存到文件
users = {user_id: user_data}
with open(users_file, 'w', encoding='utf-8') as f:
    json.dump(users, f, ensure_ascii=False, indent=2)

print(f"Default admin user created successfully!")
print(f"Username: admin")
print(f"Password: admin123")
print(f"User file: {users_file}")

