"""Локальна підготовка уроків. Не публікує в Google і не підмінює перевірку."""
import argparse, json, sys
from datetime import date
from pathlib import Path
from .engine import day_lessons, safe_name, ROOT, read_json, html_classroom_text
from .documents import create_word

def prepare(day, with_ai=False):
    output=ROOT/"Готові Word"/day
    output.mkdir(parents=True,exist_ok=True)
    lesson_list=day_lessons(day)
    output_log=[f"Підготовка уроків на {day}",f"Записів за розкладом: {len(lesson_list)}"]
    for lesson in lesson_list:
        material=None
        if with_ai:
            from .ai_writer import generate_full_lesson
            material=generate_full_lesson(lesson,read_json("Налаштування.json").get("ai_model","gpt-5"))
        name=f"{lesson.stream} — {safe_name(lesson)}"
        output_file=create_word(lesson,output/name,material)
        (output/f"{output_file.stem} Classroom.txt").write_text(html_classroom_text(lesson),encoding="utf-8")
        output_log.append(f"{lesson.period}-й урок | {lesson.stream} | КТП №{lesson.lesson_number} | {lesson.topic}")
    (output/"Перелік уроків.txt").write_text("\n".join(output_log)+
     "\n\nВНИМАНИЕ / УВАГА: локальні заготовки не призначені для публікації без перевірки. "
     "Без параметра --ai зміст лекцій не створюється.\n",encoding="utf8")
    return output,lesson_list

def main():
    p=argparse.ArgumentParser(description="Локально підготувати файли на задану дату")
    p.add_argument("--date",default=date.today().isoformat(),help="YYYY-MM-DD")
    p.add_argument("--ai",action="store_true",help="Повна AI-лекція. Потрібен OPENAI_API_KEY; може бути платний API.")
    args=p.parse_args()
    try:
        path,entries=prepare(args.date,args.ai)
        print(f"Готово: {len(entries)} уроків. Файли: {path}")
        if not args.ai:print("ВАЖЛИВО: створені Word є лише ЗАГОТОВКАМИ — не публікувати!")
    except Exception as ex:
        print(f"Помилка: {ex}",file=sys.stderr);sys.exit(1)
if __name__=="__main__":main()
