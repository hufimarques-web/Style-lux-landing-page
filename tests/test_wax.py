import sys, tempfile, unittest, threading, json, urllib.request, urllib.error, http.cookiejar
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database as db, crm, config, server

class WaxTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();d=self.temp.name
  self.old=(db.DATA_DIR,db.DB_PATH,config.DATA_DIR,config.CONFIG_FILE,config.TXT_CREDENTIALS_FILE)
  db.DATA_DIR=config.DATA_DIR=d;db.DB_PATH=d+'/test.db';config.CONFIG_FILE=d+'/admin.json';config.TXT_CREDENTIALS_FILE=d+'/access.txt'
  db.init_db();crm.init_crm()
  date=db.get_lisbon_now().date()+timedelta(days=1)
  while date.weekday()==6:date+=timedelta(days=1)
  self.day=str(date)
 def tearDown(self):
  db.DATA_DIR,db.DB_PATH,config.DATA_DIR,config.CONFIG_FILE,config.TXT_CREDENTIALS_FILE=self.old
  self.temp.cleanup()
 def payload(self,service='exterior'):
  return dict(service_key=service,customer_name='Teste Cera',customer_phone='912345678',car_model='Viatura teste',preference='Durante a tarde',utm_source='meta',booking_date=self.day,time_slot='09:00',price=1)
 def request(self,service='exterior'):
  return crm.create_wax_request(self.payload(service))['reference']
 def snapshot(self):return crm.snapshot(self.day,self.day)
 def schedule(self,ref,slot='09:00'):
  return crm.schedule_wax_request(dict(reference=ref,booking_date=self.day,time_slot=slot))
 def test_requests_do_not_reserve_or_count_as_sales(self):
  before=db.get_public_availability(self.day)
  for service,price in [('exterior',30),('exterior',30)]:
   self.assertEqual(crm.create_wax_request(self.payload(service))['price'],price)
  snap=self.snapshot()
  self.assertEqual(len(snap['wax_requests']),2);self.assertEqual(snap['bookings'],[])
  self.assertEqual(snap['report']['total'],0);self.assertEqual(snap['report']['expected_cents'],0)
  self.assertEqual(db.get_public_availability(self.day),before)
 def test_conversion_preserves_contact_and_uses_real_price(self):
  ref=self.request('exterior')
  crm.update_wax_request(dict(reference=ref,status='Contactado',notes='Cliente prefere tarde'))
  self.schedule(ref)
  snap=self.snapshot();b=snap['bookings'][0];r=snap['wax_requests'][0]
  self.assertEqual((r['status'],r['booking_id']),('Agendado',b['id']))
  self.assertEqual((b['service_key'],b['price'],b['customer_name'],b['utm_source']),('exterior',30,'Teste Cera','meta'))
  self.assertEqual(b['notes'],'Cliente prefere tarde');self.assertFalse(b['eligible'])
  self.assertFalse(next(s['available'] for s in db.get_public_availability(self.day)['slots'] if s['time']=='09:00'))
  with self.assertRaises(ValueError):self.schedule(ref,'11:00')
  with self.assertRaises(ValueError):crm.update_wax_request(dict(reference=ref,status='Em espera'))
  self.assertEqual(len(self.snapshot()['bookings']),1)
 def test_conflicts_and_archived_requests_stay_outside_calendar(self):
  ref=self.request();db.block_slot(self.day,'09:00')
  with self.assertRaises(ValueError):self.schedule(ref)
  self.assertTrue(db.create_booking('premium',self.day,'11:00','Cliente Teste','912345678','Viatura Teste')['success'])
  with self.assertRaises(ValueError):self.schedule(ref,'11:00')
  db.update_settings(daily_limit=1)
  with self.assertRaises(ValueError):self.schedule(ref,'13:00')
  snap=self.snapshot();self.assertEqual(len(snap['bookings']),1)
  self.assertEqual(snap['wax_requests'][0]['status'],'Em espera');self.assertIsNone(snap['wax_requests'][0]['booking_id'])
  crm.update_wax_request(dict(reference=ref,status='Arquivado'))
  with self.assertRaises(ValueError):self.schedule(ref,'15:00')
 def test_concurrent_conversion_is_atomic(self):
  ref=self.request()
  def attempt(slot):
   try:self.schedule(ref,slot);return True
   except ValueError:return False
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,['09:00','11:00']))
  self.assertEqual(sum(results),1);self.assertEqual(len(self.snapshot()['bookings']),1)
 def test_http_public_request_private_management_and_no_direct_booking(self):
  config.set_user('teste','password-test-only')
  httpd=server.HTTPServer(('127.0.0.1',0),server.StyleLuxRequestHandler)
  threading.Thread(target=httpd.serve_forever,daemon=True).start()
  base='http://127.0.0.1:'+str(httpd.server_port)
  client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  def call(path,body):
   req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   try:
    with client.open(req,timeout=4) as r:return r.status,json.load(r)
   except urllib.error.HTTPError as err:return err.code,json.load(err)
  try:
   code,result=call('/api/wax-requests',self.payload());self.assertEqual(code,200)
   ref=result['request']['reference'];body=dict(reference=ref,booking_date=self.day,time_slot='09:00')
   self.assertEqual(call('/api/admin/wax-requests/schedule',body)[0],401)
   self.assertEqual(call('/api/admin/wax-requests/update',dict(reference=ref,status='Contactado'))[0],401)
   self.assertEqual(call('/api/bookings',self.payload())[0],400)
   self.assertEqual(call('/api/wax-requests',self.payload('premium'))[0],400)
   self.assertEqual(call('/api/admin/login',dict(username='teste',password='password-test-only'))[0],200)
   self.assertEqual(call('/api/admin/wax-requests/schedule',body)[0],200)
   self.assertEqual(call('/api/admin/wax-requests/schedule',body)[0],400)
  finally:httpd.shutdown();httpd.server_close()

if __name__=='__main__':unittest.main()
