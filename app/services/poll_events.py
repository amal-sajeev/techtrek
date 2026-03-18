import asyncio
import json
from collections import defaultdict

_listeners: dict[int, list[asyncio.Queue]] = defaultdict(list)
_user_listeners: dict[int, list[asyncio.Queue]] = defaultdict(list)


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
    msg = json.dumps(data)
    for q in list(_listeners.get(session_id, [])):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def subscribe_user(user_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _user_listeners[user_id].append(q)
    return q


def unsubscribe_user(user_id: int, q: asyncio.Queue):
    try:
        _user_listeners[user_id].remove(q)
    except ValueError:
        pass
    if not _user_listeners[user_id]:
        del _user_listeners[user_id]


def publish_to_users(user_ids: list[int], data: dict):
    msg = json.dumps(data)
    for uid in user_ids:
        for q in list(_user_listeners.get(uid, [])):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
