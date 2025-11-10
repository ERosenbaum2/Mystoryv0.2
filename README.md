# Fairy Tale Generator

A comprehensive Flask web application that generates personalized fairy tale storybooks using AI-powered story creation and image generation. Create custom children's books featuring your child as the main character!

## ✨ Features

### Core Functionality
- **AI-Powered Story Generation**: Uses GPT-4 to create personalized narrative text
- **Image Generation**: DALL-E integration for custom storybook illustrations
- **PDF Storybook Creation**: Compiles generated content into downloadable PDFs
- **Multi-threaded Processing**: Parallel image generation for faster storybook creation
- **Real-time Progress Updates**: Server-Sent Events (SSE) for live generation progress

### User Management
- **Email/Password Authentication**: Secure registration and login with password hashing
- **OAuth Integration**: Google OAuth support for quick sign-in
- **Session Management**: Flask-Login for secure session handling
- **User Library**: Dashboard to view and download past storybooks

### Story Features
- **Pre-vetted Stories**: Database-stored story templates (Little Red Riding Hood, Jack and the Beanstalk)
- **Gender-Aligned Selection**: Dynamic story filtering based on selected gender
- **Child Name Personalization**: Custom character names throughout the story
- **Name Validation**: Profanity and format checking for child names

### Image Processing
- **Face Detection & Matching**: Ensures character consistency across pages
- **Image Quality Validation**: Mock validation service for image quality checks
- **Consistency Tracking**: RAG-based system for maintaining visual consistency

### Technical Features
- **Database Logging**: Application logs stored in database and files
- **Rate Limiting**: Protection against abuse on authentication endpoints
- **Secure File Storage**: User-specific directories with organized file naming
- **Responsive UI**: Modern, mobile-friendly interface

## 📋 Prerequisites

- **Python 3.8 or higher**
- **OpenAI API Key** (for GPT-4 and DALL-E)
- **PostgreSQL** (for production) or **SQLite** (for local development)
- **Google OAuth Credentials** (optional, for OAuth login)

## 🚀 Local Setup

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd Mystoryv0.2
```

### 2. Create Virtual Environment
```bash
python -m venv venv
```

### 3. Activate Virtual Environment
- **Windows:**
  ```bash
  venv\Scripts\activate
  ```
- **macOS/Linux:**
  ```bash
  source venv/bin/activate
  ```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Set Up Environment Variables
Create a `.env` file in the project root (or set environment variables):

```env
# Required
OPENAI_API_KEY=sk-proj-your-actual-api-key-here
SECRET_KEY=generate-a-random-secret-key-here

# Optional (for OAuth)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Database (optional - defaults to SQLite if not set)
DATABASE_URL=postgresql://user:password@localhost/dbname
```

**Generate a secret key:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 6. Initialize Database
```bash
python -c "from project import init_db; init_db()"
```

### 7. Load Initial Stories
```bash
python load_stories.py
```

This will populate the database with:
- Little Red Riding Hood (girl)
- Jack and the Beanstalk (boy)

### 8. Run the Application
```bash
python project.py
```

### 9. Access the Application
Open your browser and navigate to:
```
http://localhost:5000
```

## 📁 Project Structure

```
Mystoryv0.2/
├── project.py          # Main application file
├── models.py           # SQLAlchemy database models
├── load_stories.py     # Script to load initial stories
├── requirements.txt    # Python dependencies
├── README.md          # This file
├── .gitignore         # Git ignore rules
├── uploads/           # User-uploaded images (created automatically)
├── books/             # Generated PDF storage (created automatically)
└── logs/              # Application logs (created automatically)
```

## 🔐 Authentication

### Registration
- Navigate to `/register`
- Provide name, email, and password
- Password requirements: Minimum 8 characters, at least 1 number

### Login
- Navigate to `/login`
- Use email/password or Google OAuth
- OAuth users can link accounts automatically

### Protected Routes
- `/library` - User's book library (requires login)
- `/api/user_books` - API endpoint for user's books (requires login)
- `/download_book/<book_id>` - Download a book PDF (requires login)

## 📚 Main Features

### Story Creation Flow
1. **Select Gender**: Choose "Boy" or "Girl"
2. **Select Story**: Dynamic dropdown filtered by gender
3. **Enter Child Name**: Validated name (2-20 chars, letters only, no profanity)
4. **Upload Image**: Child's photo (PNG, JPG, JPEG, GIF, WEBP, max 16MB)
5. **Generate**: Real-time progress updates via SSE
6. **Download**: PDF available in user library

### User Library
- Access at `/library` (requires login)
- View all generated storybooks
- Download PDFs
- See creation dates and story details
- Empty state message when no books exist

## 🔌 API Endpoints

### Public Endpoints
- `GET /` - Home page with story creation form
- `GET /register` - Registration page
- `GET /login` - Login page
- `POST /register` - Create new account
- `POST /login` - Authenticate user
- `GET /logout` - Logout user
- `GET /oauth/google/callback` - Google OAuth callback
- `GET /api/stories_by_gender/<gender>` - Get stories by gender (boy/girl)

### Protected Endpoints (Require Login)
- `GET /library` - User library dashboard
- `GET /api/user_books` - Get all books for current user
- `GET /download_book/<book_id>` - Download book PDF
- `POST /generate-story` - Start storybook generation
- `GET /progress/<task_id>` - Get generation progress
- `GET /stream_progress/<book_id>` - SSE stream for real-time updates

### Test Endpoints
- `GET /test_name_validation` - Test child name validation
- `GET /test_parallel_generation` - Test multi-threaded generation
- `GET /test_sse` - Test Server-Sent Events

## 🗄️ Database Models

### User
- `user_id` (Primary Key)
- `email` (Unique)
- `name`
- `password_hash`
- `oauth_provider`
- `oauth_id`
- `created_at`

### Book
- `book_id` (Primary Key)
- `user_id` (Foreign Key → User)
- `story_id`
- `child_name`
- `pdf_path`
- `created_at`

### Log
- `log_id` (Primary Key)
- `user_id` (Foreign Key → User, nullable)
- `level` (INFO, ERROR, WARNING, DEBUG)
- `message`
- `timestamp`

### Storyline
- `story_id` (Primary Key)
- `name`
- `gender` (boy/girl)
- `pages_json` (JSON array of 12 page objects)

## 🔧 Configuration

### File Storage
- **Uploads**: `uploads/` - User-uploaded images
- **Books**: `books/{user_id}/{user_id}_{timestamp}_{story_id}.pdf`
- **Logs**: `logs/app.log` - Rotating log files

### Database
- **Development**: SQLite (`fairy_tale_generator.db`)
- **Production**: PostgreSQL (via `DATABASE_URL` environment variable)

## 🚢 Deployment

### Deploying to Render

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

2. **Create Web Service on Render**
   - Go to https://render.com
   - Click "New +" → "Web Service"
   - Connect your GitHub repository

3. **Configure Service**
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn project:app --bind 0.0.0.0:$PORT`
   - **Plan**: Free or Paid

4. **Set Environment Variables**
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `SECRET_KEY`: Random secret key
   - `DATABASE_URL`: PostgreSQL connection string (provided by Render)
   - `GOOGLE_CLIENT_ID`: (Optional) For OAuth
   - `GOOGLE_CLIENT_SECRET`: (Optional) For OAuth

5. **Deploy**
   - Click "Create Web Service"
   - Wait for deployment (2-5 minutes)
   - Access your app at `https://your-app-name.onrender.com`

### Database Setup on Render
1. Create a PostgreSQL database in Render dashboard
2. Copy the `DATABASE_URL` from the database service
3. Add it as an environment variable in your web service

## 📝 Important Notes

- **Never commit `.env` file** - It's in `.gitignore`
- **API keys are sensitive** - Always use environment variables
- **Free tier limitations**: Render free tier may spin down after 15 minutes of inactivity
- **OpenAI costs**: Ensure your OpenAI account has sufficient credits
- **File storage**: Uploads and books folders are created automatically
- **Database**: Run `init_db()` and `load_stories.py` after first deployment

## 🐛 Troubleshooting

### Import Errors
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version: `python --version` (should be 3.8+)

### API Key Errors
- Verify `OPENAI_API_KEY` is set in environment variables
- Check API key format (should start with `sk-proj-`)

### Database Errors
- Ensure database is initialized: `python -c "from project import init_db; init_db()"`
- Check `DATABASE_URL` format for PostgreSQL
- Verify database tables exist

### Port Issues
- Render sets `PORT` environment variable automatically
- For local development, app runs on port 5000
- Production should use `gunicorn` with `$PORT`

### File Upload Issues
- Check `uploads/` folder exists and has write permissions
- Verify file size is under 16MB
- Check file format is supported (PNG, JPG, JPEG, GIF, WEBP)

### OAuth Issues
- Verify `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set
- Check OAuth redirect URI matches your domain
- Ensure OAuth credentials are configured in Google Cloud Console

## 🧪 Testing

### Test Name Validation
Visit `/test_name_validation` to test child name validation rules.

### Test Parallel Generation
Visit `/test_parallel_generation` to test multi-threaded image generation.

### Test SSE
Visit `/test_sse` to test Server-Sent Events for real-time updates.

## 📄 License

[Add your license here]

## 🤝 Contributing

[Add contribution guidelines here]

## 📞 Support

[Add support contact information here]
