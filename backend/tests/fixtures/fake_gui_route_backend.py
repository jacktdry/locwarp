"""Hardware-free LocWarp GUI route lifecycle fixture.

Run only when real LocWarp is stopped (uses 127.0.0.1:8777). This fake
backend NEVER imports device, usbmux or GPS modules. It exposes two synthetic
"iPhones" and a continuously moving route, plus a test-only completion switch.
Every unexpected /api write receives HTTP 403 and is recorded, not applied.

Start: .venv/bin/python backend/tests/fixtures/fake_gui_route_backend.py
Inspect: curl http://127.0.0.1:8777/_uat/state
Finish fake route (only while GUI closed): curl http://127.0.0.1:8777/_uat/stop-route
"""
import asyncio
from collections import Counter
import math
import time

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

A, B = 'uat-fake-iphone-a', 'uat-fake-iphone-b'
BOOT = time.monotonic()
STATE = {'phase': 'moving'}
HTTP = Counter()
WRITES = []
WS_MESSAGES = 0
ROUTES = {
    A: [
        {'lat': 25.0124, 'lng': 121.5147},
        {'lat': 25.0124, 'lng': 121.5171},
        {'lat': 25.0141, 'lng': 121.5171},
        {'lat': 25.0141, 'lng': 121.5147},
    ],
    B: [
        {'lat': 25.0116, 'lng': 121.5130},
        {'lat': 25.0116, 'lng': 121.5151},
        {'lat': 25.0133, 'lng': 121.5151},
        {'lat': 25.0133, 'lng': 121.5130},
    ],
}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


def seconds():
    return max(0, time.monotonic() - BOOT)


def position(udid):
    route = ROUTES[udid]
    segment = (seconds() / 18.0 + (0.3 if udid == B else 0)) % len(route)
    index = math.floor(segment)
    fraction = segment - index
    start, end = route[index], route[(index + 1) % len(route)]
    return {
        key: round(start[key] + (end[key] - start[key]) * fraction, 7)
        for key in ('lat', 'lng')
    }


def snapshot():
    active = STATE['phase'] == 'moving'
    return {
        'primary_udid': A,
        'devices': {
            udid: {
                'state': 'looping' if active else 'idle',
                'simulation_kind': 'start_loop' if active else None,
                'current_position': position(udid) if active else None,
                'destination': ROUTES[udid][1] if active else None,
                'route_path': ROUTES[udid] if active else [],
                'waypoints': ROUTES[udid] if active else [],
                'progress': round((seconds() / 72) % 1, 4),
                'speed_mps': 1.7,
                'eta_seconds': 30,
                'distance_remaining': float(150 - int(seconds() % 150)),
                'distance_traveled': float(int(seconds() % 150)),
                'segment_index': int(seconds() / 18) % 4,
                'lap_count': int(seconds() / 72),
                'is_paused': False,
            }
            for udid in (A, B)
        },
    }


def device_list():
    return [
        {
            'udid': udid,
            'name': f'Fake {letter} (GUI UAT)',
            'ios_version': '27.0.1',
            'connection_type': transport,
            'is_connected': True,
        }
        for udid, letter, transport in ((A, 'A', 'Network'), (B, 'B', 'USB'))
    ]


@app.get('/api/location/snapshot')
def get_snapshot():
    HTTP['snapshot'] += 1
    return snapshot()


@app.get('/api/device/list')
def get_devices():
    HTTP['device/list'] += 1
    return device_list()


@app.get('/api/device/auto-connect')
def get_auto_connect():
    HTTP['auto-connect'] += 1
    return {'approved_udids': [], 'max_devices': 3}


@app.get('/_uat/state')
def get_state():
    return {
        'elapsed': round(seconds(), 1),
        'phase': STATE['phase'],
        'counts': dict(HTTP),
        'websocket_samples': WS_MESSAGES,
        'rejected_write_requests': list(WRITES),
    }


@app.get('/_uat/stop-route')
def finish_fake_route():
    STATE['phase'] = 'idle'
    return {'phase': 'idle'}


@app.get('/api/{path:path}')
def read_only_stub(path: str):
    HTTP['stub:' + path] += 1
    if path == 'bookmarks/ui-state':
        return {'expanded_categories': []}
    if path in (
        'routes', 'route/saved', 'route/categories', 'route/category',
        'recent', 'bookmarks/categories', 'bookmarks',
    ):
        return []
    if path in ('location/cooldown/status', 'location/status'):
        return {'enabled': False, 'remaining_seconds': 0}
    return {}


@app.api_route('/api/{path:path}', methods=['POST', 'PUT', 'PATCH', 'DELETE'])
async def reject_device_writes(path: str, request: Request):
    WRITES.append({'method': request.method, 'path': '/api/' + path})
    return JSONResponse({'error': 'FAKE_BACKEND_MUTATIONS_FORBIDDEN'}, status_code=403)


@app.websocket('/ws/status')
async def fake_positions(websocket: WebSocket):
    global WS_MESSAGES
    await websocket.accept()
    try:
        while True:
            await asyncio.sleep(0.6)
            if STATE['phase'] == 'moving':
                for udid in (A, B):
                    await websocket.send_json({
                        'type': 'position_update',
                        'data': {
                            'udid': udid,
                            **position(udid),
                            'progress': (seconds() / 72) % 1,
                            'eta_seconds': 30,
                            'distance_remaining': 150 - seconds() % 150,
                            'distance_traveled': seconds() % 150,
                            'speed_mps': 1.7,
                        },
                    })
            WS_MESSAGES += 1
    except Exception:
        # The renderer disconnects on window.close(); no hardware to recover.
        pass


if __name__ == '__main__':
    print('LocWarp fake GUI backend: 127.0.0.1:8777 (NO iPhone/GPS access)', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8777, log_level='error', access_log=False)
