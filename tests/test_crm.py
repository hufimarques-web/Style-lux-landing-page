import sys,os,tempfile,unittest,json,threading,urllib.request,urllib.error,http.cookiejar
from datetime import timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database as db, crm, config, server

class CRMTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();d=self.temp.name
  self.old=(db.DATA_DIR,db.DB_PATH,config.DATA_DIR,config.CONFIG_FILE,config.TXT_CREDENTIALS_FILE)
  db.DATA_DIR=config.DATA_DIR=d;db.DB_PATH=d+'/crm.db';config.CONFIG_FILE=d+'/admin.json';config.TXT_CREDENTIALS_FILE=d+'/access.txt'
  db.init_db();crm.init_crm()
  date=db.get_lisbon_now().date()+timedelta(days=1)
  while date.weekday()==6:date+=timedelta(days=1)
  self.day=str(date);self.month=self.day[:7]
 def tearDown(self):
  db.DATA_DIR,db.DB_PATH,config.DATA_DIR,config.CONFIG_FILE,config.TXT_CREDENTIALS_FILE=self.old
  self.temp.cleanup()
 def booking(self,slot='09:00',service='premium',source='meta'):
  r=db.create_booking(service,self.day,slot,'Cliente Teste','912345678','Viatura Teste',source)
  self.assertTrue(r['success'],r)
  return db.get_all_bookings()[0]['id'] if slot=='09:00' else next(b['id'] for b in db.get_all_bookings() if b['time_slot']==slot)
 def test_completed_paid_commission_and_cancelled_accounting(self):
  bid=self.booking();second=self.booking('11:00','completa')
  crm.save_terms(dict(month=self.month,commission_percent=20,ad_share_percent=50))
  crm.save_spend(dict(spend_date=self.day,campaign='Campanha teste',amount=20))
  r=crm.snapshot(self.day,self.day)['report'];self.assertEqual(r['expected_cents'],21000);self.assertEqual(r['received_cents'],0)
  db.update_booking_status(bid,'Concluída')
  r=crm.snapshot(self.day,self.day)['report'];self.assertEqual(r['completed_cents'],8000);self.assertEqual(r['received_cents'],0);self.assertEqual(r['commission_cents'],0)
  crm.update_details(dict(id=bid,notes='Preferência',paid=True,eligible=True))
  db.update_booking_status(second,'Cancelada')
  r=crm.snapshot(self.day,self.day)['report'];self.assertEqual(r['received_cents'],8000);self.assertEqual(r['commission_cents'],1600);self.assertEqual(r['ad_share_cents'],1000);self.assertEqual(r['net_cents'],600);self.assertEqual(r['roas'],4);self.assertEqual(r['cancelled'],1)
  db.update_booking_status(bid,'Cancelada');self.assertEqual(crm.snapshot(self.day,self.day)['report']['received_cents'],0)
 def test_terms_not_assumed_and_expense_edits(self):
  bid=self.booking();db.update_booking_status(bid,'Concluída');crm.update_details(dict(id=bid,notes='',paid=True,eligible=True))
  r=crm.snapshot(self.day,self.day)['report'];self.assertIsNone(r['commission_cents']);self.assertEqual(r['missing_terms'],[self.month])
  crm.save_spend(dict(spend_date=self.day,campaign='Teste',amount='12.34'));x=crm.snapshot(self.day,self.day)['expenses'][0]
  crm.save_spend(dict(id=x['id'],spend_date=self.day,campaign='Corrigida',amount='10'))
  snap=crm.snapshot(self.day,self.day);self.assertEqual(len(snap['expenses']),1);self.assertEqual(snap['report']['spend_cents'],1000)
  for rate in (-1,101,'NaN','Infinity'):
   with self.assertRaises(ValueError):crm.save_terms(dict(month=self.month,commission_percent=rate,ad_share_percent=50))
 def test_rescheduling_atomic_conflict_and_blocks(self):
  first=self.booking();self.booking('11:00')
  with self.assertRaises(ValueError):crm.reschedule(dict(id=first,booking_date=self.day,time_slot='11:00'))
  self.assertEqual(next(b for b in db.get_all_bookings() if b['id']==first)['time_slot'],'09:00')
  db.block_slot(self.day,'13:00')
  with self.assertRaises(ValueError):crm.reschedule(dict(id=first,booking_date=self.day,time_slot='13:00'))
  crm.reschedule(dict(id=first,booking_date=self.day,time_slot='15:00'))
  slots={s['time']:s['available'] for s in db.get_public_availability(self.day)['slots']}
  self.assertTrue(slots['09:00']);self.assertFalse(slots['15:00'])
 def test_http_login_isolation_and_logout(self):
  cfg=config.get_or_create_admin_config();password=Path(config.TXT_CREDENTIALS_FILE).read_text().split('Palavra-passe: ',1)[1].strip()
  httpd=server.HTTPServer(('127.0.0.1',0),server.StyleLuxRequestHandler)
  threading.Thread(target=httpd.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(httpd.server_port)
  client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  def call(path,body=None,origin=None):
   headers={'Content-Type':'application/json'}
   if origin:headers['Origin']=origin
   req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
   try:
    with client.open(req,timeout=4) as r:return r.status,json.load(r)
   except urllib.error.HTTPError as err:return err.code,json.load(err)
  try:
   path='/api/admin/crm?from='+self.day+'&to='+self.day
   self.assertEqual(call(path)[0],401)
   self.assertEqual(call('/api/admin/crm/details',dict(id=1,paid=True,eligible=True))[0],401)
   self.assertEqual(call('/api/admin/login',dict(username=cfg['username'],password=password))[0],200)
   self.assertEqual(call(path)[0],200)
   self.assertEqual(call('/api/admin/crm/terms',dict(month=self.month,commission_percent=20,ad_share_percent=50),origin='https://untrusted.example')[0],403)
   self.assertEqual(call('/api/admin/crm/terms',dict(month=self.month,commission_percent=20,ad_share_percent=50))[0],200)
   self.assertEqual(call('/api/admin/logout',{})[0],200)
   self.assertEqual(call(path)[0],401)
  finally:httpd.shutdown();httpd.server_close()
 def test_site_booking_calendar_availability_flow(self):
  config.set_user('operador-teste','palavra-passe-de-teste')
  httpd=server.HTTPServer(('127.0.0.1',0),server.StyleLuxRequestHandler)
  threading.Thread(target=httpd.serve_forever,daemon=True).start()
  base='http://127.0.0.1:'+str(httpd.server_port)
  admin=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  public=urllib.request.build_opener()
  def call(client,path,body=None):
   req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   try:
    with client.open(req,timeout=4) as r:return r.status,json.load(r)
   except urllib.error.HTTPError as err:return err.code,json.load(err)
  def available(slot):
   status,result=call(public,'/api/availability?date='+self.day)
   self.assertEqual(status,200)
   return next(s['available'] for s in result['slots'] if s['time']==slot)
  try:
   self.assertEqual(call(admin,'/api/admin/login',dict(username='operador-teste',password='palavra-passe-de-teste'))[0],200)
   self.assertTrue(available('09:00'))
   payload=dict(service_key='premium',booking_date=self.day,time_slot='09:00',customer_name='Teste do site',customer_phone='912345678',car_model='Viatura de teste')
   status,created=call(public,'/api/bookings',payload);self.assertEqual(status,200)
   self.assertFalse(available('09:00'))
   self.assertEqual(call(public,'/api/bookings',dict(payload,service_key='completa'))[0],400)
   status,snapshot=call(admin,'/api/admin/crm?from='+self.day+'&to='+self.day)
   self.assertEqual(status,200);self.assertEqual(len(snapshot['bookings']),1)
   booking=snapshot['bookings'][0]
   self.assertEqual(booking['reference'],created['booking']['reference'])
   self.assertEqual(booking['customer_name'],'Teste do site')
   self.assertEqual(call(admin,'/api/admin/crm/reschedule',dict(id=booking['id'],booking_date=self.day,time_slot='11:00'))[0],200)
   self.assertTrue(available('09:00'));self.assertFalse(available('11:00'))
   self.assertEqual(call(admin,'/api/admin/bookings/status',dict(id=booking['id'],status='Cancelada'))[0],200)
   self.assertTrue(available('11:00'))
   self.assertEqual(call(admin,'/api/admin/block-slot',dict(booking_date=self.day,time_slot='13:00',reason='Bloqueio teste'))[0],200)
   self.assertFalse(available('13:00'))
   self.assertEqual(call(admin,'/api/admin/unblock-slot',dict(booking_date=self.day,time_slot='13:00'))[0],200)
   self.assertTrue(available('13:00'))
  finally:httpd.shutdown();httpd.server_close()
if __name__=='__main__':unittest.main()
