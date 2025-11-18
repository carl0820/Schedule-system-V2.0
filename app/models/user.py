"""
用户模型
"""
from enum import Enum
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserRole(str, Enum):
    """用户角色"""
    SUPER_ADMIN = "super_admin"  # 超级管理员
    ADMIN = "admin"              # 管理员
    OPERATOR = "operator"        # 运维人员
    USER = "user"                # 普通用户


class User(BaseModel):
    """用户模型"""
    user_id: str
    username: str
    email: Optional[EmailStr] = None
    role: UserRole
    is_active: bool = True
    password_hash: Optional[str] = None  # 密码哈希（不返回给前端）
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class UserCreate(BaseModel):
    """创建用户请求"""
    username: str
    password: str
    email: Optional[EmailStr] = None
    role: UserRole


class UserUpdate(BaseModel):
    """更新用户请求"""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    user: dict  # 不包含密码哈希的用户信息


class UserResponse(BaseModel):
    """用户响应（不包含密码）"""
    user_id: str
    username: str
    email: Optional[EmailStr] = None
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None

