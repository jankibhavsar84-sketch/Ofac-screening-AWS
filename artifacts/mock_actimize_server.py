import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0') or '0')
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            payload = {}
        party_key = payload.get('partyKey', '') if isinstance(payload, dict) else ''

        if self.path.endswith('/entity-screenings'):
            response = {
                'body': {
                    'message': 'NM',
                    'partyKey': party_key,
                    'status': 'Success',
                    'timestamp': '2026-05-11T19:30:00Z',
                },
                'statusCode': 200,
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return

        self.send_response(404)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"message":"not found"}')

    def log_message(self, fmt, *args):
        return

if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 19000), Handler).serve_forever()
