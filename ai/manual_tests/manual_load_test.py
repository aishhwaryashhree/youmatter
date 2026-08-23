import asyncio
import time
import httpx
from ai_core import chat

async def saturate(client):
    """Fire 20 casual messages across different users to drain the global 
    40/min Sarvam bucket (each message = 2 Sarvam calls, so 20 messages = 40 calls)."""
    tasks = []
    for i in range(20):
        tasks.append(chat(f"load-user-{i}", "just chatting, nothing serious", client))
    await asyncio.gather(*tasks, return_exceptions=True)

async def send_crisis(client):
    """Send one clear crisis message and time how long it takes."""
    start = time.perf_counter()
    result = await chat("crisis-test-user", 
                         "everyone leaves me no one wants me am i not worth trying?", 
                         client)
    elapsed = time.perf_counter() - start
    print(f"\n--- Crisis message result ---")
    print(f"Time taken: {elapsed:.2f}s")
    print(f"Safety level: {result['safety_level']}")
    print(f"Reply: {result['reply'][:100]}...")

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("Saturating the Sarvam rate limiter with 20 casual messages...")
        await saturate(client)
        print("Saturation done. Sending crisis message immediately...")
        await send_crisis(client)

asyncio.run(main())