from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base

# --- Association Tables ---
email_tags = Table(
    'email_tags',
    Base.metadata,
    Column('email_id', Integer, ForeignKey('emails.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

thread_tags = Table(
    'thread_tags',
    Base.metadata,
    Column('thread_id', Integer, ForeignKey('threads.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

# --- Models (all now multi-tenant with user_id) ---

class Contact(Base):
    __tablename__ = 'contacts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    contact_name = Column(String(255), nullable=False)
    email_domain = Column(String(100))
    contact_emails = Column(Text)  # change to ARRAY(Text) if Postgres ARRAY
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_contact = Column(DateTime)
    total_interactions = Column(Integer, default=0)
    meta_data = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship('User', back_populates='contacts')
    topics = relationship('Topic', back_populates='contact')
    threads = relationship('Thread', back_populates='contact')


class Topic(Base):
    __tablename__ = 'topics'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    contact_id = Column(Integer, ForeignKey('contacts.id'), nullable=False)

    topic_name = Column(String(255))
    topic_reference = Column(String(100))
    thread_id = Column(String(50), unique=True)
    status = Column(String(50), default='ACTIVE')
    folder_path = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    meta_data = Column(JSONB)

    # Relationships
    user = relationship('User', back_populates='topics')
    contact = relationship('Contact', back_populates='topics')
    threads = relationship('Thread', back_populates='topic')


class Tag(Base):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(50), unique=True, nullable=False)
    color = Column(String(20), default='#6366f1')
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship('User', back_populates='tags')
    emails = relationship('Email', secondary=email_tags, back_populates='tags')
    threads = relationship('Thread', secondary=thread_tags, back_populates='tags')


class Thread(Base):
    __tablename__ = 'threads'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    thread_id = Column(String(50), unique=True, nullable=False)
    status = Column(String(50), nullable=False, default='PROCESSING')
    contact_id = Column(Integer, ForeignKey('contacts.id'))
    topic_id = Column(Integer, ForeignKey('topics.id'))
    subject = Column(Text)
    contact_name = Column(String(255))
    topic_name = Column(String(255))
    thread_reference = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source = Column(String(50))
    source_email = Column(String(255))
    source_sender = Column(String(255))

    # Relationships
    user = relationship('User', back_populates='threads')
    contact = relationship('Contact', back_populates='threads')
    topic = relationship('Topic', back_populates='threads')
    tags = relationship('Tag', secondary=thread_tags, back_populates='threads')


class Email(Base):
    __tablename__ = 'emails'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    thread_id = Column(String(50), index=True)
    email_id = Column(String(255), unique=True)
    subject = Column(Text)
    sender = Column(String(255))
    recipients = Column(Text)  # or ARRAY(Text)
    body = Column(Text)
    received_at = Column(DateTime)
    is_actionable = Column(Boolean, default=True)
    is_junk = Column(Boolean, default=False)
    is_sent = Column(Boolean, default=False)
    detection_confidence = Column(Float)
    tags_suggested = Column(Text)  # or ARRAY(Text)
    processed = Column(Boolean, default=False)
    meta_data = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship('User', back_populates='emails')
    tags = relationship('Tag', secondary=email_tags, back_populates='emails')


class Attachment(Base):
    __tablename__ = 'attachments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    thread_id = Column(String(50), index=True)
    category = Column(String(100))
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    file_path = Column(Text, nullable=False)
    file_hash = Column(String(64), nullable=False)
    file_size_bytes = Column(Integer)
    doc_type = Column(String(50))
    summary = Column(Text)
    is_correct = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String(50))

    # Relationships
    user = relationship('User', back_populates='attachments')

# Aliases
Document = Attachment

class DraftReply(Base):
    __tablename__ = 'draft_replies'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    thread_id = Column(String(50), index=True)
    draft_type = Column(String(50))
    recipient = Column(String(255), nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    email_provider = Column(String(20))
    provider_draft_id = Column(String(255))
    status = Column(String(50), default='DRAFT')
    created_by = Column(String(50), default='GENERAL_EMAIL_ASSISTANT')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime)
    in_reply_to_email_id = Column(String(255))
    meta_data = Column(JSONB)
    scheduled_at = Column(DateTime)

    # Relationships
    user = relationship('User', back_populates='draft_replies')

# Aliases
DraftEmail = DraftReply
RFIDraft = DraftReply

class FollowupTask(Base):
    __tablename__ = 'followup_tasks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    thread_id = Column(String(50), ForeignKey('threads.thread_id'))
    original_email_id = Column(String(255))
    recipient = Column(String(255))
    suggested_body = Column(Text)
    status = Column(String(50), default='PENDING')
    due_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship('User', back_populates='followup_tasks')

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255))
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default='user')  # 'superadmin', 'admin', 'user'
    is_active = Column(Boolean, default=True)
    preferences = Column(JSONB, default=lambda: {})
    brand_voice = Column(Text)
    custom_instructions = Column(Text)
    writing_style_guide = Column(Text)
    last_style_sync = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

    # Relationships
    contacts = relationship('Contact', back_populates='user')
    topics = relationship('Topic', back_populates='user')
    tags = relationship('Tag', back_populates='user')
    threads = relationship('Thread', back_populates='user')
    emails = relationship('Email', back_populates='user')
    attachments = relationship('Attachment', back_populates='user')
    draft_replies = relationship('DraftReply', back_populates='user')
    followup_tasks = relationship('FollowupTask', back_populates='user')
    audit_logs = relationship('AuditLog', back_populates='user')

class AuditLog(Base):
    __tablename__ = 'audit_log'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    thread_id = Column(String(50))
    agent = Column(String(50), default='RFI_AGENT')
    action = Column(String(100), nullable=False)
    details = Column(JSONB)
    ip_address = Column(String(50))
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship('User', back_populates='audit_logs')

class AssistantConversation(Base):
    __tablename__ = 'assistant_conversations'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(255), default='New Conversation')
    mode = Column(String(20), default='enterprise')
    created_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AssistantChat(Base):
    __tablename__ = 'assistant_chat'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    conversation_id = Column(Integer, ForeignKey('assistant_conversations.id'), nullable=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


# --- MailAccount model for per-user OAuth tokens ---
class MailAccount(Base):
    __tablename__ = 'mail_accounts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    provider = Column(String(50), nullable=False)  # 'gmail', 'outlook', etc.
    email_address = Column(String(255), nullable=False)
    token = Column(Text, nullable=False)  # Store encrypted/serialized token
    refresh_token = Column(Text)
    token_expiry = Column(DateTime)
    meta_data = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Unique per user, provider, email
        UniqueConstraint('user_id', 'provider', 'email_address', name='uq_user_provider_email'),
    )

    user = relationship('User', back_populates='mail_accounts')


# Add relationship to User
User.mail_accounts = relationship('MailAccount', back_populates='user')
