"""3.4: безкоштовні лекції через власний ChatGPT і точніший імпорт готових КТП."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from docx import Document

from classroom_assistant.chatgpt_bridge import (
    NOTEBOOK_HEADING, PROMPT_MARKER, build_prompt, lesson_code, lesson_profile,
    looks_like_answer, parse_answer, safe_chatgpt_url)
from classroom_assistant.documents import create_word
from classroom_assistant.editor_core import (
    docx_table_rows, extract_lessons, guess_columns, import_notes,
    import_source_dates, parse_source_dates, tidy)
from classroom_assistant.engine import day_lessons, read_json
from classroom_assistant.material_library import check_real_docx

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "КТП джерела"


def sample_answer(code, sections=6, notebook=10, extra=""):
    """Типова відповідь ChatGPT: жирний код, ### з номерами й емодзі, маркери."""
    parts = [f"**КОД УРОКУ: {code}**", ""]
    for i in range(1, sections + 1):
        parts.append(f"### {i}. 🏛️ Розділ про подію {i}")
        parts.append(f"Перший абзац розділу {i}: передумови, **ключові** дати й постаті, "
                     "причини та наслідки подій для України й світу.")
        parts.append("")
        parts.append(f"Другий абзац розділу {i} пояснює поняття й зв'язки між подіями.")
        if i == 2:
            parts.append("- важливий факт першого рівня;")
            parts.append("- ще один факт.")
        parts.append("")
    parts.append(extra)
    parts.append(f"## {NOTEBOOK_HEADING}")
    for i in range(1, notebook + 1):
        parts.append(f"{i}. **Пункт {i}:** стислий зміст для зошита.")
        if i == 1:
            parts.append("   - уточнення до першого пункту")
    parts += ["", "Якщо потрібно, можу також підготувати запитання для самоперевірки."]
    return "\n".join(parts)


class ChatGPTBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lessons = day_lessons("2026-10-01", read_json("Налаштування.json"))
        cls.lesson = cls.lessons[0]                     # 11 ІУ профіль, КТП №14
        cls.code = lesson_code(cls.lesson)

    def test_prompt_has_exact_ktp_data_and_format(self):
        prompt = build_prompt(self.lesson)
        self.assertIn(PROMPT_MARKER, prompt)
        self.assertIn(self.lesson.topic, prompt)
        self.assertIn("ПРОФІЛЬНИЙ", prompt)
        self.assertIn("Історія України", prompt)
        self.assertIn("№14", prompt)
        self.assertIn(f"КОД УРОКУ: {self.code}", prompt)
        self.assertIn(f"## {NOTEBOOK_HEADING}", prompt)
        self.assertIn("НЕ пиши привітання, домашнє завдання", prompt)
        self.assertNotIn("Zoom у зв", prompt)

    def test_code_is_stable_and_unique_per_lesson(self):
        codes = [lesson_code(x) for x in self.lessons]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(self.code, lesson_code(self.lesson))
        self.assertRegex(self.code, r"^#[A-Z2-7]{6}$")

    def test_profiles_for_real_streams(self):
        self.assertEqual(lesson_profile("5-Г історія")["grade"], 5)
        self.assertEqual(lesson_profile("9-Б Право")["subject"], "Правознавство")
        self.assertEqual(lesson_profile("10-Б ГО")["subject"], "Громадянська освіта")
        self.assertEqual(lesson_profile("11 ІУ стандарт")["level"], "стандартний")
        self.assertEqual(lesson_profile("8-В ВІ")["subject"], "Всесвітня історія")

    def test_lesson_type_hints(self):
        practical = replace(self.lesson, topic="Практичне заняття. Аналіз джерел.")
        self.assertIn("ПРАКТИЧНЕ ЗАНЯТТЯ", build_prompt(practical))
        review = replace(self.lesson, topic="Узагальнення з розділу 1.")
        self.assertIn("УЗАГАЛЬНЕННЯ", build_prompt(review))

    def test_review_lesson_gets_section_topics_from_ktp(self):
        from classroom_assistant.engine import build_calendar
        plan = read_json("Календарні плани.json")["8_iu"]["lessons"]
        lesson = next(x for x in build_calendar() if x.stream == "8-Б ІУ" and x.lesson_number == 18)
        self.assertEqual(lesson.topic, "Тематичне оцінювання")
        prompt = build_prompt(lesson, plan)
        self.assertIn("Походження українського козацтва", prompt)          # №12
        self.assertIn("Козацькі повстання 20–30-х років", prompt)         # №16
        self.assertNotIn("Повсякденне життя і світогляд", prompt)          # №9 — інший розділ
        self.assertIn("ОЦІНЮВАННЯ", prompt)
        ordinary = next(x for x in build_calendar() if x.stream == "8-Б ІУ" and x.lesson_number == 13)
        self.assertNotIn("Теми попередніх уроків", build_prompt(ordinary, plan))

    def test_parse_typical_chatgpt_markdown(self):
        result = parse_answer(sample_answer(self.code), self.code)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["code_ok"])
        material = result["material"]
        self.assertEqual(len(material["sections"]), 6)
        self.assertEqual(material["sections"][0]["heading"], "Розділ про подію 1")
        self.assertIn("• важливий факт першого рівня;", material["sections"][1]["paragraphs"])
        self.assertNotIn("**", " ".join(material["sections"][0]["paragraphs"]))
        self.assertEqual(len(material["notebook"]), 10)
        self.assertIn("уточнення до першого пункту", material["notebook"][0])
        self.assertTrue(all("Якщо потрібно" not in x for x in material["notebook"]))

    def test_homework_and_safety_from_chatgpt_are_ignored(self):
        extra = ("## Домашнє завдання\nПрочитати § 99 (вигадано).\n\n"
                 "## Техніка безпеки\nНе виходьте під час тривоги.\n\nД/з: вигадане\n")
        result = parse_answer(sample_answer(self.code, extra=extra), self.code)
        text = json.dumps(result["material"], ensure_ascii=False)
        self.assertNotIn("§ 99", text)
        self.assertNotIn("Не виходьте", text)
        self.assertNotIn("вигадане", text)

    def test_answer_for_other_lesson_is_rejected(self):
        other = lesson_code(self.lessons[1])
        result = parse_answer(sample_answer(other), self.code)
        self.assertTrue(any("іншого уроку" in e for e in result["errors"]))
        self.assertFalse(looks_like_answer(sample_answer(other), self.code))

    def test_missing_code_only_warns(self):
        answer = sample_answer(self.code).replace(f"**КОД УРОКУ: {self.code}**", "")
        result = parse_answer(answer, self.code)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["warnings"])

    def test_pasted_prompt_is_not_an_answer(self):
        prompt = build_prompt(self.lesson)
        self.assertTrue(parse_answer(prompt, self.code)["errors"])
        self.assertFalse(looks_like_answer(prompt, self.code))

    def test_incomplete_answer_is_rejected(self):
        result = parse_answer(sample_answer(self.code, sections=3, notebook=3), self.code)
        self.assertEqual(len(result["errors"]), 2)

    def test_json_answer_is_accepted(self):
        data = {"sections": [{"heading": f"Р{i}", "paragraphs": [f"Абзац {i} " * 20]}
                             for i in range(6)],
                "notebook": [f"Пункт {i}" for i in range(9)]}
        result = parse_answer(f"КОД УРОКУ: {self.code}\n```json\n{json.dumps(data, ensure_ascii=False)}\n```",
                              self.code)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["material"]["notebook"]), 9)

    def test_clipboard_capture_only_for_this_lesson(self):
        self.assertTrue(looks_like_answer(sample_answer(self.code), self.code))
        self.assertFalse(looks_like_answer("звичайний текст у буфері", self.code))

    def test_word_from_chatgpt_ends_with_exact_ktp_homework(self):
        lesson = self.lessons[2]                        # 8-Г ІУ: у КТП є Д/з
        code = lesson_code(lesson)
        material = parse_answer(sample_answer(code), code)["material"]
        with tempfile.TemporaryDirectory() as folder:
            path = create_word(lesson, Path(folder) / "lesson.docx", material)
            check_real_docx(path)
            texts = [p.text for p in Document(path).paragraphs if p.text.strip()]
        self.assertEqual(texts[-1], "Д/з: " + lesson.homework)
        self.assertIn(NOTEBOOK_HEADING, texts)
        self.assertFalse(any("РОБОЧА ЗАГОТОВКА" in t for t in texts))

    def test_only_https_chatgpt_addresses(self):
        self.assertEqual(safe_chatgpt_url("https://chatgpt.com/g/my-project"),
                         "https://chatgpt.com/g/my-project")
        self.assertEqual(safe_chatgpt_url("javascript:alert(1)"), "https://chatgpt.com/")

    def test_main_window_uses_chatgpt_buttons(self):
        gui = (ROOT / "classroom_assistant" / "gui.py").read_text("utf8")
        self.assertIn("✨ Word-лекція через мій ChatGPT", gui)
        self.assertIn("✨ Лекції ГПТ на весь день", gui)
        self.assertIn("Лекція через мій ChatGPT…", gui)
        self.assertNotIn("налаштувань.\\\\n", gui)


