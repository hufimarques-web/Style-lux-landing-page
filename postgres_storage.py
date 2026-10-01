"""Small DB-API adapter shared by local SQLite and hosted PostgreSQL."""
import sqlite3
import re

class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.raw.cursor()

    def execute(self, sql, parameters=()):
        statement = sql.strip()
        if statement.upper().startswith('BEGIN'):
            self.connection.lock()
            return self
        if statement.upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER')):
            self.connection.lock()
        statement = re.sub(r'\bid INTEGER PRIMARY KEY(?: AUTOINCREMENT)?', 'id SERIAL PRIMARY KEY', statement)
        statement = re.sub(r'\bREAL\b', 'DOUBLE PRECISION', statement)
        try:
            self.cursor.execute(statement.replace('?', '%s'), parameters or None)
        except self.connection.integrity_error as exc:
            raise sqlite3.IntegrityError('Conflito de dados.') from exc
        return self

    def fetchone(self): return self.cursor.fetchone()
    def fetchall(self): return self.cursor.fetchall()
    def __iter__(self): return iter(self.cursor)
    @property
    def rowcount(self): return self.cursor.rowcount

class Connection:
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row
        self.raw = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
        self.integrity_error = psycopg.IntegrityError
        self.locked = False

    def lock(self):
        # All writes use one transaction lock. Capacity checks and booking writes
        # remain atomic across independent Vercel function instances.
        if not self.locked:
            self.raw.execute('SELECT pg_advisory_xact_lock(8030130)')
            self.locked = True

    def cursor(self): return Cursor(self)
    def execute(self, sql, parameters=()): return self.cursor().execute(sql, parameters)
    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip(): self.execute(statement)
    def commit(self):
        self.raw.commit()
        self.locked = False
    def rollback(self):
        self.raw.rollback()
        self.locked = False
    def close(self): self.raw.close()
    def __enter__(self): return self
    def __exit__(self, kind, value, traceback):
        try:
            if kind is None: self.commit()
            else: self.rollback()
        finally: self.close()
