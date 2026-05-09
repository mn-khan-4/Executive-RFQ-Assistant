from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
from database.models import Thread, Email, Contact, DraftReply, User, AuditLog, Attachment
from config.database import SessionLocal, get_db
from auth.dependencies import get_current_user
from agents.rfq_agent.outlook_graph import OutlookGraphFetcher
from agents.rfq_agent.gmail_api_client import GmailAPIFetcher
from models.pixtral_client import PixtralClient
from pathlib import Path
import time
import asyncio
from datetime import datetime

router = APIRouter(tags=["dashboard"])

# Global state for sync progress
sync_progress = {"status": "Idle", "current": 0, "total": 0, "active": False}

# Performance Caching
STATS_CACHE = {"data": None, "last_updated": 0, "expiry": 60} # 60s cache
MORNING_BRIEF_CACHE = {"data": None, "last_updated": 0, "expiry": 300} # 5min cache

@router.get("/api/dashboard/stats")
async def get_dashboard_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get aggregate statistics for the dashboard with caching"""
    global STATS_CACHE
    now = time.time()
    
    if STATS_CACHE["data"] and (now - STATS_CACHE["last_updated"] < STATS_CACHE["expiry"]):
        return {"success": True, "data": STATS_CACHE["data"]}

    try:
        active_threads = db.query(Thread).filter(Thread.user_id == current_user.id).count()
        total_emails = db.query(Email).filter(Email.user_id == current_user.id).count()
        total_contacts = db.query(Contact).filter(Contact.user_id == current_user.id).count()
        pending_replies = db.query(DraftReply).filter(DraftReply.user_id == current_user.id).count()
        unprocessed_emails = db.query(Email).filter(Email.user_id == current_user.id, Email.processed == False).count()

        # New Construction Intelligence Metrics
        incomplete_tenders = db.query(Thread).filter(Thread.user_id == current_user.id, Thread.status == 'AWAITING_DOCS').count()
        urgent_tasks = db.query(Thread).filter(Thread.user_id == current_user.id, Thread.status == 'URGENT').count()

        # Efficient missing categories check
        awaiting = db.query(Thread).filter(Thread.user_id == current_user.id, Thread.status == 'AWAITING_DOCS').all()
        missing_stats = {}
        mandatory = ['01_Instructions', '02_Scope_of_Work', '03_Drawings', '04_Specifications', '05_BOQ']

        for t in awaiting:
            # Optimize: Get all attachment categories for this thread once
            existing_cats = db.query(Attachment.category).filter(Attachment.thread_id == t.thread_id, Attachment.user_id == current_user.id).all()
            existing_cats_set = {c[0] for c in existing_cats if c[0]}
            for m in mandatory:
                if m not in existing_cats_set:
                    missing_stats[m] = missing_stats.get(m, 0) + 1

        import re
        top_missing = sorted(missing_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        top_missing_data = [{"category": re.sub(r'^\\d+_','', k).replace('_', ' '), "count": v} for k, v in top_missing]

        stats_data = {
            "activeTenders": active_threads,
            "unreadEmails": total_emails,
            "unprocessedEmails": unprocessed_emails,
            "pendingRFIs": pending_replies,
            "totalClients": total_contacts,
            "incompleteTenders": incomplete_tenders,
            "urgentTasks": urgent_tasks,
            "topMissingCategories": top_missing_data,
            "calendarEvents": 0 
        }
        
        # Update cache
        STATS_CACHE["data"] = stats_data
        STATS_CACHE["last_updated"] = now
        
        return {"success": True, "data": stats_data}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Cache for system status to prevent slow startup
STATUS_CACHE = {
    "data": None,
    "last_updated": 0,
    "expiry": 120 # 2 minutes
}

@router.get("/api/status")
async def get_system_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Check connectivity to various system components with caching"""
    global STATUS_CACHE
    now = time.time()
    
    if STATUS_CACHE["data"] and (now - STATUS_CACHE["last_updated"] < STATUS_CACHE["expiry"]):
        return STATUS_CACHE["data"]

    status = {
        "database": False,
        "gmail": False,
        "outlook": "disconnected",
        "llm": False,
        "success": True
    }
    try:
        db.execute(text("SELECT 1"))
        status["database"] = True
    except: pass
    
    try:
        outlook = OutlookGraphFetcher()
        if outlook.connect(): status["outlook"] = "connected"
        elif Path(".outlook_oauth_token.json").exists(): status["outlook"] = "unauthorized"
    except: pass
        
    if Path(".gmail_oauth_token.json").exists(): status["gmail"] = True
        
    try:
        llm = PixtralClient()
        if llm.test_connection(): status["llm"] = True
    except: pass
    
    STATUS_CACHE["data"] = status
    STATUS_CACHE["last_updated"] = now
    return status


