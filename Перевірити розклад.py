from datetime import date
from collections import Counter
from classroom_assistant.engine import *
schedule=build_calendar()
counts=Counter(l.stream for l in schedule)
config=read_json("Налаштування.json")
plans=read_json("Календарні плани.json")
print("Уроків в активному розкладі:",len(schedule))
for stream in sorted(config["course_map"]):
 n=counts.get(stream,0)
 max_n=len(plans[config["course_map"][stream]["plan"]]["lessons"])
 print(f"{stream:<19} {n:>3} занять / {max_n:>3} тем КТП, залишок {max_n-n}")
print("Жодних публікацій ця команда не робить.")
