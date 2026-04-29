<!-- Banner -->
<h1 align="center"> YouMatter</h1>
<h3 align="center">AI Mental Health Companion for India 🇮🇳</h3>

<p align="center">
  <b>Empathetic. Safe. Always there.</b><br/>
  Supporting Hindi, Hinglish & English users with real-time emotional care.
</p>

---

## Overview  

YouMatter is an **AI-powered mental health companion** designed for Indian users.  
It combines **empathy, crisis detection, and intelligent memory** to provide meaningful emotional support.  

Unlike generic chatbots, YouMatter understands **language, culture, and emotional nuance**, responding like a **trusted friend — not a machine**.  

---

## Core Features  

### Human-Like AI Interaction  
- Conversations in **Hindi, Hinglish, and English**  
- Emotion-aware responses  
- Natural, non-robotic communication  

### Intelligent Memory System  
- Short-term memory for context  
- Long-term memory for personalisation  
- Learns user patterns over time  

### Advanced Crisis Detection  
- Keyword-based detection  
- AI-based safety scoring  
- Multi-level classification:  
  `safe → distress → crisis → severe`  

### Safety & Support System  
- 🇮🇳 Indian helpline integration  
-  Guardian alerts (with consent)  
- Emergency override in severe cases  

---

## Unique Features  

-  Calm Mode UI for distress situations  
-  Adaptive AI personality  
-  Mini mental health activities (breathing, grounding)  
-  Mood journal & diary  
-  Smart emotional check-ins  

---

## Tech Stack  

| Layer            | Technology                     |
|------------------|--------------------------------|
| AI Model         | Sarvam AI (sarvam-105b)        |
| Safety Scoring   | OpenRouter (Elephant Alpha)    |
| Backend (Core)   | FastAPI (Python)               |
| Backend (API)    | Express.js (Node.js)           |
| Database         | Supabase (PostgreSQL)          |
| Frontend         | React                          |
| Deployment       | AWS EC2 + Render + Vercel      |

---

##  Architecture  

```
Client (React)
     ↓
Node API (Express)
     ↓
FastAPI (AI Core)
     ↓
AI + Safety Layer
     ↓
Database (Supabase)
```

---

## API  

### Base URL  
```
http://107.21.23.105:8000
```

### GET /health  
```json
{
  "status": "YouMatter AI is running"
}
```

### POST /chat  

#### Request  
```json
{
  "user_id": "abc123",
  "message": "I feel lonely",
  "consent": {
    "guardian_alert": true,
    "helpline_alert": true,
    "alerts_paused": false,
    "guardian_email": "guardian@email.com",
    "guardian_name": "Mom"
  }
}
```

#### Response  
```json
{
  "reply": "AI response here",
  "safety_level": "safe | distress | crisis | severe",
  "show_consent_prompt": false,
  "alert_sent": false,
  "blocked": false
}
```

---

## Safety Levels  

| Level      | Meaning            | Action                          |
|------------|-------------------|----------------------------------|
| safe       | Normal            | No action                        |
| distress   | Struggling        | Gentle AI mode                   |
| crisis     | Self-harm signals | Alerts + helplines               |
| severe     | Immediate danger  | Forced emergency response        |

---

##  Project Structure  

```
youmatter/
├── ai_core.py
├── safety.py
├── memory.py
├── main.py
├── requirements.txt
├── .env
└── .gitignore
```

---

## 🇮🇳 Helplines  

| Helpline              | Number        |
|----------------------|---------------|
| iCall                | 9152987821    |
| Vandrevala Foundation| 1860-2662-345 |
| AASRA                | 9820466627    |
| Kiran                | 1800-599-0019 |
| NCW                  | 7827170170    |
| Shakti Shalini       | 10920         |

---

##  Security  

- User consent required for alerts  
- Sensitive data handled securely  
- `.env` never committed  

---

##  Team  

- AI & Architecture — Aishwarya, Supriya  
- Backend — Harshita, Neeraj  
- Frontend — Ankita, Simran, Rounit  

---

##  Future  

- Voice-based interaction  
- Therapist dashboard  
- Better personalisation  
- Mobile app  

---

## 🤍 Vision  

Make mental health support **accessible, stigma-free, and always available**.  

---

<p align="center">
  <b>YouMatter — Because your mental health matters.</b> 🤍
</p>
