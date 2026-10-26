import asyncio
import json
import os
import sys
from aiortc import RTCIceServer, AudioStreamTrack, RTCPeerConnection, RTCConfiguration, RTCSessionDescription

# Offline integration fixture: no user credentials or AI provider calls.
if sys.argv[1] == 'server':
    import uvicorn
    import openfolio_worker.server as server
    os.environ.update(OPENFOLIO_SKIP_CHECKS='1',LLM_MODEL='smoke',LLM_API_KEY='smoke',DEEPGRAM_API_KEY='smoke')
    async def fake_conversation(connection, *args, **kwargs):
        connection.replace_audio_track(AudioStreamTrack())
        @connection.event_handler('app-message')
        async def echo(conn, message):
            conn.send_app_message({'type':'smoke-echo', 'payload':message})
        await connection.connect()
        await asyncio.Future()
    server.run_conversation = fake_conversation
    uvicorn.run(server.create_app(), host='0.0.0.0', port=7860)
else:
    import httpx
    async def main():
        async with httpx.AsyncClient() as c:
            response=await c.get('http://127.0.0.1:17862/v1/personas/demo/ice-servers')
            response.raise_for_status()
            ice = [RTCIceServer(**s) for s in response.json()['iceServers']]
        pc=RTCPeerConnection(RTCConfiguration(iceServers=ice))
        pc.addTrack(AudioStreamTrack())
        dc=pc.createDataChannel('chat')
        echoed=asyncio.Event(); audio=asyncio.Event()
        @dc.on('open')
        def opened(): dc.send(json.dumps({'type':'smoke-request'}))
        @dc.on('message')
        def message(data):
            if 'smoke-echo' in str(data): echoed.set()
        @pc.on('track')
        def track(track):
            async def receive():
                frame=await track.recv()
                assert frame.samples > 0
                audio.set()
            asyncio.create_task(receive())
        try:
            await pc.setLocalDescription(await pc.createOffer())
            async with httpx.AsyncClient(timeout=20) as c:
                response=await c.post('http://127.0.0.1:17862/v1/personas/demo/offer',json={'sdp':pc.localDescription.sdp,'type':'offer'})
                response.raise_for_status(); answer=response.json()
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
            await asyncio.wait_for(asyncio.gather(echoed.wait(),audio.wait()),20)
            print('PASS: WebRTC data-channel roundtrip and synthetic audio from Docker to host')
        finally: await pc.close()
    asyncio.run(main())
