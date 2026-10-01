"""Регресійні перевірки оновлення 3.1 без зовнішніх API й публікацій."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from classroom_assistant.engine import read_json
from classroom_assistant.editor_ui import friendly_plan_id, parse_ui_date, display_ui_date
from classroom_assistant.gui import weekday_ua
from classroom_assistant import attachments
from classroom_assistant.schedule_io import export_schedule_jpeg


class Update31Tests(unittest.TestCase):
    def test_ukrainian_weekday(self):
        self.assertEqual(weekday_ua("01.10.2026"),"ЧЕТВЕР")
        self.assertEqual(weekday_ua("02.10.2026"),"П’ЯТНИЦЯ")

    def test_friendly_calendar_plan_codes(self):
        self.assertEqual(friendly_plan_id("8_iu"),"8 ІУ")
        self.assertEqual(friendly_plan_id("9B_iu"),"9-Б ІУ")
        self.assertEqual(friendly_plan_id("10_iu_profile"),"10 ІУ профіль")
        self.assertEqual(friendly_plan_id("11_iu_standard"),"11 ІУ стандарт")

    def test_local_date_roundtrip(self):
        self.assertEqual(parse_ui_date("01.10.2026"),"2026-10-01")
        self.assertEqual(display_ui_date("2027-01-11"),"11.01.2027")
        with self.assertRaises(ValueError):
            parse_ui_date("32.10.2026")

    def test_image_export_without_break(self):
        cfg=read_json("Налаштування.json")
        with tempfile.TemporaryDirectory() as directory:
            result=Path(directory)/"Розклад.jpg"
            export_schedule_jpeg(cfg,result,show_meal=False,show_bells=False)
            with Image.open(result) as im:
                self.assertEqual(im.format,"JPEG")
                self.assertGreater(im.width,1400)
                self.assertGreater(im.height,650)

    def test_attachment_copy_and_secret_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            src=base/"Ілюстрація.png"
            Image.new("RGB",(70,35),"blue").save(src)
            data={}
            with patch.object(attachments,"ATTACHMENT_ROOT",base/"attachments"):
                x=attachments.add_attachments(data,"2026-10-01|3|8-Г ІУ",[src])
                self.assertEqual(len(x),1)
                self.assertEqual(len(attachments.files_for_lesson(data,"2026-10-01|3|8-Г ІУ")),1)
                again=attachments.add_attachments(data,"2026-10-01|3|8-Г ІУ",[src])
                self.assertEqual(len(again),0)
                attachments.copy_attachments(data,"2026-10-01|3|8-Г ІУ",
                                             "2026-10-02|1|8-Б ІУ")
                self.assertEqual(len(attachments.files_for_lesson(
                    data,"2026-10-02|1|8-Б ІУ")),1)
                secret=base/"google_credentials.json"
                secret.write_text("{}",encoding="utf8")
                with self.assertRaises(ValueError):
                    attachments.add_attachments(data,"2026-10-01|3|8-Г ІУ",[secret])
                self.assertTrue(attachments.remove_attachment(data,"2026-10-01|3|8-Г ІУ",0))

    def test_show_lessons_button_removed_and_auto_date(self):
        src=(Path(__file__).parents[1]/"classroom_assistant"/"gui.py").read_text(encoding="utf8")
        self.assertNotIn('text="Показати уроки"',src)
        self.assertIn('self.datevar.trace_add("write",self._on_date_text_change)',src)
        self.assertIn('self.weekday=ttk.Label',src)
