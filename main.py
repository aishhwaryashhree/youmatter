from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ai_core import chat
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

app = FastAPI(title="YouMatter AI API")

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Health check — no auth needed
@app.get("/health")
def health_check():
    return {"status": "YouMatter AI is running"}

# Main chat endpoint — protected
@app.post("/chat")
async def chat_endpoint(request: ChatRequest, x_api_key: str = Header(None)):
    # Check API key
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
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