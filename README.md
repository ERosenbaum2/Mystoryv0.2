# Fairy Tale Generator

A Flask web application that generates personalized fairy tales with AI-powered story creation and image generation.

## Features

- AI-powered story generation
- Image generation using DALL-E
- PDF storybook creation
- User-friendly web interface

## Prerequisites

- Python 3.8 or higher
- OpenAI API key

## Local Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd <project-directory>
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**
   - Windows:
     ```bash
     venv\Scripts\activate
     ```
   - macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Set up environment variables**
   - Copy `.env.example` to `.env`:
     ```bash
     copy .env.example .env
     ```
   - Edit `.env` and add your OpenAI API key:
     ```
     OPENAI_API_KEY=sk-proj-your-actual-api-key-here
     SECRET_KEY=generate-a-random-secret-key-here
     ```

6. **Run the application**
   ```bash
   python project.py
   ```

7. **Open your browser**
   Navigate to `http://localhost:5000`

## Deploying to Render

### Step 1: Push to GitHub

1. **Initialize Git repository** (if not already done)
   ```bash
   git init
   ```

2. **Add all files**
   ```bash
   git add .
   ```

3. **Commit your changes**
   ```bash
   git commit -m "Initial commit"
   ```

4. **Create a new repository on GitHub**
   - Go to https://github.com/new
   - Create a new repository (don't initialize with README, .gitignore, or license)

5. **Push to GitHub**
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git branch -M main
   git push -u origin main
   ```

### Step 2: Deploy on Render

1. **Sign up/Login to Render**
   - Go to https://render.com
   - Sign up or log in (you can use your GitHub account)

2. **Create a New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Select the repository you just pushed

3. **Configure the service**
   - **Name**: Choose a name for your service
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python project.py`
   - **Plan**: Choose Free or Paid plan

4. **Set Environment Variables**
   In the Render dashboard, go to the "Environment" section and add:
   - `OPENAI_API_KEY`: Your OpenAI API key (starts with `sk-proj-`)
   - `SECRET_KEY`: A random secret key (you can generate one using: `python -c "import secrets; print(secrets.token_hex(32))"`)

5. **Deploy**
   - Click "Create Web Service"
   - Render will automatically build and deploy your application
   - Wait for the deployment to complete (usually 2-5 minutes)

6. **Access your app**
   - Once deployed, Render will provide you with a URL like `https://your-app-name.onrender.com`
   - Your application should now be live!

## Important Notes

- **Never commit your `.env` file** - it's already in `.gitignore`
- **API keys are sensitive** - always use environment variables in production
- The free tier on Render may spin down after 15 minutes of inactivity
- Make sure your OpenAI API account has sufficient credits

## Troubleshooting

- **Import errors**: Make sure all dependencies are in `requirements.txt`
- **API key errors**: Verify your environment variables are set correctly in Render
- **Port issues**: Render automatically sets the PORT environment variable, but your app uses port 5000. If needed, you may need to modify the app to use `os.environ.get('PORT', 5000)`

## License

[Add your license here]
