# -*- coding: utf-8 -*-
"""Windows EXE entrypoint. Показати помилку вікном, якщо запуск не вдався."""
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":          # лише для збірки на GitHub: перевірити, що .exe справді стартує
        from classroom_assistant.selftest import run
        sys.exit(run(sys.argv[2] if len(sys.argv) > 2 else None))
    try:
        from classroom_assistant.gui import launch
        launch()
    except Exception as exc:
        import os, traceback
        from pathlib import Path
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PomichnykUchyteliaClassroom" / "помилка запуску.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Не вдалося відкрити Помічник учителя",
                                 f"{exc}\n\nДеталі збережено у файлі:\n{path}")
            root.destroy()
        except Exception:
            pass
        raise
