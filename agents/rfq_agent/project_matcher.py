"""
Project Matcher Module
Matches emails to existing or new projects
"""
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from database.models import Project, Client
from database.connection import SessionLocal
from models.pixtral_client import PixtralClient
import re


class ProjectMatcher:
    """Match emails to existing or new projects"""
    
    def __init__(self):
        self.llm = PixtralClient()
    def find_matching_project(self,
                              client_id: int,
                              project_data: Dict,
                              session: Optional[Session] = None,
                              user_id: int = None) -> Optional[Project]:
        """
        Find matching project using a multi-layer strategy:
        Layer 1: Metadata Matching (100% Confidence) - Threading headers
        Layer 2: Reference Matching (95% Confidence) - Unique IDs in text
        Layer 3: Semantic Matching (85% Confidence) - LLM similarity
        """
        own_session = session is None
        if own_session:
            session = SessionLocal()
        
        try:
            # LAYER 1: Metadata / Protocol Matching (Thread Continuity)
            # 1.1 Check In-Reply-To against existing Message-IDs
            in_reply_to = project_data.get('in_reply_to')
            if in_reply_to:
                from database.models import Email
                query = session.query(Email).filter(Email.message_id == in_reply_to)
                if user_id:
                    query = query.filter(Email.user_id == user_id)
                parent_email = query.first()
                if parent_email:
                    # Found the parent! 
                    # CRITICAL: Check if the user is HIJACKING an old thread for a NEW project
                    is_new_intent = self._detect_intent_shift(project_data, parent_email.subject)
                    
                    if not is_new_intent:
                        query = session.query(Project).filter(Project.thread_id == parent_email.thread_id)
                        if user_id:
                            query = query.filter(Project.user_id == user_id)
                        project = query.first()
                        if project:
                            print(f"DONE: Matched project by Metadata Threading: {project.topic_name} (100% Confident)")
                            return project
                    else:
                        print(f"WARN: Intent shift detected! Client hijacked thread for a NEW project. Ignoring metadata match.")

            # 1.2 Check Conversation ID (Microsoft specific)
            conversation_id = project_data.get('conversation_id')
            if conversation_id:
                from database.models import Email
                # Using PostgreSQL JSONB operators
                query = session.query(Email).filter(Email.meta_data.op('->>')('conversation_id') == conversation_id)
                if user_id:
                    query = query.filter(Email.user_id == user_id)
                sibling_email = query.first()
                if sibling_email:
                    # Same logic: check for hijacking
                    is_new_intent = self._detect_intent_shift(project_data, sibling_email.subject)
                    if not is_new_intent:
                        query = session.query(Project).filter(Project.thread_id == sibling_email.thread_id)
                        if user_id:
                            query = query.filter(Project.user_id == user_id)
                        project = query.first()
                        if project:
                            print(f"DONE: Matched project by Conversation ID: {project.topic_name} (100% Confident)")
                            return project

            # LAYER 2: Reference Matching
            # Extract project reference from email
            project_ref = self.extract_project_reference(project_data)
            
            # Get all projects for this client
            query = session.query(Project).filter(
                Project.contact_id == client_id,
                Project.status == 'ACTIVE'
            )
            if user_id:
                query = query.filter(Project.user_id == user_id)
            projects = query.all()
            
            if not projects:
                return None
            
            # Try exact reference match first
            if project_ref:
                for project in projects:
                    if project.topic_reference and project_ref.lower() in project.topic_reference.lower():
                        print(f"DONE: Matched project by reference: {project.topic_name}")
                        return project
            
            # Use LLM for similarity matching
            project_name = self._extract_project_name(project_data)
            
            # GENERIC NAMES PROTECTION:
            # If the subject is very generic, do NOT match by similarity alone.
            generic_keywords = [
                'calculation', 'tender', 'rfq', 'itt', 'quotation', 'qutation', 
                'project', 'document', 'package', 'offer', 'quote'
            ]
            
            clean_name = project_name.lower().strip()
            # If name is JUST a generic keyword or starts with one followed by very little else
            is_generic = any(kw in clean_name for kw in generic_keywords)
            
            # If it's short and contains generic keywords, treat as generic
            if is_generic and len(clean_name) < 25:
                print(f"WARN: Subject '{project_name}' is too generic ({len(clean_name)} chars). Skipping similarity match.")
                return None

            for project in projects:
                similarity = self.calculate_similarity(
                    project_name,
                    project.topic_name or ""
                )
                
                # Threshold (0.8) for similarity to be more inclusive of follow-ups
                if similarity >= 0.8:  
                    print(f"DONE: Matched project by similarity ({similarity:.0%}): {project.topic_name}")
                    return project
            
            return None
            
        finally:
            if own_session:
                session.close()
    
    def extract_project_reference(self, project_data: Dict) -> str:
        """
        Extract project reference number from email
        
        Args:
            project_data: Dict with email data
        """
        subject = project_data.get('subject', '')
        body = project_data.get('body', '')
        
        # Look for patterns like TND-1234, PROJ-1234, RFQ-1234
        patterns = [
            r'(TND-\d{4,})',
            r'(PROJ-\d{4,})',
            r'(RFQ-\d{4,})',
            r'Ref:\s*([\w\-/]+)',
            r'Project No:\s*([\w\-/]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, subject, re.IGNORECASE)
            if not match:
                match = re.search(pattern, body, re.IGNORECASE)
            
            if match:
                return match.group(1)
        
        return ""
    
    def calculate_similarity(self, project1: str, project2: str) -> float:
        """Calculate similarity between two project names using LLM"""
        prompt = f"""
Compare these two project/tender titles and determine if they belong to the SAME project.
A follow-up email might have a slightly different subject (e.g. adding 'Layout Drawings' or 'Revised').

Title 1: {project1}
Title 2: {project2}

If they refer to the same core project, return a high similarity score (0.9 - 1.0).
If they are definitely different projects, return 0.0.
If they are same client/site but different scope, return 0.5.

Return JSON:
{{
    "similarity": 0.85,
    "reasoning": "Brief explanation"
}}
"""
        
        try:
            result = self.llm.generate(
                system_prompt="You are a construction project matching expert. Group follow-up emails and document resends into the same project thread.",
                user_prompt=prompt,
                temperature=0.1
            )
            
            if isinstance(result, dict) and 'similarity' in result:
                return float(result['similarity'])
            
        except Exception as e:
            print(f"Warning: Similarity calculation failed: {e}")
        
        # Fallback: simple string matching
        p1 = project1.lower()
        p2 = project2.lower()
        if p1 == p2:
            return 1.0
        elif p1 in p2 or p2 in p1:
            return 0.8 # Boosted fallback
        else:
            return 0.0
    
    def create_new_project(self,
                          client_id: int,
                          tender_id: str,
                          project_name: str,
                          project_reference: str = "",
                          session: Optional[Session] = None,
                          user_id: int = None) -> Project:
        """
        Create new project for a client
        """
        own_session = session is None
        if own_session:
            session = SessionLocal()
        
        try:
            # Update client's project count
            from database.models import Contact as Client
            client = session.query(Client).filter(Client.id == client_id).first()
            if client:
                client.total_interactions += 1
            
            # Create project
            from database.models import Topic as Project
            project = Project(
                contact_id=client_id,
                user_id=user_id,
                topic_name=project_name,
                topic_reference=project_reference,
                thread_id=tender_id,
                status='ACTIVE',
                folder_path=f"./storage/tenders/{tender_id}",
                created_at=datetime.utcnow(),
                last_updated=datetime.utcnow(),
                meta_data={}
            )
            
            session.add(project)
            session.commit()
            session.refresh(project)
            
            print(f"DONE: Created new project: {project_name}")
            return project
            
        finally:
            if own_session:
                session.close()
    
    def _detect_intent_shift(self, new_email: Dict, old_subject: str) -> bool:
        """
        Detect if a client is using an old thread for a completely NEW project.
        Returns True if a new project intent is detected.
        """
        prompt = f"""
Analyze if this incoming email is starting a NEW project or just a follow-up to an existing one.
Sometimes clients "hijack" old email threads to send a completely different tender.

Old Thread Subject: {old_subject}
New Email Subject: {new_email.get('subject', '')}
New Email Body: {new_email.get('body', '')[:1000]}

Criteria for NEW project:
1. Subject mentions a different location/site or project name.
2. Body explicitly says "New Tender", "Another project", or "Different site".
3. The scope is completely unrelated (e.g. "HVAC maintenance" vs "Suite Refurbishment").

Criteria for SAME project:
1. Mentions "Revised", "Additional info", "Missing docs", or "Phase X" of the same site.
2. Same project reference number.

Return JSON:
{{
    "is_new_project": true/false,
    "reasoning": "Brief explanation"
}}
"""
        try:
            result = self.llm.generate(
                system_prompt="You are an expert in construction procurement intent analysis.",
                user_prompt=prompt,
                temperature=0.1
            )
            
            if isinstance(result, dict) and 'is_new_project' in result:
                return bool(result['is_new_project'])
        except Exception as e:
            print(f"Warning: Intent shift detection failed: {e}")
            
        return False

    def _extract_project_name(self, project_data: Dict) -> str:
        """Extract project name from email data"""
        subject = project_data.get('subject', '')
        
        # Remove common prefixes (Case-Insensitive)
        name = subject
        prefixes = [
            'RFQ:', 'ITT:', 'Tender:', 'Re:', 'FW:', 'Fwd:', 
            'RE:', 'FWD:', 'URGENT:', 'REVISED:', 'CLEARER COPY:',
            'Project Invitation:', 'Invitation to Tender:'
        ]
        
        for prefix in prefixes:
            pattern = re.compile(re.escape(prefix), re.IGNORECASE)
            name = pattern.sub('', name)
        
        return name.strip()
