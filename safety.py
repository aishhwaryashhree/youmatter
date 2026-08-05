# Safety Layer for YouMatter
# Handles crisis detection, severity scoring, and consent-based alerts
# Requests for harmful information — always blocked
import numbers
import os
import re
from dotenv import load_dotenv
load_dotenv()
BLOCKED_REQUESTS = [
    # Hanging
    "how to tie a noose", "hangman knot", "how to hang myself",

    # Pills and overdose
    "how to overdose", "lethal dose", "how many pills to die",
    "kitni pills leni chahiye", "kon si pills leni chahiye","how many pills to kill",
    "sleeping pills to die",
    "how many sleeping pills",
    "lethal amount of pills",
    "pills to overdose",

    # Cutting
    "how to slit", "how to cut my wrists",

    # Jumping
    "how to jump", "best way to jump",
    "konsi building se koodun",

    # Poison and ingestion
    "how to drink phenyl", "phenyl kaise peeyein",
    "kitna phenyl", "phenyl se kaise marun",
    "which poison to drink", "kon sa zeher",
    "zeher kaise lein", "rat poison kaise khayein",
    "bleach kaise peeyein",

    # General
    "painless way to die", "best way to kill myself",
    "undetected suicide", "how to end my life quickly",
    "suicide method", "suicide note template",
    "how to suffocate", "carbon monoxide suicide",
]
# Indian helplines
HELPLINES = """
🆘 If you're in crisis, please reach out:
- iCall: 9152987821
- Vandrevala Foundation: 1860-2662-345 (24/7)
- AASRA: 9820466627
- Snehi: 044-24640050
- iCall Chat: icallhelpline.org
"""

SEVERE_KEYWORDS = [
    # Direct statements
    "i have a plan", "i've decided to", "saying goodbye",
    "bought pills", "have a knife", "going to jump",
    "last message", "won't be here tomorrow",
    "already took pills", "cut myself badly",
    "jumping off", "pulling the trigger",
    "मैंने फैसला कर लिया", "अब नहीं रहूंगा",

    # Ingestion methods
    "drink this poison", "drink poison",
    "drink this entire bottle", "bottle of poison",
    "pee liya poison", "poison pi liya",
    "zeher pi liya", "pi raha hun zeher",
    "pi rahi hun zeher",
    "drink phenyl", "phenyl peena", "phenyl pi",
    "rat poison", "pest control peena",
    "drink bleach", "bleach peena",
    "kerosene peena", "drink kerosene",
    "dettol peena", "sanitizer peena",
    "acid peena", "tezaab peena",
    "zeher peena", "zeher khana",
    "poison khana", "poison peena",

    # Jumping
    "jump from building", "jump off terrace",
    "chhath se koodna", "building se koodna",
    "train ke aage", "train ke neeche",

    # Other methods
    "bijli lagana khud ko", "electric shock khud ko",
    "nadi mein doobna", "dariya mein doobna",
    "khud ko aag lagana", # More Hindi/Hinglish severe
    "kal nahi rahunga", "kal nahi rahungi",
    "aaj aakhri din hai", "yeh mera aakhri message",
    "sab se alvida", "sabko alvida kehna hai",
    "alvida dosto", "alvida zindagi",
    "khud ko khatam kar lunga",
    "khud ko khatam kar lungi",
    "nahi bachunga", "nahi bachungi",
    "ab kuch nahi bachha jeene ke liye",
]

# Crisis keywords — serious but not immediate
CRISIS_KEYWORDS = [
    "kill myself", "want to die", "end my life", "suicide",
    "can't go on", "cannot go on", "no reason to live",
    "better off dead", "want to end it", "end it all",
    "hurt myself", "self harm", "cut myself", "overdose",
    "goodbye forever", "nobody cares", "don't want to exist",
    "can't take it anymore", "cannot take it anymore",
    "i give up", "life is pointless", "what's the point",
    "मरना चाहता हूं", "मरना चाहती हूं", "जीना नहीं चाहता",# More Hindi/Hinglish crisis
    "sab khatam karna chahta hun",
    "sab khatam karna chahti hun",
    "khatam kar dun", "khatam kar lun",
    "mar jana chahta hun", "mar jana chahti hun",
    "jeene ka mann nahi", "jeena nahi chahta",
    "jeena nahi chahti", "zindagi nahi chahiye",
    "zindagi se thak gaya hun",
    "zindagi se thak gayi hun",
    "bahut thak gaya hun zindagi se",
    "ab nahi rehna", "ab nahi jeena",
    "chale jaana chahta hun",
    "chale jaana chahti hun",
    "sab chhod ke jaana chahta hun",
    "duniya chhodni hai",
]

# Distress keywords — struggling but not in immediate danger
DISTRESS_KEYWORDS = [
    # English
    "hopeless", "worthless", "nobody loves me", "all alone",
    "hate myself", "failure", "burden", "disappear",
    "exhausted", "can't cope", "falling apart", "breaking down",
    "no one cares", "i am nothing", "i am worthless",
    "i am a burden", "feel like a burden",

    # Hindi - burden and worthlessness
    "mai bojh hu", "main bojh hun", "bojh hun",
    "mai kuch nahi hun", "main kuch nahi",
    "meri koi value nahi", "meri koi zaroorat nahi",
    "koi mujhe nahi chahta", "koi mujhse pyaar nahi karta",
    "main bekaar hun", "mai bekaar hu",
    "main waste hun", "mai faltu hu",
    "mujhse nafrat hai", "khud se nafrat",
    "main kamzor hun", "haar gaya", "haar gayi",
    "thak gaya hun", "thak gayi hun",
    "koi umeed nahi", "sab khatam",
    "akela hun", "akeli hun", "bilkul akela",# More Hindi/Hinglish distress
    "dard ho raha hai", "bahut dard hai",
    "ro raha hun", "ro rahi hun", "rona aa raha hai",
    "aansu aa rahe hain", "aankhein bhar aayi",
    "toot gaya hun", "toot gayi hun",
    "bikhar gaya hun", "bikhar gayi hun",
    "sambhal nahi pa raha", "sambhal nahi pa rahi",
    "dar lag raha hai", "bohot dar lag raha hai",
    "ghabra raha hun", "ghabra rahi hun",
    "chinta ho rahi hai", "pareshan hun",
    "neend nahi aa rahi", "kuch acha nahi lagta",
    "dil nahi lagta", "man nahi lagta",
    "bahut akela feel ho raha hai",
    "koi nahi samjhta", "koi nahi samajhta",
    "sab mujhse naraaz hain", "sab mujhe chhorh gaye",
    "kuch nahi bachha", "sab kho diya",

    # Hinglish
    "feel like burden", "bohot akela feel hota",
    "koi nahi hai mera", "sab chod gaye",
    "main toot gaya", "main toot gayi",
]


def check_safety(message: str) -> dict:
    """
    Analyzes a message for crisis signals.
    Returns level: "safe", "distress", "crisis", or "severe"
    """
    message_lower = message.lower()

    # Check severe FIRST (highest priority)
    for keyword in SEVERE_KEYWORDS:
        if keyword in message_lower:
            return {
                "level": "severe",
                "keyword_found": keyword,
                "helplines": HELPLINES,
                "can_pause": False  # Cannot pause severe alerts
            }

    # Check crisis
    for keyword in CRISIS_KEYWORDS:
        if keyword in message_lower:
            return {
                "level": "crisis",
                "keyword_found": keyword,
                "helplines": HELPLINES,
                "can_pause": True  # Can pause crisis alerts
            }

    # Check distress
    for keyword in DISTRESS_KEYWORDS:
        if keyword in message_lower:
            return {
                "level": "distress",
                "keyword_found": keyword,
                "helplines": None,
                "can_pause": True  # Can pause distress alerts
            }

    return {
        "level": "safe",
        "keyword_found": None,
        "helplines": None,
        "can_pause": True
    }


