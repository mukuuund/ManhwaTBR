# Manhwa Tracker ML Worker

This is a FastAPI worker designed to run on a **Hugging Face Space**. It handles heavy ML computations (embedding generation, tensor operations, semantic search) so the main Render Flask app remains lightweight and doesn't run out of memory.

## Setup Instructions

See the main `DEPLOY_HF_WORKER.md` file in the parent directory for full instructions on setting up this Space.
