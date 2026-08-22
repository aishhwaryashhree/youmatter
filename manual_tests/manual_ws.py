import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/ws/chat/test-ws-user"
    async with websockets.connect(uri) as ws:
        # Send a message in the format ws_chat expects
        await ws.send(json.dumps({"message": "hi", "consent": None}))

        # Keep receiving until we get the final safety_result event
        while True:
            raw = await ws.recv()
            event = json.loads(raw)
            if event["type"] == "token":
                print(event["content"], end="", flush=True)
            elif event["type"] == "safety_result":
                print("\n\n--- safety_result ---")
                print(event)
                break

asyncio.run(test_ws())