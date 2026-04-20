# Safety Layer for YouMatter
# Detects crisis situations and responds appropriately

# Indian helplines
HELPLINES = """
🆘 If you're in crisis, please reach out:
- iCall: 9152987821
- Vandrevala Foundation: 1860-2662-345 (24/7)
- AASRA: 9820466627
- Snehi: 044-24640050
- iCall Chat: icallhelpline.org
"""

# Crisis keywords — expandable list
CRISIS_KEYWORDS = [
    "kill myself", "want to die", "end my life", "suicide",
    "can't go on", "cannot go on", "no reason to live",
    "better off dead", "want to end it", "end it all",
    "hurt myself", "self harm", "cut myself", "overdose",
    "goodbye forever", "nobody cares", "don't want to exist",
    "can't take it anymore", "cannot take it anymore",
    "i give up", "life is pointless", "what's the point",
    "मरना चाहता हूं", "मरना चाहती हूं", "जीना नहीं चाहता",  # Hindi
]

# Soft distress keywords (not crisis but needs extra care)
DISTRESS_KEYWORDS = [
    "hopeless", "worthless", "nobody loves me", "all alone",
    "hate myself", "failure", "burden", "disappear",
    "exhausted", "can't cope", "falling apart", "breaking down"
]


def check_safety(message: str):
    """
    Analyzes a message for crisis or distress signals.
    Returns a dict with:
    - level: "safe", "distress", or "crisis"
    - message: what to show/do
    """
    message_lower = message.lower()

    # Check for crisis level
    for keyword in CRISIS_KEYWORDS:
        if keyword in message_lower:
            return {
                "level": "crisis",
                "keyword_found": keyword,
                "helplines": HELPLINES
            }

    # Check for distress level
    for keyword in DISTRESS_KEYWORDS:
        if keyword in message_lower:
            return {
                "level": "distress",
                "keyword_found": keyword,
                "helplines": None
            }

    # All clear
    return {
        "level": "safe",
        "keyword_found": None,
        "helplines": None
    }


def get_safety_system_prompt(safety_result: dict) -> str:
    """
    Returns extra instructions for the AI based on safety level.
    This gets added to the system prompt dynamically.
    """
    if safety_result["level"] == "crisis":
        return """
IMPORTANT — CRISIS DETECTED:
The user may be in immediate danger. 
- Do NOT give generic responses
- Acknowledge their pain deeply and directly
- Gently but clearly encourage them to call a helpline
- Do not leave them feeling alone
- Do not panic or be robotic
- Be the warmest, most human version of yourself
"""
    elif safety_result["level"] == "distress":
        return """
IMPORTANT — USER IN DISTRESS:
The user is struggling emotionally.
- Be extra gentle and patient
- Validate their feelings completely
- Do not give advice unless asked
- Focus on making them feel heard
"""
    else:
        return ""  # Normal conversation, no changes needed


# Test it directly
if __name__ == "__main__":
    test_messages = [
        "I feel lonely today",
        "I want to kill myself",
        "I feel so hopeless",
        "How are you?",
        "मरना चाहता हूं"
    ]

    for msg in test_messages:
        result = check_safety(msg)
        print(f"Message: '{msg}'")
        print(f"Level: {result['level']}")
        print(f"Keyword: {result['keyword_found']}")
        print("---")