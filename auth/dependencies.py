def get_current_superadmin(current_user: User = Depends(get_current_user)):
    """Dependency to enforce superadmin-only role."""
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin privileges required"
        )
    return current_user
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
from auth.security import decode_access_token
from config.database import SessionLocal
from database.models import User

def get_current_user(request: Request):
    """ELITE SECURITY: Strictly relies on HttpOnly Cookies. JS-Readable Tokens are DISALLOWED."""
    token = request.cookies.get("access_token")
    
    if not token or token in ["null", "undefined", "None", ""]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Forbidden: No professional session token found",
            headers={"WWW-Authenticate": "Cookie"},
        )
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
        
    user_id_val = payload.get("sub")
    if user_id_val is None:
        raise credentials_exception
        
    db = SessionLocal()
    try:
        # User ID might be string username from old sessions or integer ID from new ones
        if isinstance(user_id_val, str) and not user_id_val.isdigit():
            # Try to look up by email/username if it's an old token
            user = db.query(User).filter(User.email == user_id_val).first()
        else:
            user = db.query(User).filter(User.id == int(user_id_val)).first()
            
        if user is None or not user.is_active:
            raise credentials_exception
        return user
    finally:
        db.close()

def get_current_admin(current_user: User = Depends(get_current_user)):
    """Dependency to enforce admin/superadmin role."""
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have enough privileges"
        )
    return current_user

def get_optional_current_user(request: Request):
    """Optional version of the current user dependency (Cookie Based)."""
    try:
        return get_current_user(request)
    except HTTPException:
        return None
