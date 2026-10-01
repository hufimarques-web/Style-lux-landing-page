import os
import re
import sqlite3
import secrets
import json
from datetime import datetime, timezone, timedelta

try:
    import zoneinfo
    LISBON_TZ = zoneinfo.ZoneInfo("Europe/Lisbon")
except Exception:
    LISBON_TZ = timezone(timedelta(hours=1))

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DB_PATH = os.path.join(DATA_DIR, 'stylelux.db')

SERVICES = {
    'premium': {
        'name': 'Lavagem Premium',
        'price': 80.0
    },
    'completa': {
        'name': 'Lavagem Premium Completa',
        'price': 130.0
    }
}

DEFAULT_SLOTS = ["09:00", "11:00", "13:00", "15:00", "17:00"]
DEFAULT_DAILY_LIMIT = 5

def get_db_connection():
    url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    if url:
        from postgres_storage import Connection
        return Connection(url)
    if os.getenv('VERCEL'):
        raise RuntimeError('Configure DATABASE_URL para guardar as marcações online.')
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference TEXT UNIQUE NOT NULL,
        service_key TEXT NOT NULL,
        price REAL NOT NULL,
        booking_date TEXT NOT NULL,
        time_slot TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        car_model TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pendente',
        utm_source TEXT DEFAULT '',
        utm_medium TEXT DEFAULT '',
        utm_campaign TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS blocked_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_date TEXT NOT NULL,
        time_slot TEXT NOT NULL,
        reason TEXT DEFAULT 'Bloqueado pelo administrador',
        UNIQUE(booking_date, time_slot)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS failed_logins (
        ip TEXT PRIMARY KEY,
        attempts INTEGER NOT NULL DEFAULT 1,
        last_attempt TEXT NOT NULL
    )
    ''')
    
    cursor.execute("INSERT INTO settings (key, value) VALUES ('daily_limit', ?) ON CONFLICT(key) DO NOTHING", (str(DEFAULT_DAILY_LIMIT),))
        
    cursor.execute("INSERT INTO settings (key, value) VALUES ('available_slots', ?) ON CONFLICT(key) DO NOTHING", (json.dumps(DEFAULT_SLOTS),))
        
    conn.commit()
    conn.close()

def get_lisbon_now():
    return datetime.now(LISBON_TZ)

def validate_canonical_date(date_str):
    if not isinstance(date_str, str) or not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return None
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d').date()
        if dt.strftime('%Y-%m-%d') != date_str:
            return None
        return dt
    except ValueError:
        return None

def validate_time_slot(slot_str):
    if not isinstance(slot_str, str):
        return False
    if slot_str == '*':
        return True
    if not re.match(r'^\d{2}:\d{2}$', slot_str):
        return False
    try:
        h, m = map(int, slot_str.split(':'))
        return 0 <= h <= 23 and 0 <= m <= 59
    except ValueError:
        return False

def get_settings(conn=None):
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    
    if close_conn:
        conn.close()
    
    settings = {
        'daily_limit': DEFAULT_DAILY_LIMIT,
        'available_slots': DEFAULT_SLOTS
    }
    for r in rows:
        if r['key'] == 'daily_limit':
            try:
                settings['daily_limit'] = int(r['value'])
            except ValueError:
                pass
        elif r['key'] == 'available_slots':
            try:
                settings['available_slots'] = json.loads(r['value'])
            except Exception:
                pass
    return settings

def update_settings(daily_limit=None, available_slots=None):
    if daily_limit is not None:
        try:
            val = int(daily_limit)
            if val < 1 or val > 50:
                return False, 'O limite diário de lavagens deve ser um número inteiro entre 1 e 50.'
            daily_limit = val
        except (ValueError, TypeError):
            return False, 'Limite diário inválido.'

    if available_slots is not None:
        if not isinstance(available_slots, list) or len(available_slots) == 0:
            return False, 'Deve fornecer pelo menos 1 horário disponível.'
        cleaned_slots = []
        for s in available_slots:
            if not validate_time_slot(s) or s == '*':
                return False, f'Horário {s} inválido. Deve ter o formato HH:MM.'
            h, m = map(int, s.split(':'))
            if h < 9 or (h > 19 or (h == 19 and m > 0)):
                return False, f'O horário {s} está fora do expediente (09:00 - 19:00).'
            if s not in cleaned_slots:
                cleaned_slots.append(s)
        cleaned_slots.sort()
        available_slots = cleaned_slots

    conn = get_db_connection()
    cursor = conn.cursor()
    if daily_limit is not None:
        cursor.execute("INSERT INTO settings (key, value) VALUES ('daily_limit', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(daily_limit),))
    if available_slots is not None:
        cursor.execute("INSERT INTO settings (key, value) VALUES ('available_slots', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(available_slots),))
    conn.commit()
    conn.close()
    return True, 'Configurações atualizadas com sucesso.'

def get_public_availability(date_str):
    target_date = validate_canonical_date(date_str)
    if not target_date:
        return {'error': 'Data em formato inválido. Utilize o formato canónico AAAA-MM-DD.'}

    lisbon_now = get_lisbon_now()

    if target_date < lisbon_now.date():
        return {
            'date': date_str,
            'is_valid_date': False,
            'reason': 'Data no passado não é permitida.',
            'slots': [],
            'remaining_capacity': 0
        }

    if target_date.weekday() == 6:  # Sunday
        return {
            'date': date_str,
            'is_valid_date': False,
            'reason': 'Ao domingo o estabelecimento está encerrado. Funcionamos de Segunda a Sábado, 09h–19h.',
            'slots': [],
            'remaining_capacity': 0
        }

    conn = get_db_connection()
    settings = get_settings(conn)
    all_slots = settings['available_slots']
    daily_limit = settings['daily_limit']

    cursor = conn.cursor()

    cursor.execute(
        "SELECT time_slot FROM bookings WHERE booking_date = ? AND status != 'Cancelada'",
        (date_str,)
    )
    booked_slots = {row['time_slot'] for row in cursor.fetchall()}

    cursor.execute(
        "SELECT time_slot FROM blocked_slots WHERE booking_date = ?",
        (date_str,)
    )
    blocked_slots = {row['time_slot'] for row in cursor.fetchall()}

    conn.close()

    day_is_fully_blocked = ('*' in blocked_slots)

    total_active = len(booked_slots)
    remaining_capacity = 0 if day_is_fully_blocked else max(0, daily_limit - total_active)

    slot_details = []
    is_today = (target_date == lisbon_now.date())

    for slot in all_slots:
        is_available = True
        status_reason = 'Disponível'

        if day_is_fully_blocked:
            is_available = False
            status_reason = 'Dia totalmente bloqueado pelo administrador'
        elif remaining_capacity <= 0 and slot not in booked_slots:
            is_available = False
            status_reason = 'Limite diário de lavagens atingido'
        elif slot in booked_slots:
            is_available = False
            status_reason = 'Horário já reservado'
        elif slot in blocked_slots:
            is_available = False
            status_reason = 'Horário indisponível'
        elif is_today:
            slot_hour, slot_minute = map(int, slot.split(':'))
            slot_time = lisbon_now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
            if slot_time <= lisbon_now:
                is_available = False
                status_reason = 'Horário já decorrido'

        slot_details.append({
            'time': slot,
            'available': is_available,
            'reason': status_reason
        })

    return {
        'date': date_str,
        'is_valid_date': True,
        'daily_limit': daily_limit,
        'remaining_capacity': remaining_capacity,
        'day_blocked': day_is_fully_blocked,
        'slots': slot_details
    }

def create_booking(service_key, booking_date, time_slot, customer_name, customer_phone, car_model, utm_source='', utm_medium='', utm_campaign=''):
    if not isinstance(service_key, str) or service_key not in SERVICES:
        return {'success': False, 'error': 'Serviço selecionado é inválido.'}

    service_info = SERVICES[service_key]
    price = service_info['price']

    target_date = validate_canonical_date(booking_date)
    if not target_date:
        return {'success': False, 'error': 'Data em formato inválido. Utilize AAAA-MM-DD.'}

    if not validate_time_slot(time_slot) or time_slot == '*':
        return {'success': False, 'error': 'Horário de entrega inválido.'}

    if not isinstance(customer_name, str) or len(customer_name.strip()) < 2 or len(customer_name) > 100:
        return {'success': False, 'error': 'Por favor introduza o seu nome completo (máx. 100 caracteres).'}

    phone_clean = customer_phone.strip() if isinstance(customer_phone, str) else ''
    if not re.match(r'^\+?[0-9\s\-]{9,20}$', phone_clean):
        return {'success': False, 'error': 'Por favor introduza um número de telemóvel válido.'}

    if not isinstance(car_model, str) or len(car_model.strip()) < 2 or len(car_model) > 100:
        return {'success': False, 'error': 'Por favor introduza a marca e modelo da viatura.'}

    utm_source = str(utm_source)[:50] if utm_source else ''
    utm_medium = str(utm_medium)[:50] if utm_medium else ''
    utm_campaign = str(utm_campaign)[:50] if utm_campaign else ''

    lisbon_now = get_lisbon_now()

    if target_date < lisbon_now.date():
        return {'success': False, 'error': 'Não é possível efetuar marcações para datas passadas.'}

    if target_date.weekday() == 6:
        return {'success': False, 'error': 'Ao domingo o estabelecimento está encerrado.'}

    conn = get_db_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cursor = conn.cursor()

        settings = get_settings(conn)
        allowed_slots = settings['available_slots']
        daily_limit = settings['daily_limit']

        if time_slot not in allowed_slots:
            conn.rollback()
            return {'success': False, 'error': 'Horário de entrega não permitido.'}

        if target_date == lisbon_now.date():
            slot_hour, slot_minute = map(int, time_slot.split(':'))
            slot_time = lisbon_now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
            if slot_time <= lisbon_now:
                conn.rollback()
                return {'success': False, 'error': 'Este horário já decorreu no dia de hoje.'}

        # Check full day block
        cursor.execute("SELECT COUNT(*) as cnt FROM blocked_slots WHERE booking_date = ? AND time_slot = '*'", (booking_date,))
        if cursor.fetchone()['cnt'] > 0:
            conn.rollback()
            return {'success': False, 'error': 'O estabelecimento encontra-se indisponível nesta data.'}

        # Check daily limit
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = ? AND status != 'Cancelada'",
            (booking_date,)
        )
        if cursor.fetchone()['cnt'] >= daily_limit:
            conn.rollback()
            return {'success': False, 'error': 'Lamentamos, mas o limite diário de lavagens para este dia já foi atingido.'}

        # Check specific slot booking
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = ? AND time_slot = ? AND status != 'Cancelada'",
            (booking_date, time_slot)
        )
        if cursor.fetchone()['cnt'] > 0:
            conn.rollback()
            return {'success': False, 'error': 'Este horário já se encontra reservado por outro cliente.'}

        # Check specific slot block
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM blocked_slots WHERE booking_date = ? AND time_slot = ?",
            (booking_date, time_slot)
        )
        if cursor.fetchone()['cnt'] > 0:
            conn.rollback()
            return {'success': False, 'error': 'Este horário foi bloqueado pelo administrador.'}

        ref_code = f"#SL-{secrets.token_hex(3).upper()}"
        created_at_str = lisbon_now.strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute('''
        INSERT INTO bookings 
        (reference, service_key, price, booking_date, time_slot, customer_name, customer_phone, car_model, status, utm_source, utm_medium, utm_campaign, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?, ?, ?)
        ''', (ref_code, service_key, price, booking_date, time_slot, customer_name.strip(), phone_clean, car_model.strip(), utm_source, utm_medium, utm_campaign, created_at_str))

        conn.commit()

        return {
            'success': True,
            'booking': {
                'reference': ref_code,
                'service_name': service_info['name'],
                'price': price,
                'booking_date': booking_date,
                'time_slot': time_slot,
                'customer_name': customer_name.strip(),
                'customer_phone': phone_clean,
                'car_model': car_model.strip()
            }
        }
    except sqlite3.IntegrityError:
        conn.rollback()
        return {'success': False, 'error': 'Este horário acabou de ser reservado por outro cliente.'}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'error': f'Erro ao processar reserva: {str(e)}'}
    finally:
        conn.close()

def update_booking_status(booking_id, new_status):
    if new_status not in ['Pendente', 'Concluída', 'Cancelada']:
        return False, 'Estado inválido.'

    conn = get_db_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        booking = cursor.fetchone()
        if not booking:
            conn.rollback()
            return False, 'Marcação não encontrada.'

        current_status = booking['status']
        
        # If reactivating from Cancelada to Pendente or Concluída
        if current_status == 'Cancelada' and new_status != 'Cancelada':
            b_date = booking['booking_date']
            t_slot = booking['time_slot']

            # 1. Check if day is blocked
            cursor.execute("SELECT COUNT(*) as cnt FROM blocked_slots WHERE booking_date = ? AND time_slot = '*'", (b_date,))
            if cursor.fetchone()['cnt'] > 0:
                conn.rollback()
                return False, 'Não é possível reativar. O dia encontra-se totalmente bloqueado pelo administrador.'

            # 2. Check if daily capacity limit is reached
            settings = get_settings(conn)
            cursor.execute("SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = ? AND status != 'Cancelada'", (b_date,))
            if cursor.fetchone()['cnt'] >= settings['daily_limit']:
                conn.rollback()
                return False, 'Não é possível reativar. O limite diário de lavagens para este dia já foi atingido.'

            # 3. Check if slot is already occupied by another active booking
            cursor.execute("SELECT COUNT(*) as cnt FROM bookings WHERE booking_date = ? AND time_slot = ? AND status != 'Cancelada'", (b_date, t_slot))
            if cursor.fetchone()['cnt'] > 0:
                conn.rollback()
                return False, f'Não é possível reativar. O horário {t_slot} já foi reservado por outra marcação.'

            # 4. Check if slot is blocked
            cursor.execute("SELECT COUNT(*) as cnt FROM blocked_slots WHERE booking_date = ? AND time_slot = ?", (b_date, t_slot))
            if cursor.fetchone()['cnt'] > 0:
                conn.rollback()
                return False, f'Não é possível reativar. O horário {t_slot} encontra-se bloqueado.'

        cursor.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, booking_id))
        conn.commit()
        return True, 'Estado atualizado com sucesso.'
    except Exception as e:
        conn.rollback()
        return False, f'Erro ao atualizar estado: {str(e)}'
    finally:
        conn.close()

def get_all_bookings(status_filter=None, date_filter=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM bookings WHERE 1=1"
    params = []
    
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
    if date_filter and validate_canonical_date(date_filter):
        query += " AND booking_date = ?"
        params.append(date_filter)
        
    query += " ORDER BY booking_date DESC, time_slot ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_blocked_slots(date_str=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if date_str and validate_canonical_date(date_str):
        cursor.execute("SELECT * FROM blocked_slots WHERE booking_date = ?", (date_str,))
    else:
        cursor.execute("SELECT * FROM blocked_slots ORDER BY booking_date DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def block_slot(booking_date, time_slot, reason="Bloqueado pelo administrador"):
    if not validate_canonical_date(booking_date):
        return False, 'Data inválida.'
    if not validate_time_slot(time_slot):
        return False, 'Horário inválido.'

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO blocked_slots (booking_date, time_slot, reason) VALUES (?, ?, ?) ON CONFLICT(booking_date,time_slot) DO UPDATE SET reason=excluded.reason",
            (booking_date, time_slot, reason.strip()[:100])
        )
        conn.commit()
        return True, 'Bloqueio guardado com sucesso.'
    except Exception as e:
        return False, f'Erro ao bloquear: {str(e)}'
    finally:
        conn.close()

def unblock_slot(booking_date, time_slot):
    if not validate_canonical_date(booking_date) or not validate_time_slot(time_slot):
        return False, 'Parâmetros inválidos.'
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blocked_slots WHERE booking_date = ? AND time_slot = ?", (booking_date, time_slot))
    conn.commit()
    conn.close()
    return True, 'Desbloqueado com sucesso.'

# AUTHENTICATION & SESSIONS
def check_brute_force(ip):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT attempts, last_attempt FROM failed_logins WHERE ip = ?", (ip,))
    row = cursor.fetchone()
    lisbon_now = get_lisbon_now()
    
    if row:
        last_dt = datetime.strptime(row['last_attempt'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=LISBON_TZ)
        if (lisbon_now - last_dt) < timedelta(minutes=15) and row['attempts'] >= 5:
            conn.close()
            return False
        elif (lisbon_now - last_dt) >= timedelta(minutes=15):
            cursor.execute("DELETE FROM failed_logins WHERE ip = ?", (ip,))
            conn.commit()
            
    conn.close()
    return True

def record_failed_login(ip):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = get_lisbon_now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    INSERT INTO failed_logins (ip, attempts, last_attempt)
    VALUES (?, 1, ?)
    ON CONFLICT(ip) DO UPDATE SET attempts = failed_logins.attempts + 1, last_attempt = ?
    ''', (ip, now_str, now_str))
    conn.commit()
    conn.close()

def clear_failed_logins(ip):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM failed_logins WHERE ip = ?", (ip,))
    conn.commit()
    conn.close()

def create_session():
    token = secrets.token_hex(32)
    lisbon_now = get_lisbon_now()
    created_at = lisbon_now.strftime('%Y-%m-%d %H:%M:%S')
    expires_at = (lisbon_now + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO sessions (token, created_at, expires_at) VALUES (?, ?, ?)", (token, created_at, expires_at))
    conn.commit()
    conn.close()
    return token

def verify_session(token):
    if not token or not isinstance(token, str):
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expires_at FROM sessions WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return False
        
    lisbon_now = get_lisbon_now()
    try:
        exp_dt = datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=LISBON_TZ)
        if lisbon_now > exp_dt:
            delete_session(token)
            return False
        return True
    except Exception:
        return False

def delete_session(token):
    if not token:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()
