# ManhwaTBR

A web-based manhwa tracking and recommendation system that helps users organize their local manhwa library, track reading progress, and discover similar titles using machine learning.

ManhwaTBR allows users to upload/select their local manhwa folder, automatically extracts manhwa titles and chapter progress from filenames, stores the library in MySQL, and generates personalized recommendations using a Sentence-BERT based recommendation engine hosted on Hugging Face.

---

## Live Demo

* **Web App:** [Render ManhwaTBR](https://manhwatbr.onrender.com)
* **ML Worker:** [Hugging Face ML Wroker](https://huggingface.co/spaces/mukund222/manhwatbr-ml-worker)
* **Repository:** [GitHub Repo](https://github.com/mukuuund/ManhwaTBR)

---

## Project Overview

Manhwa readers often download chapters locally, but keeping track of what they have read, which chapter they stopped at, and what to read next becomes messy over time.

ManhwaTBR solves this by turning a local manhwa folder into a structured digital library.

The app scans folder and file names, extracts manhwa titles and chapter numbers, saves the user’s reading progress, and recommends new manhwa based on the user’s library and preferences.

The recommendation system uses semantic similarity with Sentence-BERT, along with genre, popularity, rating, freshness, and user feedback signals to generate better suggestions.

---

## Features

### Local Library Tracking

* Upload/select a local manhwa folder from the browser
* Extract manhwa names from folder and file paths
* Detect chapter numbers from filenames
* Track the latest available local chapter
* Store user-specific reading progress
* Edit progress manually when needed

### Personalized Recommendations

* Generate recommendations based on the user’s existing library
* Use Sentence-BERT embeddings for semantic similarity
* Compare manhwa descriptions, genres, and metadata
* Exclude titles already present in the user’s library
* Show recommendation scores and reasons

### Feedback-Based Improvement

* Mark recommendations as liked, disliked, saved, already read, clicked, or ignored
* Store user feedback in the database
* Use feedback signals to improve future recommendations
* Support personalized learning based on user interactions

### Manhwa Metadata

* Fetch metadata such as description, genres, popularity, ratings, cover image, and status
* Use external manga/manhwa metadata sources such as AniList and MangaDex
* Store metadata in MySQL for search and recommendation usage

### Web Dashboard

* View personal manhwa library
* Track reading progress
* View latest recommendations
* Search manhwa
* Add titles to library
* See update and recommendation counts
* Use a clean web-based interface

---

## How It Works

```text
User selects local manhwa folder
        ↓
Browser extracts folder/file names
        ↓
App detects manhwa titles and chapter numbers
        ↓
Flask backend stores library data in MySQL
        ↓
Metadata is fetched from AniList / MangaDex
        ↓
Hugging Face ML worker generates recommendations
        ↓
Recommendations are saved and shown in the web app
```

The actual manhwa files are not uploaded.
Only extracted metadata such as title name, chapter number, and file count is sent to the backend.

---

## Recommendation Engine

ManhwaTBR uses a hybrid recommendation system.

The ML worker generates recommendations using:

* Semantic similarity between manhwa descriptions
* Genre overlap
* Popularity score
* Average rating
* Freshness of the title
* User feedback

The semantic similarity is calculated using Sentence-BERT from the `sentence-transformers` library.

Default scoring logic:

```text
Final Score =
  Semantic Similarity
+ Genre Match
+ Popularity
+ Rating
+ Freshness
+ User Feedback
```

This makes the recommendations more personalized than a simple popularity-based list.

---

## Tech Stack

### Backend

* Python
* Flask
* Gunicorn
* MySQL

### Frontend

* HTML
* CSS
* JavaScript
* Jinja Templates

### Machine Learning

* Hugging Face Spaces
* FastAPI
* Sentence-BERT
* sentence-transformers
* PyTorch
* scikit-learn

### Database

* MySQL hosted on Filess

### Deployment

* Render for the Flask web application
* Hugging Face Spaces for ML computation
* Filess for hosted MySQL database
* GitHub for version control

### External APIs

* AniList GraphQL API
* MangaDex API

---

## Architecture

```text
Frontend Browser
    |
    | folder/file metadata
    v
Flask Web App - Render
    |
    | stores users, library, metadata, feedback
    v
MySQL Database - Filess
    |
    | user library + candidate data
    v
ML Worker - Hugging Face Spaces
    |
    | recommendation results
    v
Flask Web App
```

The ML model is kept separate from the Flask app so that the web application remains lightweight and deployment-friendly.

---

## Database Usage

The application stores:

* User accounts
* Manhwa library data
* Local chapter progress
* Manhwa metadata
* Recommendation candidates
* Recommendation results
* User feedback
* Learned recommendation weights

MySQL is used because the project requires structured relationships between users, manhwa titles, recommendations, and feedback events.

---

## Folder Structure

```text
ManhwaTBR/
├── app.py
├── config.py
├── db.py
├── requirements.txt
├── services/
│   ├── anilist_service.py
│   ├── mangadex_service.py
│   ├── recommendation_service.py
│   ├── feedback_service.py
│   ├── title_parser.py
│   └── ...
├── hf_worker/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── templates/
├── static/
├── migrations/
└── README.md
```

---

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/ManhwaTBR.git
cd ManhwaTBR
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it:

```bash
venv\Scripts\activate
```

For macOS/Linux:

```bash
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the root folder:

```env
DB_HOST=your_mysql_host
DB_PORT=3306
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_NAME=manhwa_tracker

SECRET_KEY=your_secret_key

HF_WORKER_URL=your_huggingface_worker_url
ML_WORKER_SECRET=your_worker_secret
```

### 5. Set Up the Database

Create a MySQL database and run the required schema/migration files.

```sql
CREATE DATABASE manhwa_tracker;
```

Then apply the SQL files from the project.

### 6. Run the Flask App

```bash
python app.py
```

Open the app in your browser:

```text
http://127.0.0.1:5000
```

---

## ML Worker Setup

The recommendation engine runs separately inside the `hf_worker` folder.

```bash
cd hf_worker
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 7860
```

The Flask app communicates with this worker using the `HF_WORKER_URL` and `ML_WORKER_SECRET`.

---

## Deployment

### Flask App

The main Flask app is deployed on Render.

Recommended start command:

```bash
gunicorn --bind 0.0.0.0:$PORT app:app
```

### ML Worker

The ML worker is deployed on Hugging Face Spaces using Docker.

### Database

The MySQL database is hosted on Filess.

Both the Render app and Hugging Face worker connect to the same MySQL database.

---

## Security and Privacy

* Local manhwa files are not uploaded to the server
* Only extracted metadata is stored
* Passwords are hashed before storing
* Database credentials are stored using environment variables
* ML worker endpoints are protected using a shared secret
* `.env` files are not committed to GitHub

---

## What I Learned

While building this project, I worked on:

* Flask backend development
* MySQL database design
* User authentication
* File and folder metadata extraction
* API integration with AniList and MangaDex
* Machine learning based recommendations
* Sentence-BERT embeddings
* Deploying full-stack apps on Render
* Hosting ML workloads on Hugging Face Spaces
* Connecting cloud services with a hosted MySQL database

---

## Project Status

Completed core version.

The project supports local library import, user-specific progress tracking, metadata fetching, personalized recommendations, feedback collection, and cloud deployment.

---

## Author

Built by Mukund.

---
