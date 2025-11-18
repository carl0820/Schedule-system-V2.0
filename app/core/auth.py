"""
认证核心模块
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.services.user_service import get_user_service, UserService
from app.models.user import User, UserRole

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_service: UserService = Depends(get_user_service)
) -> User:
    """获取当前用户"""
    token = credentials.credentials
    payload = user_service.verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    user = user_service.get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    return user


def require_role(*allowed_roles: UserRole):
    """角色权限装饰器"""
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return role_checker


# 权限检查函数
def can_manage_users(user: User) -> bool:
    """检查是否可以管理用户"""
    return user.role in [UserRole.SUPER_ADMIN]


def can_manage_robots(user: User) -> bool:
    """检查是否可以管理机器人"""
    return user.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]


def can_manage_tasks(user: User) -> bool:
    """检查是否可以管理任务"""
    return user.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER]


def can_manage_maps(user: User) -> bool:
    """检查是否可以管理地图"""
    return user.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN]


def can_view_system_status(user: User) -> bool:
    """检查是否可以查看系统状态"""
    return user.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.OPERATOR]


def can_modify_system_config(user: User) -> bool:
    """检查是否可以修改系统配置"""
    return user.role in [UserRole.SUPER_ADMIN]

