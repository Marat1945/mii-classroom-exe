"""Перегляд уже наявних публікацій в Google Classroom у самому помічнику.

Тільки читання. Вчитель бачить матеріали/завдання/чернетки й вкладення,
не змінюючи Classroom, КТП чи свої локальні Word.
"""
from __future__ import annotations
import threading
import tkinter as tk
from tkinter import ttk,messagebox
from pathlib import Path
import webbrowser
import io
import urllib.request
from urllib.parse import urlsplit

from .classroom_archive import compatible_classroom_title
from .window_ui import fit_work_window


class ClassroomViewer(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent)
        self.parent=parent
        self.title("МІЙ CLASSROOM • Перегляд матеріалів і чернеток")
        fit_work_window(self,"large")
        self.minsize(850,620)
        self.records=[]
        self.visible=[]
        self.courses=[]
        self.busy=False
        self.current=None
        self._build()
        self._courses_from_local()
        # Користувач просив ОДНУ кнопку: відкрили «Мій Classroom» —
        # одразу читаємо обраний курс, без окремого «Оновити».
        if self.current:
            self.after(180,self.sync)
        else:
            self.after(180,self.load_courses)
        self.protocol("WM_DELETE_WINDOW",self.destroy)
        self.transient(parent)

    def _build(self):
        top=ttk.Frame(self,padding=10);top.pack(fill="x")
        ttk.Label(top,text="МІЙ GOOGLE CLASSROOM • ПЕРЕГЛЯД",
                  font=("Segoe UI",14,"bold")).grid(row=0,column=0,columnspan=6,sticky="w",pady=(0,6))
        ttk.Label(top,text="Курс:").grid(row=1,column=0,padx=(0,6),sticky="w")
        self.course_label=tk.StringVar()
        self.combo=ttk.Combobox(top,textvariable=self.course_label,state="readonly",width=46)
        self.combo.grid(row=1,column=1,sticky="w",padx=(0,9))
        self.combo.bind("<<ComboboxSelected>>",lambda _:self._course_changed())
        self.fetch_button=ttk.Button(top,text="ОНОВЛЮЄТЬСЯ АВТОМАТИЧНО",
                                     command=self.sync)
        # Кнопка не відображається: оновлення автоматичне при відкритті
        # вікна і виборі іншого курсу.
        ttk.Button(top,text="Одержати всі курси",command=self.load_courses).grid(row=1,column=2,padx=(0,8))
        self.with_news=tk.BooleanVar(value=False)
        ttk.Checkbutton(top,text="Оголошення (окремий дозвіл)",
                        variable=self.with_news).grid(row=1,column=3,sticky="w")
        filters=ttk.Frame(self,padding=(10,0,10,5));filters.pack(fill="x")
        ttk.Label(filters,text="Статус:").pack(side="left")
        self.status=tk.StringVar(value="Усі")
        status=ttk.Combobox(filters,textvariable=self.status,
                 values=("Усі","Опубліковано","Чернетка"),state="readonly",width=18)
        status.pack(side="left",padx=6)
        status.bind("<<ComboboxSelected>>",lambda _:self.refresh_list())
        ttk.Label(filters,text="Тип:").pack(side="left",padx=(12,0))
        self.kind=tk.StringVar(value="Усі")
        kind=ttk.Combobox(filters,textvariable=self.kind,
                 values=("Усі","Матеріал","Завдання","Оголошення"),state="readonly",width=17)
        kind.pack(side="left",padx=6)
        kind.bind("<<ComboboxSelected>>",lambda _:self.refresh_list())
        ttk.Label(filters,text="Пошук:").pack(side="left",padx=(12,0))
        self.keyword=tk.StringVar()
        search=ttk.Entry(filters,textvariable=self.keyword,width=37)
        search.pack(side="left",padx=6,fill="x",expand=True)
        self.keyword.trace_add("write",lambda *_:self.refresh_list())
        self.with_news.trace_add("write",lambda *_:self._schedule_synced())

        middle=ttk.Frame(self,padding=(10,3,10,0))
        middle.pack(fill="both",expand=True)
        cols=("created","kind","state","title","files")
        self.table=ttk.Treeview(middle,columns=cols,show="headings",height=12,
                                 selectmode="browse")
        for col,title,w in (
            ("created","Дата",140),("kind","Тип",135),
            ("state","Статус",130),("title","Назва публікації",620),
            ("files","Файлів",70)):
            self.table.heading(col,text=title)
            self.table.column(col,width=w,minwidth=55)
        scroll=ttk.Scrollbar(middle,orient="vertical",command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        self.table.bind("<<TreeviewSelect>>",lambda _:self.show_item())
        self.table.bind("<Button-3>",self._record_context_menu)
        self.table.bind("<Control-c>",lambda e:self.copy_current_record())
        self.table.bind("<Delete>",lambda e:self._read_only_delete())
        detail=ttk.LabelFrame(self,text="Повний опис обраного запису",padding=8)
        detail.pack(fill="both",expand=True,padx=10,pady=(6,0))
        self.detail=tk.Text(detail,height=9,wrap="word",font=("Segoe UI",10))
        self.detail.pack(fill="both",expand=True)
        self.detail.configure(state="disabled")
        attachments=ttk.LabelFrame(self,text="Вкладення (зображення, Word, PDF, відео, посилання)",
                                    padding=8)
        attachments.pack(fill="x",padx=10,pady=6)
        self.attachment_list=tk.Listbox(attachments,height=4,
                exportselection=False,font=("Segoe UI",10))
        self.attachment_list.pack(side="left",fill="x",expand=True)
        self.thumbnail=tk.Label(attachments,text="Мініатюра\\n(за наявності)",
                                width=22,height=5,relief="groove",bg="#eef3f7",
                                compound="center")
        self.thumbnail.pack(side="right",padx=(8,0))
        self.thumbnail_ref=None
        self.thumbnail_request=0
        self.attachment_list.bind("<<ListboxSelect>>",self.preview_attachment)
        attbar=ttk.Frame(attachments)
        attbar.pack(side="right",padx=8)
        ttk.Button(attbar,text="Відкрити вибраний файл",
                   command=self.open_attachment).pack(fill="x",pady=2)
        ttk.Button(attbar,text="Відкрити оригінал Classroom",
                   command=self.open_original).pack(fill="x",pady=2)
        ttk.Label(attachments,text="Опис і назви вкладень видно тут. "
           "Сам файл відкриється окремо, якщо Google дозволяє доступ.",
           foreground="#355975").pack(side="bottom",anchor="w",pady=(4,0))
        self.notice=tk.StringVar(value="Матеріали завантажуються автоматично з вибраного курсу.")
        ttk.Label(self,textvariable=self.notice,foreground="#245574",
                 wraplength=1100).pack(anchor="w",padx=12,pady=(1,8))

    def _courses_from_local(self):
        found=[]
        # Курси вже зіставлені локально — доступні без додаткового входу в Google.
        mapping=self.parent.state.get("course_ids",{})
        for title,identifier in sorted(mapping.items()):
            if identifier:
                found.append({"id":str(identifier),"name":title})
        if self.parent.google_courses:
            found=list(self.parent.google_courses)
        self._set_courses(found)

    def _set_courses(self,courses):
        previous=self.current
        keys=set()
        clean=[]
        for item in courses:
            cid=str(item.get("id",""))
            if not cid or cid in keys:continue
            keys.add(cid);clean.append({"id":cid,"name":item.get("name",cid)})
        self.courses=sorted(clean,key=lambda x:(x["name"].casefold(),x["id"]))
        names=[f"{c['name']}   [{c['id']}]" for c in self.courses]
        self.combo.configure(values=names)
        selected=0
        current_lesson=self.parent.selected()
        target=self.parent.state.get("course_ids",{}).get(
            current_lesson.course_title if current_lesson else "")
        selected_id=str(previous or target or "")
        if selected_id:
            selected=next((i for i,c in enumerate(self.courses) if c["id"]==selected_id),0)
        if self.courses:
            self.combo.current(selected)
            self.current=self.courses[selected]["id"]
            cache=getattr(self.parent,"remote_classroom_entries",{})
            if self.current in cache:
                self.records=cache[self.current]
                self.refresh_list()
        else:
            self.current=None

    def _course_changed(self):
        index=self.combo.current()
        if not 0<=index<len(self.courses):return
        self.current=self.courses[index]["id"]
        self.records=list(getattr(self.parent,"remote_classroom_entries",{}).get(
            self.current,[]))
        self.refresh_list()
        self.notice.set("Одержую актуальні матеріали з вибраного курсу…")
        self.after(60,self.sync)

    def _schedule_synced(self):
        if self.current and not self.busy:
            self.after(100,self.sync)

    def _busy(self,yes,msg):
        self.busy=yes
        self.fetch_button.config(state="disabled" if yes else "normal")
        self.notice.set(msg)

    def load_courses(self):
        if self.busy:return
        self._busy(True,"Отримую список курсів Google…")
        def worker():
            try:
                from .google_client import list_teacher_courses
                value=list_teacher_courses()
                self.after(0,lambda:self._courses_loaded(value))
            except Exception as ex:
                info=str(ex)
                self.after(0,lambda:self._error(info))
        threading.Thread(target=worker,daemon=True).start()

    def _courses_loaded(self,items):
        if not self.winfo_exists():return
        self.parent.google_courses=items
        self._set_courses(items)
        self._busy(False,f"Отримано курсів: {len(items)}. Дані завантажуються автоматично.")
        if self.courses:self.after(80,self.sync)

    def sync(self):
        if self.busy:return
        cid=self.current
        if not cid:
            messagebox.showinfo("Курси","Спочатку підключіть Google та отримайте курси.",parent=self)
            return
        include_announcements=self.with_news.get()
        if include_announcements:
            from .engine import DATA
            if not (DATA/"google_announcements_token.json").exists():
                if not messagebox.askyesno("Окремий дозвіл",
                    "Щоб читати старі оголошення, Google один раз попросить "
                    "додатковий дозвіл тільки на перегляд оголошень. "
                    "Новий OAuth JSON чи API-ключ не потрібні. Продовжити?",
                    parent=self):return
        self._busy(True,"Одержую матеріали й завдання. До Classroom нічого не записується…")
        def worker():
            try:
                from .google_client import list_classroom_posts
                answer=list_classroom_posts(cid,include_announcements=include_announcements)
                self.after(0,lambda:self._synced(cid,answer))
            except Exception as ex:
                msg=str(ex)
                self.after(0,lambda:self._error(msg))
        threading.Thread(target=worker,daemon=True).start()

    def _synced(self,course_id,answer):
        if not self.winfo_exists():return
        posts=answer["items"]
        cache=getattr(self.parent,"remote_classroom_entries",None)
        if cache is None:
            self.parent.remote_classroom_entries={}
            cache=self.parent.remote_classroom_entries
        cache[course_id]=posts
        if self.current==course_id:
            self.records=posts
            self.refresh_list()
        else:
            # Якщо вчитель перемкнув курс під час завантаження,
            # після закінчення першого одразу завантажити новий.
            self.after(80,self.sync)
        # main list can now display status from remote Classroom, but never
        # changes local stored draft IDs or their documented validation.
        self.parent.update_day()
        note=f"Оновлено з Google: {len(posts)} записів."
        if answer["truncated"]:
            note+=" Є більше записів, ніж межа перегляду: "+", ".join(answer["truncated"])
        self._busy(False,note)

    def _error(self,error):
        if not self.winfo_exists():return
        self._busy(False,"Google не відповів. Наявні дані в таблиці збережено.")
        messagebox.showerror("Перегляд Classroom",
            error+"\n\nПеревірте інтернет, доступ до курсу й дозволи Google.",
            parent=self)

    def refresh_list(self):
        status=self.status.get()
        kind=self.kind.get()
        keyword=self.keyword.get().casefold().strip()
        self.visible=[
            record for record in self.records
            if (status=="Усі" or record["state_ua"]==status)
            and (kind=="Усі" or record["type"]==kind)
            and (not keyword or keyword in
              (record["title"]+" "+record["description"]+" "+
               " ".join(x["title"] for x in record["attachments"])).casefold())
        ]
        self.table.delete(*self.table.get_children())
        for i,record in enumerate(self.visible):
            self.table.insert("","end",iid=str(i),values=(
                record["date"],record["type"],record["state_ua"],
                record["title"][:180],len(record["attachments"])))
        self._set_detail("")
        self.attachment_list.delete(0,"end")
        self._reset_thumbnail()
        if self.visible:
            self.table.selection_set("0")
            self.show_item()

    def _set_detail(self,content):
        self.detail.configure(state="normal")
        self.detail.delete("1.0","end")
        self.detail.insert("1.0",content)
        self.detail.configure(state="disabled")

    def show_item(self):
        selected=self.table.selection()
        if not selected:return
        record=self.visible[int(selected[0])]
        self._set_detail(
            f"Назва: {record['title']}\n"
            f"Статус: {record['state_ua']} • {record['type']}\n"
            f"Створено: {record['date']}\n\n"
            +(record["description"] or "Опис відсутній."))
        self.attachment_list.delete(0,"end")
        self._reset_thumbnail()
        for item in record["attachments"]:
            self.attachment_list.insert("end",f"{item['kind']} • {item['title']}")
        if record["attachments"]:
            self.attachment_list.selection_set(0)
            self.preview_attachment()

    def _reset_thumbnail(self):
        if not hasattr(self,"thumbnail"):return
        self.thumbnail_request+=1
        self.thumbnail_ref=None
        self.thumbnail.configure(image="",text="Мініатюра\\n(за наявності)")

    def preview_attachment(self,_event=None):
        record=self._current_record()
        chosen=self.attachment_list.curselection()
        self._reset_thumbnail()
        if not record or not chosen:return
        attachment=record["attachments"][chosen[0]]
        url=attachment.get("thumbnail_url","")
        if not url:return
        # Автоматичне завантаження тільки з доменів Google/YouTube,
        # щоб учительські приватні URL не передавались стороннім сайтам.
        host=urlsplit(url).hostname or ""
        trusted=("googleusercontent.com","gstatic.com","ytimg.com","google.com")
        if not any(host==domain or host.endswith("."+domain) for domain in trusted):
            return
        request_id=self.thumbnail_request
        def worker():
            try:
                req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
                with urllib.request.urlopen(req,timeout=6) as response:
                    content=response.read(2*1024*1024+1)
                if len(content)>2*1024*1024:raise ValueError("Зображення завелике")
                from PIL import Image
                img=Image.open(io.BytesIO(content))
                img.thumbnail((150,100))
                img=img.convert("RGB")
                self.after(0,lambda:self._set_thumbnail(img,request_id))
            except (OSError,ValueError,ImportError):
                # Мініатюри необов'язкові; метадані не приховуємо.
                pass
        threading.Thread(target=worker,daemon=True).start()

    def _set_thumbnail(self,picture,request_id):
        if not self.winfo_exists() or self.thumbnail_request!=request_id:return
        from PIL import ImageTk
        photo=ImageTk.PhotoImage(picture,master=self)
        self.thumbnail_ref=photo
        self.thumbnail.configure(image=photo,text="")

    def _record_context_menu(self,event):
        item=self.table.identify_row(event.y)
        if item:self.table.selection_set(item);self.show_item()
        menu=tk.Menu(self,tearoff=False)
        menu.add_command(label="Копіювати назву і опис (Ctrl+C)",
                         command=self.copy_current_record)
        menu.add_command(label="Відкрити запис у Classroom",
                         command=self.open_original)
        menu.add_separator()
        menu.add_command(label="Видалити запис (лише на сайті Classroom)",
                         command=self._read_only_delete)
        menu.tk_popup(event.x_root,event.y_root)
        menu.grab_release()

    def copy_current_record(self):
        record=self._current_record()
        if not record:return "break"
        self.clipboard_clear()
        self.clipboard_append(
            f"{record['title']}\n{record['state_ua']}\n"
            f"{record['description']}")
        return "break"

    def _read_only_delete(self):
        messagebox.showinfo("Перегляд лише для читання",
            "Це справжній запис Google Classroom. Щоб уникнути "
            "випадкового знищення завдань учнів, видалення тут "
            "не виконується. Скористайтеся Classroom, якщо "
            "потрібно видалити опублікований матеріал.",parent=self)
        return "break"

    def _current_record(self):
        selected=self.table.selection()
        return self.visible[int(selected[0])] if selected else None

    def open_attachment(self):
        record=self._current_record()
        selection=self.attachment_list.curselection()
        if not record or not selection:return
        item=record["attachments"][selection[0]]
        if item["url"]:webbrowser.open(item["url"])
        else:messagebox.showinfo("Вкладення",
            "Google повернув назву файлу без адреси відкриття. "
            "Файл, можливо, недоступний за поточними дозволами.",parent=self)

    def open_original(self):
        record=self._current_record()
        if record and record["url"]:webbrowser.open(record["url"])
        else:messagebox.showinfo("Оригінал",
          "Для чернеток Google іноді не повертає пряме посилання. "
          "Усі доступні назва, опис і вкладення показані вище.",parent=self)


def show_classroom_viewer(parent):
    return ClassroomViewer(parent)
