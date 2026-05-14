import asyncio
from sqlalchemy.orm import Session
from database.models import User, Email
from agents.rfq_agent.style_agent import StyleAgent
from agents.rfq_agent.outlook_graph import OutlookGraphFetcher
from datetime import datetime

async def sync_user_writing_style(user_id: int, provider: str):
    """
    Background task to fetch last 50 sent emails and analyze writing style.
    """
    from config.database import SessionLocal
    db = SessionLocal()
    try:
        print(f"[TASK] Starting style sync for User {user_id} via {provider}...")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"[TASK] User {user_id} not found.")
            return

        emails_to_analyze = []

        if provider == 'outlook':
            fetcher = OutlookGraphFetcher(user_id=user_id, db=db)
            if fetcher.connect():
                # Fetch last 50 sent emails
                sent_emails = fetcher.fetch_sent_emails(limit=50)
                for e in sent_emails:
                    emails_to_analyze.append({
                        "subject": e.get('subject', ''),
                        "body": e.get('body', '')
                    })
        
        elif provider == 'gmail':
            from agents.rfq_agent.gmail_api_client import GmailAPIFetcher
            fetcher = GmailAPIFetcher(user_id=user_id, db=db)
            if fetcher.connect():
                # Fetch last 50 sent emails
                sent_emails = fetcher.fetch_sent_emails(limit=50)
                for e in sent_emails:
                    emails_to_analyze.append({
                        "subject": e.get('subject', ''),
                        "body": e.get('body', '')
                    })

        if emails_to_analyze:
            # 1. Save to Database so manual sync and RFI Assistant can use them
            for e in emails_to_analyze:
                # Basic duplicate check
                exists = db.query(Email).filter(Email.subject == e['subject'], Email.body == e['body']).first()
                if not exists:
                    new_email = Email(
                        subject=e['subject'],
                        body=e['body'],
                        sender=user.email,
                        received_at=datetime.utcnow(),
                        is_sent=True,
                        thread_id="SYNC_HISTORICAL"
                    )
                    db.add(new_email)
            
            db.commit()

            # 2. Analyze Style
            style_agent = StyleAgent()
            guide = style_agent.extract_style_from_emails(emails_to_analyze)
            
            user.writing_style_guide = guide
            user.last_style_sync = datetime.utcnow()
            db.commit()
            print(f"[TASK] Style sync complete for User {user_id}. Guide updated and emails saved.")
        else:
            print(f"[TASK] No sent emails found to analyze for User {user_id}.")

    except Exception as e:
        print(f"[TASK] Error during style sync: {e}")
        db.rollback()
    finally:
        db.close()
