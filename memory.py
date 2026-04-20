import requests

# Your backend base URL (will change when deployed)
BACKEND_URL = "http://localhost:3000"

def load_memory(user_id: str) -> list:
    """
    Fetches past conversation history from backend.
    Returns it in the format the AI expects.
    """
    try:
        response = requests.get(f"{BACKEND_URL}/api/conversation/{user_id}")
        if response.status_code == 200:
            messages = response.json()
            # Convert to OpenAI format
            history = []
            for msg in messages:
                history.append({
                    "role": msg["role"],
                    "content": msg["message"]
                })
            return history
        else:
            return []
    except Exception as e:
        print(f"Memory load failed: {e}")
        return []


def save_message(user_id: str, role: str, message: str):
    """
    Saves a single message to the backend.
    role is either "user" or "assistant"
    """
    try:
        requests.post(f"{BACKEND_URL}/api/message", json={
            "user_id": user_id,
            "role": role,
            "message": message
        })
    except Exception as e:
        print(f"Memory save failed: {e}")


def load_user_profile(user_id: str) -> str:
    """
    Fetches user profile from backend.
    Returns a summary string to inject into AI context.
    """
    try:
        response = requests.get(f"{BACKEND_URL}/api/user/{user_id}")
        if response.status_code == 200:
            user = response.json()
            profile = f"""
User Profile:
- Name: {user.get('name', 'Unknown')}
- Age: {user.get('age', 'Unknown')}
- Current concerns: {user.get('current_concerns', 'Not shared')}
- Medical history: {user.get('medical_history', 'Not shared')}
"""
            return profile
        else:
            return ""
    except Exception as e:
        print(f"Profile load failed: {e}")
        return ""


def summarize_history(history: list) -> str:
    """
    If history is too long, summarize older messages
    to save token space. Keep last 20 messages full.
    """
    if len(history) <= 20:
        return history

    # Keep only last 20 messages
    # Older ones will be summarized later when we add AI summarization
    return history[-20:]