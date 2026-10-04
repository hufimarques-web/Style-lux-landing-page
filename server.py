import os
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

import database
import config
import crm

HOST = os.getenv('HOST', '127.0.0.1')
PORT = int(os.getenv('PORT', 8080))
PUBLIC_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public'))
MAX_BODY_SIZE = 65536  # 64 KB limit for JSON payloads

class StyleLuxRequestHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {self.command} {self.path} -> {args[0]}")

    def send_json(self, data, status_code=200, headers_extra=None):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if headers_extra:
            for k, v in headers_extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def validate_same_origin(self):
        # Allow requests with matching origin/referer or internal requests
        origin = self.headers.get('Origin')
        referer = self.headers.get('Referer')
        host_header = self.headers.get('Host', f'{HOST}:{PORT}')

        if origin:
            parsed_origin = urllib.parse.urlparse(origin)
            if parsed_origin.netloc != host_header and parsed_origin.netloc not in [host_header]:
                return False
        if referer:
            parsed_ref = urllib.parse.urlparse(referer)
            if parsed_ref.netloc != host_header and parsed_ref.netloc not in [host_header]:
                return False
        return True

    def parse_json_body(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            return None, 'Tamanho do pedido inválido.'
        if content_length < 0:
            return None, 'Tamanho do pedido inválido.'
        if content_length > MAX_BODY_SIZE:
            return None, 'Payload excede o tamanho máximo permitido (64KB).'
        if content_length <= 0:
            return {}, None
        
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode('utf-8'))
            if not isinstance(body, dict):
                return None, 'O pedido deve ser um objeto JSON.'
            return body, None
        except Exception:
            return None, 'JSON malformatado ou inválido.'

    def get_auth_token(self):
        # 1. Check HTTP Cookie
        cookie_header = self.headers.get('Cookie', '')
        if cookie_header:
            cookies = urllib.parse.parse_qs(cookie_header.replace('; ', '&'))
            if 'admin_token' in cookies and cookies['admin_token']:
                return cookies['admin_token'][0]
        
        # 2. Check X-Admin-Token header
        custom_header = self.headers.get('X-Admin-Token', '').strip()
        if custom_header:
            return custom_header

        # 3. Check Authorization header
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth[7:].strip()

        return None

    def require_auth(self):
        token = self.get_auth_token()
        if not token or not database.verify_session(token):
            self.send_json({'error': 'Não autorizado. Por favor inicie sessão no painel.'}, 401)
            return False
        return True

    def serve_static(self, filepath):
        try:
            real_target = os.path.realpath(filepath)
            # Ensure path is strictly inside PUBLIC_DIR using commonpath
            if os.path.commonpath([PUBLIC_DIR, real_target]) != PUBLIC_DIR or not os.path.exists(real_target) or os.path.isdir(real_target):
                self.send_response(404)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<h1>404 - Pagina nao encontrada</h1>")
                return

            ext = os.path.splitext(real_target)[1].lower()
            mime_types = {
                '.html': 'text/html; charset=utf-8',
                '.css': 'text/css; charset=utf-8',
                '.js': 'application/javascript; charset=utf-8',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml',
                '.ico': 'image/x-icon',
                '.json': 'application/json; charset=utf-8'
            }
            content_type = mime_types.get(ext, 'application/octet-stream')

            with open(real_target, 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(500)
            self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if path == '/api/admin/crm':
            if not self.require_auth(): return
            today = database.get_lisbon_now().date().isoformat()
            try:
                result = crm.snapshot(query_params.get('from',[today[:7]+'-01'])[0], query_params.get('to',[today])[0])
                self.send_json(result)
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
            return

        # PUBLIC AVAILABILITY API
        if path == '/api/availability':
            date_param = query_params.get('date', [''])[0]
            if not date_param:
                self.send_json({'error': 'Parâmetro ?date=AAAA-MM-DD é obrigatório.'}, 400)
                return
            result = database.get_public_availability(date_param)
            status_code = 400 if 'error' in result else 200
            self.send_json(result, status_code)
            return

        # ADMIN BOOKINGS LIST (PROTECTED)
        if path == '/api/admin/bookings':
            if not self.require_auth():
                return
            status_filter = query_params.get('status', [None])[0]
            date_filter = query_params.get('date', [None])[0]
            bookings = database.get_all_bookings(status_filter, date_filter)
            self.send_json({'success': True, 'bookings': bookings})
            return

        # ADMIN BLOCKED SLOTS LIST (PROTECTED)
        if path == '/api/admin/blocked-slots':
            if not self.require_auth():
                return
            date_filter = query_params.get('date', [None])[0]
            blocked = database.get_blocked_slots(date_filter)
            self.send_json({'success': True, 'blocked_slots': blocked})
            return

        # ADMIN SETTINGS (PROTECTED)
        if path == '/api/admin/settings':
            if not self.require_auth():
                return
            settings = database.get_settings()
            self.send_json({'success': True, 'settings': settings})
            return

        # STATIC ROUTING
        if path == '/' or path == '/index.html':
            self.serve_static(os.path.join(PUBLIC_DIR, 'index.html'))
            return
        elif path in ('/admin', '/admin/', '/admin/index.html', '/crm', '/crm/'):
            self.serve_static(os.path.join(PUBLIC_DIR, 'admin.html'))
            return
        else:
            relative_path = path.lstrip('/')
            self.serve_static(os.path.join(PUBLIC_DIR, relative_path))
            return

    def do_POST(self):
        # 1. Enforce Same-Origin Check
        if not self.validate_same_origin():
            self.send_json({'error': 'Origem da requisição não permitida.'}, 403)
            return

        # 2. Require Content-Type application/json
        ct = self.headers.get('Content-Type', '')
        if not ct.startswith('application/json'):
            self.send_json({'error': 'Cabeçalho Content-Type deve ser application/json.'}, 400)
            return

        # 3. Parse JSON body safely
        body, parse_err = self.parse_json_body()
        if parse_err:
            self.send_json({'error': parse_err}, 400)
            return

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        client_ip = self.client_address[0]

        crm_actions = {
            '/api/admin/wax-requests/update': crm.update_wax_request,
            '/api/admin/wax-requests/schedule': crm.schedule_wax_request,
            '/api/admin/crm/details': crm.update_details,
            '/api/admin/crm/spend': crm.save_spend,
            '/api/admin/crm/terms': crm.save_terms,
            '/api/admin/crm/reschedule': crm.reschedule,
        }
        if path in crm_actions:
            if not self.require_auth(): return
            try:
                crm_actions[path](body)
                self.send_json({'success': True})
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
            return

        if path == '/api/wax-requests':
            try:
                result = crm.create_wax_request(body)
                self.send_json({'success': True, 'request': result})
            except ValueError as exc:
                self.send_json({'error': str(exc)}, 400)
            return

        # PUBLIC BOOKING CREATION
        if path == '/api/bookings':
            if body.get('service_key') in crm.WAX_SERVICES:
                self.send_json({'error': 'A lavagem exterior deve ser enviada como pedido de contacto, sem marcação automática.'}, 400)
                return
            service_key = body.get('service_key', '')
            booking_date = body.get('booking_date', '')
            time_slot = body.get('time_slot', '')
            customer_name = body.get('customer_name', '')
            customer_phone = body.get('customer_phone', '')
            car_model = body.get('car_model', '')
            utm_source = body.get('utm_source', '')
            utm_medium = body.get('utm_medium', '')
            utm_campaign = body.get('utm_campaign', '')

            res = database.create_booking(
                service_key=service_key,
                booking_date=booking_date,
                time_slot=time_slot,
                customer_name=customer_name,
                customer_phone=customer_phone,
                car_model=car_model,
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign
            )

            status_code = 200 if res.get('success') else 400
            self.send_json(res, status_code)
            return

        # ADMIN LOGIN
        if path == '/api/admin/login':
            if not database.check_brute_force(client_ip):
                self.send_json({'success': False, 'error': 'Demasiadas tentativas falhadas. Por favor aguarde 15 minutos.'}, 429)
                return

            username = body.get('username', '')
            password = body.get('password', '')

            if not isinstance(username, str) or not isinstance(password, str) or len(password) > 256:
                self.send_json({'success': False, 'error': 'Credenciais inválidas.'}, 400)
                return

            cfg = config.get_or_create_admin_config()
            if config.authenticate(username, password):
                database.clear_failed_logins(client_ip)
                token = database.create_session()
                # Set HttpOnly, SameSite cookie
                cookie_header = f"admin_token={token}; HttpOnly; SameSite=Strict; Path=/" + ("; Secure" if os.getenv("VERCEL") else "")
                self.send_json({'success': True, 'token': token}, status_code=200, headers_extra={'Set-Cookie': cookie_header})
            else:
                database.record_failed_login(client_ip)
                self.send_json({'success': False, 'error': 'Credenciais incorretas.'}, 401)
            return

        # ADMIN LOGOUT
        if path == '/api/admin/logout':
            token = self.get_auth_token()
            if token:
                database.delete_session(token)
            cookie_header = "admin_token=; HttpOnly; SameSite=Strict; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
            self.send_json({'success': True}, headers_extra={'Set-Cookie': cookie_header})
            return

        # ADMIN UPDATE BOOKING STATUS
        if path == '/api/admin/bookings/status':
            if not self.require_auth():
                return
            booking_id = body.get('id')
            new_status = body.get('status')
            if not booking_id or not new_status:
                self.send_json({'error': 'Parâmetros id e status são obrigatórios.'}, 400)
                return
            ok, msg = database.update_booking_status(booking_id, new_status)
            status_code = 200 if ok else 400
            self.send_json({'success': ok, 'message': msg}, status_code)
            return

        # ADMIN MANUAL BOOKING CREATION
        if path == '/api/admin/bookings/create':
            if not self.require_auth():
                return
            res = database.create_booking(
                service_key=body.get('service_key', ''),
                booking_date=body.get('booking_date', ''),
                time_slot=body.get('time_slot', ''),
                customer_name=body.get('customer_name', ''),
                customer_phone=body.get('customer_phone', ''),
                car_model=body.get('car_model', ''),
                utm_source='admin_manual',
                utm_medium='phone',
                utm_campaign='direct'
            )
            status_code = 200 if res.get('success') else 400
            self.send_json(res, status_code)
            return

        # ADMIN BLOCK SLOT / DAY
        if path == '/api/admin/block-slot':
            if not self.require_auth():
                return
            b_date = body.get('booking_date')
            t_slot = body.get('time_slot')
            reason = body.get('reason', 'Bloqueado pelo administrador')
            if not b_date or not t_slot:
                self.send_json({'error': 'Data e horário são obrigatórios.'}, 400)
                return
            ok, msg = database.block_slot(b_date, t_slot, reason)
            status_code = 200 if ok else 400
            self.send_json({'success': ok, 'message': msg}, status_code)
            return

        # ADMIN UNBLOCK SLOT / DAY
        if path == '/api/admin/unblock-slot':
            if not self.require_auth():
                return
            b_date = body.get('booking_date')
            t_slot = body.get('time_slot')
            if not b_date or not t_slot:
                self.send_json({'error': 'Data e horário são obrigatórios.'}, 400)
                return
            ok, msg = database.unblock_slot(b_date, t_slot)
            status_code = 200 if ok else 400
            self.send_json({'success': ok, 'message': msg}, status_code)
            return

        # ADMIN UPDATE SETTINGS
        if path == '/api/admin/settings':
            if not self.require_auth():
                return
            daily_limit = body.get('daily_limit')
            available_slots = body.get('available_slots')
            ok, msg = database.update_settings(daily_limit=daily_limit, available_slots=available_slots)
            status_code = 200 if ok else 400
            self.send_json({'success': ok, 'message': msg, 'settings': database.get_settings()}, status_code)
            return

        self.send_json({'error': 'Endpoint não encontrado.'}, 404)

def run_server():
    database.init_db()
    crm.init_crm()
    admin_cfg = config.get_or_create_admin_config()
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, StyleLuxRequestHandler)
    print(f"==================================================")
    print(f" Style Lux Auto Details - Servidor Local ")
    print(f" Servidor em execução em http://{HOST}:{PORT}")
    print(f" Painel Admin em http://{HOST}:{PORT}/admin")
    print(f" Ficheiro de credenciais: data/admin_config.json")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nA encerrar servidor...")
        httpd.server_close()

if __name__ == '__main__':
    run_server()
