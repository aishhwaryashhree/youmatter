import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_core import chat, chat_stream

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("youmatter.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared async client for the whole app lifetime — reuses connections
    # instead of opening a new one per request.
    app.state.http_client = httpx.AsyncClient()
    yield
    await app.state.http_client.aclose()


app = FastAPI(title="YouMatter AI API", lifespan=lifespan)

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
    conversation_id: str = None


@app.get("/health")
def health_check():
    return {"status": "YouMatter AI is running"}


@app.post("/chat/{user_id}")
async def chat_endpoint(user_id: str, request: Request, body: ChatRequest):
    try:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        
        result = await chat(
            user_id=user_id,
            user_message=body.message,
            http_client=app.state.http_client,
            user_consent=body.consent,
            token=token,
            conversation_id=body.conversation_id
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
                token = data.get("token", "")
                conversation_id = data.get("conversation_id", None)
                async for event in chat_stream(
                    user_id=user_id,
                    user_message=message,
                    http_client=websocket.app.state.http_client,
                    user_consent=consent,
                    token=token,
                    conversation_id=conversation_id,
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