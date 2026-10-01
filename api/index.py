"""Vercel entry point. Persistent records live in PostgreSQL, never /tmp."""
import os
import sys
import threading
import urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database
import crm
import config
from server import StyleLuxRequestHandler

_ready = False
_lock = threading.Lock()

class handler(StyleLuxRequestHandler):
    def prepare(self):
        global _ready
        route = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(route.query)
        destination = query.pop('_route', [None])[0]
        if destination is not None:
            self.path = '/api/' + destination + ('?' + urllib.parse.urlencode(query, doseq=True) if query else '')
        try:
            with _lock:
                if not _ready:
                    config.get_or_create_admin_config()
                    database.init_db()
                    crm.init_crm()
                    _ready = True
            return True
        except Exception:
            self.send_json({'error': 'O serviço de marcações está temporariamente indisponível. Contacte a Style Lux.'}, 503)
            return False

    def do_GET(self):
        if self.prepare(): super().do_GET()

    def do_POST(self):
        if self.prepare(): super().do_POST()
