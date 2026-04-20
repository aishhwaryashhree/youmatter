import os
from openai import OpenAI
from dotenv import load_dotenv
from safety import check_safety, get_safety_system_prompt, HELPLINES
from memory import load_memory, save_message, load_user_profile, summarize_history

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

SYSTEM_PROMPT = """
You are YouMatter, a warm and empathetic AI mental health companion.
Your goal is to make the user feel heard, understood, and supported.

Rules you must follow:
- Always respond with kindness and zero judgment
- Never diagnose or prescribe anything
- If the user seems in crisis, gently encourage professional help
- Keep responses short, warm, and conversational
- Ask one gentle follow-up question to keep the conversation going
- You are NOT a generic chatbot — you deeply care about this person
- If you know the user's name, use it naturally sometimes
- Remember what they have shared before and refer back to it
"""

def chat(user_id: str, user_message: str):
    """
    Full pipeline:
    1. Load user profile + memory
    2. Check safety
    3. Build context
    4. Get AI response
    5. Save to memory
    """

    # Step 1 — Load user profile from backend
    user_profile = load_user_profile(user_id)

    # Step 2 — Load past conversation history
    history = load_memory(user_id)
    history = summarize_history(history)

    # Step 3 — Check safety
    safety_result = check_safety(user_message)

    # Step 4 — Build dynamic system prompt
    dynamic_prompt = SYSTEM_PROMPT
    if user_profile:
        dynamic_prompt += f"\n\nUser Context:\n{user_profile}"
    dynamic_prompt += get_safety_system_prompt(safety_result)

    # Step 5 — Build messages
    messages = [{"role": "system", "content": dynamic_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_message})

    # Step 6 — Get AI response
    response = client.chat.completions.create(
        model="openrouter/elephant-alpha",
        messages=messages,
    )
    reply = response.choices[0].message.content

    # Step 7 — Append helplines if crisis
    if safety_result["level"] == "crisis":
        reply += f"\n\n{HELPLINES}"

    # Step 8 — Save both messages to memory
    save_message(user_id, "user", user_message)
    save_message(user_id, "assistant", reply)

    return reply, safety_result


if __name__ == "__main__":
    print("YouMatter AI is ready. Type 'quit' to exit.")
    
    # For testing, use a dummy user_id
    # In production this comes from auth
    user_id = input("Enter your user ID (or press Enter for 'test-user'): ").strip()
    if not user_id:
        user_id = "test-user"

    print(f"\nLogged in as: {user_id}\n")

    while True:
        user_input = input("You: ")
        if user_input.lower() == "quit":
            break

        response, safety = chat(user_id, user_input)

        if safety["level"] == "crisis":
            print("\n🚨 CRISIS DETECTED — Guardian alert would be sent now\n")
        elif safety["level"] == "distress":
            print("\n⚠️  Distress detected — AI is in extra gentle mode\n")

        print(f"\nYouMatter: {response}\n")