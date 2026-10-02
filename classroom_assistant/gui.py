"""Вікно локального клієнта. Нічого самовільно не публікує."""
import threading
import shutil
from dataclasses import replace as dataclass_replace
from datetime import date,timedelta,datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from .engine import read_json, read_state, save_state, day_lessons, build_calendar, week_phase, is_holiday, safe_name, word_path, html_classroom_text, DATA, ROOT
from .documents import create_word
from .material_library import (parallel_matches,add_document,attach_document,find_for_lesson,signature_key,signature,stream_subject,check_real_docx,copy_for_lesson)
from .attachments import add_attachments, files_for_lesson, copy_attachments, remove_attachment
from .window_ui import maximize_work_window, fit_work_window
from .ui_kit import AccentButton
from .hotkeys import install_hotkeys
from .theme import apply_theme, make_banner
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    WindowBase = TkinterDnD.Tk
except ImportError:
    DND_FILES=None
    WindowBase=tk.Tk


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


WEEKDAYS_UA=("ПОНЕДІЛОК","ВІВТОРОК","СЕРЕДА","ЧЕТВЕР","П’ЯТНИЦЯ","СУБОТА","НЕДІЛЯ")

def weekday_ua(value):
    return WEEKDAYS_UA[parse_date(value).weekday()]

class MainApp(WindowBase):
    def __init__(self):
        super().__init__()
        self.title("Асистент уроків • Classroom • універсальна версія 3.6")
        self.geometry("1250x770")
        self.minsize(1060,630)
        maximize_work_window(self)
        self.cfg=read_json("Налаштування.json")
        self.state=read_state()
        self.escape_closes=False
        apply_theme(self)
        install_hotkeys(self)
        make_banner(self,"🎓  Помічник учителя Classroom",
                    "розклад  •  календарні плани  •  лекції через ChatGPT  •  чернетки Google Classroom"
                    ).pack(fill="x")
        self._sync_running=False
        self.rows=[]
        self.google_courses=[]
        # Дані лише для перегляду, не змінюють локальні КТП і Google-чернетки.
        self.remote_classroom_entries={}
        self._build()
        self.update_day()
        # Одразу після запуску підтягнути актуальний стан Classroom (без вікна входу).
        self.after(1500,lambda:self.sync_classroom(interactive=False))

    def _build(self):
        outer=ttk.Frame(self,padding=12)
        outer.pack(fill="both",expand=True)
        hdr=ttk.Frame(outer);hdr.pack(fill="x",pady=(0,8))
        ttk.Label(hdr,text="Дата (ДД.ММ.РРРР):").pack(side="left")
        self.datevar=tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self._date_refresh_id=None
        self.datevar.trace_add("write",self._on_date_text_change)
        date_entry=ttk.Entry(hdr,width=14,textvariable=self.datevar)
        date_entry.pack(side="left",padx=6)
        date_entry.bind("<Return>",lambda _:self.update_day())
        self.weekday=ttk.Label(hdr,text="",font=("Segoe UI",11,"bold"),foreground="#245A7C",width=13)
        self.weekday.pack(side="left",padx=(5,8))
        ttk.Button(hdr,text="←",width=4,command=lambda:self.shift(-1)).pack(side="left")
        ttk.Button(hdr,text="→",width=4,command=lambda:self.shift(1)).pack(side="left")
        ttk.Button(hdr,text="ПОЧАТКОВЕ НАЛАШТУВАННЯ",
                   command=self.setup_dialog).pack(side="left",padx=(16,0))
        self.phase=ttk.Label(hdr,text="",font=("Segoe UI",11,"bold"))
        self.phase.pack(side="left",padx=15)
        ttk.Button(hdr,text="Підключити Google / одержати курси",
                   command=self.connect_google).pack(side="left")
        ttk.Button(hdr,text="🗂 Мої дані",command=self.data_dialog).pack(side="right")
        ttk.Button(hdr,text="📄 Зразки документів",
                   command=self.samples_dialog).pack(side="right",padx=6)

        cols=("№","Час","Потік","Курс Classroom","Тема","КТП","Стан")
        self.grid_columns=cols
        table_frame=ttk.Frame(outer);table_frame.pack(fill="both",expand=True)
        self.grid=ttk.Treeview(table_frame,columns=cols,show="headings",
                                selectmode="extended",height=11)
        widths=(43,100,140,160,510,60,150)
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
        self.grid.bind("<Button-3>",self._open_lesson_menu)
        # Enter на виділеному рядку = «Створити ЧЕРНЕТКУ в Classroom» (з підтвердженням).
        self.grid.bind("<Return>",self._enter_creates_draft)
        self.grid.bind("<KP_Enter>",self._enter_creates_draft)
        self.background_menu=self._open_day_menu
        self.grid.bind("<Control-c>",lambda e:self.copy_selected_lessons_as_text())
        self.grid.bind("<Delete>",lambda e:self.remove_selected_local_materials())
        self.grid.bind("<ButtonPress-1>",self._column_drag_start,add="+")
        self.grid.bind("<ButtonRelease-1>",self._column_drag_end,add="+")
        preferred=self.state.get("column_order")
        if (isinstance(preferred,list) and len(preferred)==len(cols)
                and set(preferred)==set(cols)):
            self.grid.configure(displaycolumns=preferred)
        else:self.grid.configure(displaycolumns=cols)
        self._column_start=None
        if DND_FILES:
            self.grid.drop_target_register(DND_FILES)
            self.grid.tag_configure("file-drop-hover",
                                    background="#FFE49A",foreground="#26364D")
            self._hover_lesson_item=None
            self.grid.dnd_bind("<<DropEnter>>",self._highlight_drop_lesson)
            self.grid.dnd_bind("<<DropPosition>>",self._highlight_drop_lesson)
            self.grid.dnd_bind("<<DropLeave>>",self._clear_drop_lesson)
            self.grid.dnd_bind("<<Drop>>",self._drop_on_lesson)

        actions=ttk.Frame(outer);actions.pack(fill="x",pady=9)
        AccentButton(actions,"✨ Word-лекція через мій ChatGPT",
                     self.chatgpt_word).pack(side="left",padx=(3,4))
        AccentButton(actions,"✨ Лекції ГПТ на весь день",self.chatgpt_batch,
                     color="#2E8B57",hover="#3AA36B").pack(side="left",padx=4)
        for title,callback in [
            ("Word: заготовка",lambda:self.make_word(False)),
            ("Вибрати готовий Word",self.choose_docx),
            ("Бібліотека Word",self.library_dialog),
            ("Папка Word",self.open_folder),
        ]:
            ttk.Button(actions,text=title,command=callback).pack(side="left",padx=3)
        actions2=ttk.Frame(outer);actions2.pack(fill="x",pady=2)
        ttk.Button(actions2,text="Зіставити курси",command=self.map_courses).pack(side="left",padx=3)
        ttk.Button(actions2,text="Зберегти шаблон паралелі",command=self.save_parallel_description).pack(side="left",padx=3)
        self.assignment=tk.BooleanVar(value=False)
        ttk.Checkbutton(actions2,text="Це завдання для здавання (не матеріал)",variable=self.assignment).pack(side="left",padx=8)
        ttk.Button(actions2,text="Створити ЧЕРНЕТКУ в Classroom",command=self.draft).pack(side="right",padx=3)
        actions3=ttk.Frame(outer);actions3.pack(fill="x",pady=3)
        self.batch_drafts_button=ttk.Button(
            actions3,text="СТВОРИТИ ЧЕРНЕТКИ ДЛЯ ВСІХ УРОКІВ ЦЬОГО ДНЯ",
            command=self.batch_drafts)
        self.batch_drafts_button.pack(side="right",padx=6)
        self._batch_drafts_running=False
        ttk.Button(actions3,text="РЕДАКТОР КТП, РОЗКЛАДУ І НАВЧАЛЬНОГО РОКУ",command=self.edit_academic_year).pack(side="left",padx=3)
        ttk.Button(actions3,text="❓ ДОВІДКА",command=self.show_help).pack(side="right",padx=4)
        ttk.Button(actions3,text="МІЙ CLASSROOM — ПЕРЕГЛЯД",
                   command=self.view_classroom).pack(side="right",padx=4)
        ttk.Label(actions3,text="Плани • розклад • бібліотека • дзвоники • допомога").pack(side="left",padx=10)
        ttk.Label(outer,text="Повідомлення для Classroom (можна редагувати тут перед створенням чернетки):").pack(anchor="w",pady=(10,1))
        self.desc=tk.Text(outer,height=13,wrap="word",font=("Segoe UI",10))
        self.desc.pack(fill="both",expand=True)
        self.desc.bind("<Button-3>",self._description_context_menu)
        self.attachment_toolbar=ttk.Frame(outer)
        self.attachment_toolbar.pack(fill="x",pady=(5,2))
        ttk.Button(self.attachment_toolbar,text="📎 Додати файли до Classroom",
                   command=self.choose_attachments).pack(side="left",padx=(0,10))
        self.drop_hint=ttk.Label(self.attachment_toolbar,
              text=("Перетягніть файли сюди або в поле опису" if DND_FILES else
                    "Для прикріплення натисніть «Додати файли»"),
              foreground="#245A7C")
        self.drop_hint.pack(side="left")
        self.attachment_bar=ttk.Frame(outer)
        self.attachment_bar.pack(fill="x",pady=(2,4))
        self._preview_images=[]
        if DND_FILES:
            self._desc_original_bg=self.desc.cget("background")
            normal_style=ttk.Style(self)
            normal_style.configure("TeacherHoverDrop.TLabel",
                                    background="#FFE49A",foreground="#173657")
            for widget in (self.desc,self.drop_hint,self.attachment_bar,self.attachment_toolbar):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>",self._highlight_description_drop)
                widget.dnd_bind("<<DropPosition>>",self._highlight_description_drop)
                widget.dnd_bind("<<DropLeave>>",self._clear_description_drop)
                widget.dnd_bind("<<Drop>>",self._receive_files)
        self.foot=ttk.Label(outer,text="Без авторизації Google програма працює локально. Публікацію заборонено.",foreground="#46576b")
        self.foot.pack(anchor="w",pady=(7,0))

    def _on_date_text_change(self,*_unused):
        """Відобразити уроки після введення ПОВНОЇ правильної дати."""
        pending=getattr(self,"_date_refresh_id",None)
        if pending is not None:
            self.after_cancel(pending)
        def refresh():
            self._date_refresh_id=None
            try:day=parse_date(self.datevar.get())
            except (ValueError,TypeError):return
            if day.year<2020 or day.year>2100:return
            if hasattr(self,"grid"):
                self.update_day()
        self._date_refresh_id=self.after(350,refresh)

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
        if DND_FILES:self._clear_drop_lesson()
        for item in self.grid.get_children():self.grid.delete(item)
        off=is_holiday(day,self.cfg)
        self.weekday.configure(text=WEEKDAYS_UA[day.weekday()])
        self.phase.configure(text=f"{week_phase(day,self.cfg).upper()}"+(" • КАНІКУЛИ: УРОКІВ НЕМАЄ" if off else ""))
        for k,row in enumerate(self.rows):
            item=self.state.get("drafts",{}).get(row.unique_key)
            doc=self.state.get("files",{}).get(row.unique_key,{})
            status=("Створено в Google" if item else
                    ("Готовий Word" if doc.get("validated") else
                     ("Word потребує перевірки" if doc.get("complete") else
                      ("Word заготовка" if doc else
                       ("Без Word" if row.status=="готово" else row.status)))))
            adjusted=self.effective_lesson(row)
            if row.unique_key in self.state.get("lesson_models",{}):
                status="Зразок із паралелі · "+status
            remote=self._remote_classroom_status(adjusted)
            if remote:
                # Не показувати «чернетка», якщо Google повідомляє PUBLISHED!
                document_status=(" • Word перевірено" if doc.get("validated") else "")
                status=remote+document_status
            self.grid.insert("", "end",iid=str(k),values=(row.period,f"{row.begin}–{row.end}",
                     row.stream,row.course_title,adjusted.topic,row.lesson_number,status))
        self.desc.delete("1.0","end")
        if self.rows:
            chosen=next((str(i) for i,x in enumerate(self.rows) if x.unique_key==prior),"0")
            self.grid.selection_set(chosen)
            self.grid.focus(chosen)
            self.select()
        else:self.foot.config(text="На обрану дату уроків немає (вихідний або канікули).")

    def _remote_classroom_status(self,lesson):
        """Ознака тільки після синхронізації та точного збігу теми + дати."""
        cid=str(self.state.get("course_ids",{}).get(lesson.course_title,""))
        if not cid or cid not in self.remote_classroom_entries:return ""
        from .classroom_archive import compatible_classroom_title
        own=self.state.get("drafts",{}).get(lesson.unique_key,{})
        own_id=str(own.get("id") or "")
        matched=[row for row in self.remote_classroom_entries[cid]
                 if (own_id and row["id"]==own_id)
                 or compatible_classroom_title(lesson,row)]
        if not matched:return ""
        selected=next((x for x in matched if x["state"]=="PUBLISHED"),
                      next((x for x in matched if x["state"]=="SCHEDULED"),matched[0]))
        what={"Завдання":"Завдання","Матеріал":"Матеріал",
              "Оголошення":"Оголошення"}.get(selected["type"],"Запис")
        if selected["state"]=="PUBLISHED":
            return f"{what} ОПУБЛІКОВАНО в Classroom"
        if selected["state"]=="SCHEDULED":
            return f"{what} ЗАПЛАНОВАНО в Classroom"
        return f"{what} — чернетка в Classroom"

    def view_classroom(self):
        from .classroom_browser import show_classroom_viewer
        show_classroom_viewer(self)

    def selected(self):
        selection=self.grid.selection()
        return self.rows[int(selection[0])] if selection else None

    def effective_lesson(self,lesson):
        model=self.state.get("lesson_models",{}).get(lesson.unique_key)
        if not model:
            return lesson
        return dataclass_replace(lesson,topic=model.get("topic",lesson.topic),
                                 homework=model.get("homework",lesson.homework))

    def select(self):
        original=self.selected()
        if not original:return
        lesson=self.effective_lesson(original)
        self.desc.delete("1.0","end")
        description=self.state.get("description_overrides",{}).get(lesson.unique_key)
        if description is None:
            templ=self.state.get("parallel_templates",{}).get(signature_key(lesson,self.cfg))
            description=render_template(templ,lesson) if templ is not None else html_classroom_text(lesson,asynchronous=True,video=True)
        self.desc.insert("1.0",description)
        self.desc.yview_moveto(0)
        self.refresh_attachment_previews()
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
        destination=word_path(lesson)
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
                destination=word_path(lesson)
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

    # ----- Лекції через власний ChatGPT учителя (безкоштовно, без API) -----
    def chatgpt_word(self):
        lesson=self.selected()
        if not lesson:return
        if lesson.status!="готово":
            messagebox.showerror("КТП","Теми в КТП завершилися або план не перевірено.");return
        current=self.state.get("files",{}).get(lesson.unique_key,{})
        replace=False
        if current.get("complete") and Path(current.get("path","")).is_file():
            if not messagebox.askyesno("Word уже є",
                    "Для цього уроку вже є готовий Word.\n\n"
                    "Підготувати НОВУ лекцію через ChatGPT і замінити нею поточний Word "
                    "для цього уроку та сумісної паралелі? Уроки з чернеткою Google не змінюються."):
                return
            replace=True
        else:
            reusable=find_for_lesson(lesson,self.cfg)
            if reusable is not None and messagebox.askyesno("Готова лекція є",
                    "У бібліотеці вже є відповідна лекція.\n\nВикористати її замість нової?"):
                attached=attach_document(reusable,self._parallel(lesson),self.state)
                save_state(self.state);self.update_day()
                messagebox.showinfo("Повторне використання",f"Прив'язано уроків: {len(attached)}.")
                return
            if not self._parallel_prompt(lesson,"Підготувати ОДНУ лекцію через ваш ChatGPT (безкоштовно)?"):
                return
        from .chatgpt_ui import open_chatgpt_dialog
        open_chatgpt_dialog(self,[lesson],batch=False,replace_existing=replace)

    def chatgpt_batch(self):
        lessons=[i for i in self.rows if i.status=="готово"]
        if not lessons:
            messagebox.showinfo("Розклад","На цю дату немає уроків із перевіреними КТП.");return
        pending=[];seen=set();reused=0
        files=self.state.get("files",{})
        for lesson in lessons:
            key=(signature_key(lesson,self.cfg),lesson.lesson_number,
                 lesson.topic.casefold().strip())
            # Заготовка не є лекцією: для неї теж готуємо повну лекцію.
            if files.get(lesson.unique_key,{}).get("complete") or key in seen:
                continue
            seen.add(key)
            existing=find_for_lesson(lesson,self.cfg)
            if existing is not None:
                reused+=len(attach_document(existing,self._parallel(lesson),self.state))
                continue
            pending.append(lesson)
        if reused:
            save_state(self.state);self.update_day()
        if not pending:
            messagebox.showinfo("Лекції за день",
                "Усі уроки цього дня вже мають Word"
                +(f" (з бібліотеки прив'язано: {reused})." if reused else "."))
            return
        names="\n".join(f"• {x.period}-й урок — {x.stream}: {x.topic[:70]}" for x in pending)
        if not messagebox.askyesno("Лекції за день через ChatGPT",
              (f"З бібліотеки прив'язано готових лекцій: {reused}.\n\n" if reused else "")
              +f"Нові лекції потрібні для {len(pending)} уроків:\n{names}\n\n"
              "Програма підготує ОДИН спільний запит для ChatGPT на всі ці уроки; готові файли "
              "ви перетягнете разом, а програма розкладе їх по уроках. Продовжити?"):
            return
        from .chatgpt_ui import open_day_dialog
        open_day_dialog(self,pending)

    def save_chatgpt_lecture(self,lesson,material,replace_existing=False):
        """Word із відповіді ChatGPT → бібліотека → сумісна паралель. Google не змінюється."""
        destination=word_path(lesson)
        path=create_word(lesson,destination,material)
        attached=self._attach_from_master(path,lesson,"ChatGPT",
                                          replace_existing=replace_existing)
        return path,attached

    def save_dropped_lecture(self,lesson,docx_path,extra_files=(),replace_existing=False):
        """Готовий Word від ChatGPT + інфографіка → бібліотека → паралелі → вкладення."""
        check_real_docx(docx_path)
        destination=word_path(lesson)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if Path(docx_path).resolve()!=destination.resolve():
            shutil.copy2(docx_path,destination)
        attached=self._attach_from_master(destination,lesson,"ChatGPT (файл)",
                                          replace_existing=replace_existing)
        problems=[]
        for target in attached:
            if not extra_files:break
            try:add_attachments(self.state,target.unique_key,list(extra_files))
            except Exception as ex:problems.append(str(ex))
        if extra_files:
            save_state(self.state);self.refresh_attachment_previews()
        return destination,attached,"; ".join(dict.fromkeys(problems))

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

    def copy_selected_lessons_as_text(self):
        """Ctrl+C: дані уроків у буфер як таблиця з табуляціями."""
        items=self.grid.selection()
        if not items:return "break"
        lines=["\t".join(str(v) for v in self.grid.item(item,"values"))
               for item in sorted(items,key=int)]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        return "break"

    def remove_selected_local_materials(self):
        """Del не видаляє сам урок у розкладі або публікацію Classroom."""
        chosen=self._selected_rows()
        if not chosen:return "break"
        if not messagebox.askyesno("Прибрати локальні матеріали",
            f"Очистити ЛОКАЛЬНІ Word, текстові правки й вкладення "
            f"для {len(chosen)} виділених уроків?\n"
            "Публікації Google, розклад та КТП не змінюються. "
            "Фізичні файли Word на диску не видаляються.",
            parent=self):
            return "break"
        for row in chosen:
            key=row.unique_key
            for part in ("files","description_overrides",
                         "lesson_models","attachments"):
                self.state.get(part,{}).pop(key,None)
        save_state(self.state)
        self.update_day()
        messagebox.showinfo("Видалено локально",
             "Посилання на локальні матеріали прибрано. "
             "Записи Google не змінено.",parent=self)
        return "break"

    def _column_drag_start(self,event):
        self._column_start=None
        if self.grid.identify_region(event.x,event.y)=="heading":
            self._column_start=(self.grid.identify_column(event.x),event.x)

    def _column_drag_end(self,event):
        start=self._column_start
        self._column_start=None
        if not start or self.grid.identify_region(event.x,event.y)!="heading":return
        source,index_x=start
        destination=self.grid.identify_column(event.x)
        if destination==source or abs(event.x-index_x)<14:return
        try:
            order=list(self.grid["displaycolumns"])
            a,b=int(source[1:])-1,int(destination[1:])-1
            if not (0<=a<len(order) and 0<=b<len(order)):return
            col=order.pop(a)
            order.insert(b,col)
            self.grid.configure(displaycolumns=order)
            self.state["column_order"]=list(order)
            save_state(self.state)
        except (ValueError,tk.TclError):return

    def _description_context_menu(self,event):
        menu=tk.Menu(self.desc,tearoff=False)
        menu.add_command(label="Вирізати",command=lambda:self.desc.event_generate("<<Cut>>"))
        menu.add_command(label="Копіювати",command=lambda:self.desc.event_generate("<<Copy>>"))
        menu.add_command(label="Вставити",command=lambda:self.desc.event_generate("<<Paste>>"))
        menu.add_command(label="Виділити весь текст",
                         command=lambda:self.desc.tag_add("sel","1.0","end-1c"))
        menu.add_separator()
        menu.add_command(label="Взяти текст і Word з попереднього уроку паралелі…",
                         command=lambda:self.borrow_lesson("past"))
        menu.add_command(label="Взяти текст і Word з наступного уроку паралелі…",
                         command=lambda:self.borrow_lesson("future"))
        menu.add_command(label="Зберегти текст цього уроку",
                         command=self.save_classroom_description)
        menu.add_command(label="Прикріпити файл…",command=self.choose_attachments)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return "break"

    def _selected_rows(self):
        """Тільки реально виділені рядки. Ctrl / Shift доступні в Treeview."""
        return [self.rows[int(i)] for i in self.grid.selection()
                if i.isdecimal() and int(i)<len(self.rows)]

    def copy_row_materials(self):
        focus=self.grid.focus()
        row=(self.rows[int(focus)] if focus.isdecimal() and
             int(focus)<len(self.rows) else self.selected())
        if not row:return
        self._copied_lesson_key=row.unique_key
        self._copied_row_details=self.effective_lesson(row)
        override=self.state.get("description_overrides",{}).get(row.unique_key)
        self._copied_row_text=(self.desc.get("1.0","end-1c") if
              len(self.grid.selection())==1 else override)
        messagebox.showinfo("Урок скопійовано",
              "Можна копіювати навіть БЕЗ Word: тему, текст і вкладення. "
              "Тепер затисніть Ctrl або Shift, виділіть один чи кілька рядків "
              "і натисніть праву кнопку → «Вставити копію». "
              "Готовий Word буде скопійовано, лише якщо він існує й перевірений. "
              "У Google нічого не надсилається.",parent=self)

    def paste_row_materials(self):
        source=getattr(self,"_copied_row_details",None)
        key=getattr(self,"_copied_lesson_key",None)
        if not source or not key:return
        targets=[lesson for lesson in self._selected_rows() if lesson.unique_key!=key]
        if not targets:
            messagebox.showinfo("Вставити урок","Виділіть один або кілька ІНШИХ уроків.")
            return
        src_meta=self.state.get("files",{}).get(key,{})
        source_word=(src_meta.get("path") if
                     src_meta.get("validated") and src_meta.get("complete")
                     and Path(src_meta.get("path","")).is_file() else None)
        source_grade,source_subject=stream_subject(source.stream)
        mismatched=[x for x in targets if stream_subject(x.stream)!=(source_grade,source_subject)]
        if mismatched:
            messagebox.showerror("Не той предмет",
                "Копіювати можна лише в межах одного класу навчання та предмета. "
                "Для інших предметів виберіть відповідний матеріал вручну.")
            return
        drafts=[x for x in targets if x.unique_key in self.state.get("drafts",{})]
        if drafts:
            messagebox.showerror("Уроки з чернетками",
                   "Є уроки, для яких уже створено чернетку Google. "
                   "Зніміть з них виділення, щоб не створити невідповідність.")
            return
        different=any(signature(x,self.cfg)!=signature(source,self.cfg) for x in targets)
        detail=("\n\nУвага: окремі класи мають інші КТП або кількість годин. "
                "Це ЛИШЕ ваш ручний вибір, а не автоматичне поширення."
                if different else "")
        if not messagebox.askyesno("Підтвердження копіювання",
            f"Вставити «{source.topic}» у {len(targets)} вибраних уроків?\n"
            "Копіюються тема, текст, вкладення та готовий Word (якщо він є); "
            "дата стає датою цільового "
            "уроку. КТП і курс Google НЕ змінюються."
            +detail+"\n\nОпублікування не виконується."):return
        text=self._copied_row_text
        if text is None:
            text=self.state.get("description_overrides",{}).get(key)
        if text is None:
            templ=self.state.get("parallel_templates",{}).get(signature_key(source,self.cfg))
            text=render_template(templ,source) if templ is not None else html_classroom_text(source,asynchronous=True,video=True)
        source_date=source.day[8:10]+"."+source.day[5:7]
        for target in targets:
            local=dataclass_replace(target,topic=source.topic,homework=source.homework)
            try:
                doc=copy_for_lesson(source_word,local) if source_word else None
                copy_attachments(self.state,key,target.unique_key)
            except Exception as ex:
                messagebox.showerror("Копіювання перервано",str(ex))
                save_state(self.state);self.update_day()
                return
            self.state.setdefault("lesson_models",{})[target.unique_key]={
                  "topic":source.topic,"homework":source.homework,"from":key}
            new_date=target.day[8:10]+"."+target.day[5:7]
            self.state.setdefault("description_overrides",{})[target.unique_key]=text.replace(source_date,new_date)
            if doc:
                self.state.setdefault("files",{})[target.unique_key]={
                    "path":str(doc),"validated":True,"complete":True,
                    "borrowed_from":key}
        save_state(self.state);self.update_day()
        messagebox.showinfo("Готово",f"Перенесено у {len(targets)} уроків. "
            "Перевірте теми й домашні завдання перед чернетками.")

    def _highlight_drop_lesson(self,event):
        item=self.grid.identify_row(
            self.grid.winfo_pointery()-self.grid.winfo_rooty())
        if item!=getattr(self,"_hover_lesson_item",None):
            self._clear_drop_lesson()
            if item:
                tags=set(self.grid.item(item,"tags"))
                tags.add("file-drop-hover")
                self.grid.item(item,tags=tuple(tags))
                self._hover_lesson_item=item
                self.foot.config(text="Відпустіть файл — він потрапить у підсвічений урок.")
        return "copy"

    def _clear_drop_lesson(self,_event=None):
        item=getattr(self,"_hover_lesson_item",None)
        if item and self.grid.exists(item):
            tags=[x for x in self.grid.item(item,"tags") if x!="file-drop-hover"]
            self.grid.item(item,tags=tuple(tags))
        self._hover_lesson_item=None
        return "copy"

    def _highlight_description_drop(self,event):
        self.desc.configure(background="#FFF1B4")
        self.drop_hint.configure(style="TeacherHoverDrop.TLabel")
        return "copy"

    def _clear_description_drop(self,event=None):
        self.desc.configure(background=getattr(self,"_desc_original_bg","white"))
        self.drop_hint.configure(style="TLabel")
        return "copy"

    def _drop_on_lesson(self,event):
        """Перетягнутий Word — готовий урок; інші файли — вкладення саме цього рядка."""
        self._clear_drop_lesson()
        item=self.grid.identify_row(self.grid.winfo_pointery()-self.grid.winfo_rooty())
        if not item:return "copy"
        self.grid.selection_set(item);self.grid.focus(item)
        lesson=self.rows[int(item)]
        try:paths=[Path(path) for path in self.tk.splitlist(event.data)]
        except (tk.TclError,ValueError):return "copy"
        if lesson.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Чернетка вже існує",
                  "Цей урок уже має чернетку. Додайте файли у Google Classroom.")
            return "copy"
        docs=[path for path in paths if path.suffix.casefold()==".docx"]
        others=[path for path in paths if path.suffix.casefold()!=".docx"]
        if docs:
            # Для двох Word немає однозначного головного документа — питаємо.
            if len(docs)>1:
                others+=docs[1:]
            self._accept_dropped_word(lesson,docs[0])
        if others:self._attach_paths(others,lesson=lesson)
        return "copy"

    def _accept_dropped_word(self,lesson,path):
        try:check_real_docx(path)
        except Exception as ex:
            messagebox.showerror("Word",str(ex));return
        if not self._parallel_prompt(lesson,
              "Перетягнутий Word прийняти як ПОВНУ перевірену лекцію для цієї теми "
              "й автоматично поширити на сумісну паралель?"):return
        try:
            attached=self._attach_from_master(path,lesson,"Перетягнутий Word",
                                                replace_existing=True)
        except Exception as ex:
            messagebox.showerror("Не вдалося прикріпити Word",str(ex));return
        messagebox.showinfo("Word додано",
             f"Word прив’язано до {len(attached)} уроків. "
             "Кнопку «Підтвердити Word» натискати не треба. "
             "До Google файли ще не надіслано.")

    def _enter_creates_draft(self,_event=None):
        if self.selected():self.draft()
        return "break"

    def _open_day_menu(self,event):
        """Меню для порожнього місця таблиці, шапки й фону вікна: дії над усім днем."""
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Попередній день",command=lambda:self.shift(-1))
        menu.add_command(label="Наступний день",command=lambda:self.shift(1))
        menu.add_command(label="Сьогодні",
                         command=lambda:(self.datevar.set(date.today().strftime("%d.%m.%Y")),self.update_day()))
        menu.add_separator()
        menu.add_command(label="Лекції ГПТ на весь день…",command=self.chatgpt_batch)
        menu.add_command(label="Створити чернетки для всього дня…",command=self.batch_drafts)
        menu.add_separator()
        menu.add_command(label="Оновити стан із Classroom",
                         command=lambda:self.sync_classroom(interactive=False,manual=True))
        menu.add_command(label="Мій Classroom — перегляд",command=self.view_classroom)
        menu.add_command(label="Редактор КТП, розкладу і навчального року…",command=self.edit_academic_year)
        menu.add_separator()
        menu.add_command(label="Зразки документів…",command=self.samples_dialog)
        menu.add_command(label="Мої дані…",command=self.data_dialog)
        menu.add_command(label="Початкове налаштування…",command=self.setup_dialog)
        menu.add_command(label="Довідка",command=self.show_help)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return "break"

    def reload_data(self):
        """Після очищення чи відновлення: перечитати розклад, КТП і стан з диска."""
        self.cfg=read_json("Налаштування.json")
        self.state=read_state()
        self.remote_classroom_entries={}
        self.update_day()
        self.after(400,lambda:self.sync_classroom(interactive=False))

    def _open_lesson_menu(self,event):
        item=self.grid.identify_row(event.y)
        if not item:
            return self._open_day_menu(event)
        if item not in self.grid.selection():
            self.grid.selection_set(item)
        self.grid.focus(item)
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Копіювати таблицю виділених уроків (Ctrl+C)",
                         command=self.copy_selected_lessons_as_text)
        menu.add_command(label="Копіювати урок (текст, Word якщо є, вкладення)",
                         command=self.copy_row_materials)
        selected_count=len(self.grid.selection())
        menu.add_command(label=f"Вставити копію у виділені уроки ({selected_count})",
                         command=self.paste_row_materials,
                         state="normal" if getattr(self,"_copied_lesson_key",None) else "disabled")
        menu.add_separator()
        menu.add_command(label="Взяти попередній урок із паралелі…",
                         command=lambda:self.borrow_lesson("past"))
        menu.add_command(label="Взяти майбутній урок із паралелі…",
                         command=lambda:self.borrow_lesson("future"))
        menu.add_separator()
        menu.add_command(label="Лекція через мій ChatGPT…",command=self.chatgpt_word)
        menu.add_command(label="Лекції ГПТ на весь день…",command=self.chatgpt_batch)
        menu.add_command(label="Word: заготовка",command=lambda:self.make_word(False))
        menu.add_command(label="Вибрати готовий Word…",command=self.choose_docx)
        menu.add_command(label="Бібліотека Word…",command=self.library_dialog)
        menu.add_command(label="Додати файли до Classroom…",command=self.choose_attachments)
        menu.add_command(label="Відкрити папку Word",command=self.open_folder)
        menu.add_separator()
        menu.add_command(label="Редагувати тему / Д/з цього уроку в КТП…",
                         command=self.edit_lesson_in_ktp)
        menu.add_command(label="Копіювати повідомлення Classroom",command=self.copy_classroom)
        menu.add_command(label="Зберегти опис цього уроку",command=self.save_classroom_description)
        menu.add_command(label="Зберегти шаблон для паралелі",command=self.save_parallel_description)
        menu.add_separator()
        menu.add_command(label="Створити ЧЕРНЕТКУ в Classroom…",command=self.draft)
        menu.add_command(label="Створити чернетки для всього дня…",command=self.batch_drafts)
        menu.add_command(label="Мій Classroom — перегляд",command=self.view_classroom)
        menu.add_command(label="Оновити стан із Classroom",
                         command=lambda:self.sync_classroom(interactive=False,manual=True))
        menu.add_separator()
        menu.add_command(label="Прибрати ЛОКАЛЬНІ матеріали (Delete)",
                         command=self.remove_selected_local_materials)
        menu.tk_popup(event.x_root,event.y_root)
        menu.grab_release()

    def borrow_lesson(self,when):
        """Ручний вибір попереднього/майбутнього ЗРАЗКА лише в сумісному потоці."""
        target=self.selected()
        if not target:return
        if target.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Уже є чернетка",
                    "У Classroom для цього уроку вже створено чернетку. "
                    "Редагуйте її безпосередньо в Classroom.");return
        target_sig=signature(target,self.cfg)
        candidates=[]
        for source in build_calendar(self.cfg):
            if source.unique_key==target.unique_key or source.status!="готово":continue
            if when=="past" and source.day>=target.day:continue
            if when=="future" and source.day<=target.day:continue
            src_grade,src_subject=stream_subject(source.stream)
            target_grade,target_subject=stream_subject(target.stream)
            if (src_grade,src_subject)!=(target_grade,target_subject):continue
            doc=self.state.get("files",{}).get(source.unique_key,{})
            if not doc.get("validated") or not Path(doc.get("path","")).is_file():continue
            candidates.append(source)
        candidates.sort(key=lambda x:x.day,reverse=(when=="past"))
        if not candidates:
            messagebox.showinfo("Уроки паралелі",
                   "Не знайдено готових перевірених Word для цього предмета, "
                   "навчальної програми та кількості годин у відповідному періоді.")
            return
        win=tk.Toplevel(self)
        win.title("Виберіть попередню роботу" if when=="past" else "Виберіть майбутню роботу")
        win.transient(self);fit_work_window(win,"normal")
        ttk.Label(win,text="Будуть перенесені тема, опис Classroom, готовий Word і вкладення. "
                  "Дата уроку стане поточною. Автоприв'язка для різних КТП/годин заборонена; "
                  "тут дозволяється ЛИШЕ ваш ручний вибір. КТП не змінюється.",
                  wraplength=1000).pack(anchor="w",padx=12,pady=9)
        frame=ttk.Frame(win);frame.pack(fill="both",expand=True,padx=10)
        columns=("date","stream","topic")
        table=ttk.Treeview(frame,columns=columns,show="headings")
        for name,label,width in (("date","Дата",110),("stream","Паралель",150),
                                 ("topic","Тема / вид роботи",750)):
            table.heading(name,text=label);table.column(name,width=width)
        sc=ttk.Scrollbar(frame,orient="vertical",command=table.yview)
        table.configure(yscrollcommand=sc.set)
        table.pack(side="left",fill="both",expand=True)
        sc.pack(side="right",fill="y")
        for i,x in enumerate(candidates):
            eff=self.effective_lesson(x)
            table.insert("", "end",iid=str(i),values=(display_date(x.day),x.stream,eff.topic[:130]))
        table.selection_set("0")
        def apply(_event=None):
            choice=table.selection()
            if not choice:return
            original=candidates[int(choice[0])]
            source=self.effective_lesson(original)
            if not messagebox.askyesno("Один зразок без повторної оплати",
                f"Використати готовий урок «{source.topic}» ({display_date(source.day)}, {source.stream}) "
                f"для {target.stream} ({display_date(target.day)})?\n\n"
                "Зміняться лише локальні тема, опис, Word і вкладення цього уроку. "
                "КТП та Google Classroom залишаються без змін до створення окремої чернетки.",
                parent=win):return
            different_plan=signature(source,self.cfg)!=target_sig
            if different_plan and not messagebox.askyesno(
                "Увага: різні КТП або кількість годин",
                "Ви вручну вибрали роботу з тієї самої паралелі, але з іншими "
                "годинами або календарною програмою.\n\n"
                "Перевірте відповідність теми, навчальній програмі й віку дітей. "
                "Тільки цей один урок буде змінений. Продовжити?",
                parent=win):return
            model={"topic":source.topic,"homework":source.homework,
                   "from":source.unique_key}
            destination=dataclass_replace(target,topic=source.topic,homework=source.homework)
            try:
                src=self.state["files"][source.unique_key]
                dest=copy_for_lesson(src["path"],destination)
                raw=self.state.get("description_overrides",{}).get(source.unique_key)
                if raw is None:
                    templ=self.state.get("parallel_templates",{}).get(signature_key(source,self.cfg))
                    raw=render_template(templ,source) if templ is not None else html_classroom_text(source,asynchronous=True,video=True)
                old_date=source.day[8:10]+"."+source.day[5:7]
                new_date=target.day[8:10]+"."+target.day[5:7]
                text=raw.replace(old_date,new_date)
                copy_attachments(self.state,source.unique_key,target.unique_key)
            except Exception as ex:
                messagebox.showerror("Не вдалося перенести",str(ex),parent=win);return
            self.state.setdefault("lesson_models",{})[target.unique_key]=model
            self.state.setdefault("description_overrides",{})[target.unique_key]=text
            self.state.setdefault("files",{})[target.unique_key]={
                "path":str(dest),"complete":True,"validated":True,
                "borrowed_from":source.unique_key}
            save_state(self.state);win.destroy();self.update_day()
            messagebox.showinfo("Урок використано","Готовий Word та опис перенесено без AI-запиту. "
                    "Перевірте дату, тему й Д/з перед створенням чернетки.")
        table.bind("<Double-1>",apply)
        ttk.Button(win,text="Використати вибраний урок",
                   command=apply).pack(pady=8)

    def _receive_files(self,event):
        try:
            names=list(self.tk.splitlist(event.data))
        except Exception:
            names=[]
        self._clear_description_drop()
        self._attach_paths(names)
        return "copy"

    def choose_attachments(self):
        if not self.selected():return
        paths=filedialog.askopenfilenames(
            title="Виберіть файли для додавання в Classroom (максимум 19)",
            filetypes=[("Усі файли","*.*")])
        self._attach_paths(paths)

    def _attach_paths(self,paths,lesson=None):
        lesson=lesson or self.selected()
        if not lesson or not paths:return
        if lesson.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Уже створено чернетку",
              "Вкладення до наявної чернетки слід додати в Google Classroom.");return
        try:
            added=add_attachments(self.state,lesson.unique_key,paths)
        except Exception as ex:
            messagebox.showerror("Файли",str(ex));return
        save_state(self.state);self.refresh_attachment_previews()
        if added:self.foot.config(text=f"Прикріплено додаткових файлів: "
                  f"{len(self.state.get('attachments',{}).get(lesson.unique_key,[]))} "
                  "· вони ще НЕ надіслані в Google.")

    def refresh_attachment_previews(self):
        if not hasattr(self,"attachment_bar"):return
        for child in self.attachment_bar.winfo_children():child.destroy()
        self._preview_images=[]
        lesson=self.selected()
        if not lesson:return
        attachments=self.state.get("attachments",{}).get(lesson.unique_key,[])
        if not attachments:
            ttk.Label(self.attachment_bar,text="Вкладень поки немає.",
                      foreground="#617081").pack(anchor="w")
            return
        # Horizontal scroll for many photo cards.
        canvas=tk.Canvas(self.attachment_bar,height=93,highlightthickness=0)
        scroll=ttk.Scrollbar(self.attachment_bar,orient="horizontal",command=canvas.xview)
        canvas.configure(xscrollcommand=scroll.set)
        canvas.pack(fill="x",expand=True)
        scroll.pack(fill="x")
        inside=ttk.Frame(canvas)
        canvas.create_window((0,0),window=inside,anchor="nw")
        inside.bind("<Configure>",lambda _:canvas.configure(scrollregion=canvas.bbox("all")))
        for ix,entry in enumerate(attachments):
            part=ttk.Frame(inside,relief="groove",borderwidth=1,padding=3)
            part.grid(row=0,column=ix,padx=3,sticky="nw")
            suffix=Path(entry["path"]).suffix.lower()
            if suffix in (".png",".jpg",".jpeg",".gif",".bmp",".webp"):
                try:
                    from PIL import Image,ImageTk
                    with Image.open(entry["path"]) as original:
                        picture=original.copy()
                    picture.thumbnail((87,53))
                    photo=ImageTk.PhotoImage(picture,master=self)
                    self._preview_images.append(photo)
                    ttk.Label(part,image=photo).pack(side="left",padx=3)
                except Exception:pass
            name=entry.get("name",Path(entry["path"]).name)
            ttk.Label(part,text=name[:30],width=27).pack(side="left")
            ttk.Button(part,text="×",width=3,
                       command=lambda j=ix:self.remove_attachment_at(j)).pack(side="right")

    def remove_attachment_at(self,index):
        lesson=self.selected()
        if not lesson:return
        if lesson.unique_key in self.state.get("drafts",{}):
            messagebox.showwarning("Чернетка існує",
               "Файли вже прив'язані до чернетки Google. Видалення виконуйте в Classroom.")
            return
        if remove_attachment(self.state,lesson.unique_key,index):
            save_state(self.state);self.refresh_attachment_previews()

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
        win=tk.Toplevel(self);win.title("Бібліотека перевірених лекцій");fit_work_window(win,"normal")
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
        dlg.title("Перший запуск • Google, ChatGPT та AI")
        fit_work_window(dlg,"normal")
        dlg.transient(self)
        text=(
            "РОЗКЛАД І КТП вже працюють локально, навіть без налаштувань.\n\n"
            "GOOGLE CLASSROOM: потрібен одноразовий дозвіл Google (OAuth). "
            "Спочатку у власному Google Cloud проєкті створіть OAuth Client ID типу "
            "Desktop app і увімкніть Classroom API та Drive API. Завантажений JSON "
            "імпортуйте кнопкою нижче; далі натисніть «Підключити Google». "
            "Сервісний JSON із Google Cloud містить ідентифікатор програми, "
            "а НЕ пароль вашого акаунта. Нікому не пересилайте токен доступу.\n\n"
            "ЛЕКЦІЇ БЕЗКОШТОВНО — ЧЕРЕЗ ВАШ ChatGPT: кнопка «Word: лекція через ChatGPT». "
            "Програма готує запит за КТП, ви вставляєте його у свій ChatGPT і копіюєте "
            "відповідь — Word створюється автоматично. Ключі й паролі не потрібні.\n\n"
            "ПЛАТНИЙ АВТОМАТИЧНИЙ ВАРІАНТ (за бажанням): власний OpenAI API-ключ "
            "(оплата API окрема від підписки ChatGPT). Ключ зберігається "
            "в захищеному сховищі облікових даних Windows.\n\n"
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
        ttk.Button(buttons,text="Зберегти AI-ключ (платний режим)",command=save_key).pack(side="left",padx=5)
        ttk.Button(buttons,text="Закрити",command=dlg.destroy).pack(side="right",padx=5)

    def connect_google(self):
        """Кнопка зверху: вхід у Google (за потреби) і та сама синхронізація, що при запуску."""
        self.sync_classroom(interactive=True)

    def sync_classroom(self,interactive=False,manual=False):
        """Курси (у порядку Classroom) + стан усіх наявних матеріалів. Лише читання."""
        if self._sync_running:return
        from . import google_client
        if not interactive and not google_client.token_ready():
            self.foot.config(text="Google ще не підключено: натисніть «Підключити Google / одержати курси».")
            if manual:
                messagebox.showinfo("Google","Спочатку натисніть «Підключити Google / одержати курси».")
            return
        self._sync_running=True
        titles=list(self.cfg.get("classroom_course_titles",[]))
        known=dict(self.state.get("course_ids",{}))
        def progress(text):
            self.after(0,lambda:self.foot.config(text=text))
        def run():
            try:
                result=google_client.sync_everything(titles,known,progress)
                self.after(0,lambda:self._sync_done(result,interactive))
            except Exception as ex:
                text=str(ex)
                self.after(0,lambda:self._sync_failed(text,interactive))
        threading.Thread(target=run,daemon=True).start()

    def _sync_done(self,result,interactive):
        self._sync_running=False
        self.google_courses=result["courses"]
        self.state["course_ids"]=result["mapped"]
        self.state["classroom_order"]=[c["name"] for c in result["courses"]]
        self.remote_classroom_entries.update(result["entries"])
        try:save_state(self.state)
        except Exception:pass
        self.update_day()
        records=sum(len(v) for v in result["entries"].values())
        text=(f"Classroom синхронізовано: курсів — {len(result['courses'])}, "
              f"записів — {records}.")
        if result["unmapped"]:
            text+=f" Не зіставлено з Classroom: {len(result['unmapped'])} (кнопка «Зіставити курси»)."
        if result["errors"]:
            text+=f" Не вдалося прочитати курсів: {len(result['errors'])}."
        self.foot.config(text=text)
        if interactive and (result["errors"] or result["unmapped"]):
            messagebox.showinfo("Google Classroom",text+("\n\n"+"\n".join(result["errors"][:5]) if result["errors"] else ""))

    def _sync_failed(self,error,interactive):
        self._sync_running=False
        self.foot.config(text="Синхронізація з Classroom не вдалася (дані на екрані — з останнього разу).")
        if interactive:
            messagebox.showerror("Google Classroom",error+"\n\nПеревірте інтернет і налаштування Google (ПОЧАТКОВЕ НАЛАШТУВАННЯ).")

    def edit_lesson_in_ktp(self):
        lesson=self.selected()
        if not lesson:return
        from .editor_ui import SchoolEditor
        editor=SchoolEditor(self,self.update_day)
        editor.focus_lesson(lesson.stream,lesson.lesson_number)

    def samples_dialog(self):
        from .samples_ui import show_samples
        show_samples(self)

    def data_dialog(self):
        from .samples_ui import show_data_folder
        show_data_folder(self)

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
        fit_work_window(dialog,"normal")
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

    def _description_for_batch(self,lesson):
        """Враховує змінену вручну тему й актуальний текст вибраного уроку."""
        adjusted=self.effective_lesson(lesson)
        current=self.selected()
        if current and current.unique_key==lesson.unique_key:
            return self.desc.get("1.0","end-1c").strip()
        saved=self.state.get("description_overrides",{}).get(lesson.unique_key)
        if saved is not None:return saved
        template=self.state.get("parallel_templates",{}).get(
            signature_key(lesson,self.cfg))
        if template is not None:return render_template(template,adjusted)
        return html_classroom_text(adjusted,asynchronous=True,video=True)

    def batch_drafts(self):
        """Створення лише ПЕРЕВІРЕНИХ чернеток за обрану дату, по одній."""
        if self._batch_drafts_running:return
        if not self.rows:
            messagebox.showinfo("Чернетки за день",
                  "Цього дня немає уроків (можливо, вихідний або канікули).")
            return
        from .draft_batch import plan_day_drafts
        effective_rows=[self.effective_lesson(row) for row in self.rows]
        ready,skipped=plan_day_drafts(
            effective_rows,self.state,self._description_for_batch)
        # Захист від повторів серед вже видимих записів після синхронізації.
        # Без синхронізації це не є перевіркою всього сервера.
        not_repeated=[]
        for candidate in ready:
            if self._remote_classroom_status(candidate["lesson"]):
                skipped.append((candidate["lesson"],
                   "такий урок уже видно у Classroom після синхронізації"))
            else:not_repeated.append(candidate)
        ready=not_repeated
        summary=[f"Дата: {self.datevar.get()}",
                 f"Готові для чернеток: {len(ready)}",
                 f"Пропущено: {len(skipped)}"]
        summary.extend(f"✓ {x['lesson'].period}. {x['lesson'].stream}: "
                       f"{x['lesson'].topic[:70]}" for x in ready)
        summary.extend(f"— {x.period}. {x.stream}: {reason}"
                       for x,reason in skipped)
        if not ready:
            messagebox.showinfo("Чернетки за день","\n".join(summary))
            return
        confirmation=(
            "\n".join(summary)+
            "\n\nСтворити тільки ЧЕРНЕТКИ-матеріали в указаних Google-курсах? "
            "У кожному будуть лише наявні матеріали: текст, перевірений Word "
            "(за наявності) та додаткові вкладення. "
            "Учні НЕ отримають публікацій. Відео додаються вручну.\n\n"
            "Перевірте теми, дати й домашні завдання до підтвердження."
        )
        if not messagebox.askyesno("Пакетна підготовка чернеток",confirmation):
            return
        self._batch_drafts_running=True
        self.batch_drafts_button.config(state="disabled")
        self.foot.config(text=f"Створюю {len(ready)} чернеток послідовно…")
        # Зафіксувати план до початку відправлень: зміни вибраного рядка
        # або дати після старту не вплинуть на вже підтверджений перелік.
        def task():
            from .google_client import create_draft
            done=[]
            errors=[]
            for item in ready:
                # Повторно перевірити дублікат безпосередньо перед API-запитом.
                if item["key"] in self.state.get("drafts",{}):
                    continue
                try:
                    record=create_draft(
                        item["course_id"],item["title"],item["description"],
                        item["docx_path"],False,item["attachments"])
                except Exception as ex:
                    errors.append(f"{item['lesson'].stream}: {ex}")
                    # Stop: the reason might be a network or authorization error.
                    break
                self.state.setdefault("drafts",{})[item["key"]]=record
                try:
                    # IMPORTANT: Записати кожний результат ОДРАЗУ, щоб
                    # наступна помилка не спричинила повторних публікацій.
                    save_state(self.state)
                except Exception as ex:
                    errors.append("Чернетка створена, але не вдалося зберегти "
                       "локальну позначку! Перевірте Classroom перед повтором. "
                       f"{item['lesson'].stream}: {ex}")
                    break
                done.append(item)
            return done,errors

        def finished(result):
            successful,errors=result
            self._batch_drafts_running=False
            self.batch_drafts_button.config(state="normal")
            self.update_day()
            msg=(f"Створено чернеток: {len(successful)} з {len(ready)} готових.\n"
                 f"Пропущено до початку: {len(skipped)}.\n"
                 "Жоден матеріал не опубліковано.")
            if errors:
                msg+="\n\nПісля помилки зупинено відправлення:\n"+"\n".join(errors)
                msg+="\nПеревірте вже створені чернетки в Classroom, перш ніж повторювати."
                messagebox.showwarning("Пакетна підготовка",msg)
            else:messagebox.showinfo("Пакетна підготовка",msg)
        def safe_worker():
            try:
                result=task()
                self.after(0,lambda:finished(result))
            except Exception as ex:
                msg=str(ex)
                def failed():
                    self._batch_drafts_running=False
                    self.batch_drafts_button.config(state="normal")
                    self.update_day()
                    messagebox.showerror("Пакетні чернетки",
                        "Сталася непередбачена помилка. Перевірте Classroom "
                        "перед повторним запуском:\n"+msg)
                self.after(0,failed)
        threading.Thread(target=safe_worker,daemon=True).start()

    def draft(self):
        original=self.selected()
        if not original:return
        lesson=self.effective_lesson(original)
        if lesson.status!="готово":
            messagebox.showerror("КТП","Цей урок не готовий: спочатку імпортуйте та перевірте календарний план поточного року.")
            return
        key=lesson.unique_key
        if key in self.state.get("drafts",{}):
            messagebox.showerror("Дублікат","Для цього уроку вже створено чернетку Classroom. Повторне створення заблоковано.");return
        f=self.state.get("files",{}).get(key,{})
        word_path=(str(f["path"]) if
                   f.get("validated") and f.get("complete")
                   and Path(f.get("path","")).is_file() else None)
        course_id=self.state.get("course_ids",{}).get(lesson.course_title)
        if not course_id:
            messagebox.showerror("Classroom","Цей курс ще не зіставлено з Google Classroom.");return
        duplicate=self._remote_classroom_status(lesson)
        if duplicate and not messagebox.askyesno(
                "Перевірте можливий повтор",
                f"Після синхронізації в Classroom уже знайдено: «{duplicate}».\n"
                "Ви дійсно хочете створити ще одну окрему чернетку?",
                parent=self):
            return
        text=self.desc.get("1.0","end").strip()
        assignment=self.assignment.get()
        attachment_paths=files_for_lesson(self.state,key)
        if len(attachment_paths)!=len(self.state.get("attachments",{}).get(key,[])):
            messagebox.showerror("Вкладення",
              "Деякі прикріплені файли відсутні. Приберіть їх зі списку або додайте знову.")
            return
        if not text and not word_path and not attachment_paths:
            messagebox.showwarning("Порожній матеріал",
                "Напишіть повідомлення або додайте зображення, інший файл чи Word.")
            return
        confirm=("Створити ТІЛЬКИ ЧЕРНЕТКУ?\n\n"
                 f"Курс: {lesson.course_title}\nДата уроку: {lesson.day}\n"
                 f"Тема: {lesson.topic[:110]}\n"
                 f"Word: {'додається' if word_path else 'не потрібний / не додається'}\n"
                 f"Текст: {'є' if text else 'без опису'}\n"
                 f"Додаткові вкладення: {len(attachment_paths)}\n\n"
                 "Відео потрібно додати вручну перед публікацією.")
        if not messagebox.askyesno("Підтвердження",confirm):return
        def task():
            from .google_client import create_draft
            return create_draft(course_id,
                f"Урок {lesson.day[8:10]}.{lesson.day[5:7]} — {lesson.topic}. "
                "(Асинхронно — без виходу у Zoom у зв’язку з довготривалою повітряною тривогою і загрозою для життя і здоров’я)",
                 text,word_path,assignment,attachment_paths)
        def done(result):
            self.state.setdefault("drafts",{})[key]=result
            save_state(self.state);self.update_day()
            messagebox.showinfo("Чернетка створена",f"ID: {result['id']}\nСтан: DRAFT\nУчні її поки НЕ бачать.")
        self.worker(task,done)

def launch():
    MainApp().mainloop()
