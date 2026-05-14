"""
Draft Manager - Save RFI emails as drafts in Gmail/Outlook
Handles draft creation without sending emails
"""

import os
import json
import base64
import requests
from pathlib import Path
from email.mime.text import MIMEText
from typing import Dict, Optional, List
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session
from database.models import MailAccount


class DraftManager:
    """Manage draft email creation in Gmail and Outlook"""
    
    def __init__(self, user_id: int = None, db: Session = None):
        self.user_id = user_id
        self.db = db
        self.gmail_token_file = Path('.gmail_oauth_token.json')
        self.outlook_token_file = Path('.outlook_oauth_token.json')
    
    def create_gmail_draft(self, 
                          to: str, 
                          subject: str, 
                          body: str,
                          cc: Optional[str] = None,
                          attachments: Optional[List[Dict]] = None) -> Dict:
        """
        Create draft email in Gmail with attachments
        """
        import time
        from email.mime.multipart import MIMEMultipart
        from email.mime.application import MIMEApplication
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                token_data = None
                if self.user_id and self.db:
                    mail_account = self.db.query(MailAccount).filter_by(
                        user_id=self.user_id, provider="gmail"
                    ).first()
                    if mail_account:
                        token_data = mail_account.meta_data
                        if isinstance(token_data, str):
                            token_data = json.loads(token_data)

                # Fallback to file
                if not token_data and self.gmail_token_file.exists():
                    with open(self.gmail_token_file) as f:
                        token_data = json.load(f)
                
                if not token_data:
                    raise Exception("Gmail token not found. Please authenticate first.")
                
                # Create credentials
                creds = Credentials(
                    token=token_data.get('token') or token_data.get('access_token'),
                    refresh_token=token_data.get('refresh_token'),
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=os.getenv('GMAIL_CLIENT_ID'),
                    client_secret=os.getenv('GMAIL_CLIENT_SECRET')
                )
                
                service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
                
                # Create message
                if attachments:
                    message = MIMEMultipart()
                    message.attach(MIMEText(body))
                else:
                    message = MIMEText(body)
                    
                message['to'] = to
                message['subject'] = subject
                if cc:
                    message['cc'] = cc
                
                # Add attachments
                if attachments:
                    for att in attachments:
                        part = MIMEApplication(att['content'])
                        part.add_header('Content-Disposition', 'attachment', filename=att['filename'])
                        message.attach(part)
                
                # Encode message
                raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
                
                # Create draft
                draft_body = {'message': {'raw': raw_message}}
                
                draft = service.users().drafts().create(userId='me', body=draft_body).execute()
                
                return {
                    'success': True,
                    'draft_id': draft['id'],
                    'message_id': draft['message']['id'],
                    'provider': 'gmail'
                }
                
            except Exception as e:
                error_str = str(e)
                if ("timeout" in error_str.lower() or "handshake" in error_str.lower()) and attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return {'success': False, 'error': error_str, 'provider': 'gmail'}
    
    def create_outlook_draft(self,
                            to: str,
                            subject: str,
                            body: str,
                            cc: Optional[str] = None,
                            attachments: Optional[List[Dict]] = None) -> Dict:
        """
        Create draft email in Outlook with attachments
        """
        import time
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                token_data = None
                if self.user_id and self.db:
                    mail_account = self.db.query(MailAccount).filter_by(
                        user_id=self.user_id, provider="outlook"
                    ).first()
                    if mail_account:
                        import json
                        token_data = {
                            "access_token": mail_account.token,
                            "refresh_token": mail_account.refresh_token,
                            "meta_data": mail_account.meta_data
                        }

                # Fallback to file
                if not token_data and self.outlook_token_file.exists():
                    with open(self.outlook_token_file) as f:
                        token_data = json.load(f)
                
                if not token_data:
                    raise Exception("Outlook token not found. Please authenticate first.")
                
                headers = {
                    'Authorization': f"Bearer {token_data['access_token']}",
                    'Content-Type': 'application/json'
                }
                
                # Prepare draft data
                draft_data = {
                    'subject': subject,
                    'body': {
                        'contentType': 'Text',
                        'content': body
                    },
                    'toRecipients': [{'emailAddress': {'address': to}}]
                }
                
                if cc:
                    draft_data['ccRecipients'] = [{'emailAddress': {'address': cc}}]
                
                # Create draft
                response = requests.post(
                    'https://graph.microsoft.com/v1.0/me/messages',
                    headers=headers,
                    json=draft_data,
                    timeout=30
                )
                
                response.raise_for_status()
                result = response.json()
                draft_id = result['id']
                
                # Add attachments if any
                if attachments:
                    for att in attachments:
                        att_url = f'https://graph.microsoft.com/v1.0/me/messages/{draft_id}/attachments'
                        att_payload = {
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "name": att['filename'],
                            "contentBytes": base64.b64encode(att['content']).decode('utf-8')
                        }
                        requests.post(att_url, headers=headers, json=att_payload, timeout=30)
                
                return {
                    'success': True,
                    'draft_id': draft_id,
                    'provider': 'outlook'
                }
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return {'success': False, 'error': str(e), 'provider': 'outlook'}
    
    def create_draft(self,
                    provider: str,
                    to: str,
                    subject: str,
                    body: str,
                    cc: Optional[str] = None,
                    attachments: Optional[List[Dict]] = None) -> Dict:
        """
        Create draft email in specified provider
        """
        if provider.lower() == 'gmail':
            return self.create_gmail_draft(to, subject, body, cc, attachments)
        elif provider.lower() == 'outlook':
            return self.create_outlook_draft(to, subject, body, cc, attachments)
        else:
            return {'success': False, 'error': f"Unsupported provider: {provider}", 'provider': provider}


# Test function
if __name__ == "__main__":
    # Test draft creation
    manager = DraftManager()
    
    # Test Gmail draft
    print("Testing Gmail draft creation...")
    result = manager.create_gmail_draft(
        to="test@example.com",
        subject="Test Draft - RFI",
        body="This is a test draft email.\n\nBest regards,\nRFQ Agent"
    )
    print(f"Result: {result}")
