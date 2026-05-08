from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ai_core import chat
import uvicorn

app = FastAPI(title="YouMatter AI API")

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request model
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

# Health check
@app.get("/health")
def health_check():
    return {"status": "YouMatter AI is running"}

# Main chat endpoint
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        result = chat(
            user_id=request.user_id,
            user_message=request.message,
            user_consent=request.consent
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)