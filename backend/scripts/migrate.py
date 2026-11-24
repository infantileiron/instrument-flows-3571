from pathlib import Path

from src.models.db import transaction
from src.services.ledger import resign_reversals

with transaction() as cursor:
    cursor.execute('''CREATE TABLE IF NOT EXISTS schema_migrations(
        name VARCHAR(100) PRIMARY KEY,
        applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('SELECT name FROM schema_migrations')
    applied = {row['name'] for row in cursor.fetchall()}
    for path in sorted(Path('/app/migrations').glob('*.sql')):
        if path.name in applied:
            continue
        for sql in path.read_text().split(';'):
            if sql.strip():
                cursor.execute(sql)
        cursor.execute('INSERT INTO schema_migrations(name) VALUES (%s)', (path.name,))
    resign_reversals(cursor)
