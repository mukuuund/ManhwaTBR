# Hugging Face Space ML Worker Deployment

To alleviate RAM and OOM issues on Render Free, all heavy Machine Learning (PyTorch, SentenceTransformers) has been moved to a Hugging Face Space. The Render app is now purely a lightweight Flask client.

## 1. Create a Hugging Face Space
1. Go to [Hugging Face Spaces](https://huggingface.co/spaces) and click **Create new Space**.
2. Set the **Space name** (e.g., `manhwa-tracker-ml`).
3. Choose the **Docker** SDK.
4. Choose **Blank** Docker template.
5. Choose the **Free** tier.

## 2. Upload Files to the Space
In your new Space's "Files and versions" tab, upload the contents of the `hf_worker/` directory (not the directory itself, but the files inside):
- `app.py`
- `requirements.txt`
- `README.md`

You will also need to create a `Dockerfile` in the root of the Hugging Face space containing:
```dockerfile
FROM python:3.11

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
```

## 3. Set up Hugging Face Secrets
In your Hugging Face Space Settings -> Variables and secrets -> **Secrets**, add the following (these must match your current `.env` database details):
- `DB_HOST`: Your Filess MySQL host
- `DB_PORT`: Your Filess MySQL port (e.g., 3307)
- `DB_USER`: Your Filess MySQL username
- `DB_PASSWORD`: Your Filess MySQL password
- `DB_NAME`: Your Filess MySQL database name
- `ML_WORKER_SECRET`: A secure random string (e.g., `super_secret_token_123`)

## 4. Set up Render Environment Variables
In your Render Dashboard -> Environment:
- Remove `USE_TORCH` or `USE_TF` if you have them.
- Add `HF_WORKER_URL`: The URL of your running Hugging Face space (e.g., `https://your-username-manhwa-tracker-ml.hf.space`)
- Add `ML_WORKER_SECRET`: The exact same secret string you put in Hugging Face above.

## 5. End-to-End Test
1. Make sure Render builds successfully with the updated `requirements.txt` (which no longer includes PyTorch or transformers).
2. Go to your live Render website and log in.
3. Click on **Recommendations**. It should load instantly using cached DB results.
4. Click **Generate New**. It should say "Generating...".
5. The Flask app will send a POST request to your HF Space.
6. The HF Space will connect to Filess MySQL, load the PyTorch models, compute recommendations, save them back to MySQL, and respond.
7. The Render app receives the success response and reloads to show your new recommendations.
