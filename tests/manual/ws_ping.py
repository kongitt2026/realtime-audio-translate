import asyncio, json, websockets
async def main():
    try:
        async with websockets.connect("ws://127.0.0.1:8790/ws/audio", open_timeout=8) as ws:
            print("WS_CONNECT_OK")
    except Exception as e:
        print("WS_FAIL:", type(e).__name__, e)
asyncio.run(main())
