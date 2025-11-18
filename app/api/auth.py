"""
认证API
"""
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer
from typing import List
from app.models.user import (
    LoginRequest, LoginResponse, User, UserCreate, UserUpdate, UserResponse
)
from app.services.user_service import get_user_service, UserService
from app.core.auth import get_current_user, require_role, UserRole

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    user_service: UserService = Depends(get_user_service)
):
    """用户登录"""
    user = user_service.authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    access_token = user_service.create_access_token(user)
    user_dict = user_service.user_to_dict(user, include_password=False)
    
    return LoginResponse(
        access_token=access_token,
        user=user_dict
    )


@router.get("/me", response_model=dict)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """获取当前用户信息"""
    return user_service.user_to_dict(current_user, include_password=False)


@router.get("/users", response_model=List[dict])
async def list_users(
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    user_service: UserService = Depends(get_user_service)
):
    """列出所有用户（仅超级管理员和管理员）"""
    users = user_service.list_users()
    return [user_service.user_to_dict(user, include_password=False) for user in users]


@router.post("/users", response_model=dict)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    user_service: UserService = Depends(get_user_service)
):
    """创建用户（仅超级管理员）"""
    try:
        user = user_service.create_user(user_data)
        return user_service.user_to_dict(user, include_password=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{user_id}", response_model=dict)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    user_service: UserService = Depends(get_user_service)
):
    """更新用户（仅超级管理员）"""
    if user_id == current_user.user_id and user_data.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    
    try:
        user = user_service.update_user(user_id, user_data)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user_service.user_to_dict(user, include_password=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    user_service: UserService = Depends(get_user_service)
):
    """删除用户（仅超级管理员）"""
    if user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    success = user_service.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted successfully"}


@router.post("/users/{user_id}/change-password")
async def change_password(
    user_id: str,
    request: dict,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service)
):
    """修改密码"""
    old_password = request.get("old_password", "")
    new_password = request.get("new_password", "")
    
    if not new_password:
        raise HTTPException(status_code=400, detail="New password is required")
    
    # 只能修改自己的密码，或者超级管理员可以修改任何人的密码
    if user_id != current_user.user_id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Can only change your own password")
    
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 如果不是超级管理员，需要验证旧密码
    if current_user.role != UserRole.SUPER_ADMIN:
        if not old_password:
            raise HTTPException(status_code=400, detail="Old password is required")
        if not user_service.verify_password(old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Incorrect old password")
    
    user_data = UserUpdate(password=new_password)
    user_service.update_user(user_id, user_data)
    return {"message": "Password changed successfully"}

