import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from aiolimiter import AsyncLimiter
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ai_core import chat, chat_stream

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("youmatter.main")


# ---------------------------------------------------------------------------
# Rate limiting — incoming requests
# ---------------------------------------------------------------------------
# Key function: prefer user_id from the URL path (e.g. /chat/{user_id});
# fall back to the client's IP address for routes that don't have it.
def get_user_id(request: Request) -> str:
    return request.path_params.get("user_id") or get_remote_address(request)


# slowapi looks for the limiter on app.state.limiter by convention.
limiter = Limiter(key_func=get_user_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared async client for the whole app lifetime — reuses connections
    # instead of opening a new one per request (this was one of the causes
    # of the old slowness: `requests` opened a fresh connection every call).
    app.state.http_client = httpx.AsyncClient()
    # Global outgoing limiter for all Sarvam API calls.
    # 40 requests / 60 s matches Sarvam's free-tier cap for sarvam-105b.
    # NOTE: each user message triggers 2 Sarvam calls (classify_topic_and_score
    # + reply generation), so real message throughput is capped at ~20/minute
    # across all users. This is a known trade-off, not a bug.
    app.state.sarvam_limiter = AsyncLimiter(40, 60)
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="YouMatter AI API", lifespan=lifespan)

# Register the limiter and the 429 exception handler.
# Without this, hitting the limit raises an unhandled exception instead of
# returning a clean HTTP 429 Too Many Requests response.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO before real production use: replace with your actual frontend URL(s).
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    user_id: str
    message: str
    consent: dict = {
        "guardian_alert": False,
        "helpline_alert": False,
        "alerts_paused": False,
        "guardian_email": None,
        "guardian_name": None
    }


@app.get("/health")
def health_check():
    return {"status": "YouMatter AI is running"}


# user_id is in the URL path so that the slowapi key function can read it
# synchronously (key functions cannot be async, so we can't await the body).
# The ChatRequest body still has a user_id field for backward compat, but the
# path param is authoritative for routing and rate-limiting purposes.
@app.post("/chat/{user_id}")
@limiter.limit("10/minute")  # 10 requests per 60-second window, per user_id
async def chat_endpoint(user_id: str, request: Request, body: ChatRequest):
    try:
        result = await chat(
            user_id=user_id,
            user_message=body.message,
            http_client=app.state.http_client,
            sarvam_limiter=app.state.sarvam_limiter,
            user_consent=body.consent
        )
        return result
    except Exception as e:
        logger.error(f"chat_endpoint failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Something went wrong processing your message.")


@app.websocket("/ws/chat/{user_id}")
async def ws_chat(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint that streams chat reply tokens to the client in
    real-time, then sends a final safety_result event.

    Expected client message format:
        {"message": "<user text>", "consent": {<consent dict> or null}}

    Yielded server events:
        {"type": "token",         "content": "<reply fragment>"}
        {"type": "safety_result", "safety_level": ..., "blocked": ...,
         "alert_sent": ..., "show_consent_prompt": ..., "helplines": ...}
    """
    await websocket.accept()
    try:
        while True:
            try:
                data = await websocket.receive_json()
                message = data.get("message", "")
                consent = data.get("consent", None)
                async for event in chat_stream(
                    user_id=user_id,
                    user_message=message,
                    http_client=websocket.app.state.http_client,
                    sarvam_limiter=websocket.app.state.sarvam_limiter,
                    user_consent=consent,
                ):
                    await websocket.send_json(event)
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for user {user_id}")
                break
    except Exception as e:
        logger.error(f"ws_chat error for user {user_id}: {e}", exc_info=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)