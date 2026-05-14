"""
Outlook Email Fetcher using Microsoft Graph API
Works with personal Outlook.com accounts
"""
import os
import json
import requests
import msal
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from config.oauth_config import CLIENT_ID, CLIENT_SECRET, TENANT_ID, SCOPES, TOKEN_FILE

# Database imports
from database.models import MailAccount
from sqlalchemy.orm import Session
class OutlookGraphFetcher:
    """Fetch Outlook emails using Microsoft Graph API"""
    
    _session = None

    def __init__(self, user_id: int = None, db: Session = None):
        self.user_id = user_id
        self.db = db
        self.email = os.getenv('OUTLOOK_USER')
        self.token_file = Path('.outlook_oauth_token.json')
        self.base_url = 'https://graph.microsoft.com/v1.0'
        self.access_token = None
        
        if OutlookGraphFetcher._session is None:
            OutlookGraphFetcher._session = requests.Session()
        self.session = OutlookGraphFetcher._session
    
    def _load_token(self) -> str:
        """Load and refresh OAuth2 access token"""
        token_data = None
        mail_account = None

        if self.user_id and self.db:
            # Load from database
            mail_account = self.db.query(MailAccount).filter_by(
                user_id=self.user_id, provider="outlook"
            ).first()
            if mail_account:
                token_data = {
                    "access_token": mail_account.token,
                    "refresh_token": mail_account.refresh_token,
                    "meta_data": mail_account.meta_data
                }
        
        # Fallback to file for legacy/superadmin or if db not provided
        if not token_data and TOKEN_FILE.exists():
            try:
                with open(TOKEN_FILE, 'r') as f:
                    token_data = json.load(f)
            except Exception as e:
                print(f"Error loading legacy token file: {e}")

        if not token_data:
            raise Exception(
                "No Outlook OAuth token found! "
                "Please authenticate first via the Settings page."
            )
        
        try:
            # We already loaded token_data above
            
            # Use MSAL to get a valid token (refreshes if needed)
            authority = f"https://login.microsoftonline.com/{TENANT_ID}"
            msal_app = msal.ConfidentialClientApplication(
                CLIENT_ID,
                authority=authority,
                client_credential=CLIENT_SECRET
            )
            
            # MSAL 1.28.0+ automatically manages OIDC scopes ('openid', 'profile', 'offline_access')
            # Manually including them can cause 'ValueError: API does not accept frozenset...'
            # We filter them out just in case they're still in the imported SCOPES
            reserved_scopes = {'openid', 'profile', 'offline_access'}
            scope_list = [s for s in list(SCOPES) if s not in reserved_scopes]
            
            # Use full URIs if they are short names
            scope_list = [
                s if s.startswith('http') else f"https://graph.microsoft.com/{s}" 
                for s in scope_list
            ]

            # Try to get from cache first
            accounts = msal_app.get_accounts()
            result = None
            if accounts:
                result = msal_app.acquire_token_silent(scope_list, account=accounts[0])
            
            # If not in cache or expired, try to use refresh token
            if not result and token_data.get('refresh_token'):
                result = msal_app.acquire_token_by_refresh_token(
                    token_data['refresh_token'],
                    scopes=scope_list
                )
            
            if result and 'access_token' in result:
                # Update token file if refreshed
                if result.get('access_token') and result['access_token'] != token_data.get('access_token'):
                    token_data['access_token'] = result['access_token']
                    if result.get('refresh_token'):
                        token_data['refresh_token'] = result['refresh_token']
                    
                    # Save back to DB if we have it
                    if mail_account:
                        mail_account.token = result['access_token']
                        if result.get('refresh_token'):
                            mail_account.refresh_token = result['refresh_token']
                        mail_account.meta_data = result
                        self.db.commit()
                    
                    # Also update legacy file if it exists
                    if TOKEN_FILE.exists():
                        with open(TOKEN_FILE, 'w') as f:
                            json.dump(token_data, f, indent=2)
                
                return result['access_token']
            
            # Fallback to current token if it's still good by some miracle, 
            # though usually msal should handle this.
            return token_data.get('access_token')

        except Exception as e:
            print(f"[X] Token load/refresh error: {e}")
            raise Exception(f"Error loading OAuth token: {e}")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers with auth token"""
        if not self.access_token:
            self.access_token = self._load_token()
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def connect(self) -> bool:
        """Verify connection to Graph API"""
        try:
            # Test API connection
            url = f'{self.base_url}/me/messages?$top=1'
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            
            if response.status_code == 200:
                print(f"[OK] Connected to Outlook Graph API")
                return True
            elif response.status_code == 401:
                print(f"[!] Outlook Token Expired (401). Retrying refresh...")
                self.access_token = None # Force reload
                response = self.session.get(url, headers=self._get_headers(), timeout=10)
                if response.status_code == 200:
                    return True
            
            print(f"[X] Graph API connection failed: {response.status_code} {response.text}")
            return False
        except Exception as e:
            print(f"[X] Error connecting to Graph API: {e}")
            return False
    
    def fetch_tender_emails(self, limit: int = 10) -> List[Dict]:
        """
        Fetch tender-related emails from inbox
        
        Returns list of email dictionaries compatible with EmailFetcher interface
        """
        try:
            # Build query
            # Filter for unread emails OR emails from specific time period
            # Customize filter based on your needs
            filter_query = "isRead eq false"  # Only unread emails
            
            # You can add subject filter if needed:
            # filter_query = "contains(subject, 'tender') or contains(subject, 'RFQ')"
            
            url = f'{self.base_url}/me/messages'
            params = {
                '$filter': filter_query,
                '$select': 'id,subject,from,receivedDateTime,bodyPreview,body,hasAttachments,internetMessageId,conversationId',
                '$orderby': 'receivedDateTime desc',
                '$top': limit
            }
            
            response = self.session.get(url, headers=self._get_headers(), params=params, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code} {response.text}")
            
            data = response.json()
            messages = data.get('value', [])
            
            print(f" Found {len(messages)} email(s)")
            
            # Convert to EmailFetcher format
            emails = []
            for msg in messages:
                email_data = self._convert_to_email_format(msg)
                if email_data:
                    emails.append(email_data)
            
            return emails
            
        except Exception as e:
            print(f"[X] Error fetching emails: {e}")
            return []

    def fetch_sent_emails(self, limit: int = 10) -> List[Dict]:
        """Fetch recently sent emails to learn writing style"""
        try:
            # Use 'sentitems' well-known folder
            url = f'{self.base_url}/me/mailFolders/sentitems/messages'
            params = {
                '$select': 'id,subject,from,receivedDateTime,bodyPreview,body',
                '$orderby': 'receivedDateTime desc',
                '$top': limit
            }
            
            response = self.session.get(url, headers=self._get_headers(), params=params, timeout=30)
            if response.status_code != 200:
                return []
                
            data = response.json()
            messages = data.get('value', [])
            
            emails = []
            for msg in messages:
                email_data = self._convert_to_email_format(msg)
                if email_data:
                    emails.append(email_data)
                    
            return emails
        except Exception as e:
            print(f"[X] Error fetching sent emails: {e}")
            return []
    
    def _convert_to_email_format(self, graph_message: Dict) -> Optional[Dict]:
        """Convert Graph API message to EmailFetcher format"""
        try:
            # Extract sender email
            from_field = graph_message.get('from', {})
            sender_email = from_field.get('emailAddress', {}).get('address', 'unknown@example.com')
            sender_name = from_field.get('emailAddress', {}).get('name', 'Unknown')
            
            # Get body content
            body_obj = graph_message.get('body', {})
            body_content = body_obj.get('content', '')
            body_type = body_obj.get('contentType', 'text')  # 'text' or 'html'
            
            # Convert HTML to plain text if needed
            if body_type == 'html':
                # Simple HTML removal (you may want to use BeautifulSoup for better parsing)
                import re
                body_content = re.sub('<[^<]+?>', '', body_content)
            
            email_data = {
                'email_id': graph_message['id'],
                'message_id': graph_message.get('internetMessageId'), # RFC 822 Message-ID
                'conversation_id': graph_message.get('conversationId'), # Outlook Thread ID
                'subject': graph_message.get('subject', '(No Subject)'),
                'sender': f"{sender_name} <{sender_email}>",
                'body': body_content,
                'date': self._parse_date(graph_message.get('receivedDateTime')),
                'attachments': []
            }
            
            # Fetch attachments if present
            if graph_message.get('hasAttachments', False):
                email_data['attachments'] = self._fetch_attachments(graph_message['id'])
            
            return email_data
            
        except Exception as e:
            print(f"Warning: Error converting message: {e}")
            return None
    
    def _fetch_attachments(self, message_id: str) -> List[Dict]:
        """Fetch attachments for a message"""
        try:
            url = f'{self.base_url}/me/messages/{message_id}/attachments'
            response = self.session.get(url, headers=self._get_headers(), timeout=30)
            
            if response.status_code != 200:
                print(f"Warning: Could not fetch attachments: {response.status_code}")
                return []
            
            attachments_data = response.json().get('value', [])
            attachments = []
            
            for att in attachments_data:
                # Graph API returns base64 encoded content
                import base64
                
                att_dict = {
                    'filename': att.get('name', 'attachment'),
                    'size': att.get('size', 0),
                    'content_type': att.get('contentType', 'application/octet-stream'),
                    'content': base64.b64decode(att.get('contentBytes', ''))  # Changed from 'data' to 'content'
                }
                attachments.append(att_dict)
            
            return attachments
            
        except Exception as e:
            print(f"Warning: Error fetching attachments: {e}")
            return []
    
    def _parse_date(self, date_str: Optional[str]) -> str:
        """Parse Graph API date format"""
        if not date_str:
            return datetime.now().isoformat()
        
        try:
            # Graph API uses ISO 8601 format
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return date_str
    
    def move_to_processed(self, email_data: Dict) -> bool:
        """Move email to processed folder"""
        try:
            message_id = email_data['email_id']
            
            # Get or create "RFQ_Processed" folder
            folder_id = self._get_or_create_folder('RFQ_Processed')
            
            if not folder_id:
                print("Warning: Could not get processed folder, marking as read instead")
                return self.mark_as_read(message_id)
            
            # Move message
            url = f'{self.base_url}/me/messages/{message_id}/move'
            payload = {'destinationId': folder_id}
            
            response = self.session.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                print(f"[OK] Email moved to processed folder")
                # Graph API move doesn't automatically mark as read
                self.mark_as_read(message_id)
                return True
            else:
                print(f"Warning: Could not move email: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"Warning: Error moving email: {e}")
            return False
    
    def _get_or_create_folder(self, folder_name: str) -> Optional[str]:
        """Get folder ID or create if doesn't exist"""
        try:
            # List all mail folders
            url = f'{self.base_url}/me/mailFolders'
            response = self.session.get(url, headers=self._get_headers(), timeout=10)
            
            if response.status_code != 200:
                return None
            
            folders = response.json().get('value', [])
            
            # Check if folder exists
            for folder in folders:
                if folder.get('displayName') == folder_name:
                    return folder['id']
            
            # Create folder
            create_url = f'{self.base_url}/me/mailFolders'
            payload = {'displayName': folder_name}
            
            response = self.session.post(
                create_url,
                headers=self._get_headers(),
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201]:
                new_folder = response.json()
                return new_folder.get('id')
            
            return None
            
        except Exception as e:
            print(f"Warning: Error with folder operations: {e}")
            return None
    
    def mark_as_read(self, message_id: str) -> bool:
        """Mark message as read"""
        try:
            url = f'{self.base_url}/me/messages/{message_id}'
            payload = {'isRead': True}
            
            response = requests.patch(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=10
            )
            
            return response.status_code == 200
        except:
            return False
    
    # ==========================================
    # DRAFT EMAIL MANAGEMENT METHODS
    # ==========================================
    
    def create_draft(self, to: str, subject: str, body: str, in_reply_to: str = None) -> Dict:
        """
        Create a draft email in Outlook
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text or HTML)
            in_reply_to: Optional message ID to reply to
            
        Returns:
            Dict with 'success', 'draft_id', and optional 'error'
        """
        try:
            # Build message payload
            message = {
                "subject": subject,
                "body": {
                    "contentType": "Text",  # or "HTML"
                    "content": body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to
                        }
                    }
                ]
            }
            
            # If replying to an email
            if in_reply_to:
                # Use createReply endpoint
                url = f'{self.base_url}/me/messages/{in_reply_to}/createReply'
                response = requests.post(url, headers=self._get_headers(), timeout=10)
                
                if response.status_code in [200, 201]:
                    draft = response.json()
                    draft_id = draft['id']
                    
                    # Update the draft with our content
                    return self.update_draft(draft_id, subject, body)
                else:
                    raise Exception(f"Failed to create reply draft: {response.status_code}")
            else:
                # Create new draft
                url = f'{self.base_url}/me/messages'
                response = requests.post(
                    url,
                    headers=self._get_headers(),
                    json=message,
                    timeout=30
                )
                
                if response.status_code in [200, 201]:
                    draft = response.json()
                    draft_id = draft['id']
                    
                    print(f"[OK] Draft created: {draft_id[:20]}...")
                    
                    return {
                        'success': True,
                        'draft_id': draft_id,
                        'subject': subject
                    }
                else:
                    raise Exception(f"API error: {response.status_code} {response.text}")
                    
        except Exception as e:
            print(f"[X] Error creating draft: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def update_draft(self, draft_id: str, subject: str = None, body: str = None) -> Dict:
        """
        Update an existing draft email
        
        Args:
            draft_id: Draft message ID
            subject: New subject (optional)
            body: New body content (optional)
            
        Returns:
            Dict with 'success' and optional 'error'
        """
        try:
            payload = {}
            
            if subject is not None:
                payload['subject'] = subject
            
            if body is not None:
                payload['body'] = {
                    'contentType': 'Text',
                    'content': body
                }
            
            if not payload:
                return {'success': True}  # Nothing to update
            
            url = f'{self.base_url}/me/messages/{draft_id}'
            response = requests.patch(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"[OK] Draft updated: {draft_id[:20]}...")
                return {
                    'success': True,
                    'draft_id': draft_id
                }
            else:
                raise Exception(f"API error: {response.status_code} {response.text}")
                
        except Exception as e:
            print(f"[X] Error updating draft: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def add_attachment_to_draft(self, draft_id: str, filename: str, content: bytes) -> Dict:
        """Add an attachment to an existing Outlook draft"""
        try:
            import base64
            
            url = f'{self.base_url}/me/messages/{draft_id}/attachments'
            
            # Prepare attachment payload
            payload = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename,
                "contentBytes": base64.b64encode(content).decode('utf-8')
            }
            
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                print(f"[OK] Attachment added to draft: {filename}")
                return {'success': True}
            else:
                raise Exception(f"Graph API error: {response.status_code} {response.text}")
                
        except Exception as e:
            print(f"[X] Error adding attachment to Outlook draft: {e}")
            return {'success': False, 'error': str(e)}
    
    def send_draft(self, draft_id: str) -> Dict:
        """
        Send a draft email
        
        Args:
            draft_id: Draft message ID to send
            
        Returns:
            Dict with 'success' and optional 'error'
        """
        try:
            url = f'{self.base_url}/me/messages/{draft_id}/send'
            response = requests.post(
                url,
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code == 202:  # Accepted
                print(f"[OK] Draft sent: {draft_id[:20]}...")
                return {
                    'success': True,
                    'draft_id': draft_id
                }
            else:
                raise Exception(f"API error: {response.status_code} {response.text}")
                
        except Exception as e:
            print(f"[X] Error sending draft: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def delete_draft(self, draft_id: str) -> Dict:
        """
        Delete a draft email
        
        Args:
            draft_id: Draft message ID to delete
            
        Returns:
            Dict with 'success' and optional 'error'
        """
        try:
            url = f'{self.base_url}/me/messages/{draft_id}'
            response = requests.delete(
                url,
                headers=self._get_headers(),
                timeout=10
            )
            
            if response.status_code in [200, 204]:
                print(f"[OK] Draft deleted: {draft_id[:20]}...")
                return {
                    'success': True,
                    'draft_id': draft_id
                }
            else:
                raise Exception(f"API error: {response.status_code} {response.text}")
                
        except Exception as e:
            print(f"[X] Error deleting draft: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_drafts(self, limit: int = 50) -> List[Dict]:
        """
        Get all draft emails from Drafts folder
        
        Args:
            limit: Maximum number of drafts to retrieve
            
        Returns:
            List of draft dictionaries
        """
        try:
            # Get drafts folder
            url = f'{self.base_url}/me/mailFolders/drafts/messages'
            params = {
                '$select': 'id,subject,body,toRecipients,createdDateTime',
                '$orderby': 'createdDateTime desc',
                '$top': limit
            }
            
            response = requests.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code} {response.text}")
            
            data = response.json()
            messages = data.get('value', [])
            
            drafts = []
            for msg in messages:
                # Extract recipient
                to_recipients = msg.get('toRecipients', [])
                recipient = to_recipients[0]['emailAddress']['address'] if to_recipients else ''
                
                # Get body content
                body_obj = msg.get('body', {})
                body_content = body_obj.get('content', '')
                
                drafts.append({
                    'draft_id': msg['id'],
                    'subject': msg.get('subject', ''),
                    'body': body_content,
                    'recipient': recipient,
                    'created_at': msg.get('createdDateTime', '')
                })
            
            return drafts
            
        except Exception as e:
            print(f"[X] Error getting drafts: {e}")
            return []
    
    # ==========================================
    # CALENDAR METHODS (Microsoft Graph)
    # ==========================================
    
    def fetch_calendar_events(self, days: int = 7) -> List[Dict]:
        """Fetch calendar events for the next X days"""
        try:
            from datetime import timedelta
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=days)
            
            start_iso = start_date.isoformat() + 'Z'
            end_iso = end_date.isoformat() + 'Z'
            
            # Graph API Calendar View
            url = f'{self.base_url}/me/calendar/calendarView'
            params = {
                'startDateTime': start_iso,
                'endDateTime': end_iso,
                '$select': 'id,subject,start,end,location,bodyPreview,webLink,attendees',
                '$orderby': 'start/dateTime asc'
            }
            
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            if response.status_code != 200:
                print(f"Warning: Outlook Calendar API error: {response.status_code}")
                return []
            
            data = response.json()
            events = data.get('value', [])
            
            formatted_events = []
            for ev in events:
                formatted_events.append({
                    'id': ev['id'],
                    'title': ev.get('subject', 'No Title'),
                    'start': ev['start']['dateTime'],
                    'end': ev['end']['dateTime'],
                    'source': 'outlook',
                    'location': ev.get('location', {}).get('displayName', ''),
                    'link': ev.get('webLink', ''),
                    'description': ev.get('bodyPreview', ''),
                    'attendees': [a.get('emailAddress', {}).get('address', '') for a in ev.get('attendees', [])]
                })
            
            return formatted_events
        except Exception as e:
            print(f"[X] Error fetching Outlook events: {e}")
            return []

    def create_calendar_event(self, title: str, start_iso: str, end_iso: str, attendees: List[str] = None, description: str = "") -> Dict:
        """Create a new calendar event in Outlook"""
        try:
            url = f'{self.base_url}/me/events'
            
            event_payload = {
                "subject": title,
                "body": {
                    "contentType": "HTML",
                    "content": description
                },
                "start": {
                    "dateTime": start_iso,
                    "timeZone": "UTC"
                },
                "end": {
                    "dateTime": end_iso,
                    "timeZone": "UTC"
                },
                "location": {
                    "displayName": "RFI Managed Meeting"
                },
                "attendees": [
                    {
                        "emailAddress": {"address": email},
                        "type": "required"
                    } for email in (attendees or [])
                ]
            }
            
            response = requests.post(url, headers=self._get_headers(), json=event_payload, timeout=30)
            if response.status_code in [200, 201]:
                return {'success': True, 'event': response.json()}
            else:
                raise Exception(f"Outlook API error: {response.status_code} {response.text}")
        except Exception as e:
            print(f"[X] Error creating Outlook event: {e}")
            return {'success': False, 'error': str(e)}

    def disconnect(self):
        """Cleanup (no persistent connection for REST API)"""
        print("[OK] Disconnected from Outlook Graph API")
# Test function
if __name__ == "__main__":
    print("Testing Outlook Graph API Connection...")
    print()
    
    fetcher = OutlookGraphFetcher()
    
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