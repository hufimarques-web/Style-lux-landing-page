import os
import sys
import unittest
import shutil
import json
import urllib.request
import urllib.error
import threading
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import config
import server

TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_data')
TEST_PORT = 8089

class StyleLuxFullBackendTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        database.DATA_DIR = TEST_DATA_DIR
        database.DB_PATH = os.path.join(TEST_DATA_DIR, 'test_stylelux.db')
        config.DATA_DIR = TEST_DATA_DIR
        config.CONFIG_FILE = os.path.join(TEST_DATA_DIR, 'test_admin_config.json')
        config.TXT_CREDENTIALS_FILE = os.path.join(TEST_DATA_DIR, 'acesso-admin.txt')

    def setUp(self):
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)
        os.makedirs(TEST_DATA_DIR, exist_ok=True)
        database.init_db()
        config.get_or_create_admin_config()

    def tearDown(self):
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)

    def get_next_valid_weekday_str(self):
        lisbon_now = database.get_lisbon_now()
        cur = lisbon_now.date() + timedelta(days=1)
        while cur.weekday() == 6:  # Skip Sunday
            cur += timedelta(days=1)
        return cur.strftime('%Y-%m-%d')

    def get_next_sunday_str(self):
        lisbon_now = database.get_lisbon_now()
        cur = lisbon_now.date() + timedelta(days=1)
        while cur.weekday() != 6:
            cur += timedelta(days=1)
        return cur.strftime('%Y-%m-%d')

    def test_01_pricing_and_canonical_dates(self):
        valid_date = self.get_next_valid_weekday_str()
        
        # Test Premium (80 EUR)
        res_premium = database.create_booking(
            service_key='premium',
            booking_date=valid_date,
            time_slot='09:00',
            customer_name='João Silva',
            customer_phone='912345678',
            car_model='BMW Série 3'
        )
        self.assertTrue(res_premium['success'])
        self.assertEqual(res_premium['booking']['price'], 80.0)

        # Test Completa (130 EUR)
        res_completa = database.create_booking(
            service_key='completa',
            booking_date=valid_date,
            time_slot='11:00',
            customer_name='Maria Santos',
            customer_phone='933888777',
            car_model='Mercedes A-Class'
        )
        self.assertTrue(res_completa['success'])
        self.assertEqual(res_completa['booking']['price'], 130.0)

        # Test invalid non-canonical date string (e.g. 2026-9-1)
        res_non_canon = database.create_booking(
            service_key='premium',
            booking_date='2026-9-1',
            time_slot='13:00',
            customer_name='Teste Data',
            customer_phone='910000000',
            car_model='Audi A4'
        )
        self.assertFalse(res_non_canon['success'])

    def test_02_double_booking_and_concurrency(self):
        valid_date = self.get_next_valid_weekday_str()
        results = []

        def attempt_booking(name, phone):
            r = database.create_booking(
                service_key='premium',
                booking_date=valid_date,
                time_slot='13:00',
                customer_name=name,
                customer_phone=phone,
                car_model='Concurrence Test Car'
            )
            results.append(r)

        t1 = threading.Thread(target=attempt_booking, args=('Cliente Alpha', '911111111'))
        t2 = threading.Thread(target=attempt_booking, args=('Cliente Beta', '922222222'))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [r for r in results if r['success']]
        failures = [r for r in results if not r['success']]

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)

    def test_03_cancellation_and_slot_liberation(self):
        valid_date = self.get_next_valid_weekday_str()
        
        # Create booking
        res = database.create_booking(
            service_key='premium',
            booking_date=valid_date,
            time_slot='15:00',
            customer_name='Cancel Test',
            customer_phone='910000000',
            car_model='Golf'
        )
        self.assertTrue(res['success'])
        
        # Get booking ID from database
        bookings = database.get_all_bookings(date_filter=valid_date)
        target_b = [b for b in bookings if b['time_slot'] == '15:00'][0]
        
        # Cancel booking
        ok, msg = database.update_booking_status(target_b['id'], 'Cancelada')
        self.assertTrue(ok)

        # Confirm slot is now available again
        avail = database.get_public_availability(valid_date)
        slot_15 = [s for s in avail['slots'] if s['time'] == '15:00'][0]
        self.assertTrue(slot_15['available'])

        # New client can book the liberated slot
        res_new = database.create_booking(
            service_key='completa',
            booking_date=valid_date,
            time_slot='15:00',
            customer_name='Novo Cliente',
            customer_phone='999999999',
            car_model='Clio'
        )
        self.assertTrue(res_new['success'])

    def test_04_reactivation_collision_prevention(self):
        valid_date = self.get_next_valid_weekday_str()

        # 1. Booking A created on 17:00
        resA = database.create_booking('premium', valid_date, '17:00', 'Cliente A', '910000001', 'Car A')
        self.assertTrue(resA['success'])
        bA_id = [b['id'] for b in database.get_all_bookings(date_filter=valid_date) if b['time_slot'] == '17:00'][0]

        # 2. Booking A cancelled
        database.update_booking_status(bA_id, 'Cancelada')

        # 3. Booking B created on 17:00
        resB = database.create_booking('completa', valid_date, '17:00', 'Cliente B', '910000002', 'Car B')
        self.assertTrue(resB['success'])

        # 4. Attempting to reactivate Booking A must fail!
        ok, msg = database.update_booking_status(bA_id, 'Pendente')
        self.assertFalse(ok)
        self.assertIn('já foi reservado', msg)

    def test_05_full_day_blocking(self):
        valid_date = self.get_next_valid_weekday_str()

        # Block full day using "*"
        ok, msg = database.block_slot(valid_date, '*', 'Feriado Municipal')
        self.assertTrue(ok)

        # Public availability must show day as fully blocked
        avail = database.get_public_availability(valid_date)
        self.assertTrue(avail['day_blocked'])
        self.assertEqual(avail['remaining_capacity'], 0)

        # Booking attempt must be rejected
        res = database.create_booking('premium', valid_date, '09:00', 'Teste Feriado', '910000000', 'Peugeot')
        self.assertFalse(res['success'])
        self.assertIn('indisponível', res['error'])

    def test_06_invalid_settings_rejection(self):
        # Invalid daily limit (< 1)
        ok, msg = database.update_settings(daily_limit=0)
        self.assertFalse(ok)

        # Invalid slot format or out of bounds
        ok, msg = database.update_settings(available_slots=['08:00', '20:00'])
        self.assertFalse(ok)

    def test_07_http_security_and_static_file_isolation(self):
        # Start test HTTP server in background thread
        server.PUBLIC_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'public'))
        httpd = server.HTTPServer(('127.0.0.1', TEST_PORT), server.StyleLuxRequestHandler)
        srv_thread = threading.Thread(target=httpd.serve_forever)
        srv_thread.daemon = True
        srv_thread.start()

        base_url = f"http://127.0.0.1:{TEST_PORT}"

        try:
            # 1. Unauthenticated request to /api/admin/bookings must return HTTP 401
            req_admin = urllib.request.Request(f"{base_url}/api/admin/bookings")
            try:
                urllib.request.urlopen(req_admin)
                self.fail("Should have raised HTTP 401 Error")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 401)

            # 2. Attempt path traversal to fetch private DB or config file must return HTTP 404
            traversal_urls = [
                f"{base_url}/../data/stylelux.db",
                f"{base_url}/../config.py",
                f"{base_url}/../server.py",
                f"{base_url}/%2e%2e/data/admin_config.json"
            ]
            for t_url in traversal_urls:
                try:
                    urllib.request.urlopen(t_url)
                    self.fail(f"Path traversal should have failed for {t_url}")
                except urllib.error.HTTPError as e:
                    self.assertEqual(e.code, 404)

            # 3. Public static assets (index.html, css/style.css, assets/carro.jpg) must return HTTP 200
            res_index = urllib.request.urlopen(f"{base_url}/index.html")
            self.assertEqual(res_index.status, 200)

            res_css = urllib.request.urlopen(f"{base_url}/css/style.css")
            self.assertEqual(res_css.status, 200)

        finally:
            httpd.shutdown()
            httpd.server_close()

if __name__ == '__main__':
    unittest.main()
