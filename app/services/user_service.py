"""
用户服务
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.models.user import User, UserRole, UserCreate, UserUpdate

logger = logging.getLogger(__name__)

# 密码加密上下文 - 使用pbkdf2_sha256（不需要编译，兼容性更好）
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# JWT配置
SECRET_KEY = "robot-scheduler-secret-key-change-in-production-2024"  # 应该从环境变量读取
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30天


class UserService:
    """用户服务"""
    
    STORAGE_FILE = Path("data/users.json")
    
    def __init__(self):
        self.users: Dict[str, User] = {}
        self.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_users_from_file()
        self._init_default_admin()
    
    def _load_users_from_file(self):
        """从文件加载用户"""
        if self.STORAGE_FILE.exists():
            try:
                with open(self.STORAGE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_id, user_data in data.items():
                        # 处理datetime字符串
                        if 'created_at' in user_data:
                            user_data['created_at'] = datetime.fromisoformat(user_data['created_at'])
                        if 'updated_at' in user_data:
                            user_data['updated_at'] = datetime.fromisoformat(user_data['updated_at'])
                        if 'last_login' in user_data and user_data['last_login']:
                            user_data['last_login'] = datetime.fromisoformat(user_data['last_login'])
                        self.users[user_id] = User(**user_data)
                logger.info(f"Loaded {len(self.users)} users from file")
            except Exception as e:
                logger.error(f"Failed to load users: {e}", exc_info=True)
    
    def _save_users_to_file(self):
        """保存用户到文件"""
        try:
            data = {}
            for uid, user in self.users.items():
                user_dict = user.dict()
                # 转换datetime为字符串
                if isinstance(user_dict.get('created_at'), datetime):
                    user_dict['created_at'] = user_dict['created_at'].isoformat()
                if isinstance(user_dict.get('updated_at'), datetime):
                    user_dict['updated_at'] = user_dict['updated_at'].isoformat()
                if user_dict.get('last_login') and isinstance(user_dict['last_login'], datetime):
                    user_dict['last_login'] = user_dict['last_login'].isoformat()
                data[uid] = user_dict
            
            with open(self.STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save users: {e}", exc_info=True)
    
    def _init_default_admin(self):
        """初始化默认超级管理员"""
        try:
            if not any(u.role == UserRole.SUPER_ADMIN for u in self.users.values()):
                import uuid
                user_id = str(uuid.uuid4())
                now = datetime.now()
                
                default_user = User(
                    user_id=user_id,
                    username="admin",
                    password_hash=self.get_password_hash("admin123"),  # 首次登录后应修改
                    role=UserRole.SUPER_ADMIN,
                    is_active=True,
                    created_at=now,
                    updated_at=now
                )
                self.users[user_id] = default_user
                self._save_users_to_file()
                logger.info("Created default admin user: admin/admin123")
        except Exception as e:
            logger.error(f"Failed to initialize default admin user: {e}", exc_info=True)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def get_password_hash(password: str) -> str:
        """加密密码"""
        return pwd_context.hash(password)
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """验证用户"""
        user = self.get_user_by_username(username)
        if not user:
            return None
        if not user.is_active:
            return None
        if not user.password_hash:
            return None
        if not self.verify_password(password, user.password_hash):
            return None
        
        # 更新最后登录时间
        user.last_login = datetime.now()
        self._save_users_to_file()
        return user
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        for user in self.users.values():
            if user.username == username:
                return user
        return None
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """根据ID获取用户"""
        return self.users.get(user_id)
    
    def create_user(self, user_data: UserCreate) -> User:
        """创建用户"""
        import uuid
        user_id = str(uuid.uuid4())
        
        # 检查用户名是否已存在
        if self.get_user_by_username(user_data.username):
            raise ValueError(f"Username {user_data.username} already exists")
        
        now = datetime.now()
        user = User(
            user_id=user_id,
            username=user_data.username,
            email=user_data.email,
            role=user_data.role,
            password_hash=self.get_password_hash(user_data.password),
            is_active=True,
            created_at=now,
            updated_at=now
        )
        
        self.users[user_id] = user
        self._save_users_to_file()
        logger.info(f"Created user: {user_data.username} with role {user_data.role.value}")
        return user
    
    def update_user(self, user_id: str, user_data: UserUpdate) -> Optional[User]:
        """更新用户"""
        user = self.users.get(user_id)
        if not user:
            return None
        
        if user_data.username and user_data.username != user.username:
            if self.get_user_by_username(user_data.username):
                raise ValueError(f"Username {user_data.username} already exists")
            user.username = user_data.username
        
        if user_data.email is not None:
            user.email = user_data.email
        if user_data.role is not None:
            user.role = user_data.role
        if user_data.is_active is not None:
            user.is_active = user_data.is_active
        if user_data.password is not None:
            user.password_hash = self.get_password_hash(user_data.password)
        
        user.updated_at = datetime.now()
        self._save_users_to_file()
        logger.info(f"Updated user: {user_id}")
        return user
    
    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        if user_id in self.users:
            username = self.users[user_id].username
            del self.users[user_id]
            self._save_users_to_file()
            logger.info(f"Deleted user: {username}")
            return True
        return False
    
    def list_users(self) -> list[User]:
        """列出所有用户"""
        return list(self.users.values())
    
    def create_access_token(self, user: User) -> str:
        """创建访问令牌"""
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode = {
            "sub": user.user_id,
            "username": user.username,
            "role": user.role.value,
            "exp": expire
        }
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """验证令牌"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None
    
    def user_to_dict(self, user: User, include_password: bool = False) -> dict:
        """将用户对象转换为字典（用于API响应）"""
        user_dict = {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None
        }
        if include_password:
            user_dict["password_hash"] = user.password_hash
        return user_dict


# 全局实例
_user_service: Optional[UserService] = None


def get_user_service() -> UserService:
    """获取用户服务实例"""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service

