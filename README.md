# Manhwa Discovery Dashboard

A Flask web application for tracking your local manhwa library, comparing it with Telegram updates, and generating personalized recommendations using an advanced hybrid scoring engine.

## Features
- **Library Tracking:** Scan your local downloads and keep track of your reading progress.
- **Telegram Updates:** Automatically check Telegram channels for new chapters.
- **Recommendations:** Get personalized recommendations based on semantic similarity, genre match, popularity, and user feedback.
- **Dashboard:** A modern UI to view statistics, recently updated titles, and top recommendations.

## Tech Stack
- **Backend:** Python, Flask
- **Frontend:** HTML, CSS (Tailwind CSS or Bootstrap), JavaScript
- **Database:** MySQL
- **AI/ML:** Sentence-BERT (`sentence-transformers`) for embeddings
- **APIs:** AniList GraphQL API, Telethon

## Folder Structure
```
manhwa-tracker/
├── app.py                     # Main Flask application entry point
├── config.py                  # Configuration and environment variables
├── db.py                      # Database connection setup
├── requirements.txt           # Python dependencies
├── .env.example               # Example environment variables
├── README.md                  # Project documentation
├── services/                  # Business logic and external API integrations
├── repositories/              # Database interaction layers
├── templates/                 # Jinja HTML templates
├── static/                    # CSS and JavaScript assets
└── migrations/                # Database schema migrations
```

## Setup Instructions

### 1. Database Setup
1. Ensure MySQL is installed and running.
2. Create a database: `CREATE DATABASE manhwa_tracker;`
3. Initialize the schema using `code.sql`.
4. Run the migration script in `migrations/migration.sql` to add the missing tables and columns:
   ```bash
   mysql -u root -p manhwa_tracker < code.sql
   mysql -u root -p manhwa_tracker < migrations/migration.sql
   ```

### 2. Environment Variables
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Fill in the required variables (MySQL credentials, Telegram API details, local folder path).

### 3. Installation
1. (Optional but recommended) Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### 4. Running the Flask App
Start the development server:
```bash
python app.py
```
Then navigate to `http://127.0.0.1:5000` in your web browser.

## Recommendation Engine
The hybrid recommendation engine calculates scores using the following weights:
- **Semantic Similarity (40%):** Matches manhwa descriptions using Sentence-BERT.
- **Genre Match (20%):** Uses Jaccard similarity for overlapping genres.
- **Popularity & Rating (25%):** Factors in AniList popularity and average scores.
- **Freshness (10%):** Prioritizes recently updated or newly added titles.
- **Feedback (5%):** Adjusts scores based on user likes/dislikes.

## Future Improvements
- Implement user authentication for multi-user support.
- Refine the MMR diversity scoring.
- Add more granular feedback options.

## Project Planning (Jira-Style Epics)

**Epic 1: Backend Cleanup**
- [x] Fix schema mismatch
- [x] Move hardcoded config to .env
- [x] Add requirements.txt
- [x] Add README

**Epic 2: Recommendation Engine Upgrade**
- [ ] Hybrid scoring
- [ ] User taste profile
- [ ] Feedback learning
- [ ] Diversity ranking
- [ ] Recommendation reasons

**Epic 3: Flask Web App**
- [ ] Dashboard page
- [ ] Library page
- [ ] Updates page
- [ ] Recommendations page

**Epic 4: Feedback Loop**
- [ ] Like/dislike buttons
- [ ] Already read
- [ ] Save for later
- [ ] Use feedback in scoring

**Epic 5: Testing and Polish**
- [ ] Validate routes
- [ ] Improve error handling
- [ ] Improve UI
- [ ] Add screenshots