class RealKTPImportTests(unittest.TestCase):
    """Повторний імпорт усіх 15 реальних КТП дає ті самі теми й Д/з, що в програмі."""

    @classmethod
    def setUpClass(cls):
        cls.plans = read_json("Календарні плани.json")
        cls.imported = {}
        by_file = {plan["filename"]: pid for pid, plan in cls.plans.items()}
        for path in SOURCES.glob("*.docx"):
            rows = docx_table_rows(path)
            header = next((r for r in rows[:8] if any("тема" in c.casefold() or "зміст" in c.casefold()
                                                      for c in r)), rows[0])
            topic, homework, number = guess_columns(header)
            lessons = import_source_dates(rows, extract_lessons(rows, topic, homework, number),
                                          topic, number, 2026)
            cls.imported[by_file[path.name]] = lessons

    @staticmethod
    def pairs(lessons):
        return [(tidy(x["topic"]), tidy(x["homework"])) for x in lessons]

    def test_all_plans_match_verified_data(self):
        self.assertEqual(len(self.imported), 15)
        for pid, lessons in self.imported.items():
            expected = self.plans[pid]["lessons"]
            if pid == "8_iu":
                # У поточних даних заголовок блоку «Узагальнення до курсу…» потрапив
                # уроком №51 (з Д/з = назвою блоку). Новий імпорт його не бере.
                expected = [x for x in expected if not x["topic"].startswith("Узагальнення до курсу")]
            with self.subTest(plan=pid):
                self.assertEqual(self.pairs(lessons), self.pairs(expected))

    def test_word_auto_numbering_is_read(self):
        self.assertEqual(len(self.imported["10_vi"]), 35)
        self.assertEqual(len(self.imported["10_iu_profile"]), 105)

    def test_double_lesson_and_repeated_number_kept(self):
        notes = " ".join(import_notes(self.imported["8_iu"]))
        self.assertIn("46-47", notes)
        self.assertIn("30", notes)
        self.assertIn("16 -17", " ".join(import_notes(self.imported["8_go"])))
        partition = next(x for x in self.imported["8_iu"] if x["source_number"] == "46-47")
        self.assertEqual(partition["source_dates"]["8-Б"], "2027-05-07")
        self.assertEqual(partition["source_dates"]["8-Г"], "2027-05-06")

    def test_homework_column_preferred_over_notes(self):
        self.assertEqual(self.imported["10_go"][0]["homework"], "тема1")
        self.assertEqual(guess_columns(["№", "Дата", "Примітка", "Зміст навчального матеріалу", "Д/З"]),
                         (3, 4, 0))

    def test_october_to_december_class_dates_not_january(self):
        self.assertEqual(parse_source_dates("8-Б 04.12. 8-В 04.12. 8-Г 03.12."),
                         {"8-Б": "2026-12-04", "8-В": "2026-12-04", "8-Г": "2026-12-03"})
        self.assertEqual(parse_source_dates("9-Б 02.10. 9-Г 07.10."),
                         {"9-Б": "2026-10-02", "9-Г": "2026-10-07"})
        self.assertEqual(parse_source_dates("8-Б 23.11.2026"), {"8-Б": "2026-11-23"})
        self.assertEqual(parse_source_dates("9-Б 18.01."), {"9-Б": "2027-01-18"})

    def test_class_dates_of_real_plans_are_chronological(self):
        for pid, lessons in self.imported.items():
            classes = {k for x in lessons for k in x.get("source_dates", {})}
            for klass in classes:
                dates = [x["source_dates"][klass] for x in lessons
                         if klass in x.get("source_dates", {})]
                with self.subTest(plan=pid, klass=klass):
                    self.assertEqual(dates, sorted(dates))
                    self.assertTrue("2026-09-01" <= dates[0] and dates[-1] <= "2027-06-30")

    def test_column_numbering_row_is_not_a_lesson(self):
        self.assertTrue(self.imported["11_vi"][0]["topic"].startswith("Ялтинсько"))
        rows = [["№", "Тема", "Д/з"], ["1.", "2.", "3."], ["1", "Перша тема", "§ 1"]]
        self.assertEqual([x["topic"] for x in extract_lessons(rows, 1, 2, 0)], ["Перша тема"])


if __name__ == "__main__":
    unittest.main()
