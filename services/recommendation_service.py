import os
import requests

def generate_recommendations(user_id):
    hf_url = os.environ.get("HF_WORKER_URL")
    hf_secret = os.environ.get("ML_WORKER_SECRET")
    
    if not hf_url or not hf_secret:
        return {"status": "error", "message": "Hugging Face Worker URL or Secret not configured."}
        
    try:
        url = f"{hf_url.rstrip('/')}/generate"
        headers = {"Authorization": f"Bearer {hf_secret}"}
        res = requests.post(url, json={"user_id": user_id}, headers=headers, timeout=180)
        res.raise_for_status()
        data = res.json()
        if data.get("success"):
            return {"status": "success", "message": data.get("message", "Recommendations generated"), "count": data.get("count", 0)}
        else:
            return {"status": "error", "message": data.get("error", "Failed to generate recommendations.")}
    except Exception as e:
        return {"status": "error", "message": f"Error calling ML Worker: {str(e)}"}
