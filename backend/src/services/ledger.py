from collections import defaultdict

from fastapi import HTTPException

from src.constants.domain import ReceiptKind
from src.models.db import one, rows
from src.services.catalog import audit
from src.utils.crypto import receipt_signature, signed

LEDGER_QUERY = '''SELECT r.*, u.display_name AS signer_name,
    (SELECT CAST(COALESCE(SUM(l.quantity),0) AS UNSIGNED) FROM reversal_lines l
        WHERE l.original_id=r.id) AS reversed_quantity,
    (SELECT GROUP_CONCAT(x.reference ORDER BY x.reference SEPARATOR '　') FROM reversal_lines l
        JOIN receipts x ON x.id=l.reversal_id WHERE l.original_id=r.id) AS reversed_by,
    (SELECT CAST(COALESCE(SUM(l.quantity),0) AS UNSIGNED) FROM reversal_lines l
        WHERE l.reversal_id=r.id) AS line_total
    FROM receipts r JOIN users u ON u.username=r.signer'''


def attach_lines(cursor, records):
    reversal_ids = [row['id'] for row in records if row['kind'] == ReceiptKind.REVERSAL]
    if not reversal_ids:
        return
    marks = ','.join(['%s'] * len(reversal_ids))
    lines = rows(cursor, f'''SELECT l.*, o.reference AS original_reference, o.source, o.destination, o.instrument
        FROM reversal_lines l JOIN receipts o ON o.id=l.original_id
        WHERE l.reversal_id IN ({marks}) ORDER BY l.id''', reversal_ids)
    by_reversal = defaultdict(list)
    for line in lines:
        by_reversal[line['reversal_id']].append(line)
    for row in records:
        if row['kind'] == ReceiptKind.REVERSAL:
            row['lines'] = by_reversal[row['id']]


def ledger(cursor):
    records = rows(cursor, LEDGER_QUERY + ' ORDER BY r.effective_on DESC,r.id DESC LIMIT 500')
    attach_lines(cursor, records)
    return [{**row, 'signature_valid': signed(row)} for row in records]


def insert(cursor, row, *, seed=False):
    row['signature'] = receipt_signature(row)
    sql = '''INSERT INTO receipts(reference,kind,original_id,source,destination,instrument,quantity,
        effective_on,signer,note,signature) VALUES (%(reference)s,%(kind)s,%(original_id)s,%(source)s,
        %(destination)s,%(instrument)s,%(quantity)s,%(effective_on)s,%(signer)s,%(note)s,%(signature)s)'''
    if seed:
        sql += ' ON DUPLICATE KEY UPDATE id=id'
    cursor.execute(sql, row)
    return row


def add_loan(cursor, data, user):
    if data.source == data.destination:
        raise HTTPException(422, '出借馆与入借馆须不同')
    row = insert(cursor, {**data.model_dump(), 'kind': ReceiptKind.LOAN, 'original_id': None,
                          'signer': user['username']})
    audit(cursor, user['username'], 'loan_signed', row['reference'])
    return row


def add_reversal(cursor, data, user):
    references = [line.original_reference for line in data.lines]
    if len(set(references)) != len(references):
        raise HTTPException(422, '同一原签领在一张冲销单中只能出现一次')
    marks = ','.join(['%s'] * len(references))
    found = rows(cursor, f'SELECT * FROM receipts WHERE reference IN ({marks})', references)
    by_reference = {row['reference']: row for row in found}
    wanted = []
    for item in data.lines:
        original = by_reference.get(item.original_reference)
        if not original or original['kind'] != ReceiptKind.LOAN:
            raise HTTPException(422, f'冲销须引用有效的原始签领编号（{item.original_reference}）')
        wanted.append((original, item.quantity))
    lines = []
    for candidate, quantity in sorted(wanted, key=lambda pair: pair[0]['id']):
        original = one(cursor, 'SELECT * FROM receipts WHERE id=%s FOR UPDATE', (candidate['id'],))
        if not signed(original):
            raise HTTPException(409, f'原签领 {original["reference"]} 签名失效，无法冲销')
        if data.effective_on < original['effective_on']:
            raise HTTPException(422, f'冲销日期不得早于原签领 {original["reference"]}')
        taken = rows(cursor, 'SELECT quantity FROM reversal_lines WHERE original_id=%s FOR UPDATE',
                     (original['id'],))
        remaining = original['quantity'] - sum(line['quantity'] for line in taken)
        if quantity > remaining:
            raise HTTPException(409, f'冲销数量超过 {original["reference"]} 的剩余可冲量（剩 {remaining} 件）')
        lines.append({'original_id': original['id'], 'quantity': quantity})
    row = insert(cursor, {'reference': data.reference, 'kind': ReceiptKind.REVERSAL, 'original_id': None,
                          'source': None, 'destination': None, 'instrument': None, 'quantity': None,
                          'effective_on': data.effective_on, 'note': data.note,
                          'signer': user['username'], 'lines': lines})
    reversal_id = cursor.lastrowid
    cursor.executemany('INSERT INTO reversal_lines(reversal_id,original_id,quantity) VALUES (%s,%s,%s)',
                       [(reversal_id, line['original_id'], line['quantity']) for line in lines])
    audit(cursor, user['username'], 'reversal_signed', row['reference'])
    return row


def resign_reversals(cursor):
    records = rows(cursor, "SELECT * FROM receipts WHERE kind='reversal' ORDER BY id")
    attach_lines(cursor, records)
    for record in records:
        if not signed(record):
            cursor.execute('UPDATE receipts SET signature=%s WHERE id=%s',
                           (receipt_signature(record), record['id']))
