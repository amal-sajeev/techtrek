import asyncio
from collections import defaultdict

_listeners: dict[int, list[asyncio.Queue]] = defaultdict(list)


def subscribe(session_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _listeners[session_id].append(q)
    return q


def unsubscribe(session_id: int, q: asyncio.Queue):
    try:
        _listeners[session_id].remove(q)
    except ValueError:
        pass
    if not _listeners[session_id]:
        del _listeners[session_id]


async def publish(session_id: int, data: dict):
    import json
    msg = json.dumps(data)
    for q in list(_listeners.get(session_id, [])):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass
