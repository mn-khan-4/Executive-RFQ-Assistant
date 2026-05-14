"""
Email Fetcher Module
Connects to email servers (Gmail/Outlook) via IMAP and fetches emails
"""
from typing import List, Dict, Optional
import email
from email.header import decode_header
from email.utils import parseaddr
import os
from datetime import datetime
from imapclient import IMAPClient
import ssl
from config.settings import (
    GMAIL_HOST, GMAIL_PORT, GMAIL_USER, GMAIL_PASSWORD,
    OUTLOOK_HOST, OUTLOOK_PORT, OUTLOOK_USER, OUTLOOK_PASSWORD,
    EMAIL_CHECK_FOLDER, EMAIL_PROCESSED_FOLDER,
    EMAIL_FILTER_SUBJECTS, EMAIL_MARK_AS_READ,
    EMAIL_PROVIDERS
)
from sqlalchemy.orm import Session

# Import OAuth clients
try:
    from agents.rfq_agent.gmail_api_client import GmailAPIFetcher
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False

try:
    from agents.rfq_agent.outlook_graph import OutlookGraphFetcher
    OUTLOOK_GRAPH_AVAILABLE = True
except ImportError:
    OUTLOOK_GRAPH_AVAILABLE = False


class EmailFetcher:
    """Fetch emails from Gmail or Outlook"""
    
    def __init__(self, provider=None, user_id: int = None, db: Session = None):
        self.provider = provider if provider else EMAIL_PROVIDERS[0]
        self.user_id = user_id
        self.db = db
        
        if self.provider not in EMAIL_PROVIDERS:
            available = ', '.join(EMAIL_PROVIDERS)
            raise ValueError(f"Invalid provider '{self.provider}'. Available: {available}")
        
        self.client = None
        self.outlook_graph = None
        self.gmail_api_client = None
        self.using_graph_api = False
        self.using_gmail_api = False
        
        if self.provider == 'gmail':
            gmail_oauth_enabled = os.getenv('GMAIL_OAUTH_ENABLED', 'false').lower() == 'true'
            if gmail_oauth_enabled and GMAIL_API_AVAILABLE:
                try:
                    self.gmail_api_client = GmailAPIFetcher(user_id=self.user_id, db=self.db)
                    self.using_gmail_api = True
                except Exception as e:
                    print(f"Fallback to IMAP: {e}")
            
            self.host = GMAIL_HOST
            self.port = GMAIL_PORT
            self.username = GMAIL_USER
            self.password = GMAIL_PASSWORD
        elif self.provider == 'outlook':
            outlook_oauth_enabled = os.getenv('OUTLOOK_OAUTH_ENABLED', 'false').lower() == 'true'
            if outlook_oauth_enabled and OUTLOOK_GRAPH_AVAILABLE:
                try:
                    self.outlook_graph = OutlookGraphFetcher(user_id=self.user_id, db=self.db)
                    self.using_graph_api = True
                except Exception as e:
                    print(f"Fallback to IMAP: {e}")
            
            self.host = OUTLOOK_HOST
            self.port = OUTLOOK_PORT
            self.username = OUTLOOK_USER
            self.password = OUTLOOK_PASSWORD
        
        self.check_folder = EMAIL_CHECK_FOLDER
        self.processed_folder = EMAIL_PROCESSED_FOLDER
        self.auto_mark_as_read = EMAIL_MARK_AS_READ.lower() == 'true'
        
    def connect(self):
        if self.using_gmail_api and self.gmail_api_client:
            return self.gmail_api_client.connect()
        if self.using_graph_api and self.outlook_graph:
            return self.outlook_graph.connect()
        
        try:
            ssl_context = ssl.create_default_context()
            self.client = IMAPClient(self.host, port=self.port, ssl_context=ssl_context)
            self.client.login(self.username, self.password)
            return True
        except Exception as e:
            print(f"[X] Connection failed: {e}")
            return False
    
    def disconnect(self):
        if self.using_gmail_api and self.gmail_api_client:
            self.gmail_api_client.disconnect()
            return
        if self.using_graph_api and self.outlook_graph:
            self.outlook_graph.disconnect()
            return
        if self.client:
            try:
                self.client.logout()
            except:
                pass
    
    def fetch_emails(self, limit=50):
        """Fetch unread emails (generic)"""
        if self.using_gmail_api and self.gmail_api_client:
            if not self.gmail_api_client.service:
                if not self.gmail_api_client.connect(): return []
            return self.gmail_api_client.fetch_tender_emails(limit=limit)
        
        if self.using_graph_api and self.outlook_graph:
            if not self.outlook_graph.access_token:
                if not self.outlook_graph.connect(): return []
            return self.outlook_graph.fetch_tender_emails(limit=limit)
        
        if not self.client:
            if not self.connect(): return []
        
        try:
            self.client.select_folder(self.check_folder)
            messages = self.client.search(['UNSEEN'])
            if not messages: return []
            
            messages = list(reversed(messages))[:limit]
            all_emails = []
            for msg_id in messages:
                email_data = self._parse_email(msg_id)
                if email_data: all_emails.append(email_data)
            return all_emails
        except Exception as e:
            print(f"[X] Error fetching: {e}")
            return []

    def fetch_tender_emails(self, limit=50):
        """Legacy wrapper"""
        return self.fetch_emails(limit)
    
    def fetch_sent_emails(self, limit=50):
        """Fetch recently sent emails (API only)"""
        if self.using_gmail_api and self.gmail_api_client:
            return self.gmail_api_client.fetch_sent_emails(limit=limit)
        
        if self.using_graph_api and self.outlook_graph:
            return self.outlook_graph.fetch_sent_emails(limit=limit)
            
        print(f"Warning: fetch_sent_emails not supported for IMAP/provider {self.provider}")
        return []
    
    def _parse_email(self, msg_id: int) -> Optional[Dict]:
        try:
            response = self.client.fetch([msg_id], ['RFC822'])
            raw_email = response[msg_id][b'RFC822']
            msg = email.message_from_bytes(raw_email)
            subject = self._decode_header(msg.get('Subject', ''))
            from_addr = msg.get('From', '')
            sender_name, sender_email = parseaddr(from_addr)
            date_str = msg.get('Date', '')
            body = self._extract_body(msg)
            attachments = self._extract_attachments(msg)
            message_id = msg.get('Message-ID', '')
            in_reply_to = msg.get('In-Reply-To', '')
            
            return {
                'email_id': f"{self.provider}_{msg_id}",
                'message_id': message_id,
                'in_reply_to': in_reply_to,
                'subject': subject,
                'sender': sender_email,
                'sender_name': sender_name,
                'date': date_str,
                'body': body,
                'attachments': attachments,
                'raw_msg_id': msg_id
            }
        except Exception as e:
            print(f"Error parsing {msg_id}: {e}")
            return None
    
    def _decode_header(self, header: str) -> str:
        if not header: return ''
        decoded_parts = decode_header(header)
        decoded_str = ''
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_str += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_str += part
        return decoded_str
    
    def _extract_body(self, msg) -> str:
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    try: body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except: pass
        else:
            try: body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except: body = str(msg.get_payload())
        return body.strip()
    
    def _extract_attachments(self, msg) -> List[Dict]:
        attachments = []
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                continue
            filename = part.get_filename()
            if not filename: continue
            filename = self._decode_header(filename)
            content = part.get_payload(decode=True)
            if content: attachments.append({'filename': filename, 'content': content})
        return attachments
    
    def mark_as_read(self, email_id):
        """Mark an email as read across providers"""
        if self.using_gmail_api and self.gmail_api_client:
            # For Gmail API, email_id is the string ID
            return self.gmail_api_client.mark_as_read(email_id)
        
        if self.using_graph_api and self.outlook_graph:
            return self.outlook_graph.mark_as_read(email_id)

        if self.client:
            try:
                # IMAP logic uses raw numeric ID
                self.client.add_flags([email_id], [r'\Seen'])
                return True
            except:
                return False
        return False

    def move_to_processed(self, email_data):
        if self.using_gmail_api and self.gmail_api_client:
            return self.gmail_api_client.move_to_processed(email_data)
        if self.using_graph_api and self.outlook_graph:
            return self.outlook_graph.move_to_processed(email_data)
        if not self.client: return
        try:
            msg_id = email_data['raw_msg_id']
            try: self.client.select_folder(self.processed_folder)
            except: self.client.create_folder(self.processed_folder)
            self.client.select_folder(self.check_folder)
            self.client.copy([msg_id], self.processed_folder)
            self.client.delete_messages([msg_id])
            self.client.expunge()
        except: pass
