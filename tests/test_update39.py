"""3.9: «Скинути все» і відновлення з копії — звичайні кроки історії («Назад» / «Вперед»)."""
import json
import tempfile
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from test_update36 import TkCase

from classroom_assistant import data_tools, engine, gui, history, samples_ui


class HistoryMetaTests(unittest.TestCase):
    def test_steps_carry_meta_for_undo_and_redo(self):
        h = history.History()
        h.reset("a")
        h.record("b", "скинуто", {"undo_zip": "x.zip", "redo": "reset"})
        self.assertEqual(h.undo(), ("a", "скинуто"))
        self.assertEqual(h.step_meta, {"undo_zip": "x.zip", "redo": "reset"})
        self.assertEqual(h.redo(), ("b", "скинуто"))
        self.assertEqual(h.step_meta["redo"], "reset")
        h.record("c", "інше")
        h.undo()
        self.assertIsNone(h.step_meta)                        # звичайний крок без додаткових відомостей


class ResetThenBackTests(TkCase):
    NEEDS_ROOT = False

    def make_root(self, folder):
        root = Path(folder) / "root"
        data = root / "data"
        data.mkdir(parents=True)
        config = data_tools.blank_config()
        config["course_map"] = {"8-Б ІУ": {"plan": "p", "course_title": "8-Б ІУ"}}
        config["days"]["0"][0] = ["8-Б ІУ", "8-Б ІУ"]
        plans = {"p": {"filename": "ктп.docx", "needs_review": False,
                       "lessons": [{"index": i, "topic": f"Тема {i}", "homework": "§"} for i in range(1, 6)]}}
        (data / "Налаштування.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        (data / "Календарні плани.json").write_text(json.dumps(plans, ensure_ascii=False), encoding="utf-8")
        (data / "Стан.json").write_text(json.dumps({"files": {"k": {"path": "x"}}, "drafts": {"d": {"id": "7"}}},
                                                   ensure_ascii=False), encoding="utf-8")
        (data / "google_token.json").write_text("SECRET", encoding="utf-8")
        (root / "Готові Word" / "2026-10-05").mkdir(parents=True)
        (root / "Готові Word" / "2026-10-05" / "Урок.docx").write_bytes(b"word")
        (root / "Вкладення Classroom").mkdir()
        (root / "Вкладення Classroom" / "картинка.png").write_bytes(b"img")
        return root

    def patched(self, root):
        real_reset, real_restore = data_tools.reset_to_blank, data_tools.restore_from_zip
        real_auto, real_latest = data_tools.auto_backup_path, data_tools.latest_backup
        return [
            mock.patch.object(engine, "DATA", root / "data"),
            mock.patch.object(gui, "DATA", root / "data"),
            mock.patch.object(data_tools, "reset_to_blank",
                              lambda z, **k: real_reset(z, root=root, data_dir=root / "data")),
            mock.patch.object(data_tools, "restore_from_zip", lambda z, s, **k: real_restore(z, s, root=root)),
            mock.patch.object(data_tools, "auto_backup_path", lambda p, *a, **k: real_auto(p, root=root)),
            mock.patch.object(data_tools, "latest_backup", lambda *a, **k: real_latest(root=root)),
        ]

    def run_with(self, root):
        from contextlib import ExitStack
        stack = ExitStack()
        for patcher in self.patched(root):
            stack.enter_context(patcher)
        self.addCleanup(stack.close)
        for name in ("showinfo", "showwarning", "showerror"):
            stack.enter_context(mock.patch.object(gui.messagebox, name))
        stack.enter_context(mock.patch.object(gui.messagebox, "askyesno", return_value=True))
        app = gui.MainApp()

        def close():
            try:
                app.destroy()
            except tk.TclError:
                pass
        self.addCleanup(close)
        return app

    def test_back_after_reset_restores_everything_from_the_automatic_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            app = self.run_with(root)
            word = root / "Готові Word" / "2026-10-05" / "Урок.docx"
            self.assertIn("8-Б ІУ", app.cfg["course_map"])
            app.reset_everything()
            # після скидання програма порожня, а копія є
            self.assertEqual(app.cfg["course_map"], {})
            self.assertFalse(word.exists())
            self.assertFalse((root / "Вкладення Classroom").exists())
            backups = list((root / "Резервні копії").glob("Копія перед скиданням*.zip"))
            self.assertEqual(len(backups), 1)
            self.assertNotIn("google_token.json", zipfile.ZipFile(backups[0]).namelist())
            self.assertTrue((root / "data" / "google_token.json").exists())           # вхід у Google лишився
            # «Назад» доступна й повертає ВСЕ
            self.assertEqual(str(app.undo_button.cget("state")), "normal")
            app.undo()
            self.assertIn("8-Б ІУ", app.cfg["course_map"])
            self.assertEqual(word.read_bytes(), b"word")
            self.assertEqual((root / "Вкладення Classroom" / "картинка.png").read_bytes(), b"img")
            plans = json.loads((root / "data" / "Календарні плани.json").read_text("utf-8"))
            self.assertEqual(len(plans["p"]["lessons"]), 5)
            self.assertEqual(app.state["drafts"], {"d": {"id": "7"}})
            self.assertEqual(str(app.redo_button.cget("state")), "normal")
            self.assertIn("Скасовано: Скинуто все", app.foot.cget("text"))

    def test_forward_resets_again_and_back_works_a_second_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            app = self.run_with(root)
            word = root / "Готові Word" / "2026-10-05" / "Урок.docx"
            app.reset_everything()
            app.undo()
            self.assertTrue(word.exists())
            app.redo()
            self.assertEqual(app.cfg["course_map"], {})
            self.assertFalse(word.exists())
            app.undo()
            self.assertTrue(word.exists())
            self.assertIn("8-Б ІУ", app.cfg["course_map"])

    def test_restore_last_backup_can_itself_be_undone(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            app = self.run_with(root)
            word = root / "Готові Word" / "2026-10-05" / "Урок.docx"
            app.reset_everything()
            app.restore_last_backup()                        # кнопка «Відновити останню копію»
            self.assertTrue(word.exists())
            self.assertIn("8-Б ІУ", app.cfg["course_map"])
            app.undo()                                        # назад до порожньої програми
            self.assertEqual(app.cfg["course_map"], {})
            self.assertFalse(word.exists())
            app.undo()                                        # і ще раз — до стану ДО скидання
            self.assertTrue(word.exists())
            self.assertIn("8-Б ІУ", app.cfg["course_map"])

    def test_my_data_window_reset_and_restore_are_undoable_too(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            app = self.run_with(root)
            word = root / "Готові Word" / "2026-10-05" / "Урок.docx"
            copy = Path(folder) / "моя копія.zip"
            real_reset, real_restore = data_tools.reset_to_blank, data_tools.restore_from_zip
            window = samples_ui.show_data_folder(app)

            def press(text):
                stack = [window]
                while stack:
                    widget = stack.pop()
                    stack.extend(widget.winfo_children())
                    if widget.winfo_class() == "TButton" and text in str(widget.cget("text")):
                        widget.invoke()
                        return
                self.fail(f"кнопки «{text}» немає")
            with mock.patch.object(samples_ui, "reset_to_blank",
                                   lambda z: real_reset(z, root=root, data_dir=root / "data")), \
                    mock.patch.object(samples_ui, "restore_from_zip", lambda z, s: real_restore(z, s, root=root)), \
                    mock.patch.object(samples_ui, "ROOT", root), \
                    mock.patch.object(samples_ui.messagebox, "askyesno", return_value=True), \
                    mock.patch.object(samples_ui.messagebox, "showinfo"), \
                    mock.patch.object(samples_ui.filedialog, "asksaveasfilename",
                                      side_effect=AssertionError("питати, куди зберегти, не треба")), \
                    mock.patch.object(samples_ui.filedialog, "askopenfilename", return_value=str(copy)):
                press("Почати з порожньої програми")
                self.assertEqual(app.cfg["course_map"], {})
                self.assertFalse(word.exists())
                self.assertEqual(len(list((root / "Резервні копії").glob("Копія перед скиданням*.zip"))), 1)
                app.undo()                                      # «Назад» у головному вікні
                self.assertTrue(word.exists())
                self.assertIn("8-Б ІУ", app.cfg["course_map"])
                app.redo()
                self.assertFalse(word.exists())
            window.destroy()

    def test_missing_backup_does_not_break_the_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            app = self.run_with(root)
            app.reset_everything()
            for archive in (root / "Резервні копії").glob("*.zip"):
                archive.unlink()
            with mock.patch.object(gui.messagebox, "showerror") as error:
                app.undo()
            self.assertTrue(error.called)
            self.assertIn("Копію не знайдено", error.call_args.args[1])
            self.assertEqual(app.cfg["course_map"], {})                 # лишаємось у порожній програмі
            self.assertEqual(str(app.undo_button.cget("state")), "normal")   # можна спробувати ще

    def test_ordinary_changes_after_reset_are_still_undone_one_by_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.make_root(folder)
            app = self.run_with(root)
            app.reset_everything()
            app.state["description_overrides"] = {"k": "мій текст"}
            app._history_record()
            app.undo()                                         # скасовує лише текст
            self.assertNotIn("description_overrides", app.state)
            self.assertEqual(app.cfg["course_map"], {})
            app.undo()                                         # а це вже скидання
            self.assertIn("8-Б ІУ", app.cfg["course_map"])


if __name__ == "__main__":
    unittest.main()
