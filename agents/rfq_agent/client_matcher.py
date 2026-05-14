"""
Client Matcher Module
Identifies and tracks clients from email data
"""
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from database.models import Client
from database.connection import SessionLocal
from models.pixtral_client import PixtralClient
import re


class ClientMatcher:
    """Identify and track clients from email sender information"""
    
    def __init__(self):
        self.llm = PixtralClient()
    
    def find_or_create_client(self, 
                             email_sender: str, 
                             email_body: str,
                             session: Optional[Session] = None,
                             user_id: int = None) -> Client:
        """
        Find existing client or create new one
        
        Args:
            email_sender: Email sender address
            email_body: Email body for context
            session: Database session (optional)
            
        Returns:
            Client object
        """
        own_session = session is None
        if own_session:
            session = SessionLocal()
        
        try:
            # Try to match by email domain first
            client = self.match_by_email_domain(email_sender, session, user_id=user_id)
            
            if client:
                # Update last contact
                client.last_contact = datetime.utcnow()
                if email_sender not in (client.contact_emails or []):
                    if client.contact_emails:
                        client.contact_emails.append(email_sender)
                    else:
                        client.contact_emails = [email_sender]
                session.commit()
                print(f"DONE: Found existing client: {getattr(client, 'contact_name', 'Unknown')}")
                return client
            
            # No match found, create new client
            client_name = self.extract_client_name(email_sender, email_body)
            email_domain = self._extract_domain(email_sender)
            
            new_client = Client(
                contact_name=client_name,
                user_id=user_id,
                email_domain=email_domain,
                contact_emails=[email_sender],
                first_seen=datetime.utcnow(),
                last_contact=datetime.utcnow(),
                total_interactions=1,
                meta_data={}
            )
            
            session.add(new_client)
            session.commit()
            session.refresh(new_client)
            
            print(f"DONE: Created new client: {client_name}")
            return new_client
            
        finally:
            if own_session:
                session.close()
    
    def extract_client_name(self, email_sender: str, email_body: str) -> str:
        """
        Extract client/company name from email using LLM
        
        Args:
            email_sender: Email address
            email_body: Email body text
            
        Returns:
            Client name string
        """
        prompt = f"""
From the following email, extract the company/client name.

Email Sender: {email_sender}
Email Body: {email_body[:500]}

Return ONLY the company name as a JSON object:
{{
    "client_name": "Company Name"
}}

If you cannot determine the company name, use the email domain as the name.
"""
        
        try:
            result = self.llm.generate(
                system_prompt="You are a data extraction expert.",
                user_prompt=prompt,
                temperature=0.1
            )
            
            if isinstance(result, dict) and 'client_name' in result:
                return result['client_name']
            
        except Exception as e:
            print(f"Warning: LLM extraction failed: {e}")
        
        # Fallback: use email domain
        domain = self._extract_domain(email_sender)
        # Clean domain to make it presentable
        name = domain.replace('.com', '').replace('.sa', '').replace('.org', '')
        return name.title()
    
    def match_by_email_domain(self, 
                             email: str, 
                             session: Session,
                             user_id: int = None) -> Optional[Client]:
        """
        Match client by email domain, but skip for public providers (Gmail, etc.)
        """
        domain = self._extract_domain(email)
        
        # List of common public providers that should NOT be matched by domain
        PUBLIC_DOMAINS = [
            'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 
            'icloud.com', 'me.com', 'live.com', 'msn.com', 'aol.com',
            'googlemail.com'
        ]
        
        # If it's a public domain, DO NOT match by domain. Only match by exact email.
        if domain not in PUBLIC_DOMAINS:
            # Try exact domain match first
            query = session.query(Client).filter(Client.email_domain == domain)
            if user_id:
                query = query.filter(Client.user_id == user_id)
            client = query.first()
            
            if client:
                return client
        
        # If public domain OR no domain match, try matching by exact contact emails
        
        # Try matching by contact emails using any()
        # PostgreSQL ARRAY syntax: WHERE email = ANY(contact_emails)
        try:
            query = session.query(Client).filter(Client.contact_emails.any(email))
            if user_id:
                query = query.filter(Client.user_id == user_id)
            client = query.first()
        except:
            # Fallback if any() doesn't work either
            pass
        
        return client
    
    def update_client_contact(self, 
                             client_id: int, 
                             email: str,
                             session: Optional[Session] = None):
        """
        Add new contact email to client
        
        Args:
            client_id: Client ID
            email: Email address to add
            session: Database session (optional)
        """
        own_session = session is None
        if own_session:
            session = SessionLocal()
        
        try:
            client = session.query(Client).filter(Client.id == client_id).first()
            if client:
                if email not in (client.contact_emails or []):
                    if client.contact_emails:
                        client.contact_emails.append(email)
                    else:
                        client.contact_emails = [email]
                    session.commit()
        finally:
            if own_session:
                session.close()
    
    def _extract_domain(self, email: str) -> str:
        """Extract domain from email address"""
        match = re.search(r'@([\w\.-]+)', email)
        if match:
            return match.group(1).lower()
        return email.lower()
