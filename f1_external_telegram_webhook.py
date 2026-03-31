#!/usr/bin/env python3
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get('F1_EXTERNAL_WEBHOOK_HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT') or os.environ.get('F1_EXTERNAL_WEBHOOK_PORT', '8780'))
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
APPROVAL_EVENT_URL = os.environ.get('F1_APPROVAL_EVENT_URL', '').strip()
EVENTS_FILE = Path(os.environ.get('F1_EVENTS_FILE', '/tmp/f1_approval_events.json'))
FORWARD_MODE = os.environ.get('F1_APPROVAL_FORWARD_MODE', 'store').strip().lower()


def load_events():
    if not EVENTS_FILE.exists():
        return {'events': []}
    try:
        return json.loads(EVENTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'events': []}


def save_events(data):
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def append_event(payload):
    data = load_events()
    payload['received_at'] = datetime.now(timezone.utc).isoformat()
    data.setdefault('events', []).append(payload)
    save_events(data)
    return payload


def api_post(path, data):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{path}'
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method='POST')
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def parse_callback_data(data):
    parts = (data or '').split('|')
    if len(parts) < 4:
        return None
    if parts[0] not in ('approval', 'f1'):
        return None
    return {
        'stage': parts[1] or '',
        'action': parts[2] or '',
        'task_id': parts[3] or '',
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            return self._json(200, {'ok': True, 'forward_mode': FORWARD_MODE})
        if parsed.path == '/approval/pending':
            qs = parse_qs(parsed.query)
            task_id = (qs.get('task_id') or [''])[0]
            data = load_events()
            events = data.get('events', [])
            if task_id:
                events = [e for e in events if e.get('task_id') == task_id]
            return self._json(200, {'ok': True, 'events': events})
        return self._json(404, {'error': 'not found'})

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode() or '{}')
        except Exception:
            return self._json(400, {'error': 'invalid json'})

        if self.path == '/approval/event':
            event = append_event(payload)
            return self._json(200, {'ok': True, 'event': event})

        if self.path != '/telegram/callback':
            return self._json(404, {'error': 'not found'})

        cq = payload.get('callback_query') or {}
        parsed = parse_callback_data(cq.get('data'))
        if not parsed:
            return self._json(400, {'error': 'invalid callback_data'})
        if not BOT_TOKEN:
            return self._json(500, {'error': 'missing TELEGRAM_BOT_TOKEN'})

        action = parsed['action']
        answer_text = '✅ 已通过' if action == 'approve' else '🔁 已标记重做'
        answer_result = api_post('answerCallbackQuery', {
            'callback_query_id': cq.get('id', ''),
            'text': answer_text,
        })
        event_payload = {
            **parsed,
            'source': 'telegram_external_webhook',
            'callback_query_id': cq.get('id', ''),
            'raw_data': cq.get('data', ''),
        }
        if FORWARD_MODE == 'forward' and APPROVAL_EVENT_URL:
            event_result = post_json(APPROVAL_EVENT_URL, event_payload)
        else:
            event_result = {'ok': True, 'stored': True, 'event': append_event(event_payload)}
        return self._json(200, {
            'ok': True,
            'answer_result': answer_result,
            'event_result': event_result,
        })


if __name__ == '__main__':
    server = HTTPServer((HOST, PORT), Handler)
    print(f'F1 external Telegram webhook listening on http://{HOST}:{PORT}', flush=True)
    server.serve_forever()
