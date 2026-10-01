"""3.3: дати різних класів, доступні вікна й статус Google."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from classroom_assistant.editor_core import (parse_source_dates,
    import_source_dates,source_date_for_stream,extract_lessons)
from classroom_assistant.window_ui import maximize_work_window
from classroom_assistant.gui import MainApp
from classroom_assistant.classroom_archive import compatible_classroom_title


class Update33Tests(unittest.TestCase):
    def test_source_date_multi_class(self):
        raw="8-Б 04.09.\\n8-В 04.09.\\n8-Г 03.09."
        self.assertEqual(parse_source_dates(raw),{
          "8-Б":"2026-09-04","8-В":"2026-09-04","8-Г":"2026-09-03"})

    def test_9_b_9_g_separate(self):
        raw="9-Б 02.09.\\n9-Г 07.09."
        self.assertEqual(parse_source_dates(raw),{
          "9-Б":"2026-09-02","9-Г":"2026-09-07"})

    def test_single_date_without_class(self):
        self.assertEqual(parse_source_dates("07.09."),{"*":"2026-09-07"})
        self.assertEqual(parse_source_dates("18.01.",2026),{"*":"2027-01-18"})
        self.assertEqual(parse_source_dates("практичне заняття"),{})

    def test_source_date_in_rows(self):
        rows=[["№","Тема","Дата","Д/з"],
          ["1","Урок України","8-Б 04.09. 8-Г 03.09.","§ 1"],
          ["2","Канікули","", ""]]
        lessons=extract_lessons(rows,1,3,0)
        enriched=import_source_dates(rows,lessons,1,0,2026)
        self.assertEqual(source_date_for_stream(enriched[0],"8-Б ІУ"),"2026-09-04")
        self.assertEqual(source_date_for_stream(enriched[0],"8-Г ІУ"),"2026-09-03")
        self.assertIsNone(source_date_for_stream(enriched[0],"9-Б ІУ"))

    def test_local_status_is_not_claimed_published_before_sync(self):
        self.assertIn("статус не перевірено",
                      Path(__file__).parents[1].joinpath(
                          "classroom_assistant/gui.py").read_text("utf8"))
        self.assertNotIn('status=("Чернетка Google" if item',
                      Path(__file__).parents[1].joinpath(
                          "classroom_assistant/gui.py").read_text("utf8"))

    def test_maximize_scheduled_not_error(self):
        fake=MagicMock()
        result=maximize_work_window(fake)
        self.assertIs(result,fake)
        fake.after_idle.assert_called_once()

    def test_classroom_automatic_on_open(self):
        content=Path(__file__).parents[1].joinpath(
            "classroom_assistant/classroom_browser.py").read_text("utf8")
        self.assertIn("self.after(180,self.sync)",content)
        self.assertNotIn('self.fetch_button.grid(row=1',content)

    def test_dnd_handler_returns_copy(self):
        content=Path(__file__).parents[1].joinpath(
            "classroom_assistant/gui.py").read_text("utf8")
        pos=content.index("    def _drop_on_lesson")
        stop=content.index("    def _accept_dropped_word",pos)
        self.assertNotIn('return "break"',content[pos:stop])
        self.assertIn('return "copy"',content[pos:stop])
