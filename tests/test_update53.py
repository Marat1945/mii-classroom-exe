"""5.5.1: самоперевірка зібраної програми й файл збірки, що не випускає зламаний .exe (помилка «No module named 'docx'»)."""
import ast
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from classroom_assistant import materials, selftest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Запустити Windows EXE.py"


def workflow():
    text = (ROOT / ".github" / "workflows" / "Windows_EXE.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["jobs"]["build"]["steps"]


def step(name_start):
    return next(s for s in workflow() if s["name"].startswith(name_start))


class SelfTestTests(unittest.TestCase):
    def test_a_healthy_program_passes_and_writes_a_readable_report(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "звіт.txt"
            self.assertEqual(selftest.run(report), 0)
            text = report.read_text(encoding="utf-8")
        self.assertIn("OK  імпорт docx", text)
        self.assertIn("OK  імпорт classroom_assistant.gui", text)
        self.assertIn("довідників PDF у збірці: 6", text)
        self.assertTrue(text.rstrip().endswith("ПІДСУМОК: УСПІХ"))

    def test_a_missing_library_makes_it_fail_and_names_the_library(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(selftest, "REQUIRED_LIBRARIES", selftest.REQUIRED_LIBRARIES + ("бібліотеки_немає",)):
            report = Path(folder) / "звіт.txt"
            self.assertEqual(selftest.run(report), 1)
            text = report.read_text(encoding="utf-8")
        self.assertIn("FAIL  імпорт бібліотеки_немає", text)
        self.assertIn("ПІДСУМОК: ПОМИЛКА", text)

    def test_the_exact_failure_from_the_screenshot_is_caught(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(sys.modules, {"docx": None}):
            for name in [n for n in sys.modules if n.startswith("classroom_assistant.documents")]:
                sys.modules.pop(name)
            report = Path(folder) / "звіт.txt"
            code = selftest.run(report)
            text = report.read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("імпорт docx", text)
        self.assertIn("ПОМИЛКА", text)

    def test_missing_books_are_only_a_warning_so_a_build_is_never_blocked_by_them(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as empty, \
                mock.patch.object(materials, "bundled_dir", return_value=Path(empty)):
            report = Path(folder) / "звіт.txt"
            self.assertEqual(selftest.run(report), 0)
            text = report.read_text(encoding="utf-8")
        self.assertIn("WARN  довідників PDF у збірці: 0", text)
        self.assertTrue(text.rstrip().endswith("УСПІХ"))

    def test_without_a_file_the_report_goes_to_the_screen(self):
        with mock.patch("builtins.print") as shown:
            self.assertEqual(selftest.run(None), 0)
        self.assertIn("ПІДСУМОК: УСПІХ", shown.call_args[0][0])

    def test_the_flag_is_recognised_only_in_the_right_place(self):
        self.assertTrue(selftest.requested(["exe", "--self-test", "a.txt"]))
        self.assertFalse(selftest.requested(["exe"]))
        self.assertFalse(selftest.requested(["exe", "щось"]))


class LauncherTests(unittest.TestCase):
    def run_launcher(self, prologue=""):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "звіт.txt"
            code = (f"import sys, runpy\n{prologue}\nsys.argv = ['exe', '--self-test', r'{report}']\n"
                    f"runpy.run_path(r'{LAUNCHER}', run_name='__main__')")
            done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
            return done.returncode, report.read_text(encoding="utf-8") if report.exists() else ""

    def test_the_real_launcher_starts_the_self_test_without_opening_any_window(self):
        code, text = self.run_launcher()
        self.assertEqual(code, 0, text)
        self.assertIn("ПІДСУМОК: УСПІХ", text)

    def test_the_real_launcher_exits_with_an_error_when_docx_is_missing(self):
        code, text = self.run_launcher("sys.modules['docx'] = None")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  імпорт docx", text)


class BuildFileTests(unittest.TestCase):
    def test_the_build_checks_libraries_then_builds_then_starts_the_exe_before_publishing_it(self):
        names = [s["name"] for s in workflow()]
        order = ["Install build dependencies", "Verify that every library is installed", "Build Windows EXE",
                 "Smoke test the EXE", "Check the icon inside the EXE", "Save finished EXE"]
        positions = [next(i for i, n in enumerate(names) if n.startswith(o)) for o in order]
        self.assertEqual(positions, sorted(positions))

    def test_the_exe_must_pass_its_own_self_test_or_the_build_turns_red(self):
        smoke = step("Smoke test the EXE")
        self.assertEqual(smoke["shell"], "pwsh")
        self.assertNotIn("continue-on-error", smoke)                                      # не «м'яка» перевірка
        for needle in ("--self-test", "-Wait -PassThru", "ExitCode -ne 0", "exit 1", "dist/Pomichnyk_Uchytelia.exe"):
            self.assertIn(needle, smoke["run"], needle)

    def test_the_library_check_stops_the_build_and_names_what_is_missing(self):
        check = step("Verify that every library")
        self.assertEqual(check["shell"], "python")
        ast.parse(check["run"])
        self.assertIn("sys.exit(1)", check["run"])
        self.assertIn("НЕ ВСТАНОВЛЕНО", check["run"])
        code = check["run"]
        good = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("Усі бібліотеки на місці", good.stdout)
        bad = subprocess.run([sys.executable, "-c", "import sys; sys.modules['docx'] = None\n" + code],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("python-docx", bad.stdout)

    def test_the_libraries_are_installed_twice_over_so_a_damaged_requirements_file_cannot_break_the_build(self):
        install = step("Install build dependencies")["run"]
        listed = set(re.findall(r'"([^"]+)"', install))
        wanted = {line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.strip()}
        self.assertEqual(listed, wanted)                                                  # список у файлі збірки = requirements.txt
        self.assertIn("-r requirements.txt", install)

    def test_every_library_the_self_test_demands_is_in_requirements(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower().replace("-", "_")
        names = {"docx": "python_docx", "PIL": "pillow", "googleapiclient": "google_api_python_client",
                 "google_auth_oauthlib": "google_auth_oauthlib", "google_auth_httplib2": "google_auth_httplib2",
                 "openai": "openai", "keyring": "keyring", "tkinterdnd2": "tkinterdnd2"}
        for module in selftest.REQUIRED_LIBRARIES:
            if module in names:
                self.assertIn(names[module], text, module)

    def test_the_visible_copy_of_the_build_file_is_identical(self):
        real = (ROOT / ".github" / "workflows" / "Windows_EXE.yml").read_text(encoding="utf-8")
        copy = (ROOT / "Windows_EXE.yml").read_text(encoding="utf-8")
        self.assertEqual(copy.split("\n", 1)[1], real)


if __name__ == "__main__":
    unittest.main()
