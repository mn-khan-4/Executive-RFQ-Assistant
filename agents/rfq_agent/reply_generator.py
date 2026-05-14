from models.pixtral_client import PixtralClient
from config.prompts import GENERAL_EMAIL_ASSISTANT_PROMPT, PROFESSIONAL_REPLY_PROMPT, CATEGORY_SUGGESTION_PROMPT
from typing import Dict, List
import os
import json
from sqlalchemy.orm import Session
from database.models import MailAccount

class ReplyGenerator:
    """Generate high-quality business email drafts and category suggestions"""
    
    def __init__(self, user_id: int = None, db: Session = None):
        self.user_id = user_id
        self.db = db
        self.llm = PixtralClient()
        self.system_prompt = GENERAL_EMAIL_ASSISTANT_PROMPT
    
    def generate_draft(self, 
                       sender: str,
                       subject: str, 
                       body: str, 
                       attachments: List[Dict] = None,
                       smart_instructions: str = None) -> Dict:
        """
        Produce a professional email draft based on history and attachments
        """
        
        # Summarize attachments for the prompt
        attachment_summaries = []
        if attachments:
            for att in attachments:
                summary = att.get('summary', 'Attachment')
                filename = att.get('original_filename', att.get('filename', 'Unknown'))
                attachment_summaries.append(f"- {filename}: {summary}")
        
        attachment_context = "\n".join(attachment_summaries) if attachment_summaries else "None"
        
        # Scheduling Logic: Detect if meeting/call is mentioned
        scheduling_context = ""
        meeting_keywords = ['meeting', 'call', 'zoom', 'teams', 'schedule', 'meet up', 'interview', 'calendar']
        if any(kw in (body or "").lower() for kw in meeting_keywords):
            from agents.executive.scheduler import ExecutiveScheduler
            
            # Detect provider from database
            provider = 'gmail'
            if self.user_id and self.db:
                outlook_acc = self.db.query(MailAccount).filter_by(user_id=self.user_id, provider="outlook").first()
                if outlook_acc:
                    provider = 'outlook'
            else:
                # Fallback to file check if no user_id/db (legacy)
                provider = 'gmail' if os.path.exists('.gmail_oauth_token.json') else 'outlook'
                
            scheduler = ExecutiveScheduler(provider=provider, user_id=self.user_id, db=self.db)
            scheduling_context = "\n[CALENDAR AVAILABILITY (Next 3 Days)]:\n" + scheduler.find_free_slots(days=3)

        # Prepare user prompt
        user_prompt = PROFESSIONAL_REPLY_PROMPT.format(
            sender=sender,
            subject=subject,
            body=body,
            attachment_summary=attachment_context
        )
        
        if scheduling_context:
            user_prompt += f"\n\n{scheduling_context}\n\nINSTRUCTION: Please pick 3 suitable free slots from the availability above and suggest them politely in your reply."
        
        # Tone Mirroring Logic: Fetch SENT emails to learn style
        style_examples_context = ""
        try:
            provider = 'gmail'
            if self.user_id and self.db:
                outlook_acc = self.db.query(MailAccount).filter_by(user_id=self.user_id, provider="outlook").first()
                if outlook_acc:
                    provider = 'outlook'
            else:
                provider = 'gmail' if os.path.exists('.gmail_oauth_token.json') else 'outlook'

            if provider == 'gmail':
                from agents.rfq_agent.gmail_api_client import GmailAPIFetcher
                fetcher = GmailAPIFetcher(user_id=self.user_id, db=self.db)
                if fetcher.connect():
                    sent_emails = fetcher.fetch_sent_emails(limit=5)
            else:
                from agents.rfq_agent.outlook_graph import OutlookGraphFetcher
                fetcher = OutlookGraphFetcher(user_id=self.user_id, db=self.db)
                if fetcher.connect():
                    sent_emails = fetcher.fetch_sent_emails(limit=5)
            
            if sent_emails:
                style_examples_context = "\n[USER WRITING STYLE EXAMPLES (FROM RECENT SENT EMAILS)]:\n"
                for i, email in enumerate(sent_emails):
                    # Only take first 300 chars of body for efficiency
                    clean_body = (email.get('body', '') or "")[:300].replace('\n', ' ')
                    style_examples_context += f"Example {i+1}: {clean_body}\n"
        except Exception as e:
            print(f"Warning: Tone Mirroring failed to fetch history: {e}")

        if style_examples_context:
            user_prompt += f"\n\n{style_examples_context}\n\nINSTRUCTION: Closely mimic the writing style, tone, and brevity of the examples above so that the draft looks like it was written by the user personally."

        if smart_instructions:
            user_prompt += smart_instructions
        
        # Call LLM for drafting
        draft_result = self.llm.generate(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            temperature=0.3 # Allow some creativity for "Professional" tone
        )
        
        return draft_result
    
    def suggest_categories(self, 
                           subject: str, 
                           body: str, 
                           attachment_names: List[str],
                           current_date: str = None) -> Dict:
        """
        Suggest categories (tags) and extract meeting details if present
        """
        prompt = """
        Task: Suggest 2-3 professional categories (tags) for this email.
        ALSO, if the email asks for a meeting, extract details.
        AND, identify any "Action Items" (specific tasks, commitments, or next steps) mentioned for the recipient.

        Current Date (UTC): {current_date}

        Subject: {subject}
        Body: {body}
        Attachment names: {attachment_names}

        GENERAL CATEGORIES:
        - Urgent Priority, Meeting Request, Client Inquiry, Project Management, Financial, Technical, Follow-up, HR/Legal

        Return JSON only:
        {{
            "suggested_tags": ["Category1", "Category2"],
            "meeting_detected": true/false,
            "meeting_details": {{
                "topic": "Brief topic",
                "start_time": "ISO 8601 string or null",
                "end_time": "ISO 8601 string or null"
            }},
            "action_items": [
                "Task 1 description",
                "Task 2 description"
            ]
        }}

        IMPORTANT: For start_time and end_time, use the year from Current Date unless the email explicitly specifies a different year.
        """
        
        user_prompt = prompt.format(
            current_date=current_date or "2026-04-11",
            subject=subject,
            body=body,
            attachment_names=", ".join(attachment_names) if attachment_names else "None"
        )
        
        result = self.llm.generate(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            temperature=0.1
        )
        
        # Ensure we always return a dict
        if not isinstance(result, dict):
            return {"suggested_tags": [], "meeting_detected": False}
            
        return result
