import os
from openai import OpenAI
from dotenv import load_dotenv

# Load your API key from .env file
load_dotenv()

# Connect to OpenRouter (free models)
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# This is the "personality" of your AI companion
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
    # Build the message list
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += conversation_history
    messages.append({"role": "user", "content": user_message})

    # Call the free LLM via OpenRouter
    response = client.chat.completions.create(
        model="openrouter/elephant-alpha",
        messages=messages,
    )

    # Extract the reply text
    reply = response.choices[0].message.content
    return reply


# Quick test
if __name__ == "__main__":
    print("YouMatter AI is ready. Type 'quit' to exit.\n")
    history = []

    while True:
        user_input = input("You: ")
        if user_input.lower() == "quit":
            break

        response = chat(user_input, history)
        print(f"\nYouMatter: {response}\n")

        # Save conversation so AI remembers context
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})