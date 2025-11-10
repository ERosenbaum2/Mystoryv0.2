import eventlet
eventlet.monkey_patch()
from flask import Flask, request, render_template_string, jsonify, send_from_directory, send_file, session, redirect, url_for, flash, Response, stream_with_context
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import re
from openai import OpenAI
import base64
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image
import io
import requests
import tempfile
import threading
import uuid
import time
import random
import queue
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_socketio import SocketIO
# Try to import numpy, but don't fail if it's not available
HAS_NUMPY = False
np = None
try:
    import numpy as np
    HAS_NUMPY = True
except (ImportError, ModuleNotFoundError):
    # numpy is optional - we have a fallback implementation
    HAS_NUMPY = False
    np = None

from typing import List, Dict, Tuple
import logging
from logging.handlers import RotatingFileHandler
from logging import Handler, LogRecord

# Import profanity checker
try:
    from better_profanity import profanity
    # Initialize profanity checker
    profanity.load_censor_words()
    PROFANITY_AVAILABLE = True
except ImportError:
    PROFANITY_AVAILABLE = False
    print("Warning: better-profanity not available. Profanity checking will be disabled.")

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')

# ============================================================================
# BOOK STORAGE CONFIGURATION
# ============================================================================

# Define secure, absolute path for book storage
# Uses absolute path to ensure security and consistency across environments
BOOK_STORAGE_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'books'))
# Structure: /books/{user_id}/{user_id}_{timestamp}_{story_id}.pdf

# Database configuration
# Use PostgreSQL in production (DATABASE_URL from environment) or SQLite for local development
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Production: Use PostgreSQL (DATABASE_URL format: postgresql://user:pass@host:port/dbname)
    # Render and other platforms provide DATABASE_URL
    if database_url.startswith('postgres://'):
        # Convert postgres:// to postgresql:// for SQLAlchemy compatibility
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local development: Use SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fairy_tale_generator.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
from models import db, User, Book, Log, Storyline
db.init_app(app)

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

class DBHandler(Handler):
    """
    Custom logging handler that writes log records to the database.
    This handler receives log records and stores them in the logs table.
    """
    
    def __init__(self, app_instance):
        """
        Initialize the database handler.
        
        Args:
            app_instance: Flask application instance for database context
        """
        super().__init__()
        self.app = app_instance
    
    def emit(self, record: LogRecord):
        """
        Emit a log record to the database.
        
        Args:
            record: LogRecord instance containing log information
        """
        try:
            # Extract user_id from record if available (set via extra parameter)
            user_id = getattr(record, 'user_id', None)
            
            # Get log level as string
            level = record.levelname
            
            # Format the log message
            message = self.format(record)
            
            # Create log entry in database
            with self.app.app_context():
                log_entry = Log(
                    user_id=user_id,
                    level=level,
                    message=message
                )
                db.session.add(log_entry)
                db.session.commit()
        except Exception as e:
            # If database logging fails, don't crash the application
            # Instead, log to stderr as fallback
            self.handleError(record)
            print(f"Error writing log to database: {str(e)}")

def setup_logging(app_instance):
    """
    Configure Python's logging module with file and database handlers.
    
    Args:
        app_instance: Flask application instance
    """
    # Create logs directory if it doesn't exist
    logs_dir = 'logs'
    os.makedirs(logs_dir, exist_ok=True)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File Handler with rotation
    # Rotates when file reaches 10MB, keeps 5 backup files
    file_handler = RotatingFileHandler(
        filename=os.path.join(logs_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Database Handler
    db_handler = DBHandler(app_instance)
    db_handler.setLevel(logging.INFO)
    db_handler.setFormatter(formatter)
    logger.addHandler(db_handler)
    
    # Also log to console for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    logger.info("Logging system initialized - File and Database handlers configured")
    return logger

# Initialize logging system
app_logger = setup_logging(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """Load user from database for Flask-Login session management."""
    return User.query.get(user_id)

# Initialize OAuth
oauth = OAuth(app)

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

# Register Google OAuth client (only if credentials are provided)
google = None
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    try:
        google = oauth.register(
            name='google',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
        print("✓ Google OAuth configured successfully")
    except Exception as e:
        print(f"⚠️  Warning: Failed to configure Google OAuth: {str(e)}")
        google = None
else:
    print("ℹ️  Google OAuth not configured (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not set)")

# Store progress for each generation task
generation_progress = {}

# Store SSE event queues for real-time progress updates
# Key: book_id, Value: queue.Queue for SSE events
sse_event_queues = {}
sse_event_queues_lock = threading.Lock()

# Initialize OpenAI client
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please set it before running the application.")
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Ensure book storage base directory exists
os.makedirs(BOOK_STORAGE_BASE, exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================================================================
# STORYBOOK PAGE PROMPTS FOR IMAGE GENERATION
# ============================================================================
# These prompts are designed to be used with OpenAI's DALL-E API or similar
# image generation services. Each prompt creates one page of a personalized
# children's storybook featuring the child from the uploaded photo.
#
# Structure:
#   - Cover: One cover page prompt per story
#   - Pages: Exactly 12 story page prompts per story
#   Total: 13 prompts per story (1 cover + 12 pages)
#
# Usage Example:
#   prompts = get_all_prompts_for_story('red', 'girl')
#   for prompt_info in prompts:
#       image_url = generate_image_with_dalle(
#           prompt=prompt_info['prompt'],
#           reference_image=child_photo_base64
#       )
#
# Each prompt includes:
#   - 'prompt': The text prompt for image generation
#   - 'description': A brief description of what the page shows
#   - 'page_number': The page number in the story sequence
#
# Note: When using these prompts with DALL-E, include the child's photo as a
#       reference image to ensure the generated images feature the correct child.
# ============================================================================

STORYBOOK_PROMPTS = {
    'red': {
        'cover': {
            'prompt': 'Create a beautiful children\'s book cover illustration in a watercolor/painterly style with a soft, artistic feel that is gentle and emotional. The cover shows a {gender} child dressed as Little Red Riding Hood, wearing a bright red hooded cape, standing in a magical forest clearing. The title "Little Red Riding Hood" must be displayed prominently and elegantly at the top of the cover in beautiful, readable text. The style is whimsical, colorful, and suitable for children, with soft lighting and a fairy tale atmosphere.',
            'description': 'Cover page with the child as Little Red Riding Hood'
        },
        'pages': [
            {
                'page': 1,
                'prompt': 'Create a children\'s book illustration page. The child from the photo is dressed as Little Red Riding Hood, wearing a red hooded cape, holding a wicker basket filled with bread, cakes, and a bottle of wine. The child is standing in a cozy kitchen, talking to their mother who is packing the basket. The mother has a warm, loving expression. The scene is bright, cheerful, and suitable for children, with warm colors and a homey atmosphere.',
                'description': 'Child as Little Red Riding Hood with basket, talking to mother'
            },
            {
                'page': 2,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, dressed in a red hooded cape and carrying a basket, is walking through a beautiful, enchanted forest. Sunlight filters through tall trees, flowers line the path, and friendly woodland creatures (birds, rabbits, squirrels) peek out curiously. The child looks happy and brave, following a winding path. The illustration is colorful, magical, and age-appropriate for children.',
                'description': 'Child walking through the magical forest'
            },
            {
                'page': 3,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, dressed as Little Red Riding Hood, encounters a friendly-looking wolf in the forest. The wolf is sitting on the path ahead, appearing curious but not scary. The child looks surprised but not frightened. The forest setting is still beautiful and magical, with butterflies and flowers nearby. The scene is portrayed in a gentle, non-threatening way suitable for children.',
                'description': 'Child meeting the wolf in the forest'
            },
            {
                'page': 4,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is having a conversation with the friendly wolf on the forest path. The wolf is asking where the child is going, and the child is pointing ahead, explaining they are visiting their grandmother. The wolf looks curious and interested. The scene is friendly and conversational, with the beautiful forest as the backdrop. The illustration maintains a warm, innocent tone.',
                'description': 'Child conversing with the wolf about visiting grandmother'
            },
            {
                'page': 5,
                'prompt': 'Create a children\'s book illustration page. The wolf is running ahead on the forest path, moving quickly but not appearing scary, just excited. The child from the photo, as Little Red Riding Hood, is shown in the background, still walking slowly and picking flowers. The wolf is heading toward a cottage in the distance. The scene shows the forest path with flowers and sunlight, maintaining a gentle, storybook quality.',
                'description': 'Wolf running ahead to grandmother\'s cottage'
            },
            {
                'page': 6,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, arrives at a charming cottage in the forest. The cottage has a thatched roof, a flower garden, and a welcoming door. The child is approaching the door, holding the basket, ready to visit their grandmother. The scene is warm and inviting, with soft afternoon light and a cozy, safe feeling.',
                'description': 'Child arriving at grandmother\'s cottage'
            },
            {
                'page': 7,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is knocking on grandmother\'s cottage door. The child looks cheerful and expectant, holding the basket. The cottage door is slightly ajar, which adds a touch of mystery. The scene is still warm and inviting, with flowers around the door and gentle forest light. The illustration maintains a child-friendly atmosphere.',
                'description': 'Child knocking on grandmother\'s door'
            },
            {
                'page': 8,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is inside grandmother\'s cottage, standing by a bed. In the bed is a friendly-looking wolf wearing a nightcap and glasses, pretending to be the grandmother. The child looks curious and slightly confused but not scared. The room is cozy and warm, with floral wallpaper and a fireplace. The illustration maintains a gentle, humorous tone suitable for children.',
                'description': 'Child discovers the wolf in grandmother\'s bed'
            },
            {
                'page': 9,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is noticing something unusual about "grandmother" - pointing out that the eyes, ears, and teeth look bigger than usual. The child is sitting on the edge of the bed, looking curious and thoughtful. The wolf in the bed looks friendly and comical. The scene is humorous and gentle, showing the child\'s cleverness in a non-scary way.',
                'description': 'Child noticing something different about grandmother'
            },
            {
                'page': 10,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, has realized something is wrong and is calling out for help or about to run. The child looks surprised but not terrified, maintaining a brave expression. The wolf in the bed is still looking friendly and comical. The scene shows a moment of realization but keeps a light, humorous tone suitable for children.',
                'description': 'Child realizing something is wrong and calling for help'
            },
            {
                'page': 11,
                'prompt': 'Create a children\'s book illustration page. A kind, brave hunter character enters grandmother\'s cottage and rescues the child and the real grandmother (who was hiding in the closet). The child from the photo, still dressed as Little Red Riding Hood, is being hugged by their grandmother, both looking happy and relieved. The wolf has run away, and the hunter is standing protectively nearby. The scene is joyful and safe, with warm colors and a happy resolution.',
                'description': 'Hunter rescues child and grandmother'
            },
            {
                'page': 12,
                'prompt': 'Create a children\'s book illustration page. The happy ending scene shows the child from the photo (as Little Red Riding Hood), their grandmother, and the mother all sitting together in grandmother\'s cozy cottage, sharing tea and the treats from the basket. Everyone is smiling and happy. The cottage is warm and inviting, with flowers in vases and afternoon sunlight streaming through the windows. The illustration radiates love, family, and safety.',
                'description': 'Happy ending with family together'
            }
        ]
    },
    'jack': {
        'cover': {
            'prompt': 'Create a beautiful children\'s book cover illustration in a watercolor/painterly style with a soft, artistic feel that is gentle and emotional. The cover shows a {gender} child dressed as Jack, standing at the base of an enormous, magical beanstalk that reaches high into fluffy clouds. The child looks up with wonder and excitement. The title "Jack and the Beanstalk" must be displayed prominently and elegantly at the top of the cover in beautiful, readable text. The style is whimsical, adventurous, and suitable for children, with vibrant greens, blues, and golden colors.',
            'description': 'Cover page with the child as Jack and the magical beanstalk'
        },
        'pages': [
            {
                'page': 1,
                'prompt': 'Create a children\'s book illustration page. The child from the photo is dressed as Jack, wearing simple peasant clothes, standing in a humble cottage with their mother. The mother looks sad and worried, and there\'s a cow in the background. The child, as Jack, is holding the cow\'s rope, looking determined to help. The cottage interior is cozy but shows they need money. The scene is warm and loving, showing the bond between mother and child.',
                'description': 'Child as Jack with mother and the cow at home'
            },
            {
                'page': 2,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, dressed as Jack, is standing in a village marketplace, trading their family cow for a handful of colorful, glowing magic beans. An old, mysterious merchant with a twinkle in their eye is handing over the beans. The child looks hopeful and excited, holding out their hand to receive the magical beans. The marketplace is bustling but the focus is on this magical exchange.',
                'description': 'Child trading the cow for magic beans'
            },
            {
                'page': 3,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, has returned home and is showing the magic beans to their mother. The mother looks disappointed and upset, throwing the beans out the window. The child looks sad but hopeful. The cottage interior shows their humble life. The scene captures the mother\'s frustration but also shows the love between them. The illustration is warm and emotional but not scary.',
                'description': 'Mother\'s reaction - throwing the beans away'
            },
            {
                'page': 4,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, is standing outside their cottage in the morning, looking up in amazement at an enormous, magical beanstalk that grew overnight. The beanstalk reaches high into the sky, through fluffy white clouds. The child\'s face shows wonder and excitement. The mother is also visible, looking surprised but amazed. The scene is bright and magical, with morning sunlight and a sense of adventure beginning.',
                'description': 'The magical beanstalk growing overnight'
            },
            {
                'page': 5,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, is climbing the enormous beanstalk. They are about halfway up, looking determined and brave. Giant green leaves surround them, and they can see the ground getting smaller below. The beanstalk is covered in magical sparkles and the sky above shows fluffy clouds. The illustration captures the excitement and adventure of the climb.',
                'description': 'Child climbing the giant beanstalk'
            },
            {
                'page': 6,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, has reached the top of the beanstalk and is standing in a magnificent castle in the clouds. The castle is made of gold and has beautiful architecture. The child is peeking through a window or door, looking amazed at the sight of a friendly-looking giant (not scary, but large and interesting) inside. The scene is magical and wondrous, with clouds floating by.',
                'description': 'Child discovering the giant\'s castle in the clouds'
            },
            {
                'page': 7,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, is inside the giant\'s castle, holding a golden, glowing egg or a small bag of gold coins. The child looks clever and happy, having found treasure. The giant is in the background, perhaps sleeping or looking the other way. The castle interior is magnificent with golden details. The scene shows the child being brave and resourceful.',
                'description': 'Child finding the golden treasure'
            },
            {
                'page': 8,
                'prompt': 'Create a children\'s book illustration page. The friendly giant in the castle has woken up and noticed the child from the photo (as Jack). The giant looks surprised and curious, but not angry or scary. The child is holding the treasure, looking a bit startled but not terrified. The scene is portrayed in a gentle, friendly way, with the giant appearing more like a large, curious character than a threat.',
                'description': 'Giant noticing Jack in the castle'
            },
            {
                'page': 9,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, is hiding cleverly in the giant\'s castle - perhaps behind a large golden chair or inside a cupboard - while the friendly giant looks around curiously. The child is holding the treasure and looks resourceful and quick-thinking. The castle interior is magnificent. The scene shows the child\'s cleverness in a fun, adventurous way.',
                'description': 'Child hiding from the giant in the castle'
            },
            {
                'page': 10,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, is quickly climbing down the beanstalk, holding the golden treasure. They look determined and focused, moving quickly. The friendly giant is at the top of the beanstalk, looking down curiously but not angry. The mother is visible at the bottom, looking up with concern and hope. The scene shows action and adventure, but in a child-friendly way.',
                'description': 'Child climbing down with the treasure, giant following'
            },
            {
                'page': 11,
                'prompt': 'Create a children\'s book illustration page. The child from the photo, as Jack, has reached the bottom of the beanstalk and is calling to their mother to bring an axe. The child looks determined and brave. The mother is running to help. In the background, the friendly giant is starting to climb down the beanstalk. The scene shows the child taking action to protect their family, showing courage and quick thinking.',
                'description': 'Child preparing to cut down the beanstalk'
            },
            {
                'page': 12,
                'prompt': 'Create a children\'s book illustration page. The happy ending scene shows the child from the photo (as Jack) and their mother together in their cozy cottage, now filled with the golden treasure. The beanstalk has been cut down, and they are safe. The mother is hugging the child, both looking happy and relieved. The cottage is now more comfortable, with the golden egg or coins visible. The scene radiates joy, love, and the reward for being brave and clever. The illustration is warm and celebratory.',
                'description': 'Happy ending with child and mother, now wealthy and safe'
            }
        ]
    }
}

def get_storybook_prompts(story_choice, gender):
    """
    Retrieve and format all storybook prompts for a given story and gender.
    
    Args:
        story_choice: 'red' for Little Red Riding Hood or 'jack' for Jack and the Beanstalk
        gender: 'boy' or 'girl'
    
    Returns:
        Dictionary containing:
        - cover: Cover page prompt
        - pages: List of story page prompts (12 pages)
    """
    if story_choice not in STORYBOOK_PROMPTS:
        return None
    
    story_prompts = STORYBOOK_PROMPTS[story_choice].copy()
    
    # Format the cover prompt with gender
    story_prompts['cover']['prompt'] = story_prompts['cover']['prompt'].format(gender=gender)
    
    # Format all page prompts with gender (currently they don't use {gender} but this is ready for future use)
    for page in story_prompts['pages']:
        if '{gender}' in page['prompt']:
            page['prompt'] = page['prompt'].format(gender=gender)
    
    return story_prompts

def get_all_prompts_for_story(story_choice, gender):
    """
    Get a flat list of all prompts for a story in order (cover, pages).
    Useful for generating all images in sequence.
    
    Returns:
        List of dictionaries with 'type', 'page_number', 'prompt', and 'description'
    """
    prompts = get_storybook_prompts(story_choice, gender)
    if not prompts:
        return []
    
    all_prompts = []
    
    # Add cover
    all_prompts.append({
        'type': 'cover',
        'page_number': 0,
        'prompt': prompts['cover']['prompt'],
        'description': prompts['cover']['description']
    })
    
    # Add story pages - ensure ALL pages are included (no limiting)
    print(f"DEBUG: Found {len(prompts['pages'])} story pages to add")
    for page in prompts['pages']:
        all_prompts.append({
            'type': 'story_page',
            'page_number': page['page'],
            'prompt': page['prompt'],
            'description': page['description']
        })
    
    print(f"DEBUG: Total prompts created: {len(all_prompts)} (should be 13: 1 cover + 12 pages)")
    return all_prompts

def analyze_child_appearance(image_path):
    """
    Use GPT-4 Vision to analyze the child's appearance from the photo.
    Returns a detailed description for use in prompts.
    """
    try:
        # Read and encode image
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
        
        # Determine image format
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f"image/{img_format}"
        
        # Encode to base64
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{img_base64}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """Analyze this photo of a child and provide an EXTREMELY detailed description for consistent illustration generation.

CRITICAL - Extract these EXACT features that must remain identical across all pages:
1. Age: Exact age appearance
2. Ethnicity: Specific ethnic features
3. Hair: EXACT color (e.g., "dark brown", "blonde", "black"), EXACT style (e.g., "short straight", "long curly", "braided"), length, texture
4. Eyes: EXACT color (e.g., "brown", "blue", "green"), shape (e.g., "almond", "round"), size
5. Face shape: EXACT shape (e.g., "round", "oval", "square")
6. Skin tone: EXACT tone description
7. Nose: Shape and size
8. Mouth: Shape and size
9. Distinctive features: Freckles, dimples, birthmarks, etc. - be specific
10. Overall facial proportions

This description will be used to recreate the EXACT same child in every illustration. Be extremely specific - the child must look identical across all 13 pages of the storybook."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=400
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error analyzing child appearance: {str(e)}")
        return "a child with distinct features matching the uploaded photo"

def analyze_illustration_style(image_path):
    """
    Use GPT-4 Vision to analyze the artistic style of a generated illustration.
    Returns a detailed style description including color palette, brushwork, lighting, etc.
    """
    try:
        # Read and encode image
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
        
        # Determine image format
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f"image/{img_format}"
        
        # Encode to base64
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{img_base64}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this children's book illustration and provide a detailed description of its artistic style. Focus on:\n1. Color palette (specific colors, saturation, warmth/coolness)\n2. Brushwork/technique (watercolor, painterly, digital, etc.)\n3. Lighting style (soft, bright, moody, etc.)\n4. Edge quality (soft, hard, blended)\n5. Overall artistic aesthetic\n6. Texture and visual effects\n\nBe extremely specific and detailed. This description will be used to recreate the exact same style in subsequent illustrations. Format as a clear, comprehensive style guide."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=400
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error analyzing illustration style: {str(e)}")
        return "watercolor/painterly style with soft, artistic brushstrokes, gentle color blending, and an emotional, gentle feel"

def extract_master_reference_character_details(image_path):
    """
    Extract MASTER REFERENCE character details from the FIRST generated illustration.
    This is the canonical reference that ALL subsequent images must match exactly.
    
    Returns a comprehensive character description including:
    - Face shape, eye color/shape, skin tone
    - Hair style and color
    - Overall identity and features
    - Age and ethnicity
    """
    try:
        # Read and encode image
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
        
        # Determine image format
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f"image/{img_format}"
        
        # Encode to base64
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{img_base64}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """This is the MASTER REFERENCE IMAGE - the first illustration of the child character.

You MUST extract EVERY detail about the child's appearance that will be used to recreate this EXACT child in all subsequent illustrations.

Provide an EXTREMELY detailed description including:

1. FACE SHAPE: Exact shape (round, oval, square, etc.) and proportions
2. EYE COLOR: Exact color (brown, blue, green, etc.)
3. EYE SHAPE: Exact shape (almond, round, etc.) and size
4. SKIN TONE: Exact tone description
5. HAIR COLOR: Exact color (e.g., "dark brown", "blonde", "black")
6. HAIR STYLE: Exact style (short straight, long curly, braided, etc.), length, texture
7. HAIR TEXTURE: Straight, wavy, curly, etc.
8. AGE APPEARANCE: Exact age appearance
9. ETHNICITY: Specific ethnic features visible
10. NOSE: Shape and size
11. MOUTH: Shape and size
12. DISTINCTIVE FEATURES: Freckles, dimples, birthmarks, etc. - be extremely specific
13. OVERALL FACIAL PROPORTIONS: How features relate to each other
14. FACIAL STRUCTURE: Bone structure, cheekbones, jawline

This description will be the MASTER REFERENCE for ALL subsequent pages. The child in every page MUST match this description exactly - same face, same age, same hair, same everything. Be extremely precise and detailed."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=500
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error extracting master reference character details: {str(e)}")
        return None

def analyze_child_face_from_illustration(image_path):
    """
    Use GPT-4 Vision to analyze the child's face appearance from a generated illustration.
    Returns a detailed face description that can be used to maintain consistency across pages.
    """
    try:
        # Read and encode image
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
        
        # Determine image format
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f"image/{img_format}"
        
        # Encode to base64
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{img_base64}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this children's book illustration and focus specifically on the child character's face and appearance. Provide a detailed description of:\n1. Hair color and exact style/texture\n2. Eye color and shape\n3. Face shape and structure\n4. Skin tone\n5. Nose shape and size\n6. Mouth shape and size\n7. Age appearance\n8. Any distinctive facial features (freckles, dimples, etc.)\n9. Overall facial proportions\n\nBe extremely specific and detailed. This description will be used to recreate the EXACT same child's face in all subsequent illustrations. The child must look identical in every page - this is critical for consistency."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )
        
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error analyzing child face from illustration: {str(e)}")
        return None

def verify_face_matches_master_reference(generated_image_path, master_reference_description):
    """
    Verify if the child's face in a generated image matches the master reference.
    Uses GPT-4 Vision to compare the generated image against the master reference description.
    
    Returns:
        tuple: (matches: bool, feedback: str)
    """
    try:
        # Read and encode image
        with open(generated_image_path, 'rb') as img_file:
            img_data = img_file.read()
        
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f"image/{img_format}"
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{img_base64}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"""Compare this generated illustration against the FIRST GENERATED ILLUSTRATION character description:

FIRST GENERATED ILLUSTRATION (must match exactly):
{master_reference_description}

Analyze if the child character in this NEW illustration matches the FIRST generated illustration in:
1. Face shape - EXACT match required
2. Eye color and shape - EXACT match required
3. Skin tone - EXACT match required
4. Hair style and color - EXACT match required
5. Overall identity and features - EXACT match required
6. Same ethnicity and age appearance - EXACT match required

Respond with JSON:
{{
    "matches": true/false,
    "feedback": "Brief explanation of match or mismatch"
}}

If the face does NOT match the FIRST illustration, respond with matches: false and explain what differs. The child must look like the EXACT same child from the FIRST illustration."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=200
        )
        
        import json
        result = json.loads(response.choices[0].message.content)
        return result.get('matches', False), result.get('feedback', '')
    except Exception as e:
        print(f"Error verifying face match: {str(e)}")
        # If verification fails, assume it matches to avoid blocking generation
        return True, "Verification error - assuming match"

# ============================================================================
# IMAGE VALIDATION MOCK SERVICE
# ============================================================================

def validate_image_for_book(file_path):
    """
    Mock service for complex image validation.
    
    This function simulates validation checks that would normally be performed
    by a more complex image validation service. It uses random chance (80% pass rate)
    to simulate real-world validation outcomes.
    
    Validation checks performed:
    1. Face Detection: Verifies exactly 1 face is detected
    2. Image Quality: Checks if image is blurry or underexposed
    3. Inappropriate Pose: Detects inappropriate poses (e.g., finger in mouth)
    4. Content Safety: Validates content safety
    
    Args:
        file_path: Path to the image file to validate
    
    Returns:
        dict: {
            'status': 'PASS' or 'FAIL',
            'reason': 'Error message if status is FAIL, empty string if PASS'
        }
    """
    try:
        # Verify file exists
        if not os.path.exists(file_path):
            return {
                'status': 'FAIL',
                'reason': 'Image file not found'
            }
        
        # Simulate validation with 80% pass rate
        # This simulates real-world validation where most images pass
        pass_rate = 0.80
        should_pass = random.random() < pass_rate
        
        if should_pass:
            # All checks passed
            return {
                'status': 'PASS',
                'reason': ''
            }
        else:
            # Randomly select which check failed (20% chance of failure)
            # Each check has equal probability of being the failure reason
            failure_reasons = [
                'FAIL: Exactly 1 face not detected.',
                'FAIL: Image is blurry or underexposed.',
                'FAIL: Pose is inappropriate (e.g., finger in mouth).',
                'FAIL: Content safety flag triggered.'
            ]
            
            # Select a random failure reason
            failure_reason = random.choice(failure_reasons)
            
            return {
                'status': 'FAIL',
                'reason': failure_reason
            }
    
    except Exception as e:
        # If validation service encounters an error, fail safely
        app_logger.error(f"Image validation error for {file_path}: {str(e)}", exc_info=True)
        return {
            'status': 'FAIL',
            'reason': f'Validation service error: {str(e)}'
        }

# ============================================================================
# MULTI-THREADED IMAGE GENERATION
# ============================================================================

def generate_page_image(page_data, user_image_path, output_dir, page_index):
    """
    Worker function that simulates the creation of a single page image.
    
    This function represents the work that would be done to generate one page
    of the storybook. In a real implementation, this would call the actual
    image generation API (e.g., DALL-E).
    
    Args:
        page_data: Dictionary containing page information (scene_desc, text, image_prompt_template)
        user_image_path: Path to the user's uploaded image
        output_dir: Directory where generated images should be saved
        page_index: Index of the page (0-11 for the 12 story pages)
    
    Returns:
        dict: {
            'page_number': int,  # Page number (1-12)
            'image_path': str,    # Path to generated image file
            'success': bool,      # Whether generation succeeded
            'error': str          # Error message if failed
        }
    """
    try:
        # Simulate image generation work (in real implementation, this would call DALL-E)
        # Add random delay to simulate variable generation times (0.5-2 seconds)
        generation_time = random.uniform(0.5, 2.0)
        time.sleep(generation_time)
        
        # Create a mock image file for demonstration
        # In production, this would be the actual generated image from DALL-E
        page_number = page_index + 1
        image_filename = f'page_{page_number:02d}.png'
        image_path = os.path.join(output_dir, image_filename)
        
        # Create a simple mock image using PIL
        # This simulates the generated image file
        mock_image = Image.new('RGB', (1024, 1024), color=(200, 220, 255))
        
        # Add some text to indicate it's a mock
        # Just save a simple colored image as placeholder
        mock_image.save(image_path, 'PNG')
        
        print(f"✓ Generated page {page_number} image: {image_path}")
        
        return {
            'page_number': page_number,
            'image_path': image_path,
            'success': True,
            'error': None
        }
    
    except Exception as e:
        page_number = page_index + 1
        error_msg = f"Error generating page {page_number}: {str(e)}"
        print(f"✗ {error_msg}")
        app_logger.error(error_msg, exc_info=True)
        
        return {
            'page_number': page_number,
            'image_path': None,
            'success': False,
            'error': str(e)
        }

# ============================================================================
# BOOK STORAGE AND FILE NAMING UTILITIES
# ============================================================================

def generate_book_filepath(user_id, story_id):
    """
    Generate a secure file path for a book PDF following the naming convention:
    {user_id}_{timestamp}_{story_id}.pdf
    
    The file is stored in a user-specific subdirectory: /books/{user_id}/
    
    Args:
        user_id: The user's unique identifier
        story_id: The story identifier (e.g., 'red', 'jack')
    
    Returns:
        tuple: (full_file_path, relative_file_path)
            - full_file_path: Absolute path to the file
            - relative_file_path: Relative path from the base directory (for database storage)
    """
    # Create timestamp in format: YYYYMMDD_HHMMSS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Generate filename following convention: {user_id}_{timestamp}_{story_id}.pdf
    filename = f"{user_id}_{timestamp}_{story_id}.pdf"
    
    # Create user-specific subdirectory
    user_dir = os.path.join(BOOK_STORAGE_BASE, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    
    # Generate full absolute path
    full_path = os.path.join(user_dir, filename)
    
    # Generate relative path for database storage (relative to BOOK_STORAGE_BASE)
    relative_path = os.path.join(str(user_id), filename)
    
    # Normalize paths (handle Windows/Unix differences)
    full_path = os.path.normpath(full_path)
    relative_path = os.path.normpath(relative_path).replace('\\', '/')  # Use forward slashes for DB
    
    return full_path, relative_path

def _send_sse_event(book_id, event_type, data):
    """
    Helper function to send SSE events to the queue for a specific book_id.
    
    Args:
        book_id: The book ID to send the event to
        event_type: Type of event (e.g., 'page_complete', 'generation_complete', 'error')
        data: Dictionary containing event data
    """
    with sse_event_queues_lock:
        if book_id in sse_event_queues:
            try:
                event_data = {
                    'type': event_type,
                    'data': data,
                    'timestamp': time.time()
                }
                sse_event_queues[book_id].put(event_data, timeout=0.1)
            except queue.Full:
                # Queue is full, skip this event (non-blocking)
                pass

def start_book_generation(storyline_id, user_image_path, output_dir=None, book_id=None, user_id=None, child_name=None):
    """
    Master function that orchestrates parallel image generation for all 12 story pages.
    
    This function:
    1. Loads the 12 page objects from the Storyline model
    2. Submits all 12 page generation tasks to ThreadPoolExecutor simultaneously
    3. Collects results as they complete using as_completed()
    4. Sends real-time SSE updates when book_id is provided
    5. Compiles the final PDF and saves it to the database
    
    Args:
        storyline_id: The story_id from the Storyline model (e.g., 'red', 'jack')
        user_image_path: Path to the user's uploaded image
        output_dir: Directory where generated images should be saved (optional)
        book_id: Optional book ID for SSE real-time updates
        user_id: User ID for book storage and database record (required for saving)
        child_name: Name of the child featured in the story (required for database record)
    
    Returns:
        dict: {
            'success': bool,
            'results': list of result dictionaries from generate_page_image,
            'total_pages': int,
            'completed_pages': int,
            'failed_pages': int,
            'errors': list of error messages,
            'output_dir': str,
            'pdf_path': str,  # Path to generated PDF (if saved)
            'book_id': str    # Book ID from database (if saved)
        }
    """
    try:
        # Create output directory if not provided
        if output_dir is None:
            output_dir = os.path.join('generated_images', str(uuid.uuid4()))
        os.makedirs(output_dir, exist_ok=True)
        
        # Load storyline from database
        with app.app_context():
            storyline = Storyline.query.filter_by(story_id=storyline_id).first()
            
            if not storyline:
                return {
                    'success': False,
                    'results': [],
                    'total_pages': 0,
                    'completed_pages': 0,
                    'failed_pages': 0,
                    'errors': [f'Storyline {storyline_id} not found'],
                    'output_dir': output_dir
                }
            
            # Get the 12 page objects from the storyline
            pages = storyline.get_pages()
            
            if len(pages) != 12:
                return {
                    'success': False,
                    'results': [],
                    'total_pages': len(pages),
                    'completed_pages': 0,
                    'failed_pages': 0,
                    'errors': [f'Expected 12 pages but found {len(pages)}'],
                    'output_dir': output_dir
                }
        
        print(f"\n{'='*60}")
        print(f"Starting parallel image generation for storyline: {storyline_id}")
        print(f"Total pages to generate: {len(pages)}")
        print(f"Output directory: {output_dir}")
        if book_id:
            print(f"Book ID for SSE updates: {book_id}")
        print(f"{'='*60}\n")
        
        # Initialize page status tracker for SSE updates
        page_status = {i+1: {'status': 'pending', 'image_path': None} for i in range(12)}
        
        # Send initial status update
        if book_id:
            _send_sse_event(book_id, 'generation_started', {
                'total_pages': 12,
                'status': 'started'
            })
        
        # Prepare results storage
        results = []
        errors = []
        completed_count = 0
        failed_count = 0
        
        # Use ThreadPoolExecutor to manage parallel execution
        # max_workers=12 allows all 12 pages to be generated simultaneously
        with ThreadPoolExecutor(max_workers=12) as executor:
            # Submit all 12 tasks simultaneously
            future_to_page = {}
            
            for page_index, page_data in enumerate(pages):
                # Submit each page generation task
                future = executor.submit(
                    generate_page_image,
                    page_data,
                    user_image_path,
                    output_dir,
                    page_index
                )
                future_to_page[future] = page_index
            
            print(f"✓ Submitted {len(future_to_page)} page generation tasks to ThreadPoolExecutor")
            
            # Collect results as they complete (using as_completed for real-time processing)
            for future in as_completed(future_to_page):
                page_index = future_to_page[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result['success']:
                        completed_count += 1
                        print(f"✓ Page {result['page_number']} completed successfully")
                        
                        # Update page status tracker
                        page_status[result['page_number']] = {
                            'status': 'complete',
                            'image_path': result['image_path']
                        }
                        
                        # Send SSE update for completed page
                        if book_id:
                            # Convert image path to URL-friendly path
                            image_url = result['image_path'].replace('\\', '/')
                            if not image_url.startswith('/'):
                                image_url = '/' + image_url
                            
                            _send_sse_event(book_id, 'page_complete', {
                                'page_number': result['page_number'],
                                'image_path': result['image_path'],
                                'image_url': image_url,
                                'completed_count': completed_count,
                                'total_pages': 12
                            })
                    else:
                        failed_count += 1
                        errors.append(f"Page {result['page_number']}: {result['error']}")
                        print(f"✗ Page {result['page_number']} failed: {result['error']}")
                        
                        # Update page status tracker
                        page_status[result['page_number']] = {
                            'status': 'failed',
                            'image_path': None,
                            'error': result['error']
                        }
                        
                        # Send SSE update for failed page
                        if book_id:
                            _send_sse_event(book_id, 'page_failed', {
                                'page_number': result['page_number'],
                                'error': result['error'],
                                'failed_count': failed_count,
                                'total_pages': 12
                            })
                
                except Exception as e:
                    failed_count += 1
                    error_msg = f"Page {page_index + 1} exception: {str(e)}"
                    errors.append(error_msg)
                    print(f"✗ {error_msg}")
                    
                    page_number = page_index + 1
                    results.append({
                        'page_number': page_number,
                        'image_path': None,
                        'success': False,
                        'error': str(e)
                    })
                    
                    # Update page status tracker
                    page_status[page_number] = {
                        'status': 'failed',
                        'image_path': None,
                        'error': str(e)
                    }
                    
                    # Send SSE update for exception
                    if book_id:
                        _send_sse_event(book_id, 'page_failed', {
                            'page_number': page_number,
                            'error': str(e),
                            'failed_count': failed_count,
                            'total_pages': 12
                        })
        
        # Sort results by page number for consistent ordering
        results.sort(key=lambda x: x['page_number'])
        
        print(f"\n{'='*60}")
        print(f"Parallel generation complete!")
        print(f"Total pages: {len(pages)}")
        print(f"Completed: {completed_count}")
        print(f"Failed: {failed_count}")
        print(f"{'='*60}\n")
        
        # Send final completion event
        if book_id:
            _send_sse_event(book_id, 'generation_complete', {
                'success': failed_count == 0,
                'total_pages': len(pages),
                'completed_pages': completed_count,
                'failed_pages': failed_count,
                'errors': errors,
                'output_dir': output_dir,
                'page_status': page_status
            })
        
        # Post-completion: Compile PDF and save to database
        pdf_path = None
        saved_book_id = None
        
        if failed_count == 0 and user_id and child_name:
            try:
                # Generate book filepath using naming convention
                full_pdf_path, relative_pdf_path = generate_book_filepath(user_id, storyline_id)
                
                # Simulate PDF compilation by creating an empty file
                # In production, this would compile the actual PDF from generated images
                with open(full_pdf_path, 'wb') as pdf_file:
                    # Create a minimal PDF header (simulation)
                    # In production, use reportlab or similar to create actual PDF
                    pdf_file.write(b'%PDF-1.4\n')
                    pdf_file.write(b'%Simulated PDF - Replace with actual PDF compilation\n')
                    pdf_file.write(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
                    pdf_file.write(b'xref\n0 3\ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n100\n%%EOF')
                
                print(f"✓ PDF created at: {full_pdf_path}")
                
                # Save book record to database
                with app.app_context():
                    # Generate book_id if not provided
                    if not book_id:
                        saved_book_id = str(uuid.uuid4())
                    else:
                        saved_book_id = book_id
                    
                    # Create new Book record
                    new_book = Book(
                        book_id=saved_book_id,
                        user_id=user_id,
                        story_id=storyline_id,
                        child_name=child_name,
                        pdf_path=relative_pdf_path  # Store relative path in database
                    )
                    
                    db.session.add(new_book)
                    db.session.commit()
                    
                    print(f"✓ Book record saved to database: {saved_book_id}")
                    print(f"  - User ID: {user_id}")
                    print(f"  - Story ID: {storyline_id}")
                    print(f"  - Child Name: {child_name}")
                    print(f"  - PDF Path: {relative_pdf_path}")
                
                pdf_path = relative_pdf_path
                
            except Exception as e:
                error_msg = f"Error saving book to storage/database: {str(e)}"
                app_logger.error(error_msg, exc_info=True)
                print(f"✗ {error_msg}")
                # Don't fail the entire generation if saving fails
                errors.append(error_msg)
        
        return {
            'success': failed_count == 0,
            'results': results,
            'total_pages': len(pages),
            'completed_pages': completed_count,
            'failed_pages': failed_count,
            'errors': errors,
            'output_dir': output_dir,
            'page_status': page_status,
            'pdf_path': pdf_path,
            'book_id': saved_book_id
        }
    
    except Exception as e:
        error_msg = f"Error in start_book_generation: {str(e)}"
        app_logger.error(error_msg, exc_info=True)
        return {
            'success': False,
            'results': [],
            'total_pages': 0,
            'completed_pages': 0,
            'failed_pages': 0,
            'errors': [error_msg],
            'output_dir': output_dir if 'output_dir' in locals() else None
        }

def extract_consistency_info_from_image(image_path, page_description, story_choice):
    """
    Extract structured consistency information from a generated image using GPT-4 Vision.
    This includes character features, objects, and their descriptions.
    Returns a structured dictionary for RAG storage.
    """
    try:
        # Read and encode image
        with open(image_path, 'rb') as img_file:
            img_data = img_file.read()
        
        img = Image.open(io.BytesIO(img_data))
        img_format = img.format.lower() if img.format else 'jpeg'
        mime_type = f"image/{img_format}"
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        data_url = f"data:{mime_type};base64,{img_base64}"
        
        # Determine what to extract based on story
        extraction_prompt = f"""Analyze this children's book illustration (page: {page_description}) and extract EXACT details for consistency:

1. CHARACTER FEATURES (must be identical across all pages):
   - Hair: color, style, length, texture
   - Eyes: color, shape, size
   - Face: shape, skin tone, age
   - Distinctive features: freckles, dimples, etc.

2. OBJECTS AND ITEMS (must match previous pages):
"""
        
        if story_choice == 'red':
            extraction_prompt += """   - Basket contents: EXACT items inside (bread type, cakes type, wine bottle appearance)
   - Red cape: exact shade of red, style, length, details
"""
        elif story_choice == 'jack':
            extraction_prompt += """   - Magic beans: exact color, size, glow effect
   - Treasure: exact appearance (golden egg or coins, details)
   - Beanstalk: exact green shade, leaf size, sparkle details
"""
        
        extraction_prompt += """\n3. STYLE: color palette, brushwork, lighting

Format as JSON with keys: character_features, objects, style. Be extremely specific - these details must match exactly across all pages."""
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": extraction_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )
        
        import json
        content = response.choices[0].message.content
        try:
            consistency_info = json.loads(content)
            return consistency_info
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract as text
            print(f"Warning: Could not parse JSON, trying text extraction")
            # Return as a simple dict with the raw text
            return {
                'character_features': content[:200] if len(content) > 200 else content,
                'objects': '',
                'style': ''
            }
    except Exception as e:
        print(f"Error extracting consistency info: {str(e)}")
        return None

def create_embedding(text: str) -> List[float]:
    """
    Create an embedding for text using OpenAI's text-embedding-3-small model.
    """
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Error creating embedding: {str(e)}")
        return None

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    Uses numpy if available, otherwise falls back to pure Python.
    """
    try:
        # Try numpy first (faster) if available
        if HAS_NUMPY and np is not None:
            try:
                vec1_arr = np.array(vec1)
                vec2_arr = np.array(vec2)
                return np.dot(vec1_arr, vec2_arr) / (np.linalg.norm(vec1_arr) * np.linalg.norm(vec2_arr))
            except Exception:
                pass  # Fall through to pure Python implementation
        
        # Fallback to pure Python if numpy not available or failed
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)
    except Exception as e:
        print(f"Error calculating similarity: {str(e)}")
        return 0.0

def retrieve_relevant_context(query_text: str, context_store: List[Dict], top_k: int = 3) -> List[Dict]:
    """
    Use RAG to retrieve the most relevant context chunks from previous images.
    
    Args:
        query_text: The current page description or prompt to find relevant context for
        context_store: List of previous image contexts with embeddings
        top_k: Number of top relevant chunks to retrieve
    
    Returns:
        List of top_k most relevant context chunks
    """
    if not context_store:
        return []
    
    try:
        # Create embedding for query
        query_embedding = create_embedding(query_text)
        if not query_embedding:
            return context_store[:top_k]  # Fallback to first items
        
        # Calculate similarities
        similarities = []
        for context in context_store:
            if context.get('embedding'):
                similarity = cosine_similarity(query_embedding, context['embedding'])
                similarities.append((similarity, context))
        
        # Sort by similarity and return top_k
        similarities.sort(key=lambda x: x[0], reverse=True)
        return [context for _, context in similarities[:top_k]]
    except Exception as e:
        print(f"Error in RAG retrieval: {str(e)}")
        return context_store[:top_k]  # Fallback

def generate_character_consistency_rules(child_appearance, story_choice, is_cover=False):
    """
    Generate comprehensive character consistency rules for image generation.
    These rules ensure the child looks identical across all pages.
    
    Args:
        child_appearance: Description of child's appearance from photo
        story_choice: 'red' or 'jack'
        is_cover: Whether this is the cover page
    
    Returns:
        Formatted string with consistency rules
    """
    # Truncate child appearance to fit within prompt limits
    child_appearance_short = child_appearance[:250] if len(child_appearance) > 250 else child_appearance
    
    if story_choice == 'red':
        rules = f"""CORE CHARACTER CONSISTENCY RULES - MANDATORY:
- The child character MUST look EXACTLY like the reference photo in every single image
- Based on photo: {child_appearance_short}
- ALWAYS maintain: same age, ethnicity, hair color & hairstyle, face shape, skin tone, eye color & shape
- The child must ALWAYS look like the same real child across all pages - NO variations

LITTLE RED RIDING HOOD SPECIFIC:
- Red cloak/cape: Keep the EXACT same shade of red, style, length, and details in every page
- Basket: Must contain the EXACT same items (bread, cakes, wine bottle) with same appearance
- The child's face must be identical to the photo in every illustration"""
    
    elif story_choice == 'jack':
        rules = f"""CORE CHARACTER CONSISTENCY RULES - MANDATORY:
- The child character MUST look EXACTLY like the reference photo in every single image
- Based on photo: {child_appearance_short}
- ALWAYS maintain: same age, ethnicity, hair color & hairstyle, face shape, skin tone, eye color & shape
- The child must ALWAYS look like the same real child across all pages - NO variations

JACK AND THE BEANSTALK SPECIFIC:
- Magic beans: Keep EXACT same color, size, and glow effect when shown
- Treasure: Maintain EXACT same appearance (golden egg or coins) with same details
- Beanstalk: Keep EXACT same green shade, leaf size, and sparkle details
- The child's face must be identical to the photo in every illustration"""
    
    else:
        rules = f"""CORE CHARACTER CONSISTENCY RULES - MANDATORY:
- The child character MUST look EXACTLY like the reference photo in every single image
- Based on photo: {child_appearance_short}
- ALWAYS maintain: same age, ethnicity, hair color & hairstyle, face shape, skin tone, eye color & shape
- The child must ALWAYS look like the same real child across all pages - NO variations"""
    
    return rules

def generate_style_consistency_rules(is_cover=False, style_description=None):
    """
    Generate style consistency rules for the entire storybook.
    
    Args:
        is_cover: Whether this is the cover page
        style_description: Style description from cover (if available)
    
    Returns:
        Formatted string with style rules
    """
    if is_cover:
        return """STYLE RULES - APPLY TO ALL PAGES:
- Soft illustrated children's book style
- Warm lighting, gentle colors, magical fairy-tale tone
- Watercolor/painterly technique with soft brushstrokes
- No anime style, no hyper-realism, no style changes between pages
- Consistent art style for the entire book - gentle, emotional, dreamy atmosphere"""
    else:
        if style_description:
            style_short = style_description[:200] if len(style_description) > 200 else style_description
            return f"""STYLE RULES - MATCH COVER EXACTLY:
- Use the EXACT same style as the cover page: {style_short}
- Same color palette, brushwork, lighting, edge quality, and aesthetic
- No style changes - must be visually identical to cover page"""
        else:
            return """STYLE RULES:
- Soft illustrated children's book style
- Warm lighting, gentle colors, magical fairy-tale tone
- Consistent art style - gentle, emotional, dreamy atmosphere"""

def generate_page_text(prompt_info, story_choice, page_number, total_pages, character_name):
    """
    Generate text content (speech bubbles and narrative) for a storybook page.
    
    Args:
        prompt_info: Dictionary with prompt and description
        story_choice: 'red' or 'jack'
        page_number: Current page number
        total_pages: Total number of pages
        character_name: The name of the main character to use in the story
    """
    story_context = {
        'red': 'Little Red Riding Hood',
        'jack': 'Jack and the Beanstalk'
    }
    story_name = story_context.get(story_choice, 'Story')
    
    # Create a more detailed prompt that uses the actual page prompt description
    page_prompt_text = prompt_info.get('prompt', '')[:200]  # Use first 200 chars of image prompt for context
    
    text_prompt = f"""Create storybook text for page {page_number} of {total_pages} in the children's storybook "{story_name}".

Page description: {prompt_info['description']}
Page scene: {page_prompt_text}

CRITICAL: The main character's name is "{character_name}". Use this name throughout the text instead of "the child" or generic terms.

Write 2-3 simple sentences that tell the story for this page. The text should:
- Use the character's name "{character_name}" when referring to the main character
- Be written in third person, simple past tense
- Be age-appropriate for 4-8 year olds
- Match what's happening in the illustration
- Be engaging and easy to read
- Each sentence should be 8-15 words maximum

Examples (using character name "{character_name}"):
- "{character_name} walked through the magical forest. Birds and butterflies danced around {character_name}."
- "{character_name} climbed up the enormous beanstalk. Higher and higher {character_name} went into the clouds."
- "{character_name} knocked on the door. {character_name} was excited to see their grandmother."

Format as JSON:
{{
  "narrative": ["sentence 1", "sentence 2", "sentence 3"]
}}

IMPORTANT: 
- You MUST provide at least 2 narrative sentences. The narrative cannot be empty.
- Always use the character's name "{character_name}" instead of "the child" or generic pronouns when referring to the main character."""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a children's book writer who creates simple, engaging text for picture books. Always provide narrative text - it is required."
                },
                {
                    "role": "user",
                    "content": text_prompt
                }
            ],
            max_tokens=200,
            temperature=0.7
        )
        
        text_content = response.choices[0].message.content
        
        # Try to parse JSON from response
        import json
        try:
            # Extract JSON from response if it's wrapped in markdown
            if '```json' in text_content:
                text_content = text_content.split('```json')[1].split('```')[0].strip()
            elif '```' in text_content:
                text_content = text_content.split('```')[1].split('```')[0].strip()
            
            text_data = json.loads(text_content)
            
            # Validate and ensure we have narrative text
            if not text_data.get('narrative'):
                text_data['narrative'] = []
            
            # Filter out empty strings
            text_data['narrative'] = [n for n in text_data['narrative'] if n and n.strip()]
            
            # If no narrative after filtering, create a fallback based on description
            if not text_data['narrative']:
                # Create simple narrative from description using character name
                desc = prompt_info['description'].lower()
                if 'cover' in desc:
                    text_data['narrative'] = [f"Welcome to the story of {story_name}, featuring {character_name}."]
                elif 'child' in desc or 'jack' in desc or 'red' in desc:
                    # Create narrative based on common story elements using character name
                    if 'walking' in desc or 'forest' in desc:
                        text_data['narrative'] = [f"{character_name} walked through the magical forest."]
                    elif 'mother' in desc or 'home' in desc:
                        text_data['narrative'] = [f"{character_name} was at home with their mother."]
                    elif 'beanstalk' in desc:
                        text_data['narrative'] = [f"{character_name} looked up at the enormous beanstalk."]
                    elif 'castle' in desc or 'giant' in desc:
                        text_data['narrative'] = [f"{character_name} discovered a magnificent castle in the clouds."]
                    else:
                        text_data['narrative'] = [f"{character_name}'s adventure continues on page {page_number}."]
                else:
                    text_data['narrative'] = [f"{character_name}'s adventure continues on page {page_number}."]
            
            return text_data
        except Exception as parse_error:
            print(f"Error parsing JSON for page {page_number}: {parse_error}")
            print(f"Raw response: {text_content[:200]}")
            # Fallback: create narrative from description using character name
            desc = prompt_info['description']
            fallback_narrative = f"{character_name}'s story continues: {desc}."
            return {
                "narrative": [fallback_narrative]
            }
    except Exception as e:
        print(f"Error generating page text: {str(e)}")
        # Always return at least some narrative text as fallback using character name
        desc = prompt_info.get('description', f'Page {page_number}')
        return {
            "narrative": [f"{character_name}'s story continues on page {page_number}."]
        }

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fairy Tale Generator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            color: white;
            margin-bottom: 40px;
            padding: 30px 0;
        }
        
        .header h1 {
            font-size: 3em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .header p {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .form-container {
            background: white;
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            margin-bottom: 30px;
        }
        
        .form-group {
            margin-bottom: 30px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 10px;
            font-weight: 600;
            color: #333;
            font-size: 1.1em;
        }
        
        .radio-group {
            display: flex;
            gap: 20px;
            margin-top: 10px;
        }
        
        .radio-option {
            flex: 1;
            padding: 15px;
            border: 3px solid #e1e5e9;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
            background: #f8f9fa;
        }
        
        .radio-option:hover {
            border-color: #667eea;
            background: #f0f4ff;
            transform: translateY(-2px);
        }
        
        .radio-option input[type="radio"] {
            margin-right: 8px;
        }
        
        .radio-option.selected {
            border-color: #667eea;
            background: #e8f0ff;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }
        
        select {
            width: 100%;
            padding: 15px;
            border: 3px solid #e1e5e9;
            border-radius: 12px;
            font-size: 1em;
            background: white;
            cursor: pointer;
            transition: border-color 0.3s ease;
        }
        
        select:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .file-upload {
            position: relative;
            display: inline-block;
            width: 100%;
        }
        
        .file-upload input[type="file"] {
            position: absolute;
            opacity: 0;
            width: 100%;
            height: 100%;
            cursor: pointer;
        }
        
        .file-upload-label {
            display: block;
            padding: 40px;
            border: 3px dashed #667eea;
            border-radius: 12px;
            text-align: center;
            background: #f8f9fa;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .file-upload-label:hover {
            background: #f0f4ff;
            border-color: #764ba2;
        }
        
        .file-upload-label.dragover {
            background: #e8f0ff;
            border-color: #667eea;
            transform: scale(1.02);
        }
        
        .file-name {
            margin-top: 10px;
            color: #667eea;
            font-weight: 600;
        }
        
        .preview-image {
            max-width: 100%;
            max-height: 300px;
            margin-top: 15px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .submit-btn {
            width: 100%;
            padding: 18px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1.2em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            margin-top: 20px;
        }
        
        .submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
        }
        
        .submit-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 30px;
            color: #667eea;
        }
        
        .loading-spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        .progress-container {
            margin-top: 20px;
        }
        
        .progress-bar-container {
            width: 100%;
            height: 30px;
            background-color: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin: 15px 0;
        }
        
        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 12px;
        }
        
        .progress-text {
            margin-top: 10px;
            font-size: 1em;
            color: #667eea;
            font-weight: 600;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .result-container {
            display: none;
            background: white;
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            margin-top: 30px;
        }
        
        .result-container h2 {
            color: #667eea;
            margin-bottom: 20px;
            font-size: 2em;
        }
        
        .story-content {
            line-height: 1.8;
            font-size: 1.1em;
            color: #333;
            white-space: pre-wrap;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 12px;
            border-left: 4px solid #667eea;
        }
        
        .error {
            background: #fee;
            color: #c33;
            padding: 15px;
            border-radius: 12px;
            border-left: 4px solid #c33;
            margin-top: 20px;
        }
        
        .success-msg {
            background: #efe;
            color: #3c3;
            padding: 15px;
            border-radius: 12px;
            border-left: 4px solid #3c3;
            margin-top: 20px;
        }
        
        .download-btn {
            display: inline-block;
            margin-top: 20px;
            padding: 18px 40px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1.2em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }
        
        .download-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.5);
        }
        
        .download-btn:active {
            transform: translateY(0);
        }
        
        .download-container {
            text-align: center;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>✨ Fairy Tale Generator ✨</h1>
            <p>Create a personalized story for your child</p>
        </div>
        
        <div class="form-container">
            <form id="storyForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label>Choose Gender:</label>
                    <div class="radio-group">
                        <label class="radio-option" onclick="selectRadio(this, 'gender', 'boy')">
                            <input type="radio" name="gender" value="boy" required>
                            👦 Boy
                        </label>
                        <label class="radio-option" onclick="selectRadio(this, 'gender', 'girl')">
                            <input type="radio" name="gender" value="girl" required>
                            👧 Girl
                        </label>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>Select Story:</label>
                    <select name="story" id="storySelect" required disabled>
                        <option value="">Please select a gender first</option>
                    </select>
                    <small id="storyHelp" style="color: #999; display: block; margin-top: 5px;">
                        Select a gender to see available stories
                    </small>
                </div>
                
                <div class="form-group">
                    <label>Character's Name:</label>
                    <input type="text" name="character_name" id="characterName" placeholder="Enter the main character's name" required style="width: 100%; padding: 15px; border: 3px solid #e1e5e9; border-radius: 12px; font-size: 1em; background: white; cursor: text; transition: border-color 0.3s ease;">
                    <small style="color: #999; display: block; margin-top: 5px;">This name will be used throughout the story</small>
                </div>
                
                <div class="form-group">
                    <label>Upload Child's Image:</label>
                    <div class="file-upload">
                        <input type="file" name="image" id="imageInput" accept="image/*" required>
                        <label for="imageInput" class="file-upload-label" id="fileLabel">
                            📷 Click to upload or drag and drop
                            <br>
                            <small style="color: #999;">PNG, JPG, JPEG, GIF, WEBP (max 16MB)</small>
                        </label>
                        <div id="fileName" class="file-name"></div>
                        <img id="imagePreview" class="preview-image" style="display: none;">
                    </div>
                </div>
                
                <button type="submit" class="submit-btn" id="submitBtn">Generate Story ✨</button>
            </form>
            
            <div class="loading" id="loading">
                <div class="loading-spinner"></div>
                <p id="loadingText">Creating your personalized storybook...</p>
                <div class="progress-container">
                    <div class="progress-bar-container">
                        <div class="progress-bar-fill" id="progressBar" style="width: 0%;">0%</div>
                    </div>
                    <p class="progress-text" id="progressText">Starting...</p>
                </div>
            </div>
        </div>
        
        <div class="result-container" id="resultContainer">
            <h2>Storybook Generation</h2>
            <div class="story-content" id="storyContent"></div>
        </div>
    </div>
    
    <script>
        function selectRadio(element, name, value) {
            document.querySelectorAll(`input[name="${name}"]`).forEach(radio => {
                radio.closest('.radio-option').classList.remove('selected');
            });
            element.classList.add('selected');
            document.querySelector(`input[name="${name}"][value="${value}"]`).checked = true;
            
            // If gender is being selected, trigger story dropdown update
            if (name === 'gender') {
                updateStoryDropdown(value);
            }
            
            // Validate form
            validateForm();
        }
        
        function updateStoryDropdown(gender) {
            const storySelect = document.getElementById('storySelect');
            const submitBtn = document.getElementById('submitBtn');
            const storyHelp = document.getElementById('storyHelp');
            
            // Clear current selection
            storySelect.innerHTML = '<option value="">Loading stories...</option>';
            storySelect.disabled = true;
            submitBtn.disabled = true;
            storyHelp.textContent = 'Loading stories...';
            
            // Make AJAX call to fetch stories by gender
            fetch(`/api/stories_by_gender/${gender}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Clear and populate dropdown
                        storySelect.innerHTML = '<option value="">Choose a story...</option>';
                        
                        if (data.stories && data.stories.length > 0) {
                            data.stories.forEach(story => {
                                const option = document.createElement('option');
                                option.value = story.story_id;
                                option.textContent = story.name;
                                storySelect.appendChild(option);
                            });
                            storySelect.disabled = false;
                            storyHelp.textContent = `${data.count} story${data.count !== 1 ? 'ies' : ''} available`;
                        } else {
                            storySelect.innerHTML = '<option value="">No stories available</option>';
                            storySelect.disabled = true;
                            storyHelp.textContent = 'No stories available for this gender';
                        }
                    } else {
                        storySelect.innerHTML = '<option value="">Error loading stories</option>';
                        storySelect.disabled = true;
                        storyHelp.textContent = 'Error loading stories';
                        console.error('Error loading stories:', data.error);
                    }
                    
                    // Re-validate form
                    validateForm();
                })
                .catch(error => {
                    console.error('Error fetching stories:', error);
                    storySelect.innerHTML = '<option value="">Error loading stories</option>';
                    storySelect.disabled = true;
                    storyHelp.textContent = 'Error loading stories. Please try again.';
                    validateForm();
                });
        }
        
        function validateForm() {
            const gender = document.querySelector('input[name="gender"]:checked');
            const story = document.getElementById('storySelect');
            const characterName = document.getElementById('characterName');
            const imageInput = document.getElementById('imageInput');
            const submitBtn = document.getElementById('submitBtn');
            
            // Check if all required fields are filled
            const isGenderSelected = gender !== null;
            const isStorySelected = story.value !== '';
            const isCharacterNameFilled = characterName.value.trim() !== '';
            const isImageSelected = imageInput.files.length > 0;
            
            // Enable/disable submit button based on validation
            if (isGenderSelected && isStorySelected && isCharacterNameFilled && isImageSelected) {
                submitBtn.disabled = false;
            } else {
                submitBtn.disabled = true;
            }
        }
        
        const imageInput = document.getElementById('imageInput');
        const fileLabel = document.getElementById('fileLabel');
        const fileName = document.getElementById('fileName');
        const imagePreview = document.getElementById('imagePreview');
        
        imageInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                fileName.textContent = 'Selected: ' + file.name;
                const reader = new FileReader();
                reader.onload = function(e) {
                    imagePreview.src = e.target.result;
                    imagePreview.style.display = 'block';
                };
                reader.readAsDataURL(file);
            }
            validateForm();
        });
        
        // Add event listeners for form validation
        document.getElementById('characterName').addEventListener('input', validateForm);
        document.getElementById('storySelect').addEventListener('change', validateForm);
        
        // Initialize submit button as disabled
        document.getElementById('submitBtn').disabled = true;
        
        // Drag and drop functionality
        const fileUpload = document.querySelector('.file-upload');
        
        fileUpload.addEventListener('dragover', function(e) {
            e.preventDefault();
            fileLabel.classList.add('dragover');
        });
        
        fileUpload.addEventListener('dragleave', function(e) {
            e.preventDefault();
            fileLabel.classList.remove('dragover');
        });
        
        fileUpload.addEventListener('drop', function(e) {
            e.preventDefault();
            fileLabel.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                imageInput.files = files;
                const file = files[0];
                fileName.textContent = 'Selected: ' + file.name;
                const reader = new FileReader();
                reader.onload = function(e) {
                    imagePreview.src = e.target.result;
                    imagePreview.style.display = 'block';
                };
                reader.readAsDataURL(file);
            }
        });
        
        document.getElementById('storyForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const submitBtn = document.getElementById('submitBtn');
            const loading = document.getElementById('loading');
            const resultContainer = document.getElementById('resultContainer');
            const storyContent = document.getElementById('storyContent');
            const progressBar = document.getElementById('progressBar');
            const progressText = document.getElementById('progressText');
            const loadingText = document.getElementById('loadingText');
            
            submitBtn.disabled = true;
            loading.style.display = 'block';
            resultContainer.style.display = 'none';
            progressBar.style.width = '0%';
            progressBar.textContent = '0%';
            loadingText.textContent = 'Starting storybook generation...';
            progressText.textContent = 'Initializing...';
            
            let taskId = null;
            let progressInterval = null;
            
            try {
                // Start generation
                const response = await fetch('/generate-story', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.error || 'Failed to start generation');
                }
                
                taskId = data.task_id;
                
                // Poll for progress
                progressInterval = setInterval(async () => {
                    try {
                        const progressResponse = await fetch(`/progress/${taskId}`);
                        const progressData = await progressResponse.json();
                        
                        if (progressData.error) {
                            clearInterval(progressInterval);
                            throw new Error(progressData.error);
                        }
                        
                        const percent = Math.round((progressData.progress / progressData.total) * 100);
                        progressBar.style.width = percent + '%';
                        progressBar.textContent = percent + '%';
                        progressText.textContent = progressData.current_step || 'Processing...';
                        
                        if (progressData.status === 'complete') {
                            clearInterval(progressInterval);
                            
                            // Show success message with download button
                            storyContent.innerHTML = `
                                <div class="success-msg">
                                    ✨ Your personalized storybook PDF has been generated successfully!
                                </div>
                                <div class="download-container">
                                    <button class="download-btn" onclick="downloadPDF('${taskId}')">
                                        📥 Download Storybook PDF
                                    </button>
                                </div>
                            `;
                            resultContainer.style.display = 'block';
                            resultContainer.scrollIntoView({ behavior: 'smooth' });
                            
                            loading.style.display = 'none';
                            submitBtn.disabled = false;
                        } else if (progressData.status === 'error') {
                            clearInterval(progressInterval);
                            throw new Error(progressData.error || 'Generation failed');
                        }
                    } catch (error) {
                        clearInterval(progressInterval);
                        throw error;
                    }
                }, 2000); // Poll every 2 seconds
                
            } catch (error) {
                if (progressInterval) {
                    clearInterval(progressInterval);
                }
                storyContent.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                resultContainer.style.display = 'block';
                loading.style.display = 'none';
                submitBtn.disabled = false;
            }
        });
        
        function downloadPDF(taskId) {
            // Trigger download
            window.location.href = `/download/${taskId}`;
        }
    </script>
</body>
</html>
'''

def truncate_prompt_for_dalle(prompt_text, max_length=4000):
    """
    Truncate prompt to fit DALL-E 3's maximum length requirement (4000 characters).
    Prioritizes keeping the main prompt and essential instructions.
    
    Args:
        prompt_text: The full prompt text
        max_length: Maximum allowed length (default 4000 for DALL-E 3)
    
    Returns:
        Truncated prompt that fits within the limit
    """
    if len(prompt_text) <= max_length:
        return prompt_text
    
    print(f"WARNING: Prompt is {len(prompt_text)} characters, truncating to {max_length}")
    
    # Try to intelligently truncate by shortening descriptions while keeping structure
    # Split by sections and prioritize
    lines = prompt_text.split('\n')
    
    # Keep the base prompt (first part before CRITICAL REQUIREMENTS or separator)
    if 'CRITICAL CONSISTENCY REQUIREMENTS' in prompt_text or 'CRITICAL REQUIREMENTS:' in prompt_text:
        # Find the separator
        separator = 'CRITICAL CONSISTENCY REQUIREMENTS' if 'CRITICAL CONSISTENCY REQUIREMENTS' in prompt_text else 'CRITICAL REQUIREMENTS:'
        parts = prompt_text.split(separator, 1)
        base_prompt = parts[0]
        requirements = separator + parts[1] if len(parts) > 1 else ""
        
        # If base prompt alone is too long, truncate it
        reserved_for_requirements = 800  # Reserve space for comprehensive requirements
        if len(base_prompt) > max_length - reserved_for_requirements:
            base_prompt = base_prompt[:max_length - reserved_for_requirements].rsplit('.', 1)[0] + '.'
        
        # Truncate requirements section if needed, but keep essential parts
        remaining = max_length - len(base_prompt)
        if len(requirements) > remaining:
            # Try to keep the most important parts: character rules and style rules
            if 'CORE CHARACTER CONSISTENCY RULES' in requirements:
                # Keep character rules, truncate less critical parts
                char_section = requirements.split('STYLE RULES')[0] if 'STYLE RULES' in requirements else requirements[:remaining//2]
                style_section = requirements.split('STYLE RULES')[1] if 'STYLE RULES' in requirements else ""
                if style_section:
                    style_section = style_section.split('OBJECT CONSISTENCY')[0] if 'OBJECT CONSISTENCY' in style_section else style_section[:remaining//2]
                requirements = (char_section + "\n" + style_section)[:remaining]
            else:
                requirements = requirements[:remaining].rsplit('.', 1)[0] + '.'
        
        truncated = base_prompt + requirements
    else:
        # No structure found, just truncate from end
        truncated = prompt_text[:max_length].rsplit('.', 1)[0] + '.'
    
    print(f"Truncated prompt to {len(truncated)} characters")
    return truncated

def generate_image_with_dalle(prompt_text, reference_image_path=None):
    """
    Generate an image using OpenAI's DALL-E API.
    
    Args:
        prompt_text: The text prompt for image generation
        reference_image_path: Optional path to reference image (child's photo)
    
    Returns:
        URL or base64 data of generated image
    """
    try:
        # Truncate prompt if it exceeds DALL-E 3's 4000 character limit
        prompt_text = truncate_prompt_for_dalle(prompt_text, max_length=4000)
        
        # Use DALL-E 3 to generate image
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt_text,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        image_url = response.data[0].url
        return image_url
    except Exception as e:
        print(f"Error generating image: {str(e)}")
        raise

def download_image_from_url(url):
    """
    Download an image from a URL and return as PIL Image.
    
    Args:
        url: URL of the image
    
    Returns:
        PIL Image object
    """
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content))
        return img
    except Exception as e:
        print(f"Error downloading image: {str(e)}")
        raise

def create_storybook_pdf(image_paths, text_data_list, output_path, story_title, character_name):
    """
    Create a PDF storybook with traditional layout: image on top, text at bottom.
    
    Args:
        image_paths: List of image file paths in order
        text_data_list: List of text data dictionaries (narrative) for each page
        output_path: Path to save the PDF
        story_title: Title of the story
        character_name: Name of the main character for the cover title
    """
    # Page size: 8.5 inches x 8.5 inches
    page_width = 8.5 * inch
    page_height = 8.5 * inch
    
    # Storybook layout: text on top, image below
    text_area_height = 1.5 * inch  # Text area at top
    image_height = 7 * inch  # Image area below text
    
    print(f"Creating PDF canvas at: {output_path}")
    c = canvas.Canvas(output_path, pagesize=(page_width, page_height))
    
    print(f"Processing {len(image_paths)} images for PDF...")
    for i, img_path in enumerate(image_paths):
        if i > 0:
            c.showPage()  # New page for each image after the first
        
        try:
            # Verify image file exists
            if not os.path.exists(img_path):
                print(f"WARNING: Image file not found: {img_path}")
                raise FileNotFoundError(f"Image file not found: {img_path}")
            
            print(f"Processing image {i+1}/{len(image_paths)}: {img_path}")
            
            # Yield control to eventlet periodically to prevent blocking
            eventlet.sleep(0)
            
            # Get text for this page first
            narrative_text = ""
            if i < len(text_data_list) and text_data_list[i]:
                text_data = text_data_list[i]
                narrative_list = text_data.get('narrative', [])
                
                # Filter out empty strings
                if narrative_list:
                    narrative_list = [n for n in narrative_list[:3] if n and n.strip()]  # Max 3 sentences
                
                # If no narrative, create a fallback
                if not narrative_list:
                    if i == 0:
                        narrative_list = ["Once upon a time..."]
                    else:
                        narrative_list = ["And so the story continued..."]
                
                # Join narrative into text
                narrative_text = " ".join(narrative_list)
            
            # Draw image first (full page)
            # Note: drawImage can be slow with large images, but we yield after
            c.drawImage(img_path, 0, 0, width=page_width, height=page_height, preserveAspectRatio=False)
            
            # Yield after drawing image (this is a potentially slow operation)
            # This allows eventlet to handle other requests during PDF creation
            eventlet.sleep(0.01)  # Small delay to ensure eventlet can process other requests
            
            # For cover page (i=0), draw title with character name
            if i == 0:
                # Create title text: "Story Title featuring Character Name"
                title_text = f"{story_title} featuring {character_name}"
                
                # Use a large, bold font for the title
                c.setFont("Helvetica-Bold", 28)
                
                # Calculate title dimensions
                title_width = c.stringWidth(title_text, "Helvetica-Bold", 28)
                title_height = 35
                title_y = page_height - 1.2 * inch
                
                # Draw semi-transparent background for title
                title_bg_height = title_height + 0.4 * inch
                c.setFillColorRGB(1, 1, 1, alpha=0.9)  # More opaque for title readability
                c.rect(0, page_height - title_bg_height, page_width, title_bg_height, fill=1, stroke=0)
                
                # Draw title text centered
                c.setFillColorRGB(0.1, 0.1, 0.1)  # Dark text color
                c.setFont("Helvetica-Bold", 28)
                title_x = (page_width - title_width) / 2
                c.drawString(title_x, title_y, title_text)
            
            # Draw storybook-style text on top of image (at the top of the page) for story pages
            elif narrative_text and narrative_text.strip():
                # Set up text area with margins
                margin = 0.5 * inch
                max_width = page_width - 2 * margin
                
                # Use a child-friendly font size
                c.setFont("Helvetica", 16)
                
                # Word wrap the text
                words = narrative_text.split()
                lines = []
                current_line = ""
                
                for word in words:
                    test_line = current_line + (" " if current_line else "") + word
                    if c.stringWidth(test_line, "Helvetica", 16) < max_width:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word
                if current_line:
                    lines.append(current_line)
                
                # Calculate text area dimensions
                line_height = 22
                text_box_height = len(lines) * line_height + 0.4 * inch
                text_y_start = page_height - 0.3 * inch
                
                # Draw semi-transparent white background for text area (on top of image)
                c.setFillColorRGB(1, 1, 1, alpha=0.85)  # Semi-transparent white background
                c.rect(0, page_height - text_box_height, page_width, text_box_height, fill=1, stroke=0)
                
                # Draw the text on top
                c.setFillColorRGB(0.1, 0.1, 0.1)  # Dark text color
                c.setFont("Helvetica", 16)
                
                for j, line in enumerate(lines[:4]):  # Max 4 lines
                    if line and line.strip():
                        # Center text horizontally
                        line_width = c.stringWidth(line, "Helvetica", 16)
                        text_x = (page_width - line_width) / 2
                        text_y = text_y_start - (j * line_height)
                        c.drawString(text_x, text_y, line)
            
            # Yield after processing each page to allow eventlet to handle requests
            eventlet.sleep(0.01)
            
        except Exception as e:
            print(f"ERROR adding image {i+1} to PDF: {str(e)}")
            import traceback
            traceback.print_exc()
            # Add a placeholder if image fails
            c.setFont("Helvetica", 20)
            c.drawString(50, page_height / 2, f"Image {i+1} could not be loaded")
    
    print(f"Saving PDF to: {output_path}")
    # Yield before final save operation
    eventlet.sleep(0)
    c.save()
    # Yield after save to ensure it completes
    eventlet.sleep(0)
    print(f"✓ PDF saved successfully")

# ============================================================================
# AUTHENTICATION UTILITIES
# ============================================================================

def validate_password(password):
    """
    Validate password requirements.
    
    Requirements:
    - Minimum 8 characters
    - At least 1 number
    
    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    if not password:
        return False, "Password is required"
    
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    
    return True, ""

def validate_email(email):
    """
    Validate email format.
    
    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    if not email:
        return False, "Email is required"
    
    # Basic email validation regex
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    return True, ""

def validate_child_name(name):
    """
    Validate child name according to requirements.
    
    Rules:
    1. Length: Must be 2-20 characters
    2. Characters: Letters only (no numbers, spaces, or special characters)
    3. Profanity: Must not contain profane words
    4. Nonsense: Must not be in the list of nonsense words
    
    Args:
        name: The child's name to validate
    
    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    if not name:
        return False, "Name is required"
    
    # Strip whitespace
    name = name.strip()
    
    # Rule 1: Length check (2-20 characters)
    if len(name) < 2:
        return False, "Name must be at least 2 characters long"
    
    if len(name) > 20:
        return False, "Name must be no more than 20 characters long"
    
    # Rule 2: Letters only (regex check)
    # Allow only letters (a-z, A-Z) - no numbers, spaces, or special characters
    if not re.match(r'^[a-zA-Z]+$', name):
        return False, "Name must contain only letters (no numbers, spaces, or special characters)"
    
    # Rule 3: Profanity check
    if PROFANITY_AVAILABLE:
        if profanity.contains_profanity(name):
            return False, "Name contains inappropriate language"
    else:
        # Fallback: Basic profanity check if library not available
        # This is a simple fallback - the library is preferred
        common_profanity = ['damn', 'hell', 'crap']  # Very basic fallback
        if name.lower() in common_profanity:
            return False, "Name contains inappropriate language"
    
    # Rule 4: Nonsense word check
    # Hardcoded list of common nonsense words to reject
    nonsense_words = [
        "Pizza", "Moo", "Keyboard", "Computer", "Mouse", "Screen",
        "Table", "Chair", "Door", "Window", "Car", "Bus", "Train",
        "Phone", "Book", "Pen", "Paper", "Desk", "Lamp", "Clock",
        "Test", "Example", "Sample", "Demo", "Admin", "User",
        "Password", "Login", "Email", "Website", "Internet"
    ]
    
    # Check if name matches any nonsense word (case-insensitive)
    if name.capitalize() in [word.capitalize() for word in nonsense_words]:
        return False, f"'{name}' is not a valid name. Please use a real name."
    
    # All checks passed
    return True, ""

# ============================================================================
# RATE LIMITING DECORATOR (Skeleton)
# ============================================================================

def rate_limit(max_requests=5, window_seconds=60):
    """
    Rate limiting decorator skeleton.
    
    This is a basic structure for rate limiting. In production, you would:
    1. Use a proper rate limiting library like Flask-Limiter
    2. Store request counts in Redis or a similar cache
    3. Implement IP-based or user-based rate limiting
    4. Add proper error handling and logging
    
    Args:
        max_requests: Maximum number of requests allowed
        window_seconds: Time window in seconds
    
    Usage:
        @app.route('/some-route')
        @rate_limit(max_requests=10, window_seconds=60)
        def some_route():
            ...
    """
    def decorator(f):
        def wrapper(*args, **kwargs):
            # TODO: Implement rate limiting logic here
            # Example structure:
            # - Get client IP: request.remote_addr
            # - Check request count for this IP in time window
            # - If exceeded, return 429 Too Many Requests
            # - Otherwise, allow request and increment counter
            
            # Placeholder: Always allow for now
            # In production, replace with actual rate limiting logic
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route('/register', methods=['GET', 'POST'])
@rate_limit(max_requests=5, window_seconds=300)  # 5 registrations per 5 minutes
def register():
    """User registration route."""
    if request.method == 'GET':
        # Return registration form HTML
        register_html = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Register - Fairy Tale Generator</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }
                .container {
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    max-width: 400px;
                    width: 100%;
                }
                h1 { color: #333; margin-bottom: 20px; text-align: center; }
                .form-group { margin-bottom: 20px; }
                label { display: block; margin-bottom: 5px; color: #333; font-weight: 600; }
                input {
                    width: 100%;
                    padding: 12px;
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    font-size: 1em;
                    transition: border-color 0.3s;
                }
                input:focus { outline: none; border-color: #667eea; }
                button {
                    width: 100%;
                    padding: 12px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 1.1em;
                    cursor: pointer;
                    transition: transform 0.2s;
                }
                button:hover { transform: scale(1.02); }
                .error { color: #e74c3c; margin-top: 10px; font-size: 0.9em; }
                .success { color: #27ae60; margin-top: 10px; font-size: 0.9em; }
                .link { text-align: center; margin-top: 20px; }
                .link a { color: #667eea; text-decoration: none; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Create Account</h1>
                <form method="POST">
                    <div class="form-group">
                        <label for="name">Name</label>
                        <input type="text" id="name" name="name" required>
                    </div>
                    <div class="form-group">
                        <label for="email">Email</label>
                        <input type="email" id="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" name="password" required>
                        <small style="color: #666; font-size: 0.85em;">Min 8 characters, at least 1 number</small>
                    </div>
                    <button type="submit">Register</button>
                    <div class="link">
                        <a href="/login">Already have an account? Login</a>
                    </div>
                </form>
            </div>
        </body>
        </html>
        '''
        return render_template_string(register_html)
    
    # Handle POST request
    try:
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        # Validate inputs
        email_valid, email_error = validate_email(email)
        if not email_valid:
            app_logger.warning(f"Registration attempt failed: Invalid email format (email: {email})")
            return jsonify({'success': False, 'error': email_error}), 400
        
        password_valid, password_error = validate_password(password)
        if not password_valid:
            app_logger.warning(f"Registration attempt failed: Invalid password (email: {email}, error: {password_error})")
            return jsonify({'success': False, 'error': password_error}), 400
        
        if not name:
            app_logger.warning(f"Registration attempt failed: Missing name (email: {email})")
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            app_logger.warning(
                f"Registration attempt failed: Email already registered (email: {email}, existing_user_id: {existing_user.user_id})",
                extra={'user_id': existing_user.user_id}
            )
            return jsonify({'success': False, 'error': 'Email already registered'}), 400
        
        # Create new user
        user_id = str(uuid.uuid4())
        password_hash = generate_password_hash(password)
        
        new_user = User(
            user_id=user_id,
            email=email,
            name=name,
            password_hash=password_hash,
            oauth_provider='email'
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        # Log successful registration
        app_logger.info(
            f"User registration successful (user_id: {user_id}, email: {email}, oauth_provider: email)",
            extra={'user_id': user_id}
        )
        
        # Log the user in automatically after registration
        login_user(new_user)
        
        # Log automatic login after registration
        app_logger.info(
            f"User login successful (user_id: {user_id}, email: {email}, oauth_provider: email) - Auto-login after registration",
            extra={'user_id': user_id}
        )
        
        return jsonify({
            'success': True,
            'message': 'Registration successful',
            'user': new_user.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Registration error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Registration failed. Please try again.'}), 500

@app.route('/login', methods=['GET', 'POST'])
@rate_limit(max_requests=10, window_seconds=300)  # 10 login attempts per 5 minutes
def login():
    """User login route."""
    if request.method == 'GET':
        # Return login form HTML
        login_html = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Login - Fairy Tale Generator</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }
                .container {
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    max-width: 400px;
                    width: 100%;
                }
                h1 { color: #333; margin-bottom: 20px; text-align: center; }
                .form-group { margin-bottom: 20px; }
                label { display: block; margin-bottom: 5px; color: #333; font-weight: 600; }
                input {
                    width: 100%;
                    padding: 12px;
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    font-size: 1em;
                    transition: border-color 0.3s;
                }
                input:focus { outline: none; border-color: #667eea; }
                button {
                    width: 100%;
                    padding: 12px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 1.1em;
                    cursor: pointer;
                    transition: transform 0.2s;
                }
                button:hover { transform: scale(1.02); }
                .error { color: #e74c3c; margin-top: 10px; font-size: 0.9em; }
                .link { text-align: center; margin-top: 20px; }
                .link a { color: #667eea; text-decoration: none; }
                .divider {
                    display: flex;
                    align-items: center;
                    text-align: center;
                    margin: 20px 0;
                    color: #666;
                }
                .divider::before,
                .divider::after {
                    content: '';
                    flex: 1;
                    border-bottom: 1px solid #e1e5e9;
                }
                .divider span {
                    padding: 0 10px;
                }
                .google-btn {
                    width: 100%;
                    padding: 12px;
                    background: white;
                    color: #333;
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    font-size: 1em;
                    cursor: pointer;
                    transition: all 0.2s;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                }
                .google-btn:hover {
                    border-color: #4285f4;
                    background: #f8f9fa;
                }
                .google-icon {
                    width: 20px;
                    height: 20px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Login</h1>
                ''' + (f'''
                <a href="/login/google" style="text-decoration: none;">
                    <button type="button" class="google-btn">
                        <svg class="google-icon" viewBox="0 0 24 24">
                            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                        </svg>
                        Sign in with Google
                    </button>
                </a>
                <div class="divider">
                    <span>OR</span>
                </div>
                ''' if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET else '') + '''
                <form method="POST">
                    <div class="form-group">
                        <label for="email">Email</label>
                        <input type="email" id="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" name="password" required>
                    </div>
                    <button type="submit">Login</button>
                    <div class="link">
                        <a href="/register">Don't have an account? Register</a>
                    </div>
                </form>
            </div>
        </body>
        </html>
        '''
        return render_template_string(login_html)
    
    # Handle POST request
    try:
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            app_logger.warning(f"Login attempt failed: Missing email or password (email: {email})")
            return jsonify({'success': False, 'error': 'Email and password are required'}), 400
        
        # Find user by email
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Don't reveal if email exists or not (security best practice)
            app_logger.warning(f"Login attempt failed: User not found (email: {email})")
            return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
        
        # Check if user has a password (OAuth users might not)
        if not user.password_hash:
            app_logger.warning(
                f"Login attempt failed: User has no password (user_id: {user.user_id}, email: {email}, oauth_provider: {user.oauth_provider})",
                extra={'user_id': user.user_id}
            )
            return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
        
        # Verify password
        if not check_password_hash(user.password_hash, password):
            app_logger.warning(
                f"Login attempt failed: Invalid password (user_id: {user.user_id}, email: {email})",
                extra={'user_id': user.user_id}
            )
            return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
        
        # Login successful - create session
        login_user(user)
        
        # Log successful login
        oauth_provider = user.oauth_provider or 'email'
        app_logger.info(
            f"User login successful (user_id: {user.user_id}, email: {email}, oauth_provider: {oauth_provider})",
            extra={'user_id': user.user_id}
        )
        
        return jsonify({
            'success': True,
            'message': 'Login successful',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        app_logger.error(f"Login error: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Login failed. Please try again.'}), 500

@app.route('/logout', methods=['POST', 'GET'])
@login_required
def logout():
    """User logout route."""
    try:
        logout_user()
        return jsonify({'success': True, 'message': 'Logged out successfully'}), 200
    except Exception as e:
        print(f"Logout error: {str(e)}")
        return jsonify({'success': False, 'error': 'Logout failed'}), 500

# ============================================================================
# OAUTH ROUTES
# ============================================================================

@app.route('/login/google')
@rate_limit(max_requests=10, window_seconds=300)  # 10 OAuth attempts per 5 minutes
def login_google():
    """
    Initiate Google OAuth login flow.
    Redirects user to Google's authorization page.
    """
    if not google or not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({
            'success': False,
            'error': 'Google OAuth is not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.'
        }), 500
    
    try:
        # Generate redirect URI for callback
        redirect_uri = url_for('oauth_google_callback', _external=True)
        
        # Redirect to Google OAuth authorization page
        return google.authorize_redirect(redirect_uri)
    except Exception as e:
        print(f"Google OAuth initiation error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to initiate Google OAuth. Please try again.'
        }), 500

@app.route('/oauth/google/callback')
def oauth_google_callback():
    """
    Handle Google OAuth callback.
    This route processes the OAuth response and:
    1. Retrieves user information from Google
    2. Checks if user exists by email
    3. If exists, links OAuth ID to existing account
    4. If not, creates new user account
    5. Logs the user in
    """
    if not google:
        return jsonify({
            'success': False,
            'error': 'Google OAuth is not configured.'
        }), 500
    
    try:
        # Get authorization token from Google
        token = google.authorize_access_token()
        
        # Fetch user information from Google
        resp = google.get('https://www.googleapis.com/oauth2/v2/userinfo')
        resp.raise_for_status()
        user_info = resp.json()
        
        # Extract user information
        google_id = user_info.get('id')
        email = user_info.get('email', '').lower()
        name = user_info.get('name', '')
        picture = user_info.get('picture', '')
        
        if not email:
            app_logger.warning(f"Google OAuth callback failed: Unable to retrieve email from Google account")
            return jsonify({
                'success': False,
                'error': 'Unable to retrieve email from Google account. Please ensure your Google account has an email address.'
            }), 400
        
        if not google_id:
            app_logger.warning(f"Google OAuth callback failed: Unable to retrieve user ID from Google (email: {email})")
            return jsonify({
                'success': False,
                'error': 'Unable to retrieve user ID from Google. Please try again.'
            }), 400
        
        # Check if user with this Google OAuth ID already exists
        existing_user_by_oauth = User.query.filter_by(
            oauth_provider='google',
            oauth_id=google_id
        ).first()
        
        if existing_user_by_oauth:
            # User already exists with this Google account - log them in
            login_user(existing_user_by_oauth)
            
            # Log successful OAuth login
            app_logger.info(
                f"User login successful (user_id: {existing_user_by_oauth.user_id}, email: {email}, oauth_provider: google)",
                extra={'user_id': existing_user_by_oauth.user_id}
            )
            
            return redirect(url_for('index'))
        
        # Check if user with this email already exists (account linking)
        existing_user_by_email = User.query.filter_by(email=email).first()
        
        if existing_user_by_email:
            # User exists with this email - link Google OAuth to existing account
            existing_user_by_email.oauth_provider = 'google'
            existing_user_by_email.oauth_id = google_id
            
            # Update name if not set or if Google name is available
            if not existing_user_by_email.name and name:
                existing_user_by_email.name = name
            
            db.session.commit()
            
            # Log the user in
            login_user(existing_user_by_email)
            
            # Log successful OAuth login with account linking
            app_logger.info(
                f"User login successful (user_id: {existing_user_by_email.user_id}, email: {email}, oauth_provider: google) - Account linked",
                extra={'user_id': existing_user_by_email.user_id}
            )
            
            return redirect(url_for('index'))
        
        # User doesn't exist - create new account
        user_id = str(uuid.uuid4())
        
        new_user = User(
            user_id=user_id,
            email=email,
            name=name if name else email.split('@')[0],  # Use email prefix if no name
            oauth_provider='google',
            oauth_id=google_id,
            password_hash=None  # OAuth users don't have passwords
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        # Log successful registration via OAuth
        app_logger.info(
            f"User registration successful (user_id: {user_id}, email: {email}, oauth_provider: google)",
            extra={'user_id': user_id}
        )
        
        # Log the user in
        login_user(new_user)
        
        # Log successful OAuth login
        app_logger.info(
            f"User login successful (user_id: {user_id}, email: {email}, oauth_provider: google) - Auto-login after OAuth registration",
            extra={'user_id': user_id}
        )
        
        return redirect(url_for('index'))
        
    except Exception as e:
        db.session.rollback()
        app_logger.error(f"Google OAuth callback error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'OAuth authentication failed. Please try again.'
        }), 500

# ============================================================================
# CHILD NAME VALIDATION TEST ROUTE
# ============================================================================

@app.route('/test_name_validation', methods=['GET', 'POST'])
def test_name_validation():
    """
    Test route to demonstrate child name validation.
    Accepts GET requests to show the form, and POST requests to test names.
    """
    if request.method == 'GET':
        # Return test form HTML
        test_html = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Child Name Validation Test</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }
                .container {
                    max-width: 800px;
                    margin: 0 auto;
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                }
                h1 {
                    color: #333;
                    margin-bottom: 30px;
                    text-align: center;
                }
                .form-group {
                    margin-bottom: 20px;
                }
                label {
                    display: block;
                    margin-bottom: 8px;
                    color: #333;
                    font-weight: 600;
                }
                input {
                    width: 100%;
                    padding: 12px;
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    font-size: 1em;
                    transition: border-color 0.3s;
                }
                input:focus {
                    outline: none;
                    border-color: #667eea;
                }
                button {
                    width: 100%;
                    padding: 12px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 1.1em;
                    cursor: pointer;
                    transition: transform 0.2s;
                    margin-top: 10px;
                }
                button:hover {
                    transform: scale(1.02);
                }
                .result {
                    margin-top: 30px;
                    padding: 20px;
                    border-radius: 8px;
                    font-weight: 600;
                }
                .result.success {
                    background: #d4edda;
                    color: #155724;
                    border: 2px solid #c3e6cb;
                }
                .result.error {
                    background: #f8d7da;
                    color: #721c24;
                    border: 2px solid #f5c6cb;
                }
                .test-cases {
                    margin-top: 30px;
                    padding: 20px;
                    background: #f8f9fa;
                    border-radius: 8px;
                }
                .test-cases h2 {
                    color: #333;
                    margin-bottom: 15px;
                    font-size: 1.3em;
                }
                .test-case {
                    padding: 10px;
                    margin: 5px 0;
                    background: white;
                    border-radius: 5px;
                    cursor: pointer;
                    transition: background 0.2s;
                }
                .test-case:hover {
                    background: #e8f0ff;
                }
                .back-link {
                    display: inline-block;
                    margin-top: 20px;
                    color: #667eea;
                    text-decoration: none;
                }
                .back-link:hover {
                    text-decoration: underline;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🧪 Child Name Validation Test</h1>
                <p style="color: #666; margin-bottom: 20px; text-align: center;">
                    Test the child name validation function with various inputs
                </p>
                
                <form method="POST">
                    <div class="form-group">
                        <label for="name">Enter a name to test:</label>
                        <input type="text" id="name" name="name" placeholder="e.g., Alice, Pizza, Test123" required>
                    </div>
                    <button type="submit">Validate Name</button>
                </form>
                
                ''' + (f'''
                <div class="result {'success' if request.args.get('valid') == 'true' else 'error' if request.args.get('valid') == 'false' else ''}">
                    {request.args.get('message', '')}
                </div>
                ''' if request.args.get('message') else '') + '''
                
                <div class="test-cases">
                    <h2>Quick Test Cases (Click to test):</h2>
                    <div class="test-case" onclick="testName('Alice')">✅ Valid: "Alice"</div>
                    <div class="test-case" onclick="testName('Bob')">✅ Valid: "Bob"</div>
                    <div class="test-case" onclick="testName('A')">❌ Too Short: "A" (1 character)</div>
                    <div class="test-case" onclick="testName('ThisNameIsWayTooLongForValidation')">❌ Too Long: "ThisNameIsWayTooLongForValidation"</div>
                    <div class="test-case" onclick="testName('Test123')">❌ Contains Numbers: "Test123"</div>
                    <div class="test-case" onclick="testName('John Doe')">❌ Contains Space: "John Doe"</div>
                    <div class="test-case" onclick="testName('Pizza')">❌ Nonsense Word: "Pizza"</div>
                    <div class="test-case" onclick="testName('Keyboard')">❌ Nonsense Word: "Keyboard"</div>
                    <div class="test-case" onclick="testName('Moo')">❌ Nonsense Word: "Moo"</div>
                </div>
                
                <a href="/" class="back-link">← Back to Home</a>
            </div>
            
            <script>
                function testName(name) {
                    document.getElementById('name').value = name;
                    document.querySelector('form').submit();
                }
            </script>
        </body>
        </html>
        '''
        return render_template_string(test_html)
    
    # Handle POST request
    try:
        name = request.form.get('name', '').strip()
        
        if not name:
            return redirect(url_for('test_name_validation', valid='false', message='No name provided'))
        
        # Validate the name
        is_valid, error_message = validate_child_name(name)
        
        if is_valid:
            message = f'✅ "{name}" is a valid child name!'
            return redirect(url_for('test_name_validation', valid='true', message=message))
        else:
            message = f'❌ "{name}" is invalid: {error_message}'
            return redirect(url_for('test_name_validation', valid='false', message=message))
        
    except Exception as e:
        app_logger.error(f"Name validation test error: {str(e)}", exc_info=True)
        return redirect(url_for('test_name_validation', valid='false', message=f'Error: {str(e)}'))

# ============================================================================
# MULTI-THREADED GENERATION TEST ROUTE
# ============================================================================

@app.route('/test_parallel_generation', methods=['GET', 'POST'])
def test_parallel_generation():
    """
    Test route to demonstrate parallel image generation.
    Shows that 12 tasks can be launched and completed concurrently.
    """
    if request.method == 'GET':
        # Return test form HTML
        test_html = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Parallel Generation Test</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }
                .container {
                    max-width: 900px;
                    margin: 0 auto;
                    background: white;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                }
                h1 { color: #333; margin-bottom: 20px; text-align: center; }
                .form-group { margin-bottom: 20px; }
                label { display: block; margin-bottom: 8px; color: #333; font-weight: 600; }
                select, input {
                    width: 100%;
                    padding: 12px;
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    font-size: 1em;
                }
                button {
                    width: 100%;
                    padding: 12px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 1.1em;
                    cursor: pointer;
                    margin-top: 10px;
                }
                .result {
                    margin-top: 30px;
                    padding: 20px;
                    border-radius: 8px;
                    background: #f8f9fa;
                }
                .result h2 { color: #333; margin-bottom: 15px; }
                .result-item {
                    padding: 10px;
                    margin: 5px 0;
                    background: white;
                    border-radius: 5px;
                    border-left: 4px solid #667eea;
                }
                .result-item.success { border-left-color: #27ae60; }
                .result-item.error { border-left-color: #e74c3c; }
                .summary {
                    margin-top: 20px;
                    padding: 15px;
                    background: #e8f0ff;
                    border-radius: 8px;
                    font-weight: 600;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🧵 Parallel Image Generation Test</h1>
                <p style="color: #666; margin-bottom: 20px; text-align: center;">
                    Test multi-threaded image generation with ThreadPoolExecutor
                </p>
                
                <form method="POST">
                    <div class="form-group">
                        <label for="storyline_id">Select Storyline:</label>
                        <select id="storyline_id" name="storyline_id" required>
                            <option value="">Choose a storyline...</option>
                            <option value="red">Little Red Riding Hood (girl)</option>
                            <option value="jack">Jack and the Beanstalk (boy)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="user_image_path">User Image Path (mock):</label>
                        <input type="text" id="user_image_path" name="user_image_path" 
                               placeholder="/path/to/image.jpg" 
                               value="uploads/mock_image.jpg" required>
                        <small style="color: #999;">This is a mock path for testing</small>
                    </div>
                    <button type="submit">Start Parallel Generation</button>
                </form>
                
                ''' + (f'''
                <div class="result">
                    <h2>Generation Results</h2>
                    <div class="summary">
                        Total Pages: {request.args.get('total', 'N/A')} | 
                        Completed: {request.args.get('completed', 'N/A')} | 
                        Failed: {request.args.get('failed', 'N/A')}
                    </div>
                    <pre style="background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto;">{request.args.get('details', '')}</pre>
                </div>
                ''' if request.args.get('total') else '') + '''
                
                <a href="/" style="display: inline-block; margin-top: 20px; color: #667eea; text-decoration: none;">← Back to Home</a>
            </div>
        </body>
        </html>
        '''
        return render_template_string(test_html)
    
    # Handle POST request
    try:
        storyline_id = request.form.get('storyline_id', '').strip()
        user_image_path = request.form.get('user_image_path', '').strip()
        
        if not storyline_id:
            return redirect(url_for('test_parallel_generation', error='Storyline ID is required'))
        
        if not user_image_path:
            return redirect(url_for('test_parallel_generation', error='User image path is required'))
        
        # Run parallel generation
        import json
        result = start_book_generation(storyline_id, user_image_path)
        
        # Format results for display
        details = []
        details.append(f"Success: {result['success']}")
        details.append(f"Total Pages: {result['total_pages']}")
        details.append(f"Completed: {result['completed_pages']}")
        details.append(f"Failed: {result['failed_pages']}")
        details.append(f"\nOutput Directory: {result.get('output_dir', 'N/A')}")
        details.append(f"\nPage Results:")
        
        for page_result in result['results']:
            status = "✓" if page_result['success'] else "✗"
            details.append(f"  {status} Page {page_result['page_number']}: {page_result.get('image_path', 'N/A')}")
            if not page_result['success']:
                details.append(f"    Error: {page_result.get('error', 'Unknown error')}")
        
        if result['errors']:
            details.append(f"\nErrors:")
            for error in result['errors']:
                details.append(f"  - {error}")
        
        details_str = "\n".join(details)
        
        return redirect(url_for('test_parallel_generation', 
                              total=result['total_pages'],
                              completed=result['completed_pages'],
                              failed=result['failed_pages'],
                              details=details_str))
        
    except Exception as e:
        app_logger.error(f"Parallel generation test error: {str(e)}", exc_info=True)
        return redirect(url_for('test_parallel_generation', error=f'Error: {str(e)}'))

# ============================================================================
# SERVER-SENT EVENTS (SSE) FOR REAL-TIME PROGRESS UPDATES
# ============================================================================

@app.route('/stream_progress/<book_id>')
def stream_progress(book_id):
    """
    SSE endpoint that streams real-time progress updates for book generation.
    
    This endpoint maintains a persistent connection and sends events whenever
    a page completes generation. Events include:
    - generation_started: When generation begins
    - page_complete: When a page finishes (includes page_number and image_url)
    - page_failed: When a page fails (includes page_number and error)
    - generation_complete: When all pages are done
    
    Args:
        book_id: Unique identifier for the book generation session
    
    Returns:
        Response: SSE stream with text/event-stream content type
    """
    def generate():
        # Create a queue for this book_id if it doesn't exist
        with sse_event_queues_lock:
            if book_id not in sse_event_queues:
                sse_event_queues[book_id] = queue.Queue(maxsize=100)
            event_queue = sse_event_queues[book_id]
        
        try:
            # Send initial connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'book_id': book_id})}\n\n"
            
            # Keep connection alive and listen for events
            while True:
                try:
                    # Wait for event with timeout to allow periodic keep-alive
                    try:
                        event = event_queue.get(timeout=30)
                    except queue.Empty:
                        # Send keep-alive ping
                        yield f": keep-alive\n\n"
                        continue
                    
                    # Format event as SSE message
                    event_json = json.dumps({
                        'type': event['type'],
                        'data': event['data'],
                        'timestamp': event['timestamp']
                    })
                    yield f"data: {event_json}\n\n"
                    
                    # If generation is complete, close the connection
                    if event['type'] == 'generation_complete':
                        break
                        
                except GeneratorExit:
                    # Client disconnected
                    break
                except Exception as e:
                    # Send error event
                    error_json = json.dumps({
                        'type': 'error',
                        'data': {'error': str(e)},
                        'timestamp': time.time()
                    })
                    yield f"data: {error_json}\n\n"
                    break
        
        finally:
            # Clean up: remove queue when connection closes
            with sse_event_queues_lock:
                if book_id in sse_event_queues:
                    # Drain any remaining events
                    try:
                        while True:
                            sse_event_queues[book_id].get_nowait()
                    except queue.Empty:
                        pass
                    del sse_event_queues[book_id]
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Connection': 'keep-alive'
        }
    )

@app.route('/test_sse', methods=['GET'])
def test_sse():
    """
    Test page demonstrating SSE client-side consumption.
    Shows how to connect to the SSE endpoint and update UI in real-time.
    """
    test_html = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SSE Real-Time Progress Test</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container {
                max-width: 1000px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h1 { color: #333; margin-bottom: 20px; text-align: center; }
            .status-bar {
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 20px;
            }
            .status-item {
                display: inline-block;
                margin-right: 20px;
                font-weight: 600;
            }
            .status-item .label { color: #666; }
            .status-item .value { color: #667eea; font-size: 1.2em; }
            .pages-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
                gap: 15px;
                margin-top: 20px;
            }
            .page-card {
                background: #f8f9fa;
                border: 3px solid #e1e5e9;
                border-radius: 10px;
                padding: 15px;
                text-align: center;
                transition: all 0.3s ease;
            }
            .page-card.pending {
                border-color: #e1e5e9;
                background: #f8f9fa;
            }
            .page-card.complete {
                border-color: #27ae60;
                background: #d4edda;
            }
            .page-card.failed {
                border-color: #e74c3c;
                background: #f8d7da;
            }
            .page-number {
                font-size: 1.5em;
                font-weight: 600;
                margin-bottom: 10px;
            }
            .page-status {
                font-size: 0.9em;
                color: #666;
            }
            .page-image {
                max-width: 100%;
                max-height: 120px;
                border-radius: 5px;
                margin-top: 10px;
                display: none;
            }
            .page-card.complete .page-image {
                display: block;
            }
            .controls {
                margin-top: 30px;
                text-align: center;
            }
            button {
                padding: 12px 30px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 1.1em;
                cursor: pointer;
                margin: 0 10px;
            }
            button:hover { transform: scale(1.05); }
            button:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }
            .log {
                margin-top: 20px;
                padding: 15px;
                background: #f8f9fa;
                border-radius: 8px;
                max-height: 200px;
                overflow-y: auto;
                font-family: monospace;
                font-size: 0.9em;
            }
            .log-entry {
                padding: 5px 0;
                border-bottom: 1px solid #e1e5e9;
            }
            .log-entry:last-child {
                border-bottom: none;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📡 Server-Sent Events (SSE) Test</h1>
            <p style="color: #666; margin-bottom: 20px; text-align: center;">
                Real-time progress updates for parallel image generation
            </p>
            
            <div class="status-bar">
                <div class="status-item">
                    <span class="label">Status:</span>
                    <span class="value" id="connectionStatus">Disconnected</span>
                </div>
                <div class="status-item">
                    <span class="label">Completed:</span>
                    <span class="value" id="completedCount">0</span>
                    <span class="label">/ 12</span>
                </div>
                <div class="status-item">
                    <span class="label">Failed:</span>
                    <span class="value" id="failedCount">0</span>
                </div>
            </div>
            
            <div class="pages-grid" id="pagesGrid">
                <!-- Page cards will be generated here -->
            </div>
            
            <div class="controls">
                <button id="startBtn" onclick="startGeneration()">Start Generation</button>
                <button id="connectBtn" onclick="connectSSE()" disabled>Connect to SSE</button>
                <button id="disconnectBtn" onclick="disconnectSSE()" disabled>Disconnect</button>
            </div>
            
            <div class="log" id="eventLog">
                <div class="log-entry">Ready. Click "Start Generation" to begin.</div>
            </div>
            
            <a href="/" style="display: inline-block; margin-top: 20px; color: #667eea; text-decoration: none;">← Back to Home</a>
        </div>
        
        <script>
            let eventSource = null;
            let currentBookId = null;
            let pageStatus = {};
            
            // Initialize page cards
            function initPages() {
                const grid = document.getElementById('pagesGrid');
                grid.innerHTML = '';
                for (let i = 1; i <= 12; i++) {
                    const card = document.createElement('div');
                    card.className = 'page-card pending';
                    card.id = `page-${i}`;
                    card.innerHTML = `
                        <div class="page-number">Page ${i}</div>
                        <div class="page-status">Pending</div>
                        <img class="page-image" src="" alt="Page ${i}">
                    `;
                    grid.appendChild(card);
                    pageStatus[i] = 'pending';
                }
            }
            
            function addLogEntry(message) {
                const log = document.getElementById('eventLog');
                const entry = document.createElement('div');
                entry.className = 'log-entry';
                entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
                log.insertBefore(entry, log.firstChild);
                if (log.children.length > 50) {
                    log.removeChild(log.lastChild);
                }
            }
            
            function updatePageStatus(pageNumber, status, imageUrl = null) {
                const card = document.getElementById(`page-${pageNumber}`);
                if (!card) return;
                
                card.className = `page-card ${status}`;
                const statusDiv = card.querySelector('.page-status');
                const image = card.querySelector('.page-image');
                
                if (status === 'complete') {
                    statusDiv.textContent = 'Complete ✓';
                    if (imageUrl) {
                        image.src = imageUrl;
                        image.alt = `Page ${pageNumber}`;
                    }
                } else if (status === 'failed') {
                    statusDiv.textContent = 'Failed ✗';
                } else {
                    statusDiv.textContent = 'Pending...';
                }
                
                pageStatus[pageNumber] = status;
                updateCounts();
            }
            
            function updateCounts() {
                const completed = Object.values(pageStatus).filter(s => s === 'complete').length;
                const failed = Object.values(pageStatus).filter(s => s === 'failed').length;
                
                document.getElementById('completedCount').textContent = completed;
                document.getElementById('failedCount').textContent = failed;
            }
            
            function connectSSE(bookId) {
                if (eventSource) {
                    disconnectSSE();
                }
                
                if (!bookId) {
                    bookId = currentBookId || prompt('Enter Book ID:');
                    if (!bookId) return;
                }
                
                currentBookId = bookId;
                const url = `/stream_progress/${bookId}`;
                
                addLogEntry(`Connecting to SSE endpoint: ${url}`);
                
                eventSource = new EventSource(url);
                
                eventSource.onopen = function() {
                    addLogEntry('SSE connection opened');
                    document.getElementById('connectionStatus').textContent = 'Connected';
                    document.getElementById('connectBtn').disabled = true;
                    document.getElementById('disconnectBtn').disabled = false;
                };
                
                eventSource.onmessage = function(event) {
                    try {
                        const data = JSON.parse(event.data);
                        handleSSEEvent(data);
                    } catch (e) {
                        addLogEntry(`Error parsing event: ${e.message}`);
                    }
                };
                
                eventSource.onerror = function(error) {
                    addLogEntry(`SSE error: ${error}`);
                    document.getElementById('connectionStatus').textContent = 'Error';
                };
            }
            
            function handleSSEEvent(event) {
                const { type, data } = event;
                
                switch(type) {
                    case 'connected':
                        addLogEntry(`Connected to book_id: ${data.book_id}`);
                        break;
                    
                    case 'generation_started':
                        addLogEntry(`Generation started: ${data.total_pages} pages`);
                        initPages();
                        break;
                    
                    case 'page_complete':
                        addLogEntry(`Page ${data.page_number} completed! (${data.completed_count}/${data.total_pages})`);
                        updatePageStatus(data.page_number, 'complete', data.image_url);
                        break;
                    
                    case 'page_failed':
                        addLogEntry(`Page ${data.page_number} failed: ${data.error}`);
                        updatePageStatus(data.page_number, 'failed');
                        break;
                    
                    case 'generation_complete':
                        addLogEntry(`Generation complete! Success: ${data.success}, Completed: ${data.completed_pages}, Failed: ${data.failed_pages}`);
                        document.getElementById('connectionStatus').textContent = 'Complete';
                        if (eventSource) {
                            eventSource.close();
                            eventSource = null;
                        }
                        break;
                    
                    default:
                        addLogEntry(`Unknown event type: ${type}`);
                }
            }
            
            function disconnectSSE() {
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                    addLogEntry('SSE connection closed');
                    document.getElementById('connectionStatus').textContent = 'Disconnected';
                    document.getElementById('connectBtn').disabled = false;
                    document.getElementById('disconnectBtn').disabled = true;
                }
            }
            
            async function startGeneration() {
                const bookId = prompt('Enter Book ID (or leave empty to generate one):');
                if (bookId === null) return;
                
                const finalBookId = bookId || `test-${Date.now()}`;
                currentBookId = finalBookId;
                
                addLogEntry(`Starting generation with book_id: ${finalBookId}`);
                
                // Connect to SSE first
                connectSSE(finalBookId);
                
                // In a real implementation, you would call an API endpoint to start generation
                // For this demo, we'll just show how to connect
                addLogEntry('Note: In production, call /api/start-generation with book_id to trigger generation');
                
                document.getElementById('startBtn').disabled = true;
            }
            
            // Initialize on page load
            initPages();
        </script>
    </body>
    </html>
    '''
    return render_template_string(test_html)

# ============================================================================
# GENDER-ALIGNED STORY SELECTION API
# ============================================================================

@app.route('/api/stories_by_gender/<gender>')
def api_stories_by_gender(gender):
    """
    API endpoint that returns stories filtered by gender.
    
    Args:
        gender: 'boy' or 'girl'
    
    Returns:
        JSON response with list of stories matching the specified gender
    """
    try:
        # Validate gender parameter
        if gender not in ['boy', 'girl']:
            return jsonify({
                'success': False,
                'error': 'Invalid gender. Must be "boy" or "girl"'
            }), 400
        
        # Query Storyline model for stories matching the gender
        with app.app_context():
            storylines = Storyline.query.filter_by(gender=gender).all()
            
            # Convert to list of dictionaries
            stories = []
            for storyline in storylines:
                stories.append({
                    'story_id': storyline.story_id,
                    'name': storyline.name,
                    'gender': storyline.gender
                })
            
            return jsonify({
                'success': True,
                'gender': gender,
                'stories': stories,
                'count': len(stories)
            })
    
    except Exception as e:
        app_logger.error(f"Error fetching stories by gender: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Error fetching stories: {str(e)}'
        }), 500

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

def generate_storybook_background(task_id, filepath, gender, story_choice, character_name):
    """Background function to generate storybook with progress tracking."""
    # TEST MODE: Set to True to only generate cover page for testing
    TEST_MODE_SINGLE_PAGE = False  # Change to False to generate full storybook
    
    try:
        generation_progress[task_id] = {
            'status': 'analyzing',
            'progress': 0,
            'total': 1 if TEST_MODE_SINGLE_PAGE else 13,  # Generating full storybook: 1 cover + 12 story pages (or just 1 for test mode)
            'current_step': 'Analyzing child\'s appearance...',
            'pdf_path': None,
            'error': None
        }
        
        # Analyze child's appearance
        child_appearance = analyze_child_appearance(filepath)
        generation_progress[task_id]['progress'] = 1
        generation_progress[task_id]['current_step'] = 'Child appearance analyzed'
        
        # Determine story base
        story_titles = {
            'jack': 'Jack and the Beanstalk',
            'red': 'Little Red Riding Hood'
        }
        story_title = story_titles.get(story_choice, 'Custom Story')
        
        # Get all prompts - ensure we get the FULL storybook (13 images total)
        all_prompts = get_all_prompts_for_story(story_choice, gender)
        if not all_prompts:
            generation_progress[task_id]['status'] = 'error'
            generation_progress[task_id]['error'] = 'Invalid story selection'
            return
        
        # Verify we have the expected number of prompts (13 total: 1 cover + 12 story pages)
        expected_total = 13
        if len(all_prompts) != expected_total:
            print(f"WARNING: Expected {expected_total} prompts but got {len(all_prompts)}. This may indicate a problem.")
        else:
            print(f"✓ Verified: {len(all_prompts)} prompts ready for generation (full storybook)")
        
        print(f"\n{'#'*60}")
        print(f"Starting storybook generation: {len(all_prompts)} total pages (1 cover + {len(all_prompts)-1} story pages)")
        print(f"Story: {story_title}")
        print(f"Character: {character_name}")
        print(f"{'#'*60}\n")
        
        # Track objects for consistency across pages
        story_objects = {}  # Will track objects that must remain consistent
        if story_choice == 'red':
            story_objects['basket_contents'] = ['bread', 'cakes', 'bottle of wine']
            story_objects['red_cape'] = 'bright red hooded cape'
        elif story_choice == 'jack':
            story_objects['magic_beans'] = 'colorful, glowing magic beans'
            story_objects['treasure'] = 'golden egg or bag of gold coins'
            story_objects['beanstalk'] = 'enormous, magical green beanstalk'
        
        generated_images = []
        text_data_list = []
        temp_files = []
        style_description = None  # Will store style from first image (consistent across all)
        current_face_description = None  # Will track the most recent face description from GPT-4 Vision
        
        # MASTER REFERENCE SYSTEM: Store the first generated image as the master reference
        master_reference_image_path = None
        master_reference_description = None  # Detailed character description extracted from master reference
        
        # RAG Context Store: Store consistency information from each generated image
        # Each entry contains: consistency_info (dict), embedding (list), page_description (str), page_number (int)
        context_store = []
        
        # Generate all pages for complete storybook (1 cover + 12 story pages = 13 total)
        
        print(f"\n{'*'*60}")
        print(f"STEP 1: Generating MASTER REFERENCE (cover image)")
        print(f"STEP 2: Extract master reference character details")
        print(f"STEP 3: Generate all subsequent pages using master reference")
        print(f"{'*'*60}\n")
        
        # STEP 1: Generate ONLY the cover first to establish master reference
        print(f"\n{'='*60}")
        print(f"STEP 1: GENERATING MASTER REFERENCE IMAGE (Cover)")
        print(f"{'='*60}\n")
        
        cover_prompt_info = all_prompts[0]
        generation_progress[task_id]['progress'] = 1
        generation_progress[task_id]['current_step'] = 'Generating master reference cover page...'
        
        # Build cover prompt - FIRST IMAGE: Creates the master reference illustration
        base_prompt = cover_prompt_info['prompt']
        
        # Determine story-specific outfit and items
        if story_choice == 'red':
            outfit_desc = "red hooded cape"
            items_desc = "basket"
            story_context = "Little Red Riding Hood"
        elif story_choice == 'jack':
            outfit_desc = "appropriate clothing"
            items_desc = "magic beans"
            story_context = "Jack and the Beanstalk"
        else:
            outfit_desc = "story-appropriate clothing"
            items_desc = ""
            story_context = "the story"
        
        # FIRST IMAGE PROMPT: Create master reference illustration based on uploaded photo
        cover_prompt = f"""Create a children's storybook illustration of the uploaded child as {story_context}. 

The child must look EXACTLY like the uploaded photo - same face, same age, same ethnicity, same hair, same features.

STYLE: Soft watercolor fairy-tale storybook illustration style. Gentle, magical, warm lighting.

OUTFIT AND ITEMS: {outfit_desc.title() if outfit_desc else "Story-appropriate clothing"}{f", {items_desc}" if items_desc else ""}.

This is the FIRST and MASTER REFERENCE illustration. All subsequent pages will match this exact child character, outfit, and art style."""
        
        # Generate master reference cover
        # NOTE: filepath is passed here for the FIRST image only (to match the uploaded photo)
        try:
            print(f"Generating master reference cover (FIRST illustration based on uploaded photo)...")
            image_url = generate_image_with_dalle(cover_prompt, filepath)
            img = download_image_from_url(image_url)
            master_reference_image_path = os.path.join(tempfile.gettempdir(), f"storybook_img_{task_id}_master_reference.png")
            img.save(master_reference_image_path)
            generated_images.append(master_reference_image_path)
            temp_files.append(master_reference_image_path)
            print(f"✓ Master reference image saved: {master_reference_image_path}")
        except Exception as e:
            print(f"ERROR: Failed to generate master reference: {e}")
            generation_progress[task_id]['status'] = 'error'
            generation_progress[task_id]['error'] = f'Failed to generate master reference: {str(e)}'
            return
        
        # STEP 2: Extract master reference character details
        print(f"\n{'='*60}")
        print(f"STEP 2: EXTRACTING MASTER REFERENCE CHARACTER DETAILS")
        print(f"{'='*60}\n")
        
        generation_progress[task_id]['current_step'] = 'Extracting master reference character details...'
        
        try:
            master_reference_description = extract_master_reference_character_details(master_reference_image_path)
            if master_reference_description:
                print(f"✓ Master reference description extracted: {master_reference_description[:200]}...")
            else:
                print("⚠️  Warning: Could not extract master reference details. Using fallback.")
                master_reference_description = child_appearance
        except Exception as e:
            print(f"⚠️  Warning: Error extracting master reference: {e}. Using fallback.")
            master_reference_description = child_appearance
        
        # Extract style from master reference
        try:
            style_description = analyze_illustration_style(master_reference_image_path)
            print(f"✓ Style description extracted: {style_description[:100]}...")
        except Exception as e:
            print(f"⚠️  Warning: Error analyzing style: {e}. Using default.")
            style_description = "watercolor/painterly style with soft, artistic brushstrokes, gentle color blending, and an emotional, gentle feel"
        
        # Generate text for cover
        try:
            text_data = generate_page_text(cover_prompt_info, story_choice, 1, len(all_prompts), character_name)
            text_data_list.append(text_data)
        except Exception as e:
            print(f"Warning: Error generating text for cover: {e}")
            text_data_list.append({"narrative": []})
        
        # STEP 3: Generate all subsequent pages using master reference
        print(f"\n{'='*60}")
        print(f"STEP 3: GENERATING ALL SUBSEQUENT PAGES USING MASTER REFERENCE")
        print(f"{'='*60}\n")
        
        if TEST_MODE_SINGLE_PAGE:
            print(f"\n{'!'*60}")
            print(f"TEST MODE ENABLED: Only generating cover page (skipping story pages)")
            print(f"{'!'*60}\n")
        else:
            # Track previous page image for continuity (secondary reference)
            previous_page_image_path = master_reference_image_path  # Start with master reference
            previous_page_description = None  # Will store description of previous page
            
            # Iterate through remaining prompts (skip cover, start from index 1)
            for i, prompt_info in enumerate(all_prompts[1:], start=1):
                try:
                    print(f"\n>>> LOOP ITERATION {i+1}/{len(all_prompts)} STARTING <<<")
                    page_num = prompt_info['page_number']
                    generation_progress[task_id]['progress'] = i + 1
                    
                    if i == 0:
                        generation_progress[task_id]['current_step'] = f'Generating cover page...'
                    else:
                        generation_progress[task_id]['current_step'] = f'Generating page {page_num + 1}: {prompt_info["description"]}'
                    
                    # RAG: Retrieve relevant context from previous images for consistency
                    rag_consistency_info = ""
                    if i > 0 and context_store:
                        # Use RAG to retrieve most relevant previous images
                        query_text = f"{prompt_info['description']} {prompt_info['prompt'][:200]}"
                        relevant_contexts = retrieve_relevant_context(query_text, context_store, top_k=3)
                        
                        if relevant_contexts:
                            print(f"RAG: Retrieved {len(relevant_contexts)} relevant context chunks from previous images")
                            # Build consistency instructions from retrieved contexts
                            rag_parts = []
                            for idx, ctx in enumerate(relevant_contexts):
                                if ctx.get('consistency_info'):
                                    info = ctx['consistency_info']
                                    # Extract character features (most important for consistency)
                                    if info.get('character_features'):
                                        char_features = str(info['character_features'])[:200]  # Truncate
                                        rag_parts.append(f"Character (match exactly): {char_features}")
                                    # Extract objects (basket contents, etc.)
                                    if info.get('objects'):
                                        objects = str(info['objects'])[:150]  # Truncate
                                        rag_parts.append(f"Objects (match exactly): {objects}")
                                    # Only take first 2 most relevant to keep prompt length manageable
                                    if len(rag_parts) >= 2:
                                        break
                            if rag_parts:
                                rag_consistency_info = ". ".join(rag_parts)
                                print(f"RAG consistency info retrieved ({len(rag_parts)} chunks): {rag_consistency_info[:150]}...")
                    
                    # Build enhanced prompt with appearance and object consistency
                    consistency_notes = []
                    
                    # Add object consistency notes based on story
                    if story_choice == 'red':
                        if 'basket' in prompt_info['prompt'].lower():
                            consistency_notes.append(f"The basket must contain: {', '.join(story_objects['basket_contents'])}. This is consistent across all pages.")
                        if 'red' in prompt_info['prompt'].lower() or 'cape' in prompt_info['prompt'].lower():
                            consistency_notes.append(f"The child wears a {story_objects['red_cape']} in every scene where they appear.")
                    
                    elif story_choice == 'jack':
                        if 'beanstalk' in prompt_info['prompt'].lower():
                            consistency_notes.append(f"The beanstalk is an {story_objects['beanstalk']} with giant green leaves and magical sparkles.")
                        if 'treasure' in prompt_info['prompt'].lower() or 'gold' in prompt_info['prompt'].lower():
                            consistency_notes.append(f"The treasure is a {story_objects['treasure']} - maintain this exact appearance.")
                        if 'beans' in prompt_info['prompt'].lower():
                            consistency_notes.append(f"The magic beans are {story_objects['magic_beans']} - keep them consistent.")
                    
                    # Combine RAG info with story-based consistency
                    consistency_text = " ".join(consistency_notes)
                    if rag_consistency_info:
                        consistency_text = f"{consistency_text} {rag_consistency_info}" if consistency_text else rag_consistency_info
                    
                    # Build the enhanced prompt
                    base_prompt = prompt_info['prompt']
                    if 'watercolor' not in base_prompt.lower() and 'painterly' not in base_prompt.lower():
                        base_prompt = f"Create a children's book illustration page in a watercolor/painterly style with a soft, artistic feel that is gentle and emotional. {base_prompt}"
                    
                    # For subsequent pages: Use MASTER REFERENCE description
                    # Generate comprehensive consistency rules using master reference
                    character_rules = generate_character_consistency_rules(child_appearance, story_choice, is_cover=False)
                    
                    # Add MASTER REFERENCE description (CRITICAL for consistency)
                    if master_reference_description:
                        master_ref_short = master_reference_description[:400] if len(master_reference_description) > 400 else master_reference_description
                        character_rules += f"\n\n{'='*80}\nMASTER REFERENCE CHARACTER DETAILS (MUST MATCH EXACTLY):\n{master_ref_short}\n{'='*80}"
                    
                    # Generate style rules using master reference style
                    style_rules = generate_style_consistency_rules(is_cover=False, style_description=style_description)
                    
                    # Combine all consistency information
                    # Truncate RAG consistency text if too long
                    rag_consistency_text = ""
                    if rag_consistency_info:
                        rag_consistency_text = f"\n\nRAG-RETRIEVED CONSISTENCY (from previous pages):\n{rag_consistency_info[:300]}" if len(rag_consistency_info) > 300 else f"\n\nRAG-RETRIEVED CONSISTENCY (from previous pages):\n{rag_consistency_info}"
                    
                    # Truncate story-based consistency notes if too long
                    story_consistency_text = consistency_text[:150] if consistency_text and len(consistency_text) > 150 else (consistency_text if consistency_text else "")
                    
                    # Extract previous page description for continuity (secondary reference)
                    previous_page_continuity = ""
                    if previous_page_image_path and previous_page_image_path != master_reference_image_path:
                        try:
                            previous_page_desc = analyze_child_face_from_illustration(previous_page_image_path)
                            if previous_page_desc:
                                previous_page_continuity = f"\nPREVIOUS PAGE REFERENCE: Also match the style and facial identity from the previous page. {previous_page_desc[:200]}"
                                print(f"✓ Extracted previous page description for continuity")
                        except Exception as e:
                            print(f"⚠️  Warning: Could not extract previous page description: {e}")
                    
                    # Build story-specific consistency lock text
                    if story_choice == 'red':
                        outfit_consistency_lock = "SAME red cloak, SAME basket"
                        outfit_rules = "- Same red hood and cloak every page.\n- Same basket every page."
                    elif story_choice == 'jack':
                        outfit_consistency_lock = "SAME clothing, SAME magic beans and treasure items"
                        outfit_rules = "- Same clothing style every page.\n- Same magic beans appearance every page.\n- Same treasure items (golden egg/coins) appearance every page."
                    else:
                        outfit_consistency_lock = "SAME clothing and items"
                        outfit_rules = "- Same clothing style every page.\n- Same story items every page."
                    
                    # Build the comprehensive prompt with EXACT consistency lock text from user requirements
                    enhanced_prompt = f"""{base_prompt}

================================================================================
CONSISTENCY LOCK - MANDATORY FOR ALL PAGES AFTER THE FIRST:
================================================================================

Use the FIRST illustration as the face reference. Also match the style and facial identity from the previous page. Match the reference child's face EXACTLY — identical facial features, proportions, eyes, nose, mouth, cheeks, skin tone, hair color and length, and age. Do NOT alter, stylize, or reinterpret the child's face or age. SAME hairstyle, {outfit_consistency_lock}, SAME art style, SAME brush texture, SAME lighting and color palette. If the face does not match, regenerate.

================================================================================
MASTER REFERENCE (FIRST ILLUSTRATION) CHARACTER DETAILS:
================================================================================

{master_reference_description[:400] if master_reference_description else "Match the FIRST generated illustration character exactly."}
{previous_page_continuity}

================================================================================
OUTFIT & STYLE RULES:
================================================================================

{outfit_rules}
- Soft watercolor storybook style.
- No realism, no anime, no style changes.
- SAME illustration style, SAME brush style, SAME lighting, SAME fairy-tale tone as the first image.

================================================================================
CHARACTER RULES:
================================================================================

{f"- Wolf is always a wolf (not human)." if story_choice == 'red' else ""}
- Hunter is always a human adult male (not a wolf or animal).
- No animal-human hybrids.

================================================================================
QUALITY CHECK:
================================================================================

If the child does not match the reference identity or the style changes:
- Prioritize facial identity match before style variation
- Regenerate up to 3 times if needed
- The child MUST look EXACTLY like the FIRST illustration in EVERY image.
================================================================================"""
                    
                    # Generate image with verification and regeneration logic
                    total_pages = len(all_prompts)
                    prompt_length = len(enhanced_prompt)
                    print(f"\n{'='*60}")
                    print(f"Generating image {i+1}/{total_pages}: Story page {page_num}")
                    print(f"Page description: {prompt_info['description']}")
                    print(f"Prompt length: {prompt_length} characters (max: 4000)")
                    if prompt_length > 4000:
                        print(f"⚠️  WARNING: Prompt exceeds 4000 characters! Will be truncated.")
                    print(f"{'='*60}\n")
                    
                    # Generate image (no retry logic - generate once and accept)
                    # IMPORTANT: Do NOT pass filepath for subsequent pages - only use FIRST illustration reference
                    image_url = generate_image_with_dalle(enhanced_prompt, None)
                    print(f"Image generated successfully, URL: {image_url[:50]}...")
                    
                    # Download and save
                    img = download_image_from_url(image_url)
                    temp_img_path = os.path.join(tempfile.gettempdir(), f"storybook_img_{task_id}_{i}.png")
                    img.save(temp_img_path)
                    
                    # Optional quality check (informational only - no retry)
                    if master_reference_description:
                        print(f"🔍 Quality check: Verifying face matches FIRST illustration and style consistency...")
                        matches, feedback = verify_face_matches_master_reference(temp_img_path, master_reference_description)
                        
                        if matches:
                            print(f"✓ Quality check PASSED: Face matches FIRST illustration - {feedback}")
                        else:
                            print(f"⚠️  Quality check: Face/style may not match - {feedback}")
                            print(f"   (Image accepted regardless - no regeneration)")
                    else:
                        print(f"⚠️  No master reference available for verification.")
                    
                    # Use the generated image directly (no need for separate final path)
                    final_img_path = temp_img_path
                    generated_images.append(final_img_path)
                    temp_files.append(final_img_path)
                    print(f"✓ Successfully generated and saved image {i+1}/{total_pages}: {final_img_path}")
                    
                    # Update previous page reference for next iteration (for continuity - secondary reference)
                    previous_page_image_path = final_img_path
                    
                    # RAG: Extract and store consistency information from this generated image
                    try:
                        print(f"RAG: Extracting consistency information from page {i+1}...")
                        consistency_info = extract_consistency_info_from_image(
                            final_img_path, 
                            prompt_info['description'], 
                            story_choice
                        )
                        
                        if consistency_info:
                            # Create embedding for this image's context
                            context_text = f"{prompt_info['description']} {prompt_info['prompt'][:200]}"
                            if consistency_info.get('character_features'):
                                context_text += f" {consistency_info['character_features']}"
                            if consistency_info.get('objects'):
                                context_text += f" {consistency_info['objects']}"
                            
                            embedding = create_embedding(context_text)
                            
                            # Store in context store for RAG retrieval
                            context_store.append({
                                'consistency_info': consistency_info,
                                'embedding': embedding,
                                'page_description': prompt_info['description'],
                                'page_number': i + 1,
                                'context_text': context_text
                            })
                            print(f"RAG: Stored consistency info for page {i+1} in context store (total: {len(context_store)} items)")
                        else:
                            print(f"RAG: Warning - Could not extract consistency info from page {i+1}")
                    except Exception as rag_error:
                        print(f"RAG: Warning - Error extracting/storing consistency info: {rag_error}. Continuing...")
                    
                    # For subsequent pages, we already have master reference, so no need for additional analysis
                    # The master reference is the canonical source of truth for all pages
                    # (Optional: Track latest face for logging purposes, but master reference takes precedence)
                    try:
                        generation_progress[task_id]['current_step'] = f'Page {i+1} completed and verified against master reference'
                        # Optional: Log face analysis for monitoring (but master reference is the source of truth)
                        latest_face_description = analyze_child_face_from_illustration(final_img_path)
                        if latest_face_description:
                            print(f"Face description from page {i+1}: {latest_face_description[:100]}...")
                            print(f"(Master reference description is used for all subsequent pages)")
                    except Exception as analysis_error:
                        print(f"Warning: Error in optional analysis step: {analysis_error}. Continuing...")
                        # Continue anyway - master reference is the source of truth
                    
                    # Generate text for this page
                    try:
                        text_data = generate_page_text(prompt_info, story_choice, page_num + 1, len(all_prompts), character_name)
                        text_data_list.append(text_data)
                    except Exception as text_error:
                        print(f"Warning: Error generating text for page {i+1}: {text_error}")
                        text_data_list.append({"narrative": []})
                    
                    # Continue generating all pages (no break - generating full storybook)
                    total_pages = len(all_prompts)
                    print(f"Completed image {i+1}/{total_pages}. Total images so far: {len(generated_images)}")
                    print(f"Moving to next image... (loop will continue)")
                    
                except Exception as e:
                    import traceback
                    print(f"\n{'!'*60}")
                    print(f"ERROR generating page {i+1}/{len(all_prompts)}: {str(e)}")
                    print(f"Error type: {type(e).__name__}")
                    print(f"Traceback:")
                    traceback.print_exc()
                    print(f"{'!'*60}\n")
                    # Still add empty text data and continue to next page
                    text_data_list.append({"narrative": []})
                    # Continue to next image instead of stopping
                    continue
        
        # Summary
        print(f"\n{'#'*60}")
        print(f"LOOP COMPLETED: Finished iterating through all {len(all_prompts)} prompts")
        print(f"Image generation complete!")
        print(f"Successfully generated: {len(generated_images)}/{len(all_prompts)} images")
        print(f"Text data entries: {len(text_data_list)}/{len(all_prompts)}")
        if len(generated_images) < len(all_prompts):
            print(f"WARNING: Only {len(generated_images)} images generated out of {len(all_prompts)} expected!")
        print(f"{'#'*60}\n")
        
        if not generated_images:
            generation_progress[task_id]['status'] = 'error'
            generation_progress[task_id]['error'] = 'Failed to generate any images'
            return
        
        # Create PDF
        generation_progress[task_id]['current_step'] = 'Creating PDF...'
        pdf_path = os.path.join(tempfile.gettempdir(), f"storybook_{task_id}.pdf")
        
        print(f"\n{'='*60}")
        print(f"Starting PDF creation...")
        print(f"PDF path: {pdf_path}")
        print(f"Number of images: {len(generated_images)}")
        print(f"Number of text entries: {len(text_data_list)}")
        
        # Validate all image files exist before creating PDF
        missing_images = []
        for idx, img_path in enumerate(generated_images):
            if not os.path.exists(img_path):
                missing_images.append(f"Image {idx+1}: {img_path}")
        
        if missing_images:
            error_msg = f"Missing image files: {', '.join(missing_images)}"
            print(f"ERROR: {error_msg}")
            generation_progress[task_id]['status'] = 'error'
            generation_progress[task_id]['error'] = error_msg
            return
        
        print(f"All {len(generated_images)} image files verified")
        print(f"{'='*60}\n")
        
        try:
            create_storybook_pdf(generated_images, text_data_list, pdf_path, story_title, character_name)
            
            # Verify PDF was created
            if not os.path.exists(pdf_path):
                raise Exception(f"PDF file was not created at {pdf_path}")
            
            pdf_size = os.path.getsize(pdf_path)
            print(f"✓ PDF created successfully: {pdf_path} ({pdf_size} bytes)")
            
            generation_progress[task_id]['pdf_path'] = pdf_path
            generation_progress[task_id]['status'] = 'complete'
            generation_progress[task_id]['progress'] = len(all_prompts) + 1  # All pages generated (cover + 12 story pages)
            generation_progress[task_id]['current_step'] = 'Storybook ready!'
            
            print(f"\n{'='*60}")
            print(f"PDF generation complete! Status set to 'complete'")
            print(f"{'='*60}\n")
            
        except Exception as pdf_error:
            import traceback
            print(f"\n{'!'*60}")
            print(f"ERROR creating PDF: {str(pdf_error)}")
            print(f"Error type: {type(pdf_error).__name__}")
            print(f"Traceback:")
            traceback.print_exc()
            print(f"{'!'*60}\n")
            generation_progress[task_id]['status'] = 'error'
            generation_progress[task_id]['error'] = f'Failed to create PDF: {str(pdf_error)}'
            return
        
    except Exception as e:
        print(f"Error in background generation: {str(e)}")
        generation_progress[task_id]['status'] = 'error'
        generation_progress[task_id]['error'] = str(e)

@app.route('/generate-story', methods=['POST'])
def generate_story():
    """Start storybook generation and return task ID."""
    try:
        # Get form data
        gender = request.form.get('gender')
        story_choice = request.form.get('story')
        image_file = request.files.get('image')
        
        # Get character name
        character_name = request.form.get('character_name', '').strip()
        
        # Validate inputs
        if not gender or not story_choice or not character_name:
            return jsonify({'success': False, 'error': 'Please fill in all fields'}), 400
        
        if not image_file or not allowed_file(image_file.filename):
            return jsonify({'success': False, 'error': 'Please upload a valid image file'}), 400
        
        # Save uploaded image
        filename = secure_filename(image_file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(filepath)
        
        # Create task ID
        task_id = str(uuid.uuid4())
        
        # Start background generation
        thread = threading.Thread(
            target=generate_storybook_background,
            args=(task_id, filepath, gender, story_choice, character_name)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'task_id': task_id})
        
    except Exception as e:
        print(f"Error starting generation: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    """Get progress for a generation task."""
    # Yield to eventlet to prevent blocking
    eventlet.sleep(0)
    
    if task_id not in generation_progress:
        return jsonify({'error': 'Task not found'}), 404
    
    progress = generation_progress[task_id]
    return jsonify({
        'status': progress['status'],
        'progress': progress['progress'],
        'total': progress['total'],
        'current_step': progress['current_step'],
        'error': progress.get('error')
    })

@app.route('/download/<task_id>', methods=['GET'])
def download_pdf(task_id):
    """Download the generated PDF."""
    if task_id not in generation_progress:
        return jsonify({'error': 'Task not found'}), 404
    
    progress = generation_progress[task_id]
    if progress['status'] != 'complete' or not progress['pdf_path']:
        return jsonify({'error': 'PDF not ready yet'}), 400
    
    pdf_path = progress['pdf_path']
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'PDF file not found'}), 404
    
    story_titles = {
        'jack': 'Jack and the Beanstalk',
        'red': 'Little Red Riding Hood'
    }
    
    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"Storybook.pdf"
    )

def init_db():
    """
    Initialize the database by creating all tables.
    This should be called once to set up the database schema.
    """
    with app.app_context():
        db.create_all()
        print("✅ Database initialized successfully!")

if __name__ == '__main__':
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    # Initialize database tables
    init_db()
    
    port = int(os.environ.get('PORT', 5000))
    print("✨ Starting Fairy Tale Generator...")
    print(f"🌐 Web interface: http://localhost:{port}")
    print("🎨 Ready to create magical stories!")
    print(f"📝 Server is running! Open http://localhost:{port} in your browser.")
    print("💡 Press CTRL+C to stop the server\n")
    app.run(debug=False, host='0.0.0.0', port=port)
