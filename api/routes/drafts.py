from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional, List
from database.models import DraftReply, Email, Thread, User
from config.database import get_db
from auth.dependencies import get_current_user
from agents.rfq_agent.outlook_graph import OutlookGraphFetcher
from agents.rfq_agent.gmail_api_client import GmailAPIFetcher
import json
from datetime import datetime

router = APIRouter(tags=["drafts"])

class DraftUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None

class DraftEnhance(BaseModel):
    instructions: str

@router.get("/api/drafts")
@router.get("/api/drafts/")
async def get_drafts(thread_id: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(DraftReply).filter(DraftReply.user_id == current_user.id)
    if thread_id:
        query = query.filter(DraftReply.thread_id == thread_id)
    drafts = query.order_by(DraftReply.created_at.desc()).all()
    return {"success": True, "data": drafts}

@router.get("/api/drafts/{draft_id}")
async def get_draft_detail(draft_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id, DraftReply.user_id == current_user.id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"success": True, "data": draft}

@router.put("/api/drafts/{draft_id}")
async def update_draft(draft_id: int, draft_data: DraftUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id, DraftReply.user_id == current_user.id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft_data.subject is not None:
        draft.subject = draft_data.subject
    if draft_data.body is not None:
        draft.body = draft_data.body
    db.commit()
    return {"success": True, "message": "Draft updated"}

@router.post("/api/drafts/{draft_id}/send")
async def send_draft(draft_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id, DraftReply.user_id == current_user.id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    provider = draft.email_provider.lower()
    success = False
    error = None
    try:
        if provider == 'outlook':
            fetcher = OutlookGraphFetcher(user_id=current_user.id, db=db)
            if fetcher.connect():
                result = fetcher.send_draft(draft.provider_draft_id)
                success = result.get('success', False)
                error = result.get('error')
        elif provider == 'gmail':
            fetcher = GmailAPIFetcher(user_id=current_user.id, db=db)
            if fetcher.connect(): # Added connect() check for consistency
                result = fetcher.send_draft(draft.provider_draft_id)
                success = result.get('success', False)
                error = result.get('error')
        if success:
            draft.status = 'SENT'
            draft.sent_at = datetime.utcnow()
            db.commit()
            return {"success": True, "message": "Email sent successfully"}
        else:
            return {"success": False, "error": error or "Failed to send via provider"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/drafts/{draft_id}")
async def delete_draft(draft_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id, DraftReply.user_id == current_user.id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    db.delete(draft)
    db.commit()
    return {"success": True, "message": "Draft deleted"}
