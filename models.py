"""
SQLAlchemy database models for the Fairy Tale Generator application.

This module defines the core database models:
- User: Stores user information including OAuth provider details
- Book: Stores generated storybooks with PDF paths
- Log: Stores application logs for debugging and monitoring
- Storyline: Stores pre-vetted story templates with page content
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

# Initialize SQLAlchemy instance (will be initialized in project.py)
db = SQLAlchemy()


class User(db.Model, UserMixin):
    """
    User model representing application users.
    
    Fields:
        user_id: Primary key, unique identifier for the user
        email: User's email address (unique)
        name: User's display name
        password_hash: Hashed password for email/password authentication
        oauth_provider: OAuth provider used for authentication (e.g., 'google', 'github', 'email')
        oauth_id: OAuth provider's unique identifier for this user
        created_at: Timestamp when the user account was created
    """
    __tablename__ = 'users'
    
    user_id = db.Column(db.String(255), primary_key=True, unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)  # Nullable for OAuth users
    oauth_provider = db.Column(db.String(50), nullable=True)
    oauth_id = db.Column(db.String(255), nullable=True, index=True)  # OAuth provider's user ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship to books
    books = db.relationship('Book', backref='user', lazy=True, cascade='all, delete-orphan')
    # Relationship to logs
    logs = db.relationship('Log', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.user_id}: {self.email}>'
    
    def get_id(self):
        """Required by Flask-Login. Returns the user_id as a string."""
        return str(self.user_id)
    
    def to_dict(self):
        """Convert user object to dictionary."""
        return {
            'user_id': self.user_id,
            'email': self.email,
            'name': self.name,
            'oauth_provider': self.oauth_provider,
            'oauth_id': self.oauth_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Book(db.Model):
    """
    Book model representing generated storybooks.
    
    Fields:
        book_id: Primary key, unique identifier for the book
        user_id: Foreign key to User table
        story_id: Identifier for the story template/type used
        child_name: Name of the child featured in the story
        pdf_path: File path to the generated PDF
        created_at: Timestamp when the book was created
    """
    __tablename__ = 'books'
    
    book_id = db.Column(db.String(255), primary_key=True, unique=True, nullable=False)
    user_id = db.Column(db.String(255), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    story_id = db.Column(db.String(100), nullable=True)
    child_name = db.Column(db.String(255), nullable=True)
    pdf_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<Book {self.book_id}: {self.child_name} by {self.user_id}>'
    
    def to_dict(self):
        """Convert book object to dictionary."""
        return {
            'book_id': self.book_id,
            'user_id': self.user_id,
            'story_id': self.story_id,
            'child_name': self.child_name,
            'pdf_path': self.pdf_path,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Log(db.Model):
    """
    Log model for storing application logs.
    
    Fields:
        log_id: Primary key, unique identifier for the log entry
        user_id: Foreign key to User table (nullable for system logs)
        level: Log level (e.g., 'INFO', 'ERROR', 'WARNING', 'DEBUG')
        message: Log message content
        timestamp: Timestamp when the log entry was created
    """
    __tablename__ = 'logs'
    
    log_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(255), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=True, index=True)
    level = db.Column(db.String(20), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    def __repr__(self):
        return f'<Log {self.log_id}: {self.level} - {self.message[:50]}>'
    
    def to_dict(self):
        """Convert log object to dictionary."""
        return {
            'log_id': self.log_id,
            'user_id': self.user_id,
            'level': self.level,
            'message': self.message,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


class Storyline(db.Model):
    """
    Storyline model for storing pre-vetted story templates.
    
    Fields:
        story_id: Primary key, unique identifier for the story (e.g., 'red', 'jack')
        name: Display name of the story (e.g., 'Little Red Riding Hood')
        gender: Target gender for the story ('boy' or 'girl')
        pages_json: JSON field containing array of 12 page objects, each with:
            - scene_desc: Description of the scene
            - text: Narrative text for the page
            - image_prompt_template: Template prompt for image generation (may contain {gender} placeholder)
    """
    __tablename__ = 'storylines'
    
    story_id = db.Column(db.String(100), primary_key=True, unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    gender = db.Column(db.String(10), nullable=False)  # 'boy' or 'girl'
    pages_json = db.Column(db.Text, nullable=False)  # JSON string storing array of page objects
    
    def __repr__(self):
        return f'<Storyline {self.story_id}: {self.name} ({self.gender})>'
    
    def get_pages(self):
        """Parse and return pages_json as a Python list."""
        try:
            return json.loads(self.pages_json)
        except (json.JSONDecodeError, TypeError):
            return []
    
    def set_pages(self, pages_list):
        """Set pages_json from a Python list."""
        self.pages_json = json.dumps(pages_list, ensure_ascii=False)
    
    def to_dict(self):
        """Convert storyline object to dictionary."""
        return {
            'story_id': self.story_id,
            'name': self.name,
            'gender': self.gender,
            'pages': self.get_pages()
        }

