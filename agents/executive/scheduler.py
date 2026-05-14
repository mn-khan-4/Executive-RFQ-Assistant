import os
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import msal
import requests
from sqlalchemy.orm import Session
from database.models import MailAccount

class GoogleCalendarClient:
    """Interface to Google Calendar for Free/Busy lookups"""
    def __init__(self, user_id: int = None, db: Session = None):
        self.user_id = user_id
        self.db = db
        self.token_file = Path('.gmail_oauth_token.json')
        self.service = None

    def connect(self) -> bool:
        token_data = None
        mail_account = None

        if self.user_id and self.db:
            mail_account = self.db.query(MailAccount).filter_by(
                user_id=self.user_id, provider="gmail"
            ).first()
            if mail_account:
                token_data = mail_account.meta_data
                if isinstance(token_data, str):
                    token_data = json.loads(token_data)

        if not token_data and self.token_file.exists():
            try:
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
            except: pass

        if not token_data:
            return False
            
        try:
            
            creds = Credentials(
                token=token_data.get('token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri'),
                client_id=token_data.get('client_id'),
                client_secret=token_data.get('client_secret'),
                scopes=token_data.get('scopes')
            )
            
            if creds.expired and creds.refresh_token:
                creds.refresh(GoogleRequest())
                token_data['token'] = creds.token
                
                if mail_account:
                    mail_account.token = creds.token
                    if isinstance(mail_account.meta_data, dict):
                        mail_account.meta_data['token'] = creds.token
                    self.db.commit()

                if self.token_file.exists():
                    with open(self.token_file, 'w') as f:
                        json.dump(token_data, f, indent=2)
            
            self.service = build('calendar', 'v3', credentials=creds)
            return True
        except Exception as e:
            print(f"Google Calendar Connection Error: {e}")
            return False

    def get_upcoming_events(self, days=3) -> List[Dict]:
        """Get busy slots for the next X days"""
        if not self.service: return []
        
        # Calculate range
        start_dt = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=days)
        
        # Ensure timeMin < timeMax for API
        t_min = min(start_dt, end_dt).isoformat() + 'Z'
        t_max = max(start_dt, end_dt).isoformat() + 'Z'
        
        print(f"[Google] Fetching events from {t_min} to {t_max}...")
        try:
            events_result = self.service.events().list(
                calendarId='primary', 
                timeMin=t_min,
                timeMax=t_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            items = events_result.get('items', [])
            print(f"[Google] Found {len(items)} events")
            return items
        except Exception as e:
            print(f"[Google] Event Fetch Error: {e}")
            return []

    def create_event(self, summary: str, start_time: str, end_time: str, description: str = "", attendees: List[str] = [], send_updates: str = 'all') -> Dict:
        """Create a new event on Google Calendar"""
        if not self.service: return {"success": False, "error": "Not connected"}
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
            },
            'attendees': [{'email': email} for email in attendees],
            'conferenceData': {
                'createRequest': {
                    'requestId': f"meet_{int(datetime.now().timestamp())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
        }
        
        try:
            created_event = self.service.events().insert(
                calendarId='primary', 
                body=event,
                conferenceDataVersion=1,
                sendUpdates=send_updates
            ).execute()
            # Return the full object so we can access hangoutLink
            created_event['success'] = True
            return created_event
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_event(self, event_id: str) -> Dict:
        """Delete an event from Google Calendar"""
        if not self.service: return {"success": False, "error": "Not connected"}
        try:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return {"success": True}
        except Exception as e:
            # If already deleted, consider it success
            if "Resource has been deleted" in str(e) or "410" in str(e):
                return {"success": True}
            return {"success": False, "error": str(e)}

class OutlookCalendarClient:
    """Interface to Microsoft Graph for Calendar lookups"""
    def __init__(self, user_id: int = None, db: Session = None):
        from agents.rfq_agent.outlook_graph import OutlookGraphFetcher
        self.fetcher = OutlookGraphFetcher(user_id=user_id, db=db)

    def connect(self) -> bool:
        return self.fetcher.connect()

    def get_upcoming_events(self, days=3) -> List[Dict]:
        # Calculate range
        start_dt = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=days)
        
        # Ensure startDateTime < endDateTime for API
        t_min = min(start_dt, end_dt).isoformat() + 'Z'
        t_max = max(start_dt, end_dt).isoformat() + 'Z'
        
        url = f"https://graph.microsoft.com/v1.0/me/calendar/calendarView?startDateTime={t_min}&endDateTime={t_max}"
        
        print(f"[Outlook] Fetching events from {t_min} to {t_max}...")
        try:
            headers = self.fetcher._get_headers()
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                items = response.json().get('value', [])
                print(f"[Outlook] Found {len(items)} events")
                return items
            else:
                print(f"[Outlook] Fetch failed with status {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[Outlook] Calendar Event Fetch Error: {e}")
        return []

    def create_event(self, subject: str, start_time: str, end_time: str, body_preview: str = "", attendees: List[str] = [], send_updates: bool = True) -> Dict:
        """Create a new event on Outlook Calendar"""
        if not self.connect(): return {"success": False, "error": "Not connected"}
        
        url = "https://graph.microsoft.com/v1.0/me/events"
        if not send_updates:
            url += "?sendInvitations=none"
        
        event = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_preview
            },
            "start": {
                "dateTime": start_time,
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_time,
                "timeZone": "UTC"
            },
            "attendees": [
                {
                    "emailAddress": {
                        "address": email,
                        "name": email
                    },
                    "type": "required"
                } for email in attendees
            ]
        }
        
        try:
            headers = self.fetcher._get_headers()
            response = requests.post(url, headers=headers, json=event)
            if response.status_code in (201, 200):
                return {"success": True, "id": response.json().get('id')}
            else:
                return {"success": False, "error": response.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_event(self, event_id: str) -> Dict:
        """Delete an event from Outlook Calendar"""
        if not self.connect(): return {"success": False, "error": "Not connected"}
        url = f"https://graph.microsoft.com/v1.0/me/events/{event_id}"
        try:
            headers = self.fetcher._get_headers()
            response = requests.delete(url, headers=headers)
            if response.status_code == 204:
                return {"success": True}
            else:
                return {"success": False, "error": response.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

class ExecutiveScheduler:
    """Orchestrates availability lookups and suggests slots"""
    def __init__(self, provider: str = 'gmail', user_id: int = None, db: Session = None):
        self.provider = provider
        self.user_id = user_id
        self.db = db
        self.client = GoogleCalendarClient(user_id=user_id, db=db) if provider == 'gmail' else OutlookCalendarClient(user_id=user_id, db=db)

    def find_free_slots(self, days=3) -> str:
        """Fetch busy events and return a summary for the LLM"""
        if not self.client.connect():
            return "Could not connect to calendar. Please re-authenticate."
        
        events = self.client.get_upcoming_events(days=days)
        
        if not events:
            return "Calendar is empty for the next 3 days. All slots are available (9 AM - 5 PM)."
        
        summary = "Busy periods for the next 3 days:\n"
        for ev in events:
            start = ev.get('start', {}).get('dateTime', ev.get('start', {}).get('date'))
            end = ev.get('end', {}).get('dateTime', ev.get('end', {}).get('date'))
            summary += f"- From {start} to {end}\n"
            
        return summary
