# -*- coding: utf-8 -*-
"""
Бланк «ШИФРОВКА» для «Кода Марса».

* PNG — по картинке на лист: QR-код, номер вида 041026/001, дата, ключ,
  шифровка группами по 5 знаков с номером над каждой группой.
* Word (.docx) — шифровка идёт обычным текстом документа поверх картинки
  бланка, поэтому «Выделить всё» и копирование берут только её, без пробелов
  (промежутки между группами сделаны разрядкой). Номер, дата, ключ,
  счётчики групп и пустые поля бланка — отдельные надписи, их можно править.
"""
from __future__ import annotations

import datetime as _dt
import io
import math
import zipfile
from xml.sax.saxutils import escape

import marscore as core

FORM_W, FORM_H = 2528, 3416
QR_BOX = (68, 1666, 632, 2229)
KEY_FIELD = (72, 2342, 590)          # x, середина по высоте, правый край
NUMBER = (1765, 450, 2440, 92)       # x, линия строки, правый край, высота цифр (знак № — 119 px)
FILED = (1135, 586)                  # «Подана»
TEXT_AREA = (790, 800, 2400, 2960)
PAGE_NO = (2470, 3390)
EMPTY_FIELDS = ((330, 925, 600), (1950, 2415, 600), (830, 2415, 682), (1100, 1740, 3090), (1370, 1740, 3192))
INK = (0, 0, 0)
INK_SOFT = (95, 95, 105)

PER_LINE = 7
LINES_PER_PAGE = 16
PER_PAGE = PER_LINE * LINES_PER_PAGE
GROUP_PX, NUM_PX = 52, 24
PITCH = NUM_PX + 8 + GROUP_PX + 36

LABELS = {"key": "Ключ: {key}", "per_page": "Групп на странице: {n}", "total": "Всего групп: {n}",
          "no_fit": "QR не\nпомещается"}


def groups_of(b32):
    s = core.normalize_b32(b32)
    return [s[i:i + 5] for i in range(0, len(s), 5)]


def paginate(groups):
    return [groups[i:i + PER_PAGE] for i in range(0, len(groups), PER_PAGE)] or [[]]


def form_number(when, seq):
    """041026/001 — дата отправки и порядковый номер бланка."""
    return f"{when:%d%m%y}/{seq:03d}"


def footer_lines(on_page, total, page, pages, labels=LABELS):
    if pages == 1:
        return [labels["total"].format(n=total)]
    lines = [labels["per_page"].format(n=on_page)]
    if page == pages - 1:
        lines.append(labels["total"].format(n=total))
    return lines


