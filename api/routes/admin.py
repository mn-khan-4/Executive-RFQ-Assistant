from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from config.database import SessionLocal
from database.models import User, AuditLog, Thread, Email, Attachment
from auth.dependencies import get_current_admin, get_current_superadmin
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/admin", tags=["admin"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class AdminStats(BaseModel):
    total_users: int
    active_users: int
    total_threads: int
    total_emails: int
    total_attachments: int
    total_meetings: int
    total_errors: int

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: Optional[str] = 'user'

class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[str] = None # 'user' or 'admin'

@router.get("/stats")
async def get_admin_stats(current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Get platform-wide statistics including chart data for widgets."""
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    total_threads = db.query(Thread).count()
    total_emails = db.query(Email).count()
    total_attachments = db.query(Attachment).count()
    
    # Count meetings (from email metadata)
    total_meetings = db.query(Email).filter(Email.meta_data.op('->>')('has_meeting') == 'true').count()
    
    # Distribution for Charts
    status_counts = db.query(Thread.status, func.count(Thread.id)).group_by(Thread.status).all()
    status_distribution = {s if s else "unknown": c for s, c in status_counts}
    
    # User activity distribution (Audit Logs)
    log_counts = db.query(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action).limit(8).all()
    action_distribution = {a if a else "other": c for a, c in log_counts}
    
    # Error count
    total_errors = db.query(AuditLog).filter(AuditLog.action.like('error_%')).count()
    
    # Unseen/Unprocessed emails count
    unseen_emails = db.query(Email).filter(Email.processed == False, Email.is_junk == False).count()
    
    return {
        "success": True,
        "counts": {
            "total_users": total_users,
            "active_users": active_users,
            "total_threads": total_threads,
            "total_emails": total_emails,
            "unseen_emails": unseen_emails,
            "total_attachments": total_attachments,
            "total_meetings": total_meetings,
            "total_errors": total_errors
        },
        "charts": {
            "thread_status": status_distribution,
            "admin_actions": action_distribution,
            "accuracy": {"9am": 92, "12pm": 95, "3pm": 93, "6pm": 98, "9pm": 94},
            "meetings": {"Booked": total_meetings, "Suggested": 12, "Pending": 5},
            "docs": {"PDF": total_attachments, "Excel": 15, "Word": 10},
            "errors": {"API": 4, "Auth": 2, "Database": 0},
            "conversion": {"Lead": 25, "RFI": 18, "Tender": 5}
        }
    }

@router.get("/users")
async def list_users(current_superadmin: User = Depends(get_current_superadmin), db: Session = Depends(get_db)):
    """List all registered users. SuperAdmin Only."""
    users = db.query(User).order_by(User.id.asc()).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None
        } for u in users
    ]

@router.post("/users")
async def create_user(user_data: UserCreate, request: Request, current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Create a new user. SuperAdmin Only."""
    if current_admin.role != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin privileges required")
    
    # Check if user exists
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Identity already exists")
    
    from auth.security import get_password_hash
    from auth.audit import log_action
    
    new_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=user_data.role,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    log_action(db, user_id=current_admin.id, action="admin_create_user",
               details=f"created_user_id={new_user.id} email={new_user.email} role={new_user.role}",
               ip_address=request.client.host)
               
    return {"success": True, "message": "User identity provisioned"}

@router.get("/users/{user_id}/detail")
async def get_user_detail(user_id: int, current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Get detailed info about a specific user. SuperAdmin Only."""
    if current_admin.role != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin privileges required")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    recent_logs = db.query(AuditLog).filter(AuditLog.user_id == user_id).order_by(AuditLog.timestamp.desc()).limit(10).all()
    emails_processed = db.query(AuditLog).filter(AuditLog.user_id == user_id, AuditLog.action == "email_processed").count()
    drafts_created = db.query(AuditLog).filter(AuditLog.user_id == user_id, AuditLog.action == "draft_created").count()
    
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "last_login": user.last_login
        },
        "stats": {
            "emails_processed": emails_processed,
            "drafts_created": drafts_created
        },
        "recent_activity": [
            {
                "action": log.action,
                "timestamp": log.timestamp,
                "details": log.details
            } for log in recent_logs
        ]
    }

@router.patch("/users/{user_id}")
async def update_user(user_id: int, update_data: UserUpdate, request: Request, current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Update user role or status. SuperAdmin Only."""
    if current_admin.role != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin privileges required")
    
    from auth.audit import log_action
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    old_role = user.role
    old_status = user.is_active
    
    if update_data.is_active is not None:
        user.is_active = update_data.is_active
    if update_data.role is not None:
        if update_data.role not in ["user", "admin", "superadmin"]:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = update_data.role
        
    db.commit()
    log_action(db, user_id=current_admin.id, action="admin_update_user",
               details=f"target_user_id={user_id} role:{old_role}->{user.role} active:{old_status}->{user.is_active}",
               ip_address=request.client.host)
    return {"success": True, "message": "User updated successfully"}

@router.get("/audit")
async def get_audit_logs(limit: int = 100, current_admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Get latest audit logs. SuperAdmin Only."""
    if current_admin.role != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin privileges required")
        
    logs = db.query(AuditLog, User.email, User.full_name).outerjoin(User, AuditLog.user_id == User.id).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": log.AuditLog.id,
            "action": log.AuditLog.action,
            "details": log.AuditLog.details,
            "timestamp": log.AuditLog.timestamp.isoformat(),
            "ip_address": log.AuditLog.ip_address,
            "user_email": log.email or "system",
            "user_name": log.full_name or "System"
        } for log in logs
    ]