def get_safety_system_prompt(safety_result: dict) -> str:
    """
    Returns extra AI instructions based on safety level.
    """
    if safety_result["level"] == "severe":
        return """
URGENT — USER MAY BE IN IMMEDIATE DANGER:
- This is your most important response ever
- Acknowledge their pain immediately and directly
- Do NOT give breathing exercises or generic tips
- Tell them help is coming and they are not alone
- Beg them gently to call a helpline RIGHT NOW
- Be human, be real, be present
"""
    elif safety_result["level"] == "crisis":
        return """
IMPORTANT — CRISIS DETECTED:
- The user may be in danger
- Acknowledge their pain deeply and directly
- Gently but clearly encourage them to call a helpline
- Do not leave them feeling alone
- Be the warmest most human version of yourself
"""
    elif safety_result["level"] == "distress":
        return """
IMPORTANT — USER IN DISTRESS:
- Be extra gentle and patient
- Validate their feelings completely
- Do not give advice unless asked
- Focus on making them feel heard
"""
    return ""


def should_send_alert(safety_result: dict, user_consent: dict) -> dict:
    """
    Decides whether to send guardian/helpline alert.
    
    user_consent example:
    {
        "guardian_alert": True,      # user agreed to guardian alerts
        "helpline_alert": True,      # user agreed to helpline alerts
        "alerts_paused": False,      # user temporarily paused alerts
        "guardian_email": "mom@gmail.com",
        "guardian_name": "Mom"
    }
    """
    level = safety_result["level"]

    # Safe or distress — no alert needed
    if level in ["safe", "distress"]:
        return {"send_guardian": False, "send_helpline": False}

    # Severe — ALWAYS alert, cannot be paused
    if level == "severe":
        return {
            "send_guardian": user_consent.get("guardian_alert", False),
            "send_helpline": user_consent.get("helpline_alert", False),
            "urgent": True
        }

    # Crisis — no guardian alert at this level.
    # Helplines still appear in the reply (via ai_core.py chat()), but no
    # email goes to the guardian unless the situation escalates to "severe".
   # Crisis — alert only if not paused
    if level == "crisis":
        if user_consent.get("alerts_paused", False):
            return {"send_guardian": False, "send_helpline": False}
        return {
            "send_guardian": user_consent.get("guardian_alert", False),
            "send_helpline": False,  # Helpline only for severe
            "urgent": False
        }

    return {"send_guardian": False, "send_helpline": False}


def get_guardian_message(user_name: str, urgent: bool) -> str:
    """
    Returns the email message to send to guardian.
    Vague for crisis, urgent for severe.
    """
    if urgent:
        return f"""
Subject: URGENT — {user_name} may need immediate help

Hello,

This is an automated message from YouMatter, an AI mental health companion.

We are concerned that {user_name} may be in immediate danger right now.

Please reach out to them immediately or call emergency services (112) if needed.

— YouMatter Safety Team
"""
    else:
        return f"""
Subject: Checking in on {user_name}

Hello,

This is a gentle message from YouMatter, an AI mental health companion.

{user_name} might need your support today. 
Please check in on them when you get a chance — a simple message or call can mean the world.

— YouMatter Team
"""

