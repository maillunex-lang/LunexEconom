"""Each transfer has one record and exactly two entries summing to zero."""

def transfer(conn, request_id, from_id, to_id, amount):
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0 or amount > 2**63-1 or from_id == to_id or not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise ValueError('Invalid transfer')
    with conn.transaction():
        # Serialize by request ID, then lock both account rows in stable order.
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (request_id,))
        previous = conn.execute('SELECT t.id,e.account_id,e.amount FROM ledger_transfers t JOIN ledger_entries e ON e.transfer_id=t.id WHERE t.request_id=%s ORDER BY e.account_id', (request_id,)).fetchall()
        if previous:
            if sorted((r[1], r[2]) for r in previous) != sorted([(from_id, -amount), (to_id, amount)]):
                raise ValueError('request_id reused for different transfer')
            return previous[0][0]
        rows = conn.execute('SELECT id,balance FROM ledger_accounts WHERE id IN (%s,%s) ORDER BY id FOR UPDATE', (from_id, to_id)).fetchall()
        if len(rows) != 2:
            raise ValueError('Unknown account')
        if dict(rows)[from_id] < amount:
            raise ValueError('Insufficient funds')
        transfer_id = conn.execute('INSERT INTO ledger_transfers(request_id) VALUES(%s) RETURNING id', (request_id,)).fetchone()[0]
        for account_id, delta in ((from_id, -amount), (to_id, amount)):
            conn.execute('INSERT INTO ledger_entries(transfer_id,account_id,amount) VALUES(%s,%s,%s)', (transfer_id, account_id, delta))
            conn.execute('UPDATE ledger_accounts SET balance=balance+%s WHERE id=%s', (delta, account_id))
        return transfer_id
