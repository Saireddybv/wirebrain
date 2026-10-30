"""Personal diary views use the reader's local date, not the server's timezone."""
from datetime import datetime, timezone


def validate_day(day):
    datetime.strptime(day, '%Y-%m-%d')
    if len(day) != 10: raise ValueError('Choose a valid date')
    return day


def journal(store, day, offset=0):
    validate_day(day)
    offset = int(offset)
    if not -840 <= offset <= 840: raise ValueError('Invalid timezone offset')
    with store.connect() as db:
        dates = [dict(r) for r in db.execute('SELECT date(created,?) AS day,count(*) AS count FROM conversations GROUP BY day ORDER BY day DESC', (f'{offset} minutes',))]
        note = db.execute('SELECT body,updated FROM diary_notes WHERE day=?', (day,)).fetchone()
        known = {r['day'] for r in dates}
        for row in db.execute("SELECT day FROM diary_notes WHERE body<>''"):
            if row['day'] not in known: dates.append({'day':row['day'],'count':0})
    return {'day':day,'entries':store.list(limit=10000,day=day,day_offset=offset), 'days':dates,
            'note':note['body'] if note else '', 'note_updated':note['updated'] if note else None}


def save_note(store, day, body):
    validate_day(day)
    if not isinstance(body,str) or len(body)>20000: raise ValueError('Notes can contain up to 20,000 characters')
    updated = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute('INSERT OR REPLACE INTO diary_notes VALUES (?,?,?)',(day,body,updated))
    return {'ok':True,'updated':updated}


def favorite(store, ident, value):
    if not isinstance(value,bool): raise ValueError('Saved state must be true or false')
    with store.connect() as db:
        if not db.execute('SELECT 1 FROM conversations WHERE id=?',(ident,)).fetchone(): raise ValueError('Memory not found')
        db.execute('INSERT OR REPLACE INTO entry_flags VALUES (?,?)',(ident,int(value)))
    return {'ok':True,'favorite':value}


def export_diary(store):
    with store.connect() as db:
        notes = [dict(row) for row in db.execute('SELECT * FROM diary_notes ORDER BY day')]
    return {'format':'wirebrain-diary-v1','exported_at':datetime.now(timezone.utc).isoformat(),
            'memories':store.list(limit=1000000),'notes':notes}
