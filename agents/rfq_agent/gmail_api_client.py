"""
Gmail Email Fetcher using Gmail API with OAuth2
Works with personal Gmail accounts
"""
import os
import json
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Database imports
from database.models import MailAccount
from sqlalchemy.orm import Session
# Defer heavy Google imports to inside methods to prevent startup hangs
# but consolidate common ones used repeatedly
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import base64
import email
import io
from email.message import EmailMessage
from email.policy import default
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import mimetypes


class GmailAPIFetcher:
    """Fetch Gmail emails using Gmail API"""
    
    def __init__(self, user_id: int = None, db: Session = None):
        self.user_id = user_id
        self.db = db
        self.token_file = Path('.gmail_oauth_token.json')
        self.credentials = None
        self.service = None
    
    def _load_credentials(self) -> 'Credentials':
        """Load OAuth2 credentials from database or file"""
        token_data = None
        mail_account = None

        if self.user_id and self.db:
            # Load from database
            mail_account = self.db.query(MailAccount).filter_by(
                user_id=self.user_id, provider="gmail"
            ).first()
            if mail_account:
                # Gmail tokens are often stored as JSON in the database or serialized
                # Based on api/routes/emails.py, it's saved as creds.token etc.
                # but meta_data contains the full JSON
                token_data = mail_account.meta_data
                if isinstance(token_data, str):
                    token_data = json.loads(token_data)
        
        # Fallback to file for legacy
        if not token_data and self.token_file.exists():
            try:
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
            except Exception as e:
                print(f"Error loading legacy Gmail token file: {e}")

        if not token_data:
            raise Exception(
                "No Gmail OAuth token found! "
                "Please authenticate first via the Settings page."
            )
        
        try:
            # We already loaded token_data above
            
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request as GoogleRequest
            
            credentials = Credentials(
                token=token_data.get('token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri'),
                client_id=token_data.get('client_id'),
                client_secret=token_data.get('client_secret'),
                scopes=token_data.get('scopes')
            )
            
            # Auto-refresh if expired
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(GoogleRequest())
                
                # Save refreshed token
                token_data['token'] = credentials.token
                
                # Save back to DB if we have it
                if mail_account:
                    mail_account.token = credentials.token
                    mail_account.refresh_token = credentials.refresh_token
                    mail_account.token_expiry = credentials.expiry
                    # Update meta_data with new token
                    if isinstance(mail_account.meta_data, dict):
                        mail_account.meta_data['token'] = credentials.token
                    self.db.commit()

                # Also update legacy file if it exists
                if self.token_file.exists():
                    with open(self.token_file, 'w') as f:
                        json.dump(token_data, f, indent=2)
            
            return credentials
        
        except Exception as e:
            raise Exception(f"Error loading Gmail credentials: {e}")
    
    def connect(self, verify: bool = False) -> bool:
        """Connect to Gmail API"""
        try:
            self.credentials = self._load_credentials()
            self.service = build('gmail', 'v1', credentials=self.credentials)
            
            if verify:
                # Test connection only if requested (saves 1 roundtrip)
                profile = self.service.users().getProfile(userId='me').execute()
                email = profile.get('emailAddress')
                print(f"[OK] Connected to Gmail API: {email}")
            
            return True
        
        except Exception as e:
            print(f"[X] Gmail API connection failed: {e}")
            return False
    
    def fetch_tender_emails(self, limit: int = 10) -> List[Dict]:
        """
        Fetch tender-related emails from Gmail
        
        Returns list of email dictionaries compatible with EmailFetcher interface
        """
        try:
            # Ultra-Strict query for Primary Inbox Only (exclude categories)
            query = 'label:unread label:INBOX -category:promotions -category:social'
            print(f"DEBUG: Searching Gmail with query: '{query}'")
            
            # Search emails
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=limit
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                return []
            
            print(f" Found {len(messages)} unread email(s) in Primary Inbox")
            
            # Fetch full email data
            emails = []
            for msg in messages:
                email_data = self._fetch_email_details(msg['id'])
                if email_data:
                    emails.append(email_data)
            
            return emails
        
        except Exception as e:
            print(f"[X] Error fetching emails: {e}")
            return []

    def mark_as_read(self, email_id: str) -> bool:
        """Mark an email as read by removing the UNREAD label"""
        try:
            # Strip prefix if present (e.g. 'gmail_12345' -> '12345')
            raw_id = email_id.replace('gmail_', '')
            print(f"  [GMAIL] Attempting to mark read for ID: {raw_id}")
            
            self.service.users().messages().modify(
                userId='me',
                id=raw_id,
                body={
                    'removeLabelIds': ['UNREAD']
                }
            ).execute()
            print(f"  [+] SUCCESS: Marked as read in Gmail: {raw_id}")
            return True
        except Exception as e:
            print(f"  [!] FAILED: Could not mark {email_id} as read. Error: {e}")
            return False

    def fetch_sent_emails(self, limit: int = 10) -> List[Dict]:
        """Fetch recently sent emails to learn writing style"""
        try:
            results = self.service.users().messages().list(
                userId='me',
                q='label:SENT',
                maxResults=limit
            ).execute()
            
            messages = results.get('messages', [])
            emails = []
            for msg in messages:
                email_data = self._fetch_email_details(msg['id'])
                if email_data:
                    emails.append(email_data)
            return emails
        except Exception as e:
            print(f"[X] Error fetching sent emails: {e}")
            return []
    
    def _fetch_email_details(self, message_id: str) -> Optional[Dict]:
        """Fetch full email details"""
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract headers
            headers = {h['name']: h['value'] for h in message['payload']['headers']}
            
            subject = headers.get('Subject', '(No Subject)')
            from_addr = headers.get('From', '')
            date_str = headers.get('Date', '')
            
            # Extract body
            body = self._extract_body(message['payload'])
            
            # Extract attachments
            attachments = self._extract_attachments(message_id, message['payload'])
            
            # Standardize sender to only email address
            from email.utils import parseaddr
            _, sender_email = parseaddr(from_addr)
            
            # Extract Threading Headers (RFC 822)
            message_id_header = headers.get('Message-ID', '')
            in_reply_to_header = headers.get('In-Reply-To', '')
            
            return {
                'email_id': message_id,
                'message_id': message_id_header,
                'in_reply_to': in_reply_to_header,
                'conversation_id': message.get('threadId'), # Gmail Thread ID
                'subject': subject,
                'sender': sender_email,
                'sender_name': from_addr,
                'date': date_str,
                'body': body,
                'attachments': attachments
            }
        
        except Exception as e:
            print(f"Warning: Error fetching email {message_id}: {e}")
            return None
    
    def move_to_processed(self, email_data: Dict) -> bool:
        """Move email to processed label and mark as read"""
        try:
            message_id = email_data['email_id']
            # Remove provider prefix if present (e.g., 'gmail_12345' -> '12345')
            if '_' in message_id:
                message_id = message_id.split('_')[-1]
            
            # Get or create "RFQ_Processed" label
            label_id = self._get_or_create_label('RFQ_Processed')
            
            if not label_id:
                # Fallback: just mark as read
                self.service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                print(f"[OK] Email marked as read (Label not found)")
                return True
            
            # Add label, remove from inbox, and remove UNREAD
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={
                    'addLabelIds': [label_id],
                    'removeLabelIds': ['INBOX', 'UNREAD']
                }
            ).execute()
            
            print(f"[OK] Email moved to processed label and marked as read")
            return True
        
        except Exception as e:
            print(f"Warning: Error moving email {email_data.get('email_id')}: {e}")
            return False

    def _get_or_create_label(self, label_name: str) -> Optional[str]:
        """Get label ID or create if doesn't exist"""
        try:
            # List all labels
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            # Check if label exists
            for label in labels:
                if label['name'] == label_name:
                    return label['id']
            
            # Create label
            label_object = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            
            created_label = self.service.users().labels().create(
                userId='me',
                body=label_object
            ).execute()
            
            return created_label['id']
        
        except Exception as e:
            print(f"Warning: Error with labels: {e}")
            return None

    def mark_as_read(self, message_id: str) -> bool:
        """Mark email as read by removing UNREAD label"""
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            print(f"[OK] Email {message_id[:10]}... marked as read")
            return True
        except Exception as e:
            print(f"Warning: Could not mark email as read: {e}")
            return False
    
    def _extract_body(self, payload: Dict) -> str:
        """Extract email body from payload recursively"""
        body = ""
        
        # If this is a part, try to get data
        if 'body' in payload and payload['body'].get('data'):
            data = payload['body']['data']
            try:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            except:
                pass

        # If we have parts, recurse and prioritize text/plain or text/html
        if 'parts' in payload:
            parts = payload['parts']
            
            # First pass: try to find text/plain
            for part in parts:
                if part.get('mimeType') == 'text/plain':
                    part_body = self._extract_body(part)
                    if part_body: return part_body
            
            # Second pass: try to find text/html if no plain text
            for part in parts:
                if part.get('mimeType') == 'text/html':
                    part_body = self._extract_body(part)
                    if part_body: return part_body
                    
            # Third pass: just recurse into everything else
            for part in parts:
                part_body = self._extract_body(part)
                if part_body: return part_body
        
        return body

    def _extract_attachments(self, message_id: str, payload: Dict) -> List[Dict]:
        """Extract attachments from email recursively"""
        attachments = []
        
        def _get_parts_with_attachments(parts):
            for part in parts:
                filename = part.get('filename')
                attachment_id = part.get('body', {}).get('attachmentId')
                
                if filename and attachment_id:
                    try:
                        attachment = self.service.users().messages().attachments().get(
                            userId='me',
                            messageId=message_id,
                            id=attachment_id
                        ).execute()
                        
                        data = base64.urlsafe_b64decode(attachment['data'])
                        
                        attachments.append({
                            'filename': filename,
                            'content': data,
                            'content_type': part.get('mimeType', 'application/octet-stream'),
                            'size': attachment.get('size', 0)
                        })
                    except Exception as e:
                        print(f"Warning: Could not download attachment {filename}: {e}")
                
                # Recursive call for nested parts
                if 'parts' in part:
                    _get_parts_with_attachments(part['parts'])
 
        if 'parts' in payload:
            _get_parts_with_attachments(payload['parts'])
        
        return attachments

    # ==========================================
    # DRAFT EMAIL MANAGEMENT METHODS
    # ==========================================

    def create_draft(self, to: str, subject: str, body: str, in_reply_to: str = None, attachments: List[Dict] = None) -> Dict:
        """Create a draft email in Gmail with optional attachments"""
        try:
            from email.utils import parseaddr
            
            # Create message container
            if attachments:
                message = MIMEMultipart()
                message.attach(MIMEText(body))
            else:
                message = MIMEText(body)
            
            message['to'] = to
            message['subject'] = subject

            # If replying, add headers
            if in_reply_to:
                message['In-Reply-To'] = in_reply_to
                message['References'] = in_reply_to

            # Add attachments
            if attachments:
                for att in attachments:
                    part = MIMEApplication(att['content'])
                    part.add_header('Content-Disposition', 'attachment', filename=att['filename'])
                    message.attach(part)

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            draft_body = {'message': {'raw': raw_message}}
            
            draft = self.service.users().drafts().create(userId='me', body=draft_body).execute()
            
            return {
                'success': True,
                'draft_id': draft['id'],
                'subject': subject
            }
        except Exception as e:
            print(f"[X] Error creating Gmail draft: {e}")
            return {'success': False, 'error': str(e)}

    def add_attachment_to_draft(self, draft_id: str, filename: str, content: bytes) -> Dict:
        """Add an attachment to an existing Gmail draft by recreating it"""
        try:
            # Get the draft in raw format to preserve everything
            draft = self.service.users().drafts().get(userId='me', id=draft_id, format='raw').execute()
            
            # Decode existing message using modern policy
            raw_existing = base64.urlsafe_b64decode(draft['message']['raw'])
            msg = email.message_from_bytes(raw_existing, policy=default)

            # Detect MIME type
            maintype, subtype = 'application', 'octet-stream'
            ctype, encoding = mimetypes.guess_type(filename)
            if ctype:
                maintype, subtype = ctype.split('/', 1)

            # Add attachment - modern EmailMessage handles conversion to multipart automatically
            msg.add_attachment(
                content,
                maintype=maintype,
                subtype=subtype,
                filename=filename
            )

            # Encode updated message
            msg_bytes = msg.as_bytes()
            raw_updated = base64.urlsafe_b64encode(msg_bytes).decode('utf-8')
            updated_draft_body = {'id': draft_id, 'message': {'raw': raw_updated}}
            
            # Use Resumable Media Upload for better speed/reliability with large files
            # Note: For drafts, we still send the JSON but we can wrap the whole updated draft 
            # if we were using a different endpoint. For now, let's optimize the request.
            # Actually, standard update is fine for metadata. For RAW messages, 
            # we can use MediaIoBaseUpload if we send JUST the raw bytes to the 'upload' path.
            
            # Optimization: If the message is large (> 1MB), use resumable upload
            if len(msg_bytes) > 1 * 1024 * 1024:
                print(f"DEBUG: Large draft detected ({len(msg_bytes)/1024/1024:.2f} MB). Using resumable upload.")
                from googleapiclient.http import MediaIoBaseUpload
                import io
                
                fh = io.BytesIO(msg_bytes)
                media = MediaIoBaseUpload(fh, mimetype='message/rfc822', resumable=True)
                
                # We need to use the 'upload' version of the API
                result = self.service.users().drafts().update(
                    userId='me', 
                    id=draft_id, 
                    body={'id': draft_id}, # Metadata
                    media_body=media
                ).execute()
            else:
                result = self.service.users().drafts().update(
                    userId='me', 
                    id=draft_id, 
                    body=updated_draft_body
                ).execute()
            
            return {'success': True, 'draft_id': result['id']}
        except Exception as e:
            print(f"[X] Error adding attachment to Gmail draft: {e}")
            return {'success': False, 'error': str(e)}

    def update_draft(self, draft_id: str, subject: str = None, body: str = None) -> Dict:
        """Update an existing Gmail draft"""
        try:
            # Gmail update requires re-sending the whole message raw
            draft = self.service.users().drafts().get(userId='me', id=draft_id, format='raw').execute()
            
            from email.mime.text import MIMEText
            import base64
            from email import message_from_bytes

            # Decode existing message
            raw_existing = base64.urlsafe_b64decode(draft['message']['raw'])
            msg = message_from_bytes(raw_existing)

            if subject is not None:
                msg.replace_header('subject', subject)
            
            if body is not None:
                # Update body (MIMEText payload)
                msg.set_payload(body)

            raw_updated = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
            
            updated_draft_body = {'id': draft_id, 'message': {'raw': raw_updated}}
            
            result = self.service.users().drafts().update(userId='me', id=draft_id, body=updated_draft_body).execute()
            
            return {
                'success': True,
                'draft_id': result['id']
            }
        except Exception as e:
            print(f"[X] Error updating Gmail draft: {e}")
            return {'success': False, 'error': str(e)}

    def send_draft(self, draft_id: str) -> Dict:
        """Send a Gmail draft"""
        try:
            result = self.service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
            return {
                'success': True,
                'draft_id': result.get('id', draft_id)
            }
        except Exception as e:
            print(f"[X] Error sending Gmail draft: {e}")
            return {'success': False, 'error': str(e)}

    def send_immediate_email(self, to: str, subject: str, body: str) -> Dict:
        """Send an email directly without creating a draft first"""
        try:
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            create_body = {'raw': raw_message}
            
            result = self.service.users().messages().send(userId='me', body=create_body).execute()
            return {'success': True, 'message_id': result['id']}
        except Exception as e:
            print(f"[X] Error sending immediate email: {e}")
            return {'success': False, 'error': str(e)}

    def delete_draft(self, draft_id: str) -> Dict:
        """Delete a Gmail draft"""
        try:
            self.service.users().drafts().delete(userId='me', id=draft_id).execute()
            return {'success': True}
        except Exception as e:
            print(f"[X] Error deleting Gmail draft: {e}")
            return {'success': False, 'error': str(e)}
    
    # ==========================================
    # CALENDAR METHODS (Google Calendar API)
    # ==========================================
    
    def fetch_calendar_events(self, days: int = 7) -> List[Dict]:
        """Fetch calendar events for the next X days"""
        try:
            from datetime import timedelta
            # We need the calendar service
            cal_service = build('calendar', 'v3', credentials=self.credentials)
            
            now = datetime.utcnow().isoformat() + 'Z'
            max_time = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'
            
            events_result = cal_service.events().list(
                calendarId='primary',
                timeMin=now,
                timeMax=max_time,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            formatted_events = []
            
            for ev in events:
                start = ev['start'].get('dateTime', ev['start'].get('date'))
                end = ev['end'].get('dateTime', ev['end'].get('date'))
                
                formatted_events.append({
                    'id': ev['id'],
                    'title': ev.get('summary', 'No Title'),
                    'start': start,
                    'end': end,
                    'source': 'google',
                    'location': ev.get('location', ''),
                    'link': ev.get('htmlLink', ''),
                    'description': ev.get('description', ''),
                    'attendees': [a.get('email', '') for a in ev.get('attendees', [])]
                })
            
            return formatted_events
        except Exception as e:
            print(f"[X] Error fetching Google Calendar events: {e}")
            return []

    def create_calendar_event(self, title: str, start_iso: str, end_iso: str, attendees: List[str] = None, description: str = "") -> Dict:
        """Create a new calendar event in Google Calendar"""
        try:
            cal_service = build('calendar', 'v3', credentials=self.credentials)
            
            event = {
                'summary': title,
                'location': 'RFI Managed Meeting',
                'description': description,
                'start': {
                    'dateTime': start_iso,
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_iso,
                    'timeZone': 'UTC',
                },
                'attendees': [{'email': email} for email in (attendees or [])],
                'reminders': {
                    'useDefault': True
                },
            }
            
            event = cal_service.events().insert(calendarId='primary', body=event).execute()
            return {'success': True, 'event': event}
        except Exception as e:
            print(f"[X] Error creating Google event: {e}")
            return {'success': False, 'error': str(e)}

    def disconnect(self):
        """Cleanup (no persistent connection for API)"""
        print("[OK] Disconnected from Gmail API")


# Test function
if __name__ == "__main__":
    print("Testing Gmail API Connection...")
    print()
    
    fetcher = GmailAPIFetcher()
    
    if fetcher.connect():
        print("\nFetching emails...")
        emails = fetcher.fetch_tender_emails(limit=5)
        
        print(f"\nFound {len(emails)} emails:")
        for email in emails:
            print(f"\n- Subject: {email['subject']}")
            print(f"  From: {email['sender']}")
            print(f"  Attachments: {len(email['attachments'])}")
        
        fetcher.disconnect()
        print("\nTest successful!")
    else:
        print("\nTest failed - could not connect")
