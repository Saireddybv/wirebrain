import tempfile
import unittest

from wirebrain.store import Store
from wirebrain.diary import journal,save_note,favorite,export_diary


class DiaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)

    def test_diary_uses_local_day_across_utc_midnight(self):
        ident=self.store.add('claude','web','An evening question')
        with self.store.connect() as db:
            db.execute('UPDATE conversations SET created=? WHERE id=?',('2026-10-29T22:30:00+00:00',ident))
        self.assertEqual(len(journal(self.store,'2026-10-30',330)['entries']),1)
        self.assertEqual(journal(self.store,'2026-10-29',330)['entries'],[])
        self.assertEqual(journal(self.store,'2026-10-30',330)['days'][0]['day'],'2026-10-30')
        self.assertEqual(len(journal(self.store,'2026-10-29',-300)['entries']),1)

    def test_notes_persist_independently_and_export_with_memories(self):
        save_note(self.store,'2026-10-30','A thought to keep. 🌱')
        save_note(self.store,'2026-10-29','Yesterday was different.')
        reopened=Store(self.tmp.name)
        self.assertEqual(journal(reopened,'2026-10-30')['note'],'A thought to keep. 🌱')
        self.assertEqual(journal(reopened,'2026-10-29')['note'],'Yesterday was different.')
        self.assertEqual(len(journal(reopened,'2026-10-30')['days']),2)
        data=export_diary(reopened)
        self.assertEqual(data['format'],'wirebrain-diary-v1')
        self.assertEqual(len(data['notes']),2)
        self.assertEqual(data['memories'],[])

    def test_saved_memories_search_and_delete(self):
        a=self.store.add('claude','web','Remember SQLite')
        self.store.update(a,'A useful reply')
        b=self.store.add('chatgpt','web','Another SQLite question')
        favorite(self.store,a,True)
        self.assertEqual([row['id'] for row in self.store.list('SQLite',favorites=True)],[a])
        self.assertTrue(export_diary(self.store)['memories'][1]['favorite'])
        favorite(self.store,a,False)
        self.assertEqual(self.store.list(favorites=True),[])
        favorite(self.store,a,True)
        self.store.delete(a)
        self.assertEqual([row['id'] for row in self.store.list()],[b])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM entry_flags').fetchone()[0],0)

    def test_invalid_input_is_rejected(self):
        for day in ('2026-02-30','2026-1-1','not-a-day'):
            with self.assertRaises(ValueError): save_note(self.store,day,'note')
        with self.assertRaises(ValueError): save_note(self.store,'2026-10-30','x'*20001)
        with self.assertRaises(ValueError): journal(self.store,'2026-10-30',9999)
        with self.assertRaises(ValueError): favorite(self.store,'missing',True)
