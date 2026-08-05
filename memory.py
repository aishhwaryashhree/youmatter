BACKEND_DISABLED = True  # Flip to False once new backend is ready
import logging

logger = logging.getLogger("youmatter.memory")

# Your backend base URL
BACKEND_URL = "https://you-matter-backend.onrender.com/api/v1"


async def load_memory(user_id: str, http_client) -> list:
    """
    Fetches past conversation history from backend.
    Returns it in the format the AI expects.
    http_client is a shared httpx.AsyncClient passed in from the request layer.
    """
    if BACKEND_DISABLED:
        return []
    try:
        response = await http_client.get(
            f"{BACKEND_URL}/api/conversation/{user_id}", timeout=5.0
        )
        if response.status_code == 200:
            messages = response.json()
            return [
                {"role": msg["role"], "content": msg["message"]}
                for msg in messages
            ]
        logger.warning(
            f"load_memory: backend returned {response.status_code} for user {user_id}"
        )
        return []
    except Exception as e:
        logger.error(f"load_memory failed for user {user_id}: {e}", exc_info=True)
        return []


async def save_message(user_id: str, role: str, message: str, http_client, token: str = ""):
    if BACKEND_DISABLED:
        return
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = await http_client.post(
            f"{BACKEND_URL}/message",
            json={"message": message, "sender": role},
            headers=headers,
            timeout=5.0
        )
        if response.status_code >= 400:
            logger.warning(
                f"save_message: backend returned {response.status_code} for user {user_id}"
            )
    except Exception as e:
        logger.error(f"save_message failed for user {user_id}: {e}", exc_info=True)

async def load_user_profile(user_id: str, http_client) -> str:
    """
    Fetches user profile from backend.
    Returns a summary string to inject into AI context.
    """
    if BACKEND_DISABLED:
        return ""
    try:
        response = await http_client.get(
            f"{BACKEND_URL}/api/user/{user_id}", timeout=5.0
        )
        if response.status_code == 200:
            user = response.json()
            return f"""
User Profile:
- Name: {user.get('name', 'Unknown')}
- Age: {user.get('age', 'Unknown')}
- Current concerns: {user.get('current_concerns', 'Not shared')}
- Medical history: {user.get('medical_history', 'Not shared')}
"""
        logger.warning(
            f"load_user_profile: backend returned {response.status_code} for user {user_id}"
        )
        return ""
    except Exception as e:
        logger.error(f"load_user_profile failed for user {user_id}: {e}", exc_info=True)
        return ""


def summarize_history(history: list, keep_last: int = 20) -> list:
    """
    Trims history to the last `keep_last` messages.
    NOTE: this is truncation, not summarization — older context is dropped
    rather than condensed. True summarization (e.g. periodically compressing
    older turns into a short synopsis) is a follow-up improvement, not done here.
    """
    if len(history) <= keep_last:
        return history
    return history[-keep_last:]