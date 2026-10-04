"""Private CRM data and reporting, using the existing booking database."""
import re
from decimal import Decimal, InvalidOperation
import database as db


def init_crm():
    with db.get_db_connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS wax_requests (
          reference TEXT PRIMARY KEY, service_key TEXT NOT NULL,
          customer_name TEXT NOT NULL, customer_phone TEXT NOT NULL, car_model TEXT NOT NULL,
          preference TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'Em espera', created_at TEXT NOT NULL,
          utm_source TEXT NOT NULL DEFAULT '', utm_medium TEXT NOT NULL DEFAULT '',
          utm_campaign TEXT NOT NULL DEFAULT '', booking_id INTEGER REFERENCES bookings(id));
        CREATE TABLE IF NOT EXISTS crm_booking (
          booking_id INTEGER PRIMARY KEY REFERENCES bookings(id), notes TEXT NOT NULL DEFAULT '',
          paid INTEGER NOT NULL DEFAULT 0, eligible INTEGER);
        CREATE TABLE IF NOT EXISTS ad_spend (
          id INTEGER PRIMARY KEY, spend_date TEXT NOT NULL, campaign TEXT NOT NULL,
          amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0));
        CREATE TABLE IF NOT EXISTS finance_terms (
          month TEXT PRIMARY KEY, commission_percent REAL NOT NULL, ad_share_percent REAL NOT NULL);
        ''')


def money(value, limit=1000000):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > limit:
            raise ValueError('Valor fora do intervalo permitido.')
        return int((number * 100).quantize(Decimal('1')))
    except (InvalidOperation, TypeError):
        raise ValueError('Valor inválido.')


def attributed(b):
    return b.get('utm_source', '').lower() in ('facebook', 'fb', 'instagram', 'ig', 'meta') or b.get('utm_medium', '').lower() in ('cpc', 'paid', 'paid_social', 'paid-social')


def snapshot(start, end):
    if not db.validate_canonical_date(start) or not db.validate_canonical_date(end) or start > end:
        raise ValueError('Selecione um período de datas válido.')
    with db.get_db_connection() as c:
        bookings = [dict(r) for r in c.execute('''SELECT b.*, COALESCE(d.notes,'') AS notes,
          COALESCE(d.paid,0) AS paid, d.eligible FROM bookings b LEFT JOIN crm_booking d ON d.booking_id=b.id
          ORDER BY booking_date,time_slot''')]
        wax_requests = [dict(r) for r in c.execute('SELECT * FROM wax_requests ORDER BY created_at DESC,reference')]
        expenses = [dict(r) for r in c.execute('SELECT * FROM ad_spend WHERE spend_date BETWEEN ? AND ? ORDER BY spend_date DESC,id DESC', (start,end))]
        terms = {r['month']: dict(r) for r in c.execute('SELECT * FROM finance_terms')}
    for b in bookings:
        b['eligible'] = bool(b['eligible']) if b['eligible'] is not None else attributed(b)
    selected = [b for b in bookings if start <= b['booking_date'] <= end]
    completed = [b for b in selected if b['status'] == 'Concluída']
    pending = [b for b in selected if b['status'] == 'Pendente']
    paid = [b for b in completed if b['paid']]
    value = lambda rows: sum(money(b['price']) for b in rows)
    commission = 0
    unconfigured = set()
    for b in paid:
        if b['eligible']:
            t = terms.get(b['booking_date'][:7])
            if t is None:
                unconfigured.add(b['booking_date'][:7])
            else:
                commission += round(money(b['price']) * t['commission_percent'] / 100)
    ad_share = 0
    for x in expenses:
        t = terms.get(x['spend_date'][:7])
        if t is None:
            unconfigured.add(x['spend_date'][:7])
        else:
            ad_share += round(x['amount_cents'] * t['ad_share_percent'] / 100)
    by_day = {}
    for b in completed:
        by_day[b['booking_date']] = by_day.get(b['booking_date'], 0) + money(b['price'])
    breakdown = []
    for key, service in db.SERVICES.items():
        rows = [b for b in selected if b['service_key'] == key]
        breakdown.append({'name': service['name'], 'bookings': len(rows), 'completed': sum(b['status']=='Concluída' for b in rows), 'value_cents': value([b for b in rows if b['status']=='Concluída'])})
    spend = sum(x['amount_cents'] for x in expenses)
    attributed_paid = value([b for b in paid if b['eligible']])
    report = dict(total=len(selected), completed=len(completed), pending=len(pending), cancelled=sum(b['status']=='Cancelada' for b in selected),
      completed_cents=value(completed), expected_cents=value(pending), received_cents=value(paid), unpaid_cents=value(completed)-value(paid),
      spend_cents=spend, commission_cents=commission if not unconfigured else None,
      ad_share_cents=ad_share if not unconfigured else None, net_cents=commission-ad_share if not unconfigured else None,
      roas=round(attributed_paid/spend,2) if spend else None, attributed_received_cents=attributed_paid,
      missing_terms=sorted(unconfigured), by_day=by_day, by_service=breakdown)
    return dict(wax_requests=wax_requests, bookings=bookings, expenses=expenses, terms=terms, report=report, settings=db.get_settings(), blocks=db.get_blocked_slots(), today=db.get_lisbon_now().date().isoformat())


def update_details(body):
    bid = body.get('id')
    if type(bid) is not int or type(body.get('paid')) is not bool or type(body.get('eligible')) is not bool:
        raise ValueError('Dados da marcação inválidos.')
    notes = body.get('notes','')
    if not isinstance(notes,str) or len(notes)>4000:
        raise ValueError('As notas podem ter até 4000 caracteres.')
    with db.get_db_connection() as c:
        if not c.execute('SELECT id FROM bookings WHERE id=?',(bid,)).fetchone():
            raise ValueError('Marcação não encontrada.')
        c.execute('''INSERT INTO crm_booking(booking_id,notes,paid,eligible) VALUES(?,?,?,?)
          ON CONFLICT(booking_id) DO UPDATE SET notes=excluded.notes,paid=excluded.paid,eligible=excluded.eligible''',
          (bid,notes,int(body['paid']),int(body['eligible'])))


def save_spend(body):
    date=body.get('spend_date'); campaign=body.get('campaign','')
    if not db.validate_canonical_date(date) or not isinstance(campaign,str) or not 1<=len(campaign.strip())<=150:
        raise ValueError('Preencha a data e o nome da campanha (até 150 caracteres).')
    amount=money(body.get('amount'))
    if amount<=0: raise ValueError('O investimento deve ser superior a zero.')
    with db.get_db_connection() as c:
        if body.get('id') is not None:
            if type(body['id']) is not int: raise ValueError('Registo inválido.')
            if c.execute('UPDATE ad_spend SET spend_date=?,campaign=?,amount_cents=? WHERE id=?',(date,campaign.strip(),amount,body['id'])).rowcount!=1:
                raise ValueError('Investimento não encontrado.')
        else:
            c.execute('INSERT INTO ad_spend(spend_date,campaign,amount_cents) VALUES(?,?,?)',(date,campaign.strip(),amount))


def save_terms(body):
    month=body.get('month','')
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month) or not db.validate_canonical_date(month+'-01'):
        raise ValueError('Mês inválido.')
    rate=money(body.get('commission_percent'),100)/100
    share=money(body.get('ad_share_percent'),100)/100
    with db.get_db_connection() as c:
        c.execute('INSERT INTO finance_terms VALUES(?,?,?) ON CONFLICT(month) DO UPDATE SET commission_percent=excluded.commission_percent,ad_share_percent=excluded.ad_share_percent',(month,rate,share))


def reschedule(body):
    bid=body.get('id'); date=body.get('booking_date'); slot=body.get('time_slot')
    target=db.validate_canonical_date(date)
    now=db.get_lisbon_now()
    if type(bid) is not int or not target or target.weekday()==6 or target<now.date() or not db.validate_time_slot(slot) or slot=='*':
        raise ValueError('Data ou horário inválidos.')
    if target==now.date() and slot<=now.strftime('%H:%M'):
        raise ValueError('Este horário já passou.')
    with db.get_db_connection() as c:
        c.execute('BEGIN IMMEDIATE')
        b=c.execute('SELECT * FROM bookings WHERE id=?',(bid,)).fetchone()
        if not b or b['status']!='Pendente': raise ValueError('Só pode reagendar marcações pendentes.')
        settings=db.get_settings(c)
        if slot not in settings['available_slots']: raise ValueError('Escolha um horário de entrega configurado.')
        if c.execute("SELECT 1 FROM blocked_slots WHERE booking_date=? AND time_slot IN (?, '*')",(date,slot)).fetchone():
            raise ValueError('Este horário está bloqueado.')
        if c.execute("SELECT 1 FROM bookings WHERE id!=? AND booking_date=? AND time_slot=? AND status!='Cancelada'",(bid,date,slot)).fetchone():
            raise ValueError('Este horário já está ocupado.')
        count=c.execute("SELECT COUNT(*) AS total FROM bookings WHERE id!=? AND booking_date=? AND status!='Cancelada'",(bid,date)).fetchone()['total']
        if count>=settings['daily_limit']: raise ValueError('Capacidade diária atingida.')
        c.execute('UPDATE bookings SET booking_date=?,time_slot=? WHERE id=?',(date,slot,bid))


WAX_SERVICES = ('exterior',)

def create_wax_request(body):
    service = body.get('service_key')
    if service not in WAX_SERVICES:
        raise ValueError('Selecione Lavagem Exterior + proteção básica (30 €).')
    fields = {}
    for key, minimum, maximum in [('customer_name',2,100),('customer_phone',9,20),('car_model',2,100),('preference',0,500)]:
        value = body.get(key, '')
        if not isinstance(value,str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError('Verifique o nome, telemóvel, viatura e preferência de horário.')
        fields[key] = value.strip()
    if not re.fullmatch(r'\+?[0-9\s\-]{9,20}',fields['customer_phone']):
        raise ValueError('Introduza um telemóvel válido.')
    reference = '#CP-' + db.secrets.token_hex(6).upper()
    with db.get_db_connection() as c:
        c.execute('INSERT INTO wax_requests(reference,service_key,customer_name,customer_phone,car_model,preference,created_at,utm_source,utm_medium,utm_campaign) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (reference,service,fields['customer_name'],fields['customer_phone'],fields['car_model'],fields['preference'],db.get_lisbon_now().strftime('%Y-%m-%d %H:%M:%S'),
             str(body.get('utm_source') or '')[:50],str(body.get('utm_medium') or '')[:50],str(body.get('utm_campaign') or '')[:50]))
    return dict(reference=reference,service_name=db.SERVICES[service]['name'],price=db.SERVICES[service]['price'],car_model=fields['car_model'])


def update_wax_request(body):
    if not isinstance(body.get('reference'),str): raise ValueError('Referência inválida.')
    status = body.get('status')
    notes = body.get('notes','')
    if status not in ('Em espera','Contactado','Arquivado') or not isinstance(notes,str) or len(notes)>4000:
        raise ValueError('Estado ou notas inválidos.')
    with db.get_db_connection() as c:
        if c.execute('UPDATE wax_requests SET status=?,notes=? WHERE reference=? AND booking_id IS NULL',
                     (status,notes,body.get('reference'))).rowcount != 1:
            raise ValueError('Pedido não encontrado ou já agendado.')


def schedule_wax_request(body):
    if not isinstance(body.get('reference'),str): raise ValueError('Referência inválida.')
    # Keep queue conversion and the shared-capacity check in one transaction.
    with db.get_db_connection() as c:
        c.execute('BEGIN EXCLUSIVE')
        row=c.execute('SELECT * FROM wax_requests WHERE reference=?',(body.get('reference'),)).fetchone()
        if not row or row['booking_id'] is not None or row['status']=='Arquivado':
            raise ValueError('Pedido não encontrado, arquivado ou já agendado.')
        result=db.create_booking(row['service_key'],body.get('booking_date'),body.get('time_slot'),
            row['customer_name'],row['customer_phone'],row['car_model'],row['utm_source'],row['utm_medium'],row['utm_campaign'],_connection=c)
        if not result.get('success'): raise ValueError(result['error'])
        booking=c.execute('SELECT id FROM bookings WHERE reference=?',(result['booking']['reference'],)).fetchone()
        c.execute("UPDATE wax_requests SET status='Agendado',booking_id=? WHERE reference=?",(booking['id'],row['reference']))
        c.execute('INSERT INTO crm_booking(booking_id,notes,paid,eligible) VALUES(?,?,0,0)',
                  (booking['id'],row['notes']))
