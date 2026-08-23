import asyncio
import httpx

async def send(i, user_id):
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                f"http://localhost:8000/chat/{user_id}",
                json={"message": "hi", "user_id": user_id}
            )
            print(f"Request {i} ({user_id}): Status {r.status_code}")
        except httpx.ReadTimeout:
            print(f"Request {i} ({user_id}): Timed out")

async def main():
    tasks = []
    # 12 requests for test-user — should trip the 10/min limit
    for i in range(1, 13):
        tasks.append(send(i, "test-user"))
    # 3 requests for a totally different user — should NOT be blocked
    for i in range(1, 4):
        tasks.append(send(f"other-{i}", "different-user"))
    await asyncio.gather(*tasks)

asyncio.run(main())