import unittest
from pathlib import Path
import copy
from datetime import date

from classroom_assistant.editor_core import (guess_columns,extract_lessons,docx_table_rows,validate_working,safe_backup,tidy)
from classroom_assistant.engine import read_json,week_phase,day_lessons,is_holiday,build_calendar

ROOT=Path(__file__).resolve().parents[1]

class EditorTests(unittest.TestCase):
    def test_column_detection(self):
        self.assertEqual((2,3,0),guess_columns(["№","Дата","Тема уроку","Д/з"]))
        self.assertEqual((1,4,0),guess_columns(["№","Зміст уроку","Дата","Дата","Д/з"]))
    def test_avoid_sections_and_dates(self):
        rows=[["№","Дата","Тема","Д/з"],
              ["Розділ 1","Розділ 1","Розділ 1","Розділ 1"],
              ["1","8-Б 07.09","Історія в Україні","Прочитати § 1"],
              ["2","9-А 12.09","Наступна тема",""],
              ["Підсумки","","",""]]
        got=extract_lessons(rows,2,3,0)
        self.assertEqual(2,len(got))
        self.assertEqual("Історія в Україні",got[0]["topic"])
        self.assertEqual("",got[1]["homework"])
    def test_numberless_plan_section_not_included(self):
        rows=[["РОЗДІЛ","ПОВТОРЕННЯ",""],["","Якась тема","ДЗ"]]
        self.assertEqual([],extract_lessons(rows,1,2,0,True))
    def test_import_real_docx(self):
        f=ROOT/"КТП джерела"/"Календарне_8_клас_ІУ_2026-2027_дати_і_ДЗ(1).docx"
        rows=docx_table_rows(f)
        result=extract_lessons(rows,1,3,0)
        self.assertGreater(len(result),40)
        self.assertIn("Берестейська",result[5]["topic"])
        self.assertIn("§ 7",result[5]["homework"])
    def test_multi_section_document(self):
        f=next((ROOT/"КТП джерела").glob("Календарно-тематичне планування*"))
        rows=docx_table_rows(f)
        result=extract_lessons(rows,4,6,0)
        self.assertGreaterEqual(len(result),25)
        self.assertIn("ідентичність",result[0]["topic"].casefold())
        self.assertNotIn("Розділ 2.", " ".join(r["topic"] for r in result))
    def test_phase_configurable_in_new_year(self):
        c=read_json("Налаштування.json")
        c=copy.deepcopy(c)
        c["anchor_phase"]="знаменник"
        self.assertEqual("знаменник",week_phase(date(2026,9,28),c))
        self.assertEqual("чисельник",week_phase(date(2026,10,5),c))
    def test_unverified_plan_never_sends(self):
        c=read_json("Налаштування.json");p=read_json("Календарні плани.json")
        p=copy.deepcopy(p)
        p["8_iu"]["needs_review"]=True
        lesson=next(row for row in day_lessons("2026-10-01",c,p) if row.stream=="8-Г ІУ")
        self.assertNotEqual("готово",lesson.status)
        self.assertFalse(lesson.homework)
    def test_year_and_holiday_validated(self):
        cfg=read_json("Налаштування.json")
        plans=read_json("Календарні плани.json")
        self.assertFalse(validate_working(cfg,plans))
        invalid=copy.deepcopy(cfg);invalid["anchor_monday"]="2026-09-29"
        self.assertTrue(any("понеділком" in e for e in validate_working(invalid,plans)))
    def test_original_schedule_intact(self):
        p=read_json("Налаштування.json")
        self.assertFalse(day_lessons("2026-10-26",p))
        self.assertEqual("знаменник",week_phase(date(2026,11,2),p))

if __name__=="__main__":
    unittest.main()
