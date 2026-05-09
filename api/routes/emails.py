from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import json
import os
import msal
from pathlib import Path
from config.database import get_db
from database.models import User, Email, MailAccount
from auth.dependencies import get_current_user
from api.tasks import sync_user_writing_style
from config.oauth_config import CLIENT_ID, CLIENT_SECRET, TENANT_ID, SCOPES, TOKEN_FILE, REDIRECT_URI

# Gmail Config
from google_auth_oauthlib.flow import Flow
from config.gmail_oauth_config import (
    GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REDIRECT_URI, GMAIL_SCOPES
)

router = APIRouter(tags=["emails"])

# State storage for OAuth (simplified, should be in Redis/DB in prod)
oauth_sessions = {}

def get_msal_app():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=authority, client_credential=CLIENT_SECRET
    )

@router.get("/api/oauth/login")
@router.get("/api/outlook/oauth/login")
async def outlook_oauth_login():
    msal_app = get_msal_app()
    # Use REDIRECT_URI from config which matches .env
    auth_url = msal_app.get_authorization_request_url(list(SCOPES), redirect_uri=REDIRECT_URI)
    return {"auth_url": auth_url}

@router.get("/api/oauth/callback")
@router.get("/api/outlook/oauth/callback")
@router.get("/oauth/callback") # Alias for console compatibility
async def outlook_oauth_callback(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    code = request.query_params.get('code')
    if not code:
        return HTMLResponse("<h1>Error: No code received</h1>", status_code=400)

    msal_app = get_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code, scopes=list(SCOPES), redirect_uri=REDIRECT_URI
    )

    if "access_token" in result:
        # Save token to mail_accounts table
        email_address = result.get("id_token_claims", {}).get("preferred_username") or result.get("id_token_claims", {}).get("email")
        if not email_address:
            email_address = result.get("userPrincipalName") or "unknown@outlook"
        mail_account = db.query(MailAccount).filter_by(
            user_id=current_user.id, provider="outlook", email_address=email_address
        ).first()
        if not mail_account:
            mail_account = MailAccount(
                user_id=current_user.id,
                provider="outlook",
                email_address=email_address,
                token=result["access_token"],
                refresh_token=result.get("refresh_token"),
                token_expiry=None,
                meta_data=result
            )
            db.add(mail_account)
        else:
            mail_account.token = result["access_token"]
            mail_account.refresh_token = result.get("refresh_token")
            mail_account.meta_data = result
        db.commit()

        background_tasks.add_task(sync_user_writing_style, current_user.id, 'outlook')

        return HTMLResponse(content=f"""
            <html>
                <head>
                    <title>Outlook Connected</title>
                    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
                    <style>
                        body {{ font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f9fafb; }}
                        .card {{ background: white; padding: 40px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); text-align: center; max-width: 400px; }}
                        .icon {{ font-size: 48px; margin-bottom: 20px; }}
                        h1 {{ color: #111827; margin: 0 0 10px 0; font-size: 24px; }}
                        p {{ color: #6b7280; line-height: 1.5; margin: 0; }}
                        .timer {{ margin-top: 25px; font-size: 14px; color: #9ca3af; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="icon">✅</div>
                        <h1>Outlook Connected!</h1>
                        <p>Your executive RFI agent is now synchronized with your Outlook workspace.</p>
                        <div class="timer">Closing in <span id="sec">3</span>s...</div>
                    </div>
                    <script>
                        let s = 3;
                        setInterval(() => {{
                            s--;
                            document.getElementById('sec').innerText = s;
                            if (s <= 0) window.close();
                        }}, 1000);
                        setTimeout(() => window.close(), 3500);
                    </script>
                </body>
            </html>
        """)
    
    return HTMLResponse(f"<h1>Error: {result.get('error_description')}</h1>", status_code=400)

# GMAIL ROUTES
def get_gmail_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GMAIL_CLIENT_ID,
                "client_secret": GMAIL_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GMAIL_REDIRECT_URI]
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=GMAIL_REDIRECT_URI
    )