def _font(size):
    from PIL import ImageFont

    for name in ("courbd.ttf", "cour.ttf", "consolab.ttf", "DejaVuSansMono-Bold.ttf",
                 "LiberationMono-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def base_image(form_path, b32, labels=LABELS):
    """Чистый бланк с QR-кодом в квадрате."""
    from PIL import Image, ImageDraw

    img = Image.open(form_path).convert("RGB")
    x0, y0, x1, y1 = QR_BOX
    inner = min(x1 - x0, y1 - y0) - 44
    try:
        m = core.qr_matrix(core.normalize_b32(b32), border=2)
        q = core.qr_image(m, max(1, inner // len(m))).convert("RGB")
        img.paste(q, (x0 + (x1 - x0 - q.width) // 2, y0 + (y1 - y0 - q.height) // 2))
    except core.MarsError:
        ImageDraw.Draw(img).text(((x0 + x1) // 2, (y0 + y1) // 2), labels["no_fit"], font=_font(40),
                                 fill=INK, anchor="mm", align="center")
    return img


def _number_mask(number):
    """Номер шифровки чуть ниже знака №; если не влезает по ширине — сжимается."""
    from PIL import Image, ImageDraw

    x, _, right, height = NUMBER
    box = _font(150).getbbox("0123456789", anchor="ls")
    size = max(20, round(150 * height / max(1, box[3] - box[1])))
    font = _font(size)
    asc, desc = font.getmetrics()
    mask = Image.new("L", (int(math.ceil(font.getlength(number))) + 4, asc + desc), 0)
    ImageDraw.Draw(mask).text((0, asc), number, font=font, fill=255, anchor="ls")
    if mask.width > right - x:
        mask = mask.resize((right - x, mask.height), Image.LANCZOS)
    return mask, asc


def _draw_header(img, number, key_label, when, labels):
    from PIL import Image, ImageDraw

    d = ImageDraw.Draw(img)
    mask, asc = _number_mask(number)
    img.paste(Image.new("RGB", mask.size, INK), (NUMBER[0], NUMBER[1] - asc), mask)
    d.text(FILED, when.strftime("%d.%m.%Y %H:%M"), font=_font(42), fill=INK, anchor="ls")
    kx, ky, kright = KEY_FIELD
    label, size = labels["key"].format(key=key_label), 40
    font = _font(size)
    while font.getlength(label) > kright - kx and size > 20:
        size -= 2
        font = _font(size)
    while font.getlength(label) > kright - kx and len(label) > 8:
        label = label[:-2] + "…"
    d.text((kx, ky), label, font=font, fill=INK, anchor="lm")


def render_png_pages(form_path, b32, key_label, number, when=None, labels=LABELS):
    """Список картинок-листов бланка."""
    from PIL import ImageDraw

    when = when or _dt.datetime.now()
    groups = groups_of(b32)
    pages = paginate(groups)
    head = base_image(form_path, b32, labels)
    _draw_header(head, number, key_label, when, labels)
    gfont, nfont, ffont = _font(GROUP_PX), _font(NUM_PX), _font(40)
    x0, y0, x1, _ = TEXT_AREA
    gw = gfont.getlength("MMMMM")
    gap = (x1 - x0 - PER_LINE * gw) / (PER_LINE - 1)   # выравнивание по ширине поля
    out = []
    for p, page in enumerate(pages):
        img = head.copy()
        d = ImageDraw.Draw(img)
        y = y0
        for li in range(0, len(page), PER_LINE):
            for ci, g in enumerate(page[li:li + PER_LINE]):
                gx = x0 + ci * (gw + gap)
                d.text((gx + gw / 2, y), str(p * PER_PAGE + li + ci + 1), font=nfont, fill=INK_SOFT, anchor="mt")
                d.text((gx, y + NUM_PX + 8), g, font=gfont, fill=INK)
            y += PITCH
        y += 10
        for line in footer_lines(len(page), len(groups), p, len(pages), labels):
            d.text((x0, y), line, font=ffont, fill=INK)
            y += 56
        if len(pages) > 1:
            d.text(PAGE_NO, str(p + 1), font=_font(60), fill=INK, anchor="rs")
        out.append(img)
    return out


# ---------------------------------------------------------------------------
# Word (.docx), собирается вручную: никаких дополнительных библиотек
# ---------------------------------------------------------------------------
PAGE_W_TW, PAGE_H_TW = 11906, 16838            # A4 в twips
TW = PAGE_W_TW / FORM_W                        # twips на пиксель бланка
OFF_Y = round((PAGE_H_TW - FORM_H * TW) / 2)   # бланк по центру листа
FONT = "Courier New"
ASC, LINE_H, ADV, DIGIT_H = 0.8325, 1.1328, 0.6001, 0.615   # метрики Courier New в долях кегля
CIPHER_PT, CIPHER_LINE = 14, 480

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
      'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"')
SHAPETYPE = ('<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe">'
             '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>')


def _x(px):
    return round(px * TW)


def _y(px):
    return OFF_Y + round(px * TW)


def _rpr(half_pt, spacing=None, scale=None):
    s = (f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/>'
         '<w:b/><w:bCs/><w:color w:val="000000"/>')
    if spacing:
        s += f'<w:spacing w:val="{spacing}"/>'
    if scale and scale != 100:
        s += f'<w:w w:val="{scale}"/>'
    s += f'<w:sz w:val="{half_pt}"/><w:szCs w:val="{half_pt}"/>'
    return f"<w:rPr>{s}</w:rPr>"


def _run(text, half_pt, spacing=None, scale=None):
    return f'<w:r>{_rpr(half_pt, spacing, scale)}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


class _Shapes:
    """Надписи (текстовые поля VML) с точным местом на листе."""

    def __init__(self):
        self.n = 0

    def box(self, x0_px, x1_px, top_tw, height_tw, paragraphs):
        self.n += 1
        style = (f"position:absolute;margin-left:{_x(x0_px) / 20:.2f}pt;margin-top:{top_tw / 20:.2f}pt;"
                 f"width:{(_x(x1_px) - _x(x0_px)) / 20:.2f}pt;height:{height_tw / 20:.2f}pt;"
                 f"z-index:{251659264 + self.n};mso-position-horizontal-relative:page;"
                 "mso-position-vertical-relative:page")
        body = "".join(
            f'<w:p><w:pPr><w:spacing w:before="{before}" w:after="0" w:line="{line}" w:lineRule="exact"/>'
            f'<w:jc w:val="{jc}"/>{_rpr(half)}</w:pPr>{runs}</w:p>'
            for jc, line, before, runs, half in paragraphs)
        first = SHAPETYPE if self.n == 1 else ""
        return (f'<w:r><w:pict>{first}<v:shape id="km_box{self.n}" o:spid="_x0000_s{1024 + self.n}" '
                f'type="#_x0000_t202" style="{style}" filled="f" stroked="f"><v:textbox inset="0,0,0,0">'
                f'<w:txbxContent>{body}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>')

    def field(self, x0, x1, base_px, pt, text="", jc="left", scale=None):
        """Однострочная надпись: текст стоит на линии base_px бланка."""
        half = int(round(pt * 2))
        line = round(LINE_H * pt * 20)
        runs = _run(text, half, scale=scale) if text else ""
        return self.box(x0, x1, _y(base_px) - round(ASC * pt * 20), line + 40, [(jc, line, 0, runs, half)])


def _background(page_no, cx, cy):
    """Картинка бланка за текстом, привязанная к своему листу."""
    return (
        '<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
        f'relativeHeight="{page_no}" behindDoc="1" locked="1" layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{OFF_Y * 635}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{100 + page_no}" name="Бланк {page_no}"/><wp:cNvGraphicFramePr>'
        '<a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
        f'<pic:nvPicPr><pic:cNvPr id="{100 + page_no}" name="blank.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rIdBg"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
        '</wp:anchor></w:drawing></w:r>')


def _page_objects(shapes, p, pages, page_groups, total, number, key_label, when, labels, cx, cy):
    x, base, right, height = NUMBER
    pt = round(height * TW / 20 / DIGIT_H)
    scale = max(50, min(100, int(100 * (_x(right) - _x(x)) / (len(number) * ADV * pt * 20))))
    kx, ky, kright = KEY_FIELD
    key = labels["key"].format(key=key_label)
    kpt = math.floor(max(6.0, min(10.0, (_x(kright) - _x(kx)) / (len(key) * ADV * 20))) * 2) / 2
    parts = [_background(p + 1, cx, cy),
             shapes.field(x, right, base, pt, number, scale=scale),
             shapes.field(1125, 1735, FILED[1], 10, when.strftime("%d.%m.%Y %H:%M")),
             shapes.field(kx, kright, ky + 11, kpt, key)]
    parts += [shapes.field(a, b, base_px, 10) for a, b, base_px in EMPTY_FIELDS]
    # счётчики групп — сразу под последней строкой шифровки этого листа
    lines = math.ceil(len(page_groups) / PER_LINE)
    footer = footer_lines(len(page_groups), total, p, pages, labels)
    paragraphs = [("left", 300, 0, _run(line, 22), 22) for line in footer]
    parts.append(shapes.box(TEXT_AREA[0], TEXT_AREA[2], _y(TEXT_AREA[1]) + lines * CIPHER_LINE + 240,
                            300 * len(footer) + 60, paragraphs))
    if pages > 1:
        parts.append(shapes.field(2250, PAGE_NO[0], PAGE_NO[1], 16, str(p + 1), jc="right"))
    return "".join(parts)


def build_docx(form_path, b32, key_label, number, target, when=None, labels=LABELS):
    """Документ Word с листами бланка (target — путь или файловый объект)."""
    when = when or _dt.datetime.now()
    groups = groups_of(b32)
    pages = paginate(groups)
    bg = io.BytesIO()
    base_image(form_path, b32, labels).save(bg, "PNG", optimize=True)
    cx, cy = PAGE_W_TW * 635, round(FORM_H * TW) * 635
    half = CIPHER_PT * 2
    adv = ADV * CIPHER_PT * 20
    x0, y0, x1, _ = TEXT_AREA
    gap = int((_x(x1) - _x(x0) - adv / 2 - PER_LINE * 5 * adv) // (PER_LINE - 1))
    shapes, runs = _Shapes(), []
    for p, page in enumerate(pages):
        objects = _page_objects(shapes, p, len(pages), page, len(groups), number, key_label, when, labels, cx, cy)
        if not page:
            runs.append(objects)
        for k, g in enumerate(page):
            spacing = None if (k % PER_LINE == PER_LINE - 1 or k == len(page) - 1) else gap
            if k == 0 and p == 0:
                runs.append(objects)           # первый лист: объекты в самом начале
            if len(g) == 1:
                runs.append(_run(g, half, spacing=spacing))
                if k == 0 and p > 0:
                    runs.append(objects)
                continue
            runs.append(_run(g[0], half))
            if k == 0 and p > 0:
                runs.append(objects)           # следующие листы: после первой буквы листа
            if len(g) > 2:
                runs.append(_run(g[1:-1], half))
            runs.append(_run(g[-1], half, spacing=spacing))
    top = _y(y0)
    bottom = PAGE_H_TW - (top + LINES_PER_PAGE * CIPHER_LINE + 200)
    body = (f'<w:p><w:pPr><w:widowControl w:val="0"/><w:spacing w:before="0" w:after="0" '
            f'w:line="{CIPHER_LINE}" w:lineRule="exact"/><w:jc w:val="left"/>{_rpr(half)}</w:pPr>'
            f'{"".join(runs)}</w:p>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document {NS}><w:body>{body}'
        f'<w:sectPr><w:pgSz w:w="{PAGE_W_TW}" w:h="{PAGE_H_TW}"/>'
        f'<w:pgMar w:top="{top}" w:right="{PAGE_W_TW - _x(x1)}" w:bottom="{bottom}" w:left="{_x(x0)}" '
        'w:header="0" w:footer="0" w:gutter="0"/></w:sectPr></w:body></w:document>')
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults>'
        f'<w:rPrDefault><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/>'
        '<w:color w:val="000000"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
        '</w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/></w:style></w:styles>')
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:zoom w:percent="100"/><w:defaultTabStop w:val="708"/>'
        '<w:characterSpacingControl w:val="doNotCompress"/><w:compat><w:compatSetting '
        'w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>'
        '</w:compat></w:settings>')
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
        f'<Override PartName="/word/document.xml" ContentType="{ct}.document.main+xml"/>'
        f'<Override PartName="/word/styles.xml" ContentType="{ct}.styles+xml"/>'
        f'<Override PartName="/word/settings.xml" ContentType="{ct}.settings+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>')
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    root_rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{pkg}">'
        f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/>'
        f'<Relationship Id="rId2" Type="{pkg}/metadata/core-properties" Target="docProps/core.xml"/>'
        f'<Relationship Id="rId3" Type="{rel}/extended-properties" Target="docProps/app.xml"/></Relationships>')
    doc_rels = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{pkg}">'
        f'<Relationship Id="rIdStyles" Type="{rel}/styles" Target="styles.xml"/>'
        f'<Relationship Id="rIdSettings" Type="{rel}/settings" Target="settings.xml"/>'
        f'<Relationship Id="rIdBg" Type="{rel}/image" Target="media/blank.png"/></Relationships>')
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{escape(number)}</dc:title><dc:creator>Код Марса</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{when:%Y-%m-%dT%H:%M:%S}Z</dcterms:created>'
        '</cp:coreProperties>')
    app_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
               '<Application>Код Марса</Application></Properties>')
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core_xml)
        z.writestr("docProps/app.xml", app_xml)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/settings.xml", settings)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/media/blank.png", bg.getvalue())
