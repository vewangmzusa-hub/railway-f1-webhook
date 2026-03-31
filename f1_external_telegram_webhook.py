#!/usr/bin/env python3
import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = os.environ.get('F1_EXTERNAL_WEBHOOK_HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT') or os.environ.get('F1_EXTERNAL_WEBHOOK_PORT', '8780'))
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
APPROVAL_EVENT_URL = os.environ.get('F1_APPROVAL_EVENT_URL', '').strip()


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
        if self.path == '/health':
            return self._json(200, {'ok': True})
        return self._json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path != '/telegram/callback':
            return self._json(404, {'error': 'not found'})

        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode() or '{}')
        except Exception:
            return self._json(400, {'error': 'invalid json'})

        msg = payload.get('message') or {}
        if msg:
            chat = msg.get('chat') or {}
            from_user = msg.get('from') or {}
            record = {
                'ok': True,
                'type': 'message',
                'chat_id': chat.get('id'),
                'text': msg.get('text', ''),
                'from': {
                    'id': from_user.get('id'),
                    'username': from_user.get('username'),
                }
            }
            print(json.dumps(record, ensure_ascii=False), flush=True)
            return self._json(200, record)

        cq = payload.get('callback_query') or {}
        parsed = parse_callback_data(cq.get('data'))
        if not parsed:
            return self._json(400, {'error': 'invalid callback_data'})
        if not BOT_TOKEN:
            return self._json(500, {'error': 'missing TELEGRAM_BOT_TOKEN'})
        if not APPROVAL_EVENT_URL:
            return self._json(500, {'error': 'missing F1_APPROVAL_EVENT_URL'})

        action = parsed['action']
        answer_text = '✅ 已通过' if action == 'approve' else '🔁 已标记重做'
        answer_result = api_post('answerCallbackQuery', {
            'callback_query_id': cq.get('id', ''),
            'text': answer_text,
        })
        event_result = post_json(APPROVAL_EVENT_URL, {
            **parsed,
            'source': 'telegram_external_webhook',
            'callback_query_id': cq.get('id', ''),
            'raw_data': cq.get('data', ''),
        })
        return self._json(200, {
            'ok': True,
            'answer_result': answer_result,
            'event_result': event_result,
        })


if __name__ == '__main__':
    server = HTTPServer((HOST, PORT), Handler)
    print(f'F1 external Telegram webhook listening on http://{HOST}:{PORT}', flush=True)
    server.serve_forever()
