# YouMatter 🤍

### AI Mental Health Companion for India

YouMatter is an empathetic AI-powered mental health companion designed
specifically for Indian users. It understands Hindi, Hinglish, and English,
detects crisis situations, and responds like a caring friend — not a robot.

---

## Features

- 🤝 Empathetic AI conversations in Hindi, Hinglish, and English
- 🚨 Two-layer crisis detection (keywords + AI scoring)
- 🇮🇳 Indian helplines integration (iCall, Vandrevala, AASRA)
- 👨‍👩‍👧 Guardian alert system with consent-based notifications
- 📔 Diary and mood tracking
- 🔒 Secure user data handling
- 🧠 Short and long term memory system

---

## Tech Stack

| Component      | Technology                  |
| -------------- | --------------------------- |
| AI Model       | Sarvam AI (sarvam-105b)     |
| Safety Scoring | OpenRouter (Elephant Alpha) |
| Backend        | FastAPI (Python)            |
| Node Backend   | Express.js                  |
| Database       | Supabase (PostgreSQL)       |
| Frontend       | React                       |
| Deployment     | AWS EC2 + Render + Vercel   |

---

## API Documentation

### Base URL: http://107.21.23.105:8000

### Endpoints

#### Health Check

-GET /health
Response:

```json
{ "status": "YouMatter AI is running" }
```

#### Chat

POST /chat
Request:

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

Response:

```json
{
  "reply": "AI response here",
  "safety_level": "safe/distress/crisis/severe",
  "show_consent_prompt": false,
  "alert_sent": false,
  "blocked": false
}
```

---

## Safety Levels

| Level      | Description                  | Action                          |
| ---------- | ---------------------------- | ------------------------------- |
| `safe`     | Normal conversation          | No action                       |
| `distress` | User struggling emotionally  | AI in gentle mode               |
| `crisis`   | Self harm or suicide mention | Guardian alert + helplines      |
| `severe`   | Immediate danger             | Urgent alert + helplines always |

---

## Project Structure

youmatter/
├── ai_core.py # Main AI brain
├── safety.py # Crisis detection system
├── memory.py # Short + long term memory
├── main.py # FastAPI server
├── requirements.txt
├── .env # API keys (never commit)
└── .gitignore

---

## Indian Helplines

| Helpline              | Number        |
| --------------------- | ------------- |
| iCall                 | 9152987821    |
| Vandrevala Foundation | 1860-2662-345 |
| AASRA                 | 9820466627    |
| Kiran Mental Health   | 1800-599-0019 |
| NCW (Women)           | 7827170170    |
| Shakti Shalini (DV)   | 10920         |

---

## Team

- AI & Architecture — Aishwarya(project lead),Supriya(helped with prompts)
- Backend — Node.js + Supabase -Harshita,Neeraj(helped with testing)
- Frontend — React-Ankita,Simran,Rounit

---

_YouMatter — Because your mental health matters._ 🤍
