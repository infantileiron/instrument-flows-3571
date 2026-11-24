import hashlib
import json
from collections import defaultdict

from fastapi import HTTPException

from src.constants.domain import ReceiptKind, Role, RunStatus
from src.models.db import one, rows
from src.services.catalog import audit, catalog
from src.utils.crypto import canonical

RUN_FIELDS = '''r.id,r.plan_id,r.status,r.error,r.created_by,r.created_at,r.published_at,r.published_by,
    p.series,p.version,p.start_on,p.end_on,p.instrument'''


def add_plan(cursor, data, user):
    cursor.execute('''INSERT INTO plans(series,version,start_on,end_on,instrument,created_by)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (data.series, data.version, data.start_on, data.end_on, data.instrument, user['username']))
    plan_id = cursor.lastrowid
    audit(cursor, user['username'], 'plan_created', plan_id)
    return {**data.model_dump(), 'id': plan_id, 'created_by': user['username']}


def snapshot_for(cursor, plan):
    start, end, instrument = plan['start_on'], plan['end_on'], plan['instrument']
    loans = rows(cursor, '''SELECT * FROM receipts WHERE kind='loan'
        AND effective_on BETWEEN %s AND %s AND (%s IS NULL OR instrument=%s) ORDER BY id''',
        (start, end, instrument, instrument))
    reversals = rows(cursor, '''SELECT DISTINCT r.* FROM receipts r
        LEFT JOIN reversal_lines l ON l.reversal_id=r.id LEFT JOIN receipts o ON o.id=l.original_id
        WHERE r.kind='reversal' AND r.effective_on BETWEEN %s AND %s
        AND (%s IS NULL OR o.instrument=%s OR l.id IS NULL)
        ORDER BY r.id''', (start, end, instrument, instrument))
    lines, originals = [], []
    if reversals:
        marks = ','.join(['%s'] * len(reversals))
        referenced = rows(cursor, f'''SELECT DISTINCT original_id FROM reversal_lines
            WHERE reversal_id IN ({marks})''', [row['id'] for row in reversals])
        original_ids = sorted(line['original_id'] for line in referenced)
        marks = ','.join(['%s'] * len(original_ids))
        originals = rows(cursor, f'SELECT * FROM receipts WHERE id IN ({marks}) ORDER BY id', original_ids)
        # 同一原单在周期外的冲销行也一并冻结，用于整单与累计件数核验
        lines = rows(cursor, f'SELECT * FROM reversal_lines WHERE original_id IN ({marks}) ORDER BY id',
                     original_ids)
    receipts = sorted(loans + reversals, key=lambda row: row['id'])
    snapshot = {**catalog(cursor), 'receipts': receipts, 'lines': lines, 'originals': originals}
    if instrument:
        snapshot['instruments'] = [item for item in snapshot['instruments'] if item['code'] == instrument]
    return canonical(snapshot)


def enqueue(cursor, plan_id, user):
    plan = one(cursor, 'SELECT * FROM plans WHERE id=%s', (plan_id,))
    if not plan:
        raise HTTPException(404, '方案版本不存在')
    cursor.execute('INSERT INTO runs(plan_id,snapshot,created_by) VALUES (%s,%s,%s)',
                   (plan_id, snapshot_for(cursor, plan), user['username']))
    run_id = cursor.lastrowid
    audit(cursor, user['username'], 'run_queued', run_id)
    return {'id': run_id, 'status': RunStatus.QUEUED}


def list_plans(cursor, user):
    visibility = '' if user['role'] != Role.OBSERVER else (
        'WHERE EXISTS (SELECT 1 FROM runs r WHERE r.plan_id=p.id AND r.published_at IS NOT NULL)')
    return rows(cursor, f'SELECT p.* FROM plans p {visibility} ORDER BY p.series,p.version DESC')


def list_runs(cursor, user):
    visibility = '' if user['role'] != Role.OBSERVER else 'WHERE r.published_at IS NOT NULL'
    return rows(cursor, f'''SELECT {RUN_FIELDS} FROM runs r JOIN plans p ON p.id=r.plan_id
        {visibility} ORDER BY r.id DESC LIMIT 100''')


def reversal_details(snapshot):
    originals = {row['id']: row for row in snapshot['originals']}
    details = []
    if 'lines' in snapshot:
        by_reversal = defaultdict(list)
        for line in snapshot['lines']:
            by_reversal[line['reversal_id']].append(line)
        for row in snapshot['receipts']:
            if row['kind'] != ReceiptKind.REVERSAL:
                continue
            lines = []
            for line in by_reversal.get(row['id'], []):
                original = originals.get(line['original_id'], {})
                lines.append({'original_reference': original.get('reference', '—'),
                              'source': original.get('source'), 'destination': original.get('destination'),
                              'instrument': original.get('instrument'), 'quantity': line['quantity']})
            details.append({'reference': row['reference'], 'effective_on': row['effective_on'], 'lines': lines})
    else:
        # 旧版快照：一单一行全额冲销
        for row in snapshot['receipts']:
            if row['kind'] != ReceiptKind.REVERSAL:
                continue
            original = originals.get(row['original_id'], {})
            details.append({'reference': row['reference'], 'effective_on': row['effective_on'],
                            'lines': [{'original_reference': original.get('reference', '—'),
                                       'source': row['source'], 'destination': row['destination'],
                                       'instrument': row['instrument'], 'quantity': row['quantity']}]})
    return details


def get_run(cursor, run_id, user):
    run = one(cursor, f'''SELECT {RUN_FIELDS}, r.snapshot, r.result FROM runs r
        JOIN plans p ON p.id=r.plan_id WHERE r.id=%s''', (run_id,))
    if not run or (user['role'] == Role.OBSERVER and not run['published_at']):
        raise HTTPException(404, '当前席位没有可阅的这份报告')
    snapshot = json.loads(run.pop('snapshot'))
    run['snapshot_hash'] = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
    run['catalog'] = {key: snapshot[key] for key in ('halls', 'instruments')}
    run['receipt_refs'] = [row['reference'] for row in snapshot['receipts']]
    run['reversals'] = reversal_details(snapshot)
    run['result'] = json.loads(run['result']) if run['result'] else None
    return run, snapshot


def publish(cursor, run_id, user):
    run = one(cursor, 'SELECT status,published_at FROM runs WHERE id=%s FOR UPDATE', (run_id,))
    if not run:
        raise HTTPException(404, '运行记录不存在')
    if run['status'] != RunStatus.DONE:
        raise HTTPException(409, '只有核验完成的运行可以发布')
    if not run['published_at']:
        cursor.execute('UPDATE runs SET published_at=UTC_TIMESTAMP(),published_by=%s WHERE id=%s',
                       (user['username'], run_id))
        audit(cursor, user['username'], 'run_published', run_id)
    return get_run(cursor, run_id, user)[0]
