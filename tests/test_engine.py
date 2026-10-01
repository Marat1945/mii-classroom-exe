import sys, unittest
from pathlib import Path
from datetime import date
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from classroom_assistant.engine import *

class TestCalendar(unittest.TestCase):
    def test_configuration(self):
        self.assertEqual([],check_configuration())
    def test_full_week_both_sides(self):
        self.assertTrue(any(x.stream=="5-Г історія" for x in day_lessons("2026-09-28")))
        self.assertTrue(any(x.stream=="5-Г історія" for x in day_lessons("2026-10-05")))
    def test_phases_during_holidays(self):
        self.assertEqual("чисельник",week_phase(date(2026,9,28)))
        self.assertEqual("чисельник",week_phase(date(2026,10,26)))
        self.assertEqual("знаменник",week_phase(date(2026,11,2)))
        self.assertEqual("знаменник",week_phase(date(2027,1,11)))
    def test_holiday_off(self):
        for d in ("2026-10-26","2026-10-30","2026-12-24","2027-01-08","2027-03-22","2027-03-26"):
            self.assertEqual(0,len(day_lessons(d)))
    def test_known_from_calendar_and_photo(self):
        expected={
            ("2026-09-28","8-Б ІУ"):6,
            ("2026-09-28","5-Г історія"):4,
            ("2026-09-28","9-Б ВІ"):4,
            ("2026-09-30","9-Б Право"):3,
            ("2026-10-01","8-Г ІУ"):7,
            ("2026-10-05","9-Г Право"):3,
            ("2026-10-05","8-Б ГО"):3,
        }
        for (d,stream),n in expected.items():
            matches=[x for x in day_lessons(d) if x.stream==stream]
            self.assertEqual(1,len(matches),(d,stream))
            self.assertEqual(n,matches[0].lesson_number,(d,stream))
    def test_separate_profile_standard(self):
        thu=day_lessons("2026-10-01")
        self.assertEqual(1,len([x for x in thu if x.stream=="11 ІУ профіль"]))
        self.assertEqual(1,len([x for x in thu if x.stream=="11 ІУ стандарт"]))
        self.assertNotEqual(next(x for x in thu if x.stream=="11 ІУ профіль").plan_id,
                            next(x for x in thu if x.stream=="11 ІУ стандарт").plan_id)
    def test_day_cannot_be_published_by_engine(self):
        # engine is read-only w.r.t. Google; check all keys unique
        lessons=build_calendar()
        self.assertEqual(len(lessons),len({l.unique_key for l in lessons}))
        self.assertTrue(all(l.status=="готово" for l in lessons))
    def test_homework_is_from_source(self):
        lesson=next(x for x in day_lessons("2026-09-30") if x.stream=="9-Б Право")
        self.assertEqual(lesson.homework,"Прочитати § 2 (с. 12–21), повторити § 1.")
if __name__=="__main__":unittest.main()
