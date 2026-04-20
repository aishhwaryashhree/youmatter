import os
from openai import OpenAI
from dotenv import load_dotenv
from safety import check_safety, get_safety_system_prompt, HELPLINES

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
"""

def chat(user_message, conversation_history=[]):
    # Step 1 — Check safety FIRST before anything else
    safety_result = check_safety(user_message)

    # Step 2 — Build dynamic system prompt based on safety level
    dynamic_prompt = SYSTEM_PROMPT + get_safety_system_prompt(safety_result)

    # Step 3 — Build messages
    messages = [{"role": "system", "content": dynamic_prompt}]
    messages += conversation_history
    messages.append({"role": "user", "content": user_message})

    # Step 4 — Get AI response
    response = client.chat.completions.create(
        model="openrouter/elephant-alpha",
        messages=messages,
    )
    reply = response.choices[0].message.content

    # Step 5 — If crisis, append helplines to response
    if safety_result["level"] == "crisis":
        reply += f"\n\n{HELPLINES}"

    return reply, safety_result


if __name__ == "__main__":
    print("YouMatter AI is ready. Type 'quit' to exit.\n")
    history = []

    while True:
        user_input = input("You: ")
        if user_input.lower() == "quit":
            break

        response, safety = chat(user_input, history)

        # Alert if crisis detected
        if safety["level"] == "crisis":
            print("\n🚨 CRISIS DETECTED — Guardian alert would be sent now\n")
        elif safety["level"] == "distress":
            print("\n⚠️  Distress detected — AI is in extra gentle mode\n")

        print(f"\nYouMatter: {response}\n")

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})