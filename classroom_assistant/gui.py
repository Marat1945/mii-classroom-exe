"""Вікно локального клієнта. Нічого самовільно не публікує."""
import threading
from datetime import date,timedelta,datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from .engine import read_json, read_state, save_state, day_lessons, week_phase, is_holiday, safe_name, html_classroom_text, DATA, ROOT
from .documents import create_word
from .material_library import (parallel_matches,add_document,attach_document,find_for_lesson,signature_key,stream_subject,check_real_docx)

def display_date(value):
    return date.fromisoformat(value).strftime("%d.%m.%Y")

def parse_date(value):
    value=value.strip()
    if "." in value:return datetime.strptime(value,"%d.%m.%Y").date()
    return date.fromisoformat(value)

def topic_template(text,lesson):
    """Перетворюємо особисті дати/тему/ДЗ в параметризований шаблон."""
    ddmm=lesson.day[8:10]+"."+lesson.day[5:7]
    text=text.replace(lesson.topic,"{topic}").replace(lesson.homework,"{homework}") if lesson.homework else text.replace(lesson.topic,"{topic}")
    text=text.replace(ddmm,"{date}")
    return text

def render_template(text,lesson):
    ddmm=lesson.day[8:10]+"."+lesson.day[5:7]
    out=str(text)
    for key,value in [("{date}",ddmm),("{topic}",lesson.topic),("{homework}",lesson.homework or "не зазначено у КТП"),("{stream}",lesson.stream)]:
        out=out.replace(key,value)
    return out


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Асистент уроків • Classroom • універсальна версія 3.0")
        self.geometry("1250x770")
        self.minsize(1060,630)
        self.cfg=read_json("Налаштування.json")
        self.state=read_state()
        self.rows=[]
        self.google_courses=[]
        self._build()
        self.update_day()

    def _build(self):
        outer=ttk.Frame(self,padding=12)
        outer.pack(fill="both",expand=True)
        hdr=ttk.Frame(outer);hdr.pack(fill="x",pady=(0,8))
        ttk.Label(hdr,text="Дата (ДД.ММ.РРРР):").pack(side="left")
        self.datevar=tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        ttk.Entry(hdr,width=14,textvariable=self.datevar).pack(side="left",padx=6)
        ttk.Button(hdr,text="←",width=4,command=lambda:self.shift(-1)).pack(side="left")
        ttk.Button(hdr,text="→",width=4,command=lambda:self.shift(1)).pack(side="left")
        ttk.Button(hdr,text="Показати уроки",command=self.update_day).pack(side="left",padx=8)
        self.phase=ttk.Label(hdr,text="",font=("Segoe UI",11,"bold"))
        self.phase.pack(side="left",padx=15)

        cols=("№","Час","Потік","Курс Classroom","КТП","Тема","Стан")
        table_frame=ttk.Frame(outer);table_frame.pack(fill="both",expand=True)
        self.grid=ttk.Treeview(table_frame,columns=cols,show="headings",height=11)
        widths=(43,100,140,160,60,510,150)
        for col,width in zip(cols,widths):
            self.grid.heading(col,text=col)
            self.grid.column(col,width=width,minwidth=42,anchor="w")
        sy=ttk.Scrollbar(table_frame,orient="vertical",command=self.grid.yview)
        sx=ttk.Scrollbar(table_frame,orient="horizontal",command=self.grid.xview)
        self.grid.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.grid.grid(row=0,column=0,sticky="nsew")
        sy.grid(row=0,column=1,sticky="ns");sx.grid(row=1,column=0,sticky="ew")
        table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        self.grid.bind("<<TreeviewSelect>>",lambda _:self.select())

        actions=ttk.Frame(outer);actions.pack(fill="x",pady=9)
        for title,callback in [
            ("Word: заготовка",lambda:self.make_word(False)),
            ("Word: повна AI-лекція",lambda:self.make_word(True)),
            ("ВСІ Word за день (AI)",self.batch_ai),
            ("Вибрати готовий Word",self.choose_docx),
            ("Бібліотека Word",self.library_dialog),
            ("Папка Word",self.open_folder),
        ]:
            ttk.Button(actions,text=title,command=callback).pack(side="left",padx=3)
        actions2=ttk.Frame(outer);actions2.pack(fill="x",pady=2)
        ttk.Button(actions2,text="ПОЧАТКОВЕ НАЛАШТУВАННЯ",command=self.setup_dialog).pack(side="left",padx=3)
        ttk.Button(actions2,text="Підключити Google / одержати курси",command=self.get_courses).pack(side="left",padx=3)
        ttk.Button(actions2,text="Зіставити курси",command=self.map_courses).pack(side="left",padx=3)
        ttk.Button(actions2,text="Копіювати повідомлення",command=self.copy_classroom).pack(side="left",padx=3)
        ttk.Button(actions2,text="Зберегти опис уроку",command=self.save_classroom_description).pack(side="left",padx=3)
        ttk.Button(actions2,text="Зберегти шаблон паралелі",command=self.save_parallel_description).pack(side="left",padx=3)
        self.assignment=tk.BooleanVar(value=False)
        ttk.Checkbutton(actions2,text="Це завдання для здавання (не матеріал)",variable=self.assignment).pack(side="left",padx=8)
        ttk.Button(actions2,text="Створити ЧЕРНЕТКУ в Classroom",command=self.draft).pack(side="right",padx=3)
        actions3=ttk.Frame(outer);actions3.pack(fill="x",pady=3)
        ttk.Button(actions3,text="РЕДАКТОР КТП, РОЗКЛАДУ І НАВЧАЛЬНОГО РОКУ",command=self.edit_academic_year).pack(side="left",padx=3)
        ttk.Button(actions3,text="❓ ДОВІДКА",command=self.show_help).pack(side="right",padx=4)
        ttk.Label(actions3,text="Плани • розклад • бібліотека • дзвоники • допомога").pack(side="left",padx=10)
        ttk.Label(outer,text="Повідомлення для Classroom (можна редагувати тут перед створенням чернетки):").pack(anchor="w",pady=(10,1))
        self.desc=tk.Text(outer,height=13,wrap="word",font=("Segoe UI",10))
        self.desc.pack(fill="both",expand=True)
        self.foot=ttk.Label(outer,text="Без авторизації Google програма працює локально. Публікацію заборонено.",foreground="#46576b")
        self.foot.pack(anchor="w",pady=(7,0))

    def shift(self,amount):
        try:d=parse_date(self.datevar.get())+timedelta(days=amount)
        except ValueError:d=date.today()
        self.datevar.set(d.strftime("%d.%m.%Y"))
        self.update_day()

    def update_day(self):
        prior=self.selected().unique_key if getattr(self,"rows",None) and self.grid.selection() else None
        try:
            day=parse_date(self.datevar.get())
            self.rows=day_lessons(day.isoformat(),self.cfg)
        except Exception as ex:
            messagebox.showerror("Дата або КТП",str(ex));return
        for item in self.grid.get_children():self.grid.delete(item)
        off=is_holiday(day,self.cfg)
        self.phase.configure(text=f"{week_phase(day,self.cfg).upper()}"+(" • КАНІКУЛИ: УРОКІВ НЕМАЄ" if off else ""))
        for k,row in enumerate(self.rows):
            item=self.state.get("drafts",{}).get(row.unique_key)
            doc=self.state.get("files",{}).get(row.unique_key,{})
            status=("Чернетка Google" if item else
                    ("Готовий Word" if doc.get("validated") else
                     ("Word потребує перевірки" if doc.get("complete") else
                      ("Word заготовка" if doc else
                       ("Немає Word" if row.status=="готово" else row.status)))))
            self.grid.insert("", "end",iid=str(k),values=(row.period,f"{row.begin}–{row.end}",row.stream,row.course_title,row.lesson_number,row.topic,status))
        self.desc.delete("1.0","end")
        if self.rows:
            chosen=next((str(i) for i,x in enumerate(self.rows) if x.unique_key==prior),"0")
            self.grid.selection_set(chosen)
            self.grid.focus(chosen)
            self.select()
        else:self.foot.config(text="На обрану дату уроків немає (вихідний або канікули).")

    def selected(self):
        selection=self.grid.selection()
        return self.rows[int(selection[0])] if selection else None

    def select(self):
        lesson=self.selected()
        if not lesson:return
        self.desc.delete("1.0","end")
        description=self.state.get("description_overrides",{}).get(lesson.unique_key)
        if description is None:
            templ=self.state.get("parallel_templates",{}).get(signature_key(lesson,self.cfg))
            description=render_template(templ,lesson) if templ is not None else html_classroom_text(lesson,asynchronous=True,video=True)
        self.desc.insert("1.0",description)
        f=self.state.get("files",{}).get(lesson.unique_key,{})
        status=f"Обрано: {lesson.stream}, урок КТП №{lesson.lesson_number}. Джерело: {lesson.source_file}"
        if f: status+=f" | Word: {f['path']} | Перевірено: {f.get('validated',False)}"
        self.foot.config(text=status[:240])

    def worker(self,task,on_success):
        self.config(cursor="watch")
        def run():
            try:
                result=task()
                self.after(0,lambda:self.finish_worker(on_success,result,None))
            except Exception as ex:
                text=str(ex)
                self.after(0,lambda:self.finish_worker(on_success,None,text))
        threading.Thread(target=run,daemon=True).start()

    def finish_worker(self,callback,result,error):
        self.config(cursor="")
        if error:messagebox.showerror("Помилка",error)
        else:callback(result)

    def _parallel(self,lesson):
        return parallel_matches(lesson,self.cfg)

    def _attach_from_master(self,master,lesson,origin,replace_existing=False):
        selected=self._parallel(lesson)
        item=add_document(master,lesson,self.cfg,origin=origin)
        attached=attach_document(item,selected,self.state,replace_existing=replace_existing)
        save_state(self.state)
        self.update_day()
        return attached

    def _parallel_prompt(self,lesson,verb):
        targets=self._parallel(lesson)
        lines=[f"• {x.stream} — {display_date(x.day)} (№{x.lesson_number})" for x in targets]
        shown="\n".join(lines[:18])
        if len(lines)>18:shown+=f"\n... ще {len(lines)-18} уроків"
        return messagebox.askyesno("Єдина лекція для паралелі",
            f"{verb}\n\nАвтоматична прив'язка до сумісної паралелі:\n{shown}\n\n"
            "Перевірте, що лекція повна, тема правильна, а дати/Д/з оновлено.\n"
            "Для відмінної програми або кількості годин перенесення НЕ виконується.\n"
            "Google Classroom НЕ буде опубліковано автоматично.")

    def make_word(self,with_ai):
        lesson=self.selected()
        if not lesson:return
        if lesson.status!="готово":
            messagebox.showerror("КТП","Теми в КТП завершилися або план не перевірено.");return
        if with_ai:
            reusable=find_for_lesson(lesson,self.cfg)
            if reusable is not None:
                if messagebox.askyesno("Економія API","У бібліотеці вже є відповідна лекція.\n\nВикористати її без платного AI-запиту?"):
                    attached=attach_document(reusable,self._parallel(lesson),self.state)
                    save_state(self.state);self.update_day()
                    messagebox.showinfo("Безкоштовне повторне використання",f"Прив'язано уроків: {len(attached)}.")
                    return
            if not self._parallel_prompt(lesson,"Створити ОДНУ платну AI-лекцію?"):
                return
        else:
            if not messagebox.askyesno("Word-заготовка","Створити ТІЛЬКИ порожню заготовку? Учням її надсилати НЕ можна."):
                return
        destination=ROOT/"Готові Word"/lesson.day/safe_name(lesson)
        def task():
            material=None
            if with_ai:
                from .ai_writer import generate_full_lesson
                material=generate_full_lesson(lesson,self.cfg.get("ai_model","gpt-5"))
            return create_word(lesson,destination,material)
        def done(path):
            if with_ai:
                attached=self._attach_from_master(path,lesson,"AI")
                messagebox.showinfo("AI-лекція готова",
                    f"Лекцію збережено в бібліотеці й автоматично прив'язано до {len(attached)} сумісних уроків.\n"
                    "У Classroom поки нічого не створено. Перевірте всі дати, історичні факти й Д/з "
                    "перед створенням чернеток.")
            else:
                self.state.setdefault("files",{})[lesson.unique_key]={
                    "path":str(path),"validated":False,"complete":False}
                save_state(self.state);self.update_day()
                messagebox.showwarning("Word-заготовка","Це НЕ готова лекція. Не надсилайте її учням.")
        self.worker(task,done)

    def batch_ai(self):
        lessons=[i for i in self.rows if i.status=="готово"]
        if not lessons:
            messagebox.showinfo("Розклад","На цю дату немає уроків із перевіреними КТП.");return
        pending=[]
        seen=set()
        for lesson in lessons:
            key=(signature_key(lesson,self.cfg),lesson.lesson_number,
                 lesson.topic.casefold().strip())
            if lesson.unique_key in self.state.get("files",{}) or key in seen:
                continue
            seen.add(key);pending.append(lesson)
        if not pending:
            messagebox.showinfo("Економія API","Усі обрані уроки вже мають Word. Повторної оплати не потрібно.")
            return
        if not messagebox.askyesno("Пакетна генерація",
              f"Максимум {len(pending)} AI-запитів. Спершу програма повторно використає те, "
              "що є у бібліотеці.\n\nПісля генерації одна лекція підійде тільки "
              "сумісним класам із тією ж темою, програмою та годинами.\nПродовжити?"):
            return
        def task():
            made=[]
            from .ai_writer import generate_full_lesson
            for lesson in pending:
                existing=find_for_lesson(lesson,self.cfg)
                if existing is not None:
                    made.append((lesson,existing))
                    continue
                material=generate_full_lesson(lesson,self.cfg.get("ai_model","gpt-5"))
                destination=ROOT/"Готові Word"/lesson.day/safe_name(lesson)
                path=create_word(lesson,destination,material)
                item=add_document(path,lesson,self.cfg,origin="AI")
                made.append((lesson,item))
            return made
        def done(items):
            n=0
            for lesson,item in items:
                n+=len(attach_document(item,self._parallel(lesson),self.state))
            save_state(self.state);self.update_day()
            messagebox.showinfo("Пакетна підготовка",
                f"Опрацьовано тематичних груп: {len(items)}. Прив'язок: {n}.\n"
                "Перед створенням чернеток відкрийте Word і перевірте вміст.")
        self.worker(task,done)

    def choose_docx(self):
        lesson=self.selected()
        if not lesson:return
        path=filedialog.askopenfilename(title="Виберіть ГОТОВИЙ ПОВНИЙ Word (.docx)",
                                        filetypes=[("Word","*.docx")])
        if not path:return
        try:check_real_docx(path)
        except Exception as ex:
            messagebox.showerror("Неправильний Word",str(ex));return
        if not self._parallel_prompt(lesson,"Вибрано ваш готовий Word. Вважаєте його перевіреним і бажаєте прив'язати?"):
            return
        try:targets=self._attach_from_master(path,lesson,"власний Word",replace_existing=True)
        except Exception as ex:messagebox.showerror("Word",str(ex));return
        messagebox.showinfo("Word готовий",
            f"Документ прийнято в бібліотеку.\nПрив'язано до {len(targets)} уроків.\n"
            "Повторно натискати «Підтвердити Word» НЕ потрібно. "
            "Classroom не змінено.")

    def library_dialog(self):
        from .material_library import load_index,signature,norm
        lesson=self.selected()
        if not lesson:return
        sig=signature(lesson,self.cfg)
        matching=[item for item in load_index()['items']
                  if item['signature']==sig and item['topic_norm']==norm(lesson.topic)
                  and Path(item['path']).is_file()]
        if not matching:
            messagebox.showinfo("Бібліотека","Відповідної лекції немає. Натисніть «Вибрати готовий Word», щоб додати її.");return
        win=tk.Toplevel(self);win.title("Бібліотека перевірених лекцій");win.geometry("800x360")
        ttk.Label(win,text="Показано лише лекції з тим самим предметом, програмою, годинами і темою.").pack(anchor="w",padx=12,pady=8)
        box=tk.Listbox(win,height=9)
        box.pack(fill="both",expand=True,padx=12,pady=10)
        for item in matching:box.insert("end",f"{item['topic'][:82]} · {item['added']} · {item['origin']}")
        box.selection_set(0)
        def apply():
            ids=box.curselection()
            if not ids:return
            item=matching[ids[0]]
            if not self._parallel_prompt(lesson,"Використати цей раніше перевірений Word без додаткової оплати?"):
                return
            attached=attach_document(item,self._parallel(lesson),self.state)
            save_state(self.state);self.update_day();win.destroy()
            messagebox.showinfo("Бібліотека",f"Прив'язано уроків: {len(attached)}.")
        ttk.Button(win,text="Використати для паралелі",command=apply).pack(pady=6)

    def validate_docx(self):
        lesson=self.selected()
        if not lesson:return
        doc=self.state.get("files",{}).get(lesson.unique_key)
        if not doc:messagebox.showwarning("Немає файлу","Спочатку створіть або виберіть Word.");return
        if not doc.get("complete"):
            messagebox.showwarning("Неповний документ","Це лише заготовка. Виберіть готову лекцію або згенеруйте повну лекцію через AI.");return
        if not Path(doc["path"]).exists():
            messagebox.showerror("Файл", "Word-файл не знайдено");return
        if messagebox.askyesno("Перевірка","Ви переглянули Word повністю, перевірили точність матеріалу, план-конспект і Д/з?"):
            doc["validated"]=True;save_state(self.state);self.update_day()

    def open_folder(self):
        lesson=self.selected()
        f=self.state.get("files",{}).get(lesson.unique_key) if lesson else None
        path=Path(f["path"]).parent if f else ROOT/"Готові Word"
        path.mkdir(parents=True,exist_ok=True)
        import os,subprocess,sys
        if sys.platform=="win32":os.startfile(str(path))
        elif sys.platform=="darwin":subprocess.Popen(["open",str(path)])
        else:subprocess.Popen(["xdg-open",str(path)])

    def copy_classroom(self):
        content=self.desc.get("1.0","end").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update()
            messagebox.showinfo("Classroom", "Повідомлення скопійоване.")

    def save_classroom_description(self):
        lesson=self.selected()
        if lesson is None:return
        description=self.desc.get("1.0","end").strip()
        if not description:
            messagebox.showwarning("Classroom","Опис уроку не може бути порожнім.")
            return
        self.state.setdefault("description_overrides",{})[lesson.unique_key]=description
        save_state(self.state)
        messagebox.showinfo("Опис збережено","Текст опису збережено для цього уроку на цьому комп'ютері. У Classroom його ще НЕ надіслано.")

    def save_parallel_description(self):
        lesson=self.selected()
        if not lesson:return
        text=self.desc.get("1.0","end").strip()
        if not text:
            messagebox.showerror("Опис","Текст не може бути порожнім.");return
        template=topic_template(text,lesson)
        if "{topic}" not in template or "{date}" not in template or "{homework}" not in template:
            if not messagebox.askyesno("Динамічні поля",
                "Не всі змінні {topic}, {date}, {homework} є в тексті. "
                "Це може перенести стару дату або Д/з в інші класи. Зберегти?"):
                return
        if not messagebox.askyesno("Шаблон паралелі",
             "Застосувати відредагований шаблон до тієї ж паралелі з однаковою "
             "програмою та кількістю годин? Змінні тема/дата/Д/з будуть підставлятися окремо."):
            return
        self.state.setdefault("parallel_templates",{})[signature_key(lesson,self.cfg)]=template
        # User asked to save parallel format; drop this lesson's local override so it also uses template.
        self.state.setdefault("description_overrides",{}).pop(lesson.unique_key,None)
        save_state(self.state)
        messagebox.showinfo("Шаблон збережено",
                            "Збережено для сумісної паралелі. Під час вибору іншого "
                            "класу буде підставлено його дату, тему та Д/з.")
        self.select()

    def show_help(self):
        from .help_ui import show_help
        show_help(self)

    def edit_academic_year(self):
        from .editor_ui import SchoolEditor
        SchoolEditor(self,self.update_day)

    def setup_dialog(self):
        """Настроювання без ручного копіювання JSON або змінних середовища."""
        import json
        import shutil
        from tkinter import simpledialog
        dlg=tk.Toplevel(self)
        dlg.title("Перший запуск • Google та AI")
        dlg.geometry("760x475")
        dlg.transient(self)
        text=(
            "РОЗКЛАД І КТП вже працюють локально, навіть без налаштувань.\\n\\n"
            "GOOGLE CLASSROOM: потрібен одноразовий дозвіл Google (OAuth). "
            "Спочатку у власному Google Cloud проєкті створіть OAuth Client ID типу "
            "Desktop app і увімкніть Classroom API та Drive API. Завантажений JSON "
            "імпортуйте кнопкою нижче; далі натисніть «Підключити Google». "
            "Сервісний JSON із Google Cloud містить ідентифікатор програми, "
            "а НЕ пароль вашого акаунта. Нікому не пересилайте токен доступу.\\n\\n"
            "AI-ЛЕКЦІЇ: для їх генерації потрібен ваш власний OpenAI API-ключ "
            "(оплата API окрема від підписки ChatGPT). Ключ зберігається "
            "в захищеному сховищі облікових даних Windows. Без ключа можна "
            "переглядати календар, отримувати тексти Classroom та прикріплювати "
            "готові Word вручну.\\n\\n"
            "БЕЗПЕКА: програма ніколи сама не опублікує матеріал; у Classroom "
            "створює тільки ЧЕРНЕТКИ і тільки після вашого підтвердження."
        )
        label=tk.Text(dlg,wrap="word",height=15,padx=16,pady=14,font=("Segoe UI",10))
        label.insert("1.0",text)
        label.configure(state="disabled",bg="#f3f6fa",relief="flat")
        label.pack(fill="both",expand=True,padx=10,pady=10)
        buttons=ttk.Frame(dlg)
        buttons.pack(fill="x",padx=10,pady=8)

        def import_credentials():
            path=filedialog.askopenfilename(
                parent=dlg,title="Оберіть OAuth JSON із Google Cloud",
                filetypes=[("JSON","*.json"),("Усі файли","*.*")]
            )
            if not path: return
            try:
                content=json.loads(Path(path).read_text(encoding="utf-8-sig"))
                details=content.get("installed")
                if not isinstance(details,dict) or not all(k in details for k in ("client_id","auth_uri","token_uri")):
                    raise ValueError("Це не OAuth Desktop JSON. Потрібен файл клієнта типу «Desktop app».")
                DATA.mkdir(parents=True,exist_ok=True)
                target=DATA/"google_credentials.json"
                shutil.copyfile(path,target)
                messagebox.showinfo("OAuth", "Google OAuth налаштування імпортовано. Тепер натисніть «Підключити Google / одержати курси» у головному вікні.",parent=dlg)
            except Exception as ex:
                messagebox.showerror("Google OAuth",str(ex),parent=dlg)

        def save_key():
            from .editor_ui import api_key_dialog
            api_key_dialog(dlg)

        ttk.Button(buttons,text="Імпортувати Google OAuth JSON",command=import_credentials).pack(side="left",padx=5)
        ttk.Button(buttons,text="Зберегти AI-ключ",command=save_key).pack(side="left",padx=5)
        ttk.Button(buttons,text="Закрити",command=dlg.destroy).pack(side="right",padx=5)

    def get_courses(self):
        def task():
            from .google_client import list_teacher_courses
            return list_teacher_courses()
        def done(courses):
            self.google_courses=courses
            messagebox.showinfo("Google Classroom",f"Отримано курсів: {len(courses)}. Тепер натисніть «Зіставити курси».")
            self.map_courses()
        self.worker(task,done)

    def map_courses(self):
        if not self.google_courses:
            messagebox.showinfo("Курси","Спочатку натисніть «Підключити Google / одержати курси».");return
        dialog=tk.Toplevel(self);dialog.title("Зіставлення місцевих потоків і Google Classroom")
        dialog.geometry("850x600")
        ttk.Label(dialog,text="Кожен потік або об'єднаний курс зіставте з курсом Google. Порожній рядок не публікується.").pack(anchor="w",padx=12,pady=10)
        wrap=ttk.Frame(dialog);wrap.pack(fill="both",expand=True)
        canvas=tk.Canvas(wrap)
        bar=ttk.Scrollbar(wrap,orient="vertical",command=canvas.yview)
        frame=ttk.Frame(canvas)
        frame.bind("<Configure>",lambda _ :canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=frame,anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left",fill="both",expand=True);bar.pack(side="right",fill="y")
        choices=["— не вибрано —"]+[f"{c['name']} [{c['id']}]" for c in self.google_courses]
        vars={}
        known_ids=self.state.get("course_ids",{})
        for i,title in enumerate(self.cfg["classroom_course_titles"]):
            ttk.Label(frame,text=title,width=23).grid(row=i,column=0,padx=10,pady=4,sticky="w")
            var=tk.StringVar()
            box=ttk.Combobox(frame,textvariable=var,values=choices,width=69,state="readonly")
            target=known_ids.get(title)
            matched=next((choice for choice,c in zip(choices[1:],self.google_courses) if str(c["id"])==str(target)),None)
            if not matched:
                exact=[choice for choice,c in zip(choices[1:],self.google_courses) if c["name"].strip().casefold()==title.strip().casefold()]
                matched=exact[0] if len(exact)==1 else choices[0]
            box.set(matched);box.grid(row=i,column=1,padx=7,pady=4,sticky="ew")
            vars[title]=var
        def save():
            mapped={}
            for title,var in vars.items():
                for c in self.google_courses:
                    if var.get()==f"{c['name']} [{c['id']}]":
                        mapped[title]=str(c["id"]);break
            self.state["course_ids"]=mapped;save_state(self.state)
            dialog.destroy()
            messagebox.showinfo("Збережено",f"Зіставлено курсів: {len(mapped)}/{len(vars)}")
        ttk.Button(dialog,text="Зберегти зіставлення",command=save).pack(pady=9)

    def draft(self):
        lesson=self.selected()
        if not lesson:return
        if lesson.status!="готово":
            messagebox.showerror("КТП","Цей урок не готовий: спочатку імпортуйте та перевірте календарний план поточного року.")
            return
        key=lesson.unique_key
        if key in self.state.get("drafts",{}):
            messagebox.showerror("Дублікат","Для цього уроку вже створено чернетку Classroom. Повторне створення заблоковано.");return
        f=self.state.get("files",{}).get(key)
        if not f or not f.get("validated"):
            messagebox.showerror("Перевірка","Потрібен ГОТОВИЙ і перевірений Word. Заготовка не підходить.");return
        course_id=self.state.get("course_ids",{}).get(lesson.course_title)
        if not course_id:
            messagebox.showerror("Classroom","Цей курс ще не зіставлено з Google Classroom.");return
        text=self.desc.get("1.0","end").strip()
        assignment=self.assignment.get()
        confirm=("Створити ТІЛЬКИ ЧЕРНЕТКУ?\n\n"
                 f"Курс: {lesson.course_title}\nДата уроку: {lesson.day}\n"
                 f"Тема: {lesson.topic[:110]}\n\n"
                 "Відео потрібно додати вручну перед публікацією.")
        if not messagebox.askyesno("Підтвердження",confirm):return
        def task():
            from .google_client import create_draft
            return create_draft(course_id,
                f"Урок {lesson.day[8:10]}.{lesson.day[5:7]} — {lesson.topic}. "
                "(Асинхронно — без виходу у Zoom у зв’язку з довготривалою повітряною тривогою і загрозою для життя і здоров’я)",
                 text,f["path"],assignment)
        def done(result):
            self.state.setdefault("drafts",{})[key]=result
            save_state(self.state);self.update_day()
            messagebox.showinfo("Чернетка створена",f"ID: {result['id']}\nСтан: DRAFT\nУчні її поки НЕ бачать.")
        self.worker(task,done)

def launch():
    MainApp().mainloop()
