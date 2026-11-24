from collections import defaultdict
from itertools import combinations, permutations

from src.constants.domain import ReceiptKind
from src.utils.crypto import signed


class LedgerMismatch(ValueError):
    pass


def calculate(snapshot):
    halls = [item['code'] for item in snapshot['halls']]
    originals = {row['id']: row for row in snapshot['originals']}
    allowed = {item['code'] for item in snapshot['instruments']}
    lines_by_reversal = defaultdict(list)
    consumed = defaultdict(int)
    for line in snapshot_lines(snapshot):
        lines_by_reversal[line['reversal_id']].append(line)
        consumed[line['original_id']] += line['quantity']
    for original_id, total in consumed.items():
        original = originals.get(original_id)
        if not original or original['kind'] != ReceiptKind.LOAN or not signed(original):
            raise LedgerMismatch('冲销引用的原签领缺失或签名失效')
        if total > original['quantity']:
            raise LedgerMismatch(f'{original["reference"]} 的冲销合计 {total} 件超过签领 {original["quantity"]} 件')

    signed_events = defaultdict(lambda: [0, 0])
    for row in snapshot['receipts']:
        if row['kind'] == ReceiptKind.LOAN:
            if not signed(row):
                raise LedgerMismatch(f'{row["reference"]} 的签名校验失败')
            if row['instrument'] in allowed:
                signed_events[row['instrument'], row['source'], row['destination']][0] += row['quantity']
            continue
        lines = sorted(lines_by_reversal.get(row['id'], []), key=lambda line: line['id'])
        if not lines:
            raise LedgerMismatch(f'{row["reference"]} 缺少扣减明细')
        if not signed({**row, 'lines': lines}):
            raise LedgerMismatch(f'{row["reference"]} 的签名校验失败')
        for line in lines:
            original = originals.get(line['original_id'])
            if (not original or original['kind'] != ReceiptKind.LOAN or not signed(original)
                    or original['effective_on'] > row['effective_on']):
                raise LedgerMismatch(f'{row["reference"]} 与原签领无法配对')
            if row.get('original_id') is not None and any(
                    row[field] != original[field] for field in ('source', 'destination', 'instrument', 'quantity')):
                raise LedgerMismatch(f'{row["reference"]} 与原签领无法配对')
            if original['instrument'] in allowed:
                signed_events[original['instrument'], original['source'], original['destination']][1] += line['quantity']

    families = {}
    aggregate = matrix(halls)
    for item in snapshot['instruments']:
        family = item['code']
        directional = matrix(halls)
        directions = []
        for source, destination in permutations(halls, 2):
            loan, reversal = signed_events[family, source, destination]
            effective = loan - reversal
            directional[source][destination] = effective
            aggregate[source][destination] += effective
            directions.append({'source': source, 'destination': destination, 'loan': loan,
                               'reversal': reversal, 'effective': effective})
        pairs = []
        for left, right in combinations(halls, 2):
            forward, backward = directional[left][right], directional[right][left]
            if forward or backward:
                pairs.append({'left': left, 'right': right, 'forward': forward, 'backward': backward,
                              'matched': max(0, min(forward, backward)), 'balance': forward - backward})
        families[family] = {**margins(halls, directional), 'pairs': pairs, 'directions': directions}

    result = margins(halls, aggregate)
    result['family'] = families
    result['matched'] = sum(pair['matched'] for family in families.values() for pair in family['pairs'])
    result['loan'] = sum(counts[0] for counts in signed_events.values())
    result['reversal'] = sum(counts[1] for counts in signed_events.values())
    result['receipt_count'] = len(snapshot['receipts'])
    result['verified'] = (result['net_total'] == 0 and result['total_in'] == result['total_out']
                          == result['loan'] - result['reversal'])
    if not result['verified']:
        raise LedgerMismatch('签名净额与矩阵边际不守恒')
    return result


def snapshot_lines(snapshot):
    if 'lines' in snapshot:
        return snapshot['lines']
    # 旧版快照：一单一行全额冲销，折合成扣减行按同一口径核验
    return [{'id': row['id'], 'reversal_id': row['id'], 'original_id': row['original_id'],
             'quantity': row['quantity']}
            for row in snapshot['receipts'] if row['kind'] == ReceiptKind.REVERSAL]


def matrix(halls):
    return {source: dict.fromkeys(halls, 0) for source in halls}


def margins(halls, directional):
    outgoing = {source: sum(directional[source].values()) for source in halls}
    incoming = {destination: sum(directional[source][destination] for source in halls) for destination in halls}
    hall_totals = {hall: {'in': incoming[hall], 'out': outgoing[hall], 'net': incoming[hall] - outgoing[hall]}
                   for hall in halls}
    return {'matrix': directional, 'halls': hall_totals, 'total_in': sum(incoming.values()),
            'total_out': sum(outgoing.values()), 'net_total': sum(row['net'] for row in hall_totals.values())}