@router.get("/api/agent/status")
async def get_agent_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the current processing status of the agent with live logs"""
    global sync_progress

    # Fetch latest logs from AuditLog for the active session
    latest_logs = db.query(AuditLog).filter(AuditLog.user_id == current_user.id).order_by(desc(AuditLog.timestamp)).limit(5).all()

    logs_data = []
    for log in latest_logs:
        logs_data.append({
            "timestamp": log.timestamp.isoformat(),
            "action": log.action,
            "details": log.details or {}
        })

    return {
        **sync_progress,
        "latest_logs": logs_data
    }

@router.get("/api/session-summary")
async def get_session_summary(from_time: str, to_time: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a summary of tender activities within a specific time range"""
    try:
        # Parse ISO strings
        dt_from = datetime.fromisoformat(from_time.replace('Z', '+00:00'))
        dt_to = datetime.fromisoformat(to_time.replace('Z', '+00:00'))

        # Query emails processed in this range for this user
        emails = db.query(Email).filter(
            Email.user_id == current_user.id,
            Email.received_at >= dt_from,
            Email.received_at <= dt_to,
            Email.processed == True
        ).all()

        summary_data = []
        for e in emails:
            # Get attachment count
            doc_count = db.query(Thread).filter(Thread.thread_id == e.thread_id, Thread.user_id == current_user.id).first()
            attachments_count = db.query(Attachment).filter(Attachment.thread_id == e.thread_id, Attachment.user_id == current_user.id).count()

            summary_data.append({
                "email_id": e.email_id,
                "subject": e.subject,
                "sender": e.sender,
                "processed_at": e.received_at.isoformat(),
                "thread_id": e.thread_id,
                "doc_count": attachments_count
            })

        return {
            "success": True,
            "count": len(summary_data),
            "data": summary_data
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/process-emails")
async def trigger_email_processing(background_tasks: BackgroundTasks, current_user: User = Depends(get_current_user)):
    """Trigger the email processing agent in the background"""
    global sync_progress
    
    if sync_progress.get("active"):
        return {"success": True, "message": "Sync already in progress"}
    
    # Reset progress
    sync_progress = {"status": "Starting...", "current": 0, "total": 0, "active": True}
    
    # Start background task
    background_tasks.add_task(run_sync_intelligence, current_user.id)
    
    return {"success": True, "message": "Email processing triggered"}

async def run_sync_intelligence(user_id: int):
    """Background task to fetch and process emails"""
    global sync_progress
    from agents.rfq_agent.email_fetcher import EmailFetcher
    from scripts.run_rfq_agent import process_incoming_email
    from config.database import SessionLocal
    
    db = SessionLocal()
    try:
        sync_progress["status"] = "Connecting to email providers..."
        fetcher_gmail = EmailFetcher(provider='gmail')
        fetcher_outlook = EmailFetcher(provider='outlook')
        
        all_emails = []
        
        # 1. Fetch from Gmail
        if fetcher_gmail.connect():
            sync_progress["status"] = "Fetching Gmail..."
            gmail_emails = fetcher_gmail.fetch_emails(limit=20)
            all_emails.extend([{**e, 'provider': 'gmail'} for e in gmail_emails])
            
        # 2. Fetch from Outlook
        if fetcher_outlook.connect():
            sync_progress["status"] = "Fetching Outlook..."
            outlook_emails = fetcher_outlook.fetch_emails(limit=20)
            all_emails.extend([{**e, 'provider': 'outlook'} for e in outlook_emails])
            
        sync_progress["total"] = len(all_emails)
        sync_progress["status"] = f"Processing {len(all_emails)} emails..."
        
        if not all_emails:
            sync_progress["status"] = "No new emails found"
            sync_progress["active"] = False
            return

        for i, email_data in enumerate(all_emails):
            sync_progress["current"] = i + 1
            sync_progress["status"] = f"Analyzing: {email_data.get('subject', 'No Subject')[:30]}..."
            
            try:
                # Process the email (Multi-agent workflow)
                process_incoming_email(email_data)
                
                # Mark as read/processed in provider
                if email_data['provider'] == 'gmail':
                    fetcher_gmail.mark_as_read(email_data['email_id'])
                else:
                    fetcher_outlook.mark_as_read(email_data['email_id'])
                    
            except Exception as e:
                error_msg = str(e)
                print(f"[SYNC] Error processing email {email_data.get('email_id')}: {error_msg}")
                sync_progress["status"] = f"AI Error: Skipping email..."
                await asyncio.sleep(1) # Give user time to see the error

        sync_progress["status"] = "Sync Complete"
        sync_progress["active"] = False
        
    except Exception as e:
        error_msg = str(e)
        if "openrouter" in error_msg.lower() or "connection" in error_msg.lower():
            sync_progress["status"] = "AI Provider Error (Check Internet/API)"
        else:
            sync_progress["status"] = f"Error: {error_msg[:30]}..."
        sync_progress["active"] = False
    finally:
        db.close()


@router.get("/api/morning-brief")
async def get_morning_brief(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    global MORNING_BRIEF_CACHE
    now = time.time()
    if MORNING_BRIEF_CACHE["data"] and (now - MORNING_BRIEF_CACHE["last_updated"] < MORNING_BRIEF_CACHE["expiry"]):
        return MORNING_BRIEF_CACHE["data"]

    urgent = db.query(Thread).filter(Thread.status == 'URGENT').count()
    awaiting = db.query(Thread).filter(Thread.status == 'AWAITING_DOCS').count()
    
    brief = f"Good morning, {current_user.full_name or 'Abdullah'}. You have {urgent} high-priority threads and {awaiting} tenders awaiting documents."
    data = {"brief": brief, "tasks": []}
    
    MORNING_BRIEF_CACHE["data"] = data
    MORNING_BRIEF_CACHE["last_updated"] = now
    return data

@router.get("/api/tasks")
async def get_tasks(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Identify threads that need attention (e.g. no reply for 3 days)
    # This is a placeholder for actual task logic, but we'll return some threads
    threads = db.query(Thread).filter(Thread.status == 'URGENT').limit(5).all()
    tasks = [{"task": f"Review {t.subject}", "sender": t.contact_name, "subject": t.subject} for t in threads]
    return {"success": True, "data": tasks}

@router.get("/api/followups")
async def get_followups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Follow-ups for threads with no reply
    threads = db.query(Thread).filter(Thread.status == 'AWAITING_DOCS').limit(3).all()
    followups = [{"id": t.id, "subject": t.subject, "contact": t.contact_name} for t in threads]
    return {"success": True, "data": followups}

# Simple in-memory cache for calendar events to improve performance
CALENDAR_CACHE = {
    "data": [],
    "last_updated": 0,
    "expiry": 300 # 5 minutes
}

@router.get("/api/calendar/events")
async def get_calendar_events(days: int = 30, current_user: User = Depends(get_current_user)):
    """Fetch events from both Google and Outlook with simple caching"""
    global CALENDAR_CACHE
    
    now = time.time()
    # Return cached data if not expired and not forcing refresh
    if CALENDAR_CACHE["data"] and (now - CALENDAR_CACHE["last_updated"] < CALENDAR_CACHE["expiry"]):
        return {"success": True, "data": CALENDAR_CACHE["data"], "cached": True}
        
    all_events = []
    
    # 1. Fetch from Outlook
    try:
        if Path(".outlook_oauth_token.json").exists():
            outlook = OutlookGraphFetcher()
            if outlook.connect():
                events = outlook.fetch_calendar_events(days=days)
                all_events.extend(events)
    except Exception as e:
        print(f"Dashboard: Outlook fetch error: {e}")
        
    # 2. Fetch from Gmail/Google
    try:
        if Path(".gmail_oauth_token.json").exists():
            gmail = GmailAPIFetcher()
            if gmail.connect():
                events = gmail.fetch_calendar_events(days=days)
                all_events.extend(events)
    except Exception as e:
        print(f"Dashboard: Google fetch error: {e}")
        
    # Sort by start time
    all_events.sort(key=lambda x: x['start'])
    
    # Update cache
    CALENDAR_CACHE["data"] = all_events
    CALENDAR_CACHE["last_updated"] = now
    
    return {"success": True, "data": all_events}


@router.get("/api/session-summary")
async def get_session_summary(from_time: str, to_time: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get construction pulse summary for a specific time range"""
    try:
        dt_from = datetime.fromisoformat(from_time.replace('Z', '+00:00'))
        dt_to = datetime.fromisoformat(to_time.replace('Z', '+00:00'))
        
        # Count emails processed in this window
        processed_count = db.query(Email).filter(
            Email.received_at >= dt_from,
            Email.received_at <= dt_to
        ).count()
        
        # Count threads created/updated
        threads_updated = db.query(Thread).filter(
            Thread.updated_at >= dt_from,
            Thread.updated_at <= dt_to
        ).count()
        
        # Identify top contacts in this window
        # (This is simplified logic)
        top_threads = db.query(Thread).filter(
            Thread.updated_at >= dt_from,
            Thread.updated_at <= dt_to
        ).limit(5).all()
        
        summaries = []
        for t in top_threads:
            summaries.append({
                "subject": t.subject,
                "contact": t.contact_name,
                "status": t.status,
                "id": t.thread_id
            })

        return {
            "success": True,
            "count": processed_count,
            "threads": threads_updated,
            "summaries": summaries
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/calendar/events")
async def create_calendar_event(data: dict, current_user: User = Depends(get_current_user)):
    """Create an event in either Google or Outlook"""
    provider = data.get('provider', 'google')
    title = data.get('title', 'RFI Meeting')
    start = data.get('start')
    end = data.get('end')
    attendees = data.get('attendees', [])
    description = data.get('description', "")
    
    if not start or not end:
        raise HTTPException(status_code=400, detail="Start and End times required")
        
    try:
        if provider == 'outlook':
            fetcher = OutlookGraphFetcher()
            if not fetcher.connect(): return {"success": False, "error": "Outlook not connected"}
            result = fetcher.create_calendar_event(title, start, end, attendees, description)
            return result
        else:
            fetcher = GmailAPIFetcher()
            if not fetcher.connect(): return {"success": False, "error": "Gmail not connected"}
            result = fetcher.create_calendar_event(title, start, end, attendees, description)
            return result
    except Exception as e:
        return {"success": False, "error": str(e)}