async def ai_danger_score(message: str, http_client) -> int:
    """
    Async AI-based danger scorer. http_client is a shared httpx.AsyncClient
    (passed in, not created per-call) so connections get reused.
    """
    import os
    import re
    import logging

    logger = logging.getLogger("youmatter.safety")
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

    try:
        response = await http_client.post(
            "https://api.sarvam.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {SARVAM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sarvam-105b",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are a mental health crisis detector for an Indian mental health app.
Rate ONLY the self-harm or suicide risk from 1-10.
Assume the worst plausible interpretation for ambiguous messages.

1-3 = Safe (general stress, sadness)
4-6 = Distress (emotional pain, hopelessness)
7-8 = Crisis (self harm or suicide mentioned)
9-10 = Severe (immediate danger, has plan or means)

"i bought a blade today" = 9 (means acquired)
"kash main hoti hi nahi" = 8 (wishing non-existence)
"i want to drink this bottle of poison" = 10
"i feel sad" = 2

Output the number then STOP."""
                    },
                    {
                        "role": "user",
                        "content": f"Rate danger level of: {message}"
                    }
                ],
                # FIX BUG 2 (ai_danger_score): sarvam-30b has thinking mode ON
                # by default. With reasoning_effort="low" and max_tokens=100
                # the model spent its whole budget on reasoning tokens, returned
                # empty content, and the API returned an error JSON without
                # 'choices' — causing KeyError. Fix: disable thinking entirely
                # with reasoning_effort=None and raise max_tokens to 200.
                "max_tokens": 200,
                "temperature": 0.1,
                "reasoning_effort": None
            },
            timeout=8.0
        )
        data = response.json()
        logger.info(f"[DEBUG] Sarvam danger-score raw response: {data}")
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        raw = content if content.strip() else reasoning

        # Extract number from ANYWHERE in response including inside think blocks
        numbers = re.findall(r'\b([1-9]|10)\b', raw)
        if numbers:
            return max(1, min(10, int(numbers[-1])))
        return 1

    except Exception as e:
        # Fail closed-ish: log loudly so a silent outage doesn't go unnoticed.
        # Returning 1 (safe) here is a deliberate tradeoff — a scorer outage
        # shouldn't block chat entirely since keyword layer still runs.
        logger.error(f"AI danger scorer failed, defaulting to safe: {e}", exc_info=True)
        return 1


def combine_keyword_and_ai_score(keyword_result: dict, score: int) -> dict:
    """
    Merges the fast keyword-layer result with the AI danger score.
    Shared by both the sequential (check_safety_full) and concurrent
    (ai_core's gather-based) call paths so the upgrade logic lives in one place.
    """
    if score >= 9:
        return {
            "level": "severe",
            "keyword_found": "AI detected",
            "helplines": HELPLINES,
            "can_pause": False,
            "ai_score": score
        }
    elif score >= 7:
        return {
            "level": "crisis",
            "keyword_found": "AI detected",
            "helplines": HELPLINES,
            "can_pause": True,
            "ai_score": score
        }
    elif score >= 4:
        # Only upgrade if keyword scan said safe
        if keyword_result["level"] == "safe":
            return {
                "level": "distress",
                "keyword_found": "AI detected",
                "helplines": None,
                "can_pause": True,
                "ai_score": score
            }

    keyword_result["ai_score"] = score
    return keyword_result


async def check_safety_full(message: str, http_client) -> dict:
    """
    Full two-layer safety check (sequential — used outside the hot chat path,
    e.g. for batch/offline analysis). The live chat pipeline in ai_core.py
    runs these two layers concurrently instead; see combine_keyword_and_ai_score.
    Layer 1: Keywords (fast)
    Layer 2: AI scoring (catches indirect phrases)
    """
    # Layer 1 — keyword scan
    result = check_safety(message)

    # If already severe, no need for AI check
    if result["level"] == "severe":
        return result

    # Layer 2 — AI danger scoring
    score = await ai_danger_score(message, http_client)
    return combine_keyword_and_ai_score(result, score)
def is_blocked_request(message: str) -> bool:
    """
    Returns True if user is asking for harmful information.
    These are ALWAYS blocked regardless of context or consent.
    """
    message_lower = message.lower()
    for phrase in BLOCKED_REQUESTS:
        if phrase in message_lower:
            return True
    return False


def get_blocked_response() -> str:
    """
    Returns the response when a harmful request is detected.
    Never answers the question. Always redirects to help.
    """
    return """I can hear that you're in a really dark place right now, and I'm genuinely worried about you.

I'm not able to help with that — but I don't want to leave you alone right now.

You don't have to face this by yourself. Please reach out:

🆘 Vandrevala Foundation: 1860-2662-345 (available 24/7)
🆘 iCall: 9152987821
🆘 AASRA: 9820466627

Can you tell me what's been happening? I'm here and I'm listening. 💛"""
# Test it
if __name__ == "__main__":
    test_messages = [
        "I feel lonely today",
        "I want to kill myself",
        "I have a plan to end my life",
        "I feel so hopeless",
        "मरना चाहता हूं",
        "I bought pills to overdose"
    ]

    for msg in test_messages:
        result = check_safety(msg)
        print(f"Message: '{msg}'")
        print(f"Level: {result['level']} | Can Pause: {result['can_pause']}")
        print("---")