"""Розклад: імпорт таблиці, ручне редагування та експорт у друкований DOCX."""
from __future__ import annotations
import csv
import io
import re
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from .editor_core import csv_rows,docx_table_rows,tidy

DAYS=("Понеділок","Вівторок","Середа","Четвер","П’ятниця")
ALTS=("пн","вт","ср","чт","пт")
NAMES=("понеділок","вівторок","середа","четвер","пятниця","п'ятниця","п’ятниця")

def _xlsx_rows(path):
    """Читання першого аркуша XLSX стандартною бібліотекою, без макросів."""
    m={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    r={'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            ss=ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings=[''.join(x.text or '' for x in si.iter('{'+m['m']+'}t'))
                     for si in ss.findall('m:si',m)]
        workbook=ET.fromstring(z.read('xl/workbook.xml'))
        sheet=workbook.find('m:sheets/m:sheet',m)
        if sheet is None:raise ValueError("У XLSX немає аркушів")
        relid=sheet.get('{'+r['r']+'}id')
        reltree=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        relnode=next((x for x in reltree if x.get('Id')==relid),None)
        if relnode is None:raise ValueError("Не вдалося прочитати аркуш XLSX")
        target=relnode.get('Target').lstrip('/')
        if not target.startswith('xl/'):target='xl/'+target
        doc=ET.fromstring(z.read(target))
        ret=[]
        for row in doc.findall('.//m:sheetData/m:row',m):
            cells={}
            for cell in row.findall('m:c',m):
                ref=cell.get('r','')
                match=re.match(r'^([A-Z]+)',ref)
                if not match:continue
                ind=0
                for ch in match.group(1):ind=ind*26+ord(ch)-64
                val=cell.find('m:v',m)
                text=(val.text or '') if val is not None else ''
                if cell.get('t')=='s':
                    text=strings[int(text)] if text else ''
                elif cell.get('t')=='inlineStr':
                    text=''.join(n.text or '' for n in cell.findall('.//m:t',m))
                cells[ind-1]=tidy(text)
            if cells:
                ret.append([cells.get(i,'') for i in range(max(cells)+1)])
        return ret

def table_rows(path):
    suffix=Path(path).suffix.lower()
    if suffix=='.csv':return csv_rows(path)
    if suffix in ('.doc','.docx'):return docx_table_rows(path)
    if suffix=='.xlsx':return _xlsx_rows(path)
    raise ValueError("Імпорт розкладу підтримує DOCX, DOC, CSV та XLSX.")

def _normalize(text):
    return tidy(text).casefold().replace('’',"'").replace('–','-').replace('—','-')

def resolve_stream(raw,stream_names,base="",aliases=None):
    raw=tidy(raw)
    if not raw or raw in ('—','-','–'):return None
    match=re.match(r'^(\d{1,2})\s*[-–]\s*([А-Яа-яA-Z])(?:\s+(.+))?$',raw)
    if base and not re.match(r'^\d',raw):
        c=re.match(r'^(\d{1,2})\s*[-–]\s*[А-Яа-яA-Z]',base)
        if c:
            raw=base.split()[0]+' '+raw
    alias=(aliases or {}).get(_normalize(raw))
    if alias in stream_names:return alias
    exact=[s for s in stream_names if _normalize(s)==_normalize(raw)]
    return exact[0] if len(exact)==1 else ("? "+raw)

def parse_cell(value,known_streams,aliases=None):
    text=tidy(value).replace('\n',' ')
    if not text or text in ('—','–','-'):return [None,None]
    halves=[tidy(x) for x in text.split('/',1)]
    if len(halves)==1:halves=[halves[0],halves[0]]
    a=resolve_stream(halves[0],known_streams,aliases=aliases)
    b=resolve_stream(halves[1],known_streams,base=halves[0],aliases=aliases)
    return [a,b]

def decode_schedule(rows,config):
    """Повертає всі дні без перезапису; невідомі потоки повідомляються у прев'ю."""
    header_i=None
    daycols={}
    for i,row in enumerate(rows[:18]):
        found={}
        for j,cell in enumerate(row):
            text=_normalize(cell)
            for d,token in enumerate(("понеділ","вівтор","серед","четвер","пятниц","п'ятниц")):
                if token in text:
                    found[d if d<4 else 4]=j
        if len(found)==5:
            header_i=i;daycols=found;break
    if header_i is None:
        raise ValueError("Не знайдено рядок із п'ятьма днями тижня. Потрібна таблиця: №, Понеділок, ..., П'ятниця.")
    count=len(config['period_times'])
    schedule={str(d):[[None,None] for _ in range(count)] for d in range(5)}
    unknown=set()
    found_numbers=set()
    aliases=config.get("schedule_aliases",{})
    for row in rows[header_i+1:]:
        if not row:continue
        label=_normalize(row[0])
        match=re.match(r'^(\d{1,2})(?:\b|[.)\s])',label)
        if not match:continue
        period=int(match.group(1))
        if period<1 or period>count:continue
        found_numbers.add(period)
        for day,col in daycols.items():
            value=row[col] if col<len(row) else ''
            pair=parse_cell(value,config['course_map'],aliases=aliases)
            for x in pair:
                if x and x.startswith('? '):unknown.add(x[2:])
            schedule[str(day)][period-1]=pair
    if not found_numbers:raise ValueError("У таблиці не знайдено уроків із номерами 1, 2, ...")
    return schedule,sorted(unknown),sorted(found_numbers)

def export_schedule_docx(config,path,show_bells=False,show_meal=False,show_numbers=True):
    from docx import Document
    from docx.shared import Pt,Cm,RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc=Document()
    sect=doc.sections[0]
    sect.orientation=WD_ORIENT.LANDSCAPE
    sect.page_width=Cm(29.7);sect.page_height=Cm(21.0)
    sect.left_margin=Cm(1.3);sect.right_margin=Cm(1.3)
    sect.top_margin=Cm(1.5);sect.bottom_margin=Cm(1.5)
    default=doc.styles['Normal']
    default.font.name='Times New Roman';default.font.size=Pt(11)
    head=doc.add_paragraph()
    head.alignment=WD_ALIGN_PARAGRAPH.CENTER
    h=head.add_run("НАВАНТАЖЕННЯ · РОЗКЛАД УРОКІВ")
    h.bold=True;h.font.name='Times New Roman';h.font.size=Pt(16)
    years=f"{config['year_start'][:4]}–{config['year_end'][:4]}"
    sub=doc.add_paragraph(f"Навчальний рік: {years}    •    Чисельник / знаменник")
    sub.alignment=WD_ALIGN_PARAGRAPH.CENTER
    table=doc.add_table(rows=1,cols=6)
    table.style='Table Grid'
    for j,value in enumerate(('№',)+DAYS):table.rows[0].cells[j].text=value
    def fill_color(cell,color):
        tcpr=cell._tc.get_or_add_tcPr();s=OxmlElement('w:shd');s.set(qn('w:fill'),color);tcpr.append(s)
    for cell in table.rows[0].cells:fill_color(cell,'D9EAF4')
    count=len(config['period_times'])
    meal_after=int(config.get('meal_break_after',2))
    for n in range(1,count+1):
        row=table.add_row()
        times=config["period_times"][n-1]
        number=str(n) if show_numbers else ""
        row.cells[0].text=number+(f"\n{times[0]}–{times[1]}" if show_bells else "")
        for d in range(5):
            entry=config['days'].get(str(d),[])
            a,b=entry[n-1] if len(entry)>=n else (None,None)
            if a==b:
                content=a or ''
            else:
                content=f"{a or ''} / {b or ''}"
            row.cells[d+1].text=content
        if show_meal and n==meal_after:
            meal=table.add_row().cells[0]
            merged=meal.merge(table.rows[-1].cells[5])
            merged.text=config.get('meal_label','ХАРЧУВАННЯ У ЇДАЛЬНІ')
            fill_color(merged,'FFF0D1')
            for p in merged.paragraphs:
                p.alignment=WD_ALIGN_PARAGRAPH.CENTER
                for run in p.runs:run.bold=True
    for index,row in enumerate(table.rows):
        row.height=Cm(1.14)
        row.height_rule=WD_ROW_HEIGHT_RULE.AT_LEAST
        for cell in row.cells:
            cell.vertical_alignment=1
            for para in cell.paragraphs:
                para.alignment=WD_ALIGN_PARAGRAPH.CENTER
                for run in para.runs:
                    run.font.size=Pt(11)
                    if index==0:run.bold=True
    doc.save(path)
    return Path(path)
