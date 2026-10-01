"""Не обов'язковий AI: API ключ береться лише з OPENAI_API_KEY середовища."""
import json, os, re
def _api_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        import keyring
        return (keyring.get_password("Помічник учителя Classroom", "OPENAI_API_KEY") or "").strip()
    except Exception:
        return ""

def generate_full_lesson(lesson, model="gpt-5"):
    key = _api_key()
    if not key:
        raise RuntimeError("Не налаштовано AI-ключ. У вікні програми натисніть «Початкове налаштування» → «Зберегти AI-ключ». "
                           "Підписка ChatGPT не замінює API-ключ і білінг API.")
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Не встановлено бібліотеку openai. Виконайте pip install -r requirements.txt")
    system=(
        "Ти складаєш повноцінний україномовний навчальний матеріал для шкільного уроку. "
        "Використовуй ТІЛЬКИ тему й домашнє завдання з переданого КТП як доказ того, який урок потрібен. "
        "Для доповнення пояснюй загальновідомі верифіковані факти; не вигадуй зміст невідомого підручника, сторінки або джерела. "
        "Не політизуй історичні оцінки; викладай історичні події збалансовано, з фактами, датами, контекстом і причинно-наслідковими зв'язками. "
        "Давай точні визначення й вікову відповідність; не давай невірних юридичних порад. "
        "Створи 8–12 змістовних тематичних розділів з абзацами (кожен розділ 2–4 повні абзаци) "
        "і план-конспект на 1–2 сторінки з 9–13 повних пунктів, придатних до переписування в зошит. "
        "Не вставляй текст про Zoom, тривогу і Д/з — їх додає програма. "
        "Відповідь ЛИШЕ коректний JSON виду "
        '{"sections":[{"heading":"заголовок","paragraphs":["абзац 1","абзац 2"]}],'
        '"notebook":["пункт 1","пункт 2"]}.'
    )
    response=OpenAI(api_key=key).responses.create(
        model=model,
        input=[{"role":"system","content":system},
            {"role":"user","content":f"Предмет/клас: {lesson.stream}\nДата: {lesson.day}\nТема КТП: {lesson.topic}\nД/з КТП: {lesson.homework}\nСклади урок."}],
    )
    raw=response.output_text.strip()
    if raw.startswith("```"):
        raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw)
    obj=json.loads(raw)
    if len(obj.get("sections",[])) < 5 or len(obj.get("notebook",[])) < 5:
        raise ValueError("Згенерований матеріал неповний — повторіть і перевірте.")
    return obj