@router.get("/api/gmail/oauth/login")
async def gmail_oauth_login():
    flow = get_gmail_flow()
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    return {"auth_url": auth_url}

@router.get("/api/gmail/oauth/callback")
@router.get("/gmail/oauth/callback") # Alias for console compatibility
async def gmail_oauth_callback(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    code = request.query_params.get('code')
    flow = get_gmail_flow()
    flow.fetch_token(code=code)

    # Save credentials to mail_accounts table
    creds = flow.credentials
    email_address = creds.id_token.get("email") if creds.id_token else None
    if not email_address:
        email_address = creds._client_id or "unknown@gmail"
    mail_account = db.query(MailAccount).filter_by(
        user_id=current_user.id, provider="gmail", email_address=email_address
    ).first()
    if not mail_account:
        mail_account = MailAccount(
            user_id=current_user.id,
            provider="gmail",
            email_address=email_address,
            token=creds.token,
            refresh_token=getattr(creds, "refresh_token", None),
            token_expiry=getattr(creds, "expiry", None),
            meta_data=json.loads(creds.to_json())
        )
        db.add(mail_account)
    else:
        mail_account.token = creds.token
        mail_account.refresh_token = getattr(creds, "refresh_token", None)
        mail_account.token_expiry = getattr(creds, "expiry", None)
        mail_account.meta_data = json.loads(creds.to_json())
    db.commit()

    background_tasks.add_task(sync_user_writing_style, current_user.id, 'gmail')

    return HTMLResponse(content=f"""
        <html>
            <head>
                <title>Gmail Connected</title>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
                <style>
                    body {{ font-family: 'Inter', sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f9fafb; }}
                    .card {{ background: white; padding: 40px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); text-align: center; max-width: 400px; }}
                    .icon {{ font-size: 48px; margin-bottom: 20px; }}
                    h1 {{ color: #111827; margin: 0 0 10px 0; font-size: 24px; }}
                    p {{ color: #6b7280; line-height: 1.5; margin: 0; }}
                    .timer {{ margin-top: 25px; font-size: 14px; color: #9ca3af; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="icon">📩</div>
                    <h1>Gmail Connected!</h1>
                    <p>Authentication successful. The RFI agent is now connected to your Gmail account.</p>
                    <div class="timer">Closing in <span id="sec">3</span>s...</div>
                </div>
                <script>
                    let s = 3;
                    setInterval(() => {{
                        s--;
                        document.getElementById('sec').innerText = s;
                        if (s <= 0) window.close();
                    }}, 1000);
                    setTimeout(() => window.close(), 3500);
                </script>
            </body>
        </html>
    """)

@router.get("/api/emails")
async def get_emails(thread_id: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Email).filter(Email.user_id == current_user.id)
    # Hide training/historical emails by default unless specifically requested
    if thread_id:
        query = query.filter(Email.thread_id == thread_id)
    else:
        query = query.filter(Email.thread_id != "SYNC_HISTORICAL")
    emails = query.order_by(Email.received_at.desc()).all()
    return {"success": True, "data": emails}

@router.get("/api/emails/{id}")
async def get_single_email(id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = db.query(Email).filter(Email.id == id, Email.user_id == current_user.id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return {"success": True, "data": email}

@router.get("/api/oauth/status")
@router.get("/api/gmail/oauth/status")
async def get_oauth_status(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Query mail_accounts for this user
    gmail_account = db.query(MailAccount).filter_by(user_id=current_user.id, provider="gmail").first()
    outlook_account = db.query(MailAccount).filter_by(user_id=current_user.id, provider="outlook").first()

    gmail_connected = gmail_account is not None and gmail_account.token is not None
    outlook_connected = outlook_account is not None and outlook_account.token is not None

    if "gmail" in request.url.path:
        return {
            "success": True,
            "status": "connected" if gmail_connected else "disconnected",
            "authenticated": gmail_connected
        }

    return {
        "success": True,
        "status": "connected" if outlook_connected else "disconnected",
        "outlook": "connected" if outlook_connected else "disconnected",
        "gmail": "connected" if gmail_connected else "disconnected",
        "authenticated": gmail_connected or outlook_connected
    }
