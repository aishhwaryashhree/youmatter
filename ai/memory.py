import os
import logging

logger = logging.getLogger("youmatter.memory")

BACKEND_DISABLED = False  # Flip to False once verified end-to-end

# Local dev default; override with the real Render URL via env var once deployed
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")


def _auth_headers(token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def load_memory(user_id: str, http_client, token: str = "") -> list:
    """
    Fetches past conversation history from the backend.
    Backend returns nested conversations: { conversations: [{ id, title, messages: [...] }] }
    We flatten every message across all of the user's conversations into one
    list, in the shape the AI expects: [{"role": ..., "content": ...}, ...]
    """
    if BACKEND_DISABLED:
        return []
    try:
        response = await http_client.get(
            f"{BACKEND_URL}/api/conversation/{user_id}",
            headers=_auth_headers(token),
            timeout=5.0
        )
        if response.status_code == 200:
            data = response.json()
            conversations = data.get("conversations", [])
            flat_messages = []
            for conv in conversations:
                for msg in conv.get("messages", []):
                    flat_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            return flat_messages
        logger.warning(
            f"load_memory: backend returned {response.status_code} for user {user_id}"
        )
        return []
    except Exception as e:
        logger.error(f"load_memory failed for user {user_id}: {e}", exc_info=True)
        return []


async def save_message(
    user_id: str,
    role: str,
    message: str,
    http_client,
    token: str = "",
    conversation_id: str = None,
    safety_level: str = None,
    ai_score: int = None,
):
    """
    Saves a message to the backend. Returns the conversation_id used —
    either the one passed in, or a newly created one if none was given.
    Callers MUST use the returned conversation_id for the next call, so
    that a user message and its assistant reply land in the same
    conversation. On any failure, returns whatever conversation_id was
    passed in unchanged (fail-soft — never crashes the caller).
    """
    if BACKEND_DISABLED:
        return conversation_id
    try:
        payload = {
            "user_id": user_id,
            "role": role,
            "content": message,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if safety_level is not None:
            payload["safety_level"] = safety_level
        if ai_score is not None:
            payload["ai_score"] = ai_score

        response = await http_client.post(
            f"{BACKEND_URL}/message",
            json=payload,
            headers=_auth_headers(token),
            timeout=5.0
        )
        if response.status_code >= 400:
            logger.warning(
                f"save_message: backend returned {response.status_code} for user {user_id}: {response.text}"
            )
            return conversation_id
        data = response.json()
        return data.get("conversation_id", conversation_id)
    except Exception as e:
        logger.error(f"save_message failed for user {user_id}: {e}", exc_info=True)
        return conversation_id

async def load_user_profile(user_id: str, http_client, token: str = "") -> str:
    """
    Fetches user profile from the backend.
    Returns a summary string to inject into the AI's system prompt.
    """
    if BACKEND_DISABLED:
        return ""
    try:
        response = await http_client.get(
            f"{BACKEND_URL}/api/user/{user_id}",
            headers=_auth_headers(token),
            timeout=5.0
        )
        if response.status_code == 200:
            user = response.json()
            return f"""
User Profile:
- Name: {user.get('display_name') or 'Unknown'}
- Guardian: {user.get('guardian_name') or 'Not shared'}
- Current concerns: {user.get('current_concerns') or 'Not shared'}
- Medical history: {user.get('medical_history') or 'Not shared'}
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
    NOTE: this is truncation, not summarization — see original docstring.
    """
    if len(history) <= keep_last:
        return history
    return history[-keep_last:]