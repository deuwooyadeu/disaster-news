#!/usr/bin/env python3
"""
재난·사고 일일 브리핑 PDF 생성기.

brief.json(정리된 사건 목록)을 읽어 매일 같은 형식의 PDF를 만든다.
내용은 날마다 달라지지만 레이아웃·글꼴·구성은 고정된다.

사용:
    python make_pdf.py brief.json 재난브리핑_2026-07-24.pdf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping as _addMapping


def registerFontFamily(family, normal, bold, italic, boldItalic):
    from reportlab.pdfbase.pdfmetrics import registerFontFamily as _rff
    _rff(family, normal=normal, bold=bold, italic=italic, boldItalic=boldItalic)
    _addMapping(family, 0, 0, normal)
    _addMapping(family, 1, 0, bold)
    _addMapping(family, 0, 1, italic)
    _addMapping(family, 1, 1, boldItalic)
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

# 레포트랩 내장 한중일 글꼴. 별도 폰트 파일이 필요 없다.
HERE = Path(__file__).resolve().parent


def _find_fonts() -> tuple[str, str, str, bool]:
    """
    쓸 수 있는 한글 글꼴을 찾아 (본문, 제목, 이름, 완전지원여부)를 돌려준다.

    1순위 맑은 고딕 — 사용자가 지정한 글꼴. 글꼴 파일이 곁에 있을 때만 쓴다.
    2순위 나눔고딕 — pip 패키지에 들어 있어 어느 환경에서든 설치할 수 있다.
                    예약 작업이 원격에서 돌 때 실제로 쓰이는 글꼴이다.
    3순위 레포트랩 내장 CJK — 최후의 수단. 가운뎃점 등 일부 글자가 깨진다.
    """
    candidates = [
        ("맑은 고딕", HERE / "malgun.ttf", HERE / "malgunbd.ttf"),
        ("맑은 고딕", Path("/usr/share/fonts/malgun.ttf"),
         Path("/usr/share/fonts/malgunbd.ttf")),
    ]

    # 나눔고딕은 koreanize_matplotlib 패키지 안에 들어 있다.
    try:
        import koreanize_matplotlib as _km
        d = Path(_km.__file__).parent / "fonts"
        candidates.append(("나눔고딕", d / "NanumGothic.ttf", d / "NanumGothicBold.ttf"))
    except Exception:
        pass

    for name, reg, bold in candidates:
        if not reg.exists():
            continue
        pdfmetrics.registerFont(TTFont("BodyKR", str(reg)))
        pdfmetrics.registerFont(TTFont("HeadKR", str(bold if bold.exists() else reg)))
        registerFontFamily("BodyKR", normal="BodyKR", bold="HeadKR",
                           italic="BodyKR", boldItalic="HeadKR")
        return "BodyKR", "HeadKR", name, True

    for f in ("HYSMyeongJo-Medium", "HYGothic-Medium"):
        pdfmetrics.registerFont(UnicodeCIDFont(f))
    return "HYSMyeongJo-Medium", "HYGothic-Medium", "내장 CJK", False


BODY_FONT, HEAD_FONT, FONT_NAME, FULL_GLYPHS = _find_fonts()
NUM = HEAD_FONT if FULL_GLYPHS else "Helvetica"
USING_MALGUN = FULL_GLYPHS   # 완전한 글꼴이면 문자 치환이 필요 없다

# 예전 이름 유지 (본문/제목 글꼴)
SERIF = BODY_FONT
SANS = HEAD_FONT

# 가장 작은 글자가 11pt가 되도록 전체 크기를 같은 비율로 키운다.
# 기존 최소값이 7.4pt였으므로 배율은 11/7.4.
MIN_PT = 11.0
SCALE = MIN_PT / 7.4


def pt(original: float) -> float:
    """예전 크기를 11pt 기준으로 환산한다."""
    return round(original * SCALE, 1)

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b6b6b")
RULE = colors.HexColor("#d4d4d4")
ACCENT = colors.HexColor("#8c2f24")
BAND = colors.HexColor("#f2f0ed")
LINK = colors.HexColor("#2f5d8a")

CATEGORY_COLOR = {
    "자연재난": colors.HexColor("#2f5d50"),
    "사회재난": colors.HexColor("#8c2f24"),
    "사고": colors.HexColor("#3b4a6b"),
}

MARGIN_X = 20 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOT = 18 * mm

# 내장 CJK 글꼴에 없는 글자는 검은 상자로 찍힌다. 실제로 렌더링해 확인한
# 결과 아래 문자들이 빠져 있어, 모양이 같고 출력되는 글자로 바꿔 쓴다.
GLYPH_FIX = {"\u00a0": " "} if USING_MALGUN else {
    "\u00b7": "\u318d",
    "\u2027": "\u318d",
    "\uff65": "\u318d",
    "\u2022": "\u318d",
    "\u00a0": " ",
}


def safe(text):
    """글꼴에 없는 문자를 치환한다. 문자열이 아니면 그대로 돌려준다."""
    if isinstance(text, str):
        for bad, good in GLYPH_FIX.items():
            text = text.replace(bad, good)
        return text
    if isinstance(text, dict):
        return {k: safe(v) for k, v in text.items()}
    if isinstance(text, list):
        return [safe(v) for v in text]
    return text


def styles() -> dict:
    return {
        "title": ParagraphStyle(
            "title", fontName=HEAD_FONT, fontSize=pt(20), leading=pt(26),
            textColor=INK, spaceAfter=3,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=BODY_FONT, fontSize=pt(10.5), leading=pt(15),
            textColor=MUTED,
        ),
        "section": ParagraphStyle(
            "section", fontName=HEAD_FONT, fontSize=pt(11), leading=pt(15),
            textColor=INK, spaceBefore=pt(10), spaceAfter=pt(5),
        ),
        "event_title": ParagraphStyle(
            "event_title", fontName=HEAD_FONT, fontSize=pt(11), leading=pt(15.5),
            textColor=INK,
        ),
        "meta": ParagraphStyle(
            "meta", fontName=BODY_FONT, fontSize=pt(8.6), leading=pt(12.5),
            textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "body", fontName=BODY_FONT, fontSize=pt(9.6), leading=pt(14.5),
            textColor=INK, alignment=TA_LEFT,
        ),
        "note": ParagraphStyle(
            "note", fontName=BODY_FONT, fontSize=pt(8.2), leading=pt(12),
            textColor=MUTED,
        ),
        "rank": ParagraphStyle(
            "rank", fontName=HEAD_FONT, fontSize=pt(13), leading=pt(15),
            textColor=colors.HexColor("#b9b4ae"),
        ),
        "count": ParagraphStyle(
            "count", fontName=HEAD_FONT, fontSize=pt(8.4), leading=pt(11),
            textColor=MUTED,
        ),
    }


def header_footer(canvas, doc, meta: dict):
    canvas.saveState()
    w, h = A4

    canvas.setFont(BODY_FONT, pt(7.8))
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN_X, h - 13 * mm, safe("재난·사고 일일 브리핑"))
    canvas.drawRightString(w - MARGIN_X, h - 13 * mm, meta.get("date_label", ""))
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN_X, h - 15 * mm, w - MARGIN_X, h - 15 * mm)

    canvas.line(MARGIN_X, 13 * mm, w - MARGIN_X, 13 * mm)
    canvas.drawString(MARGIN_X, 9 * mm, meta.get("source_note", ""))
    canvas.drawRightString(w - MARGIN_X, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def stat_band(data: dict, st: dict) -> Table:
    s = data["stats"]
    t = data.get("totals", {})

    def cell(label, value, sub=""):
        # 한글이 섞인 값은 라틴 글꼴로 찍으면 깨지므로 글꼴을 나눠 쓴다.
        hangul = any("가" <= ch <= "힣" for ch in str(value))
        font, size = (HEAD_FONT, pt(12.5)) if hangul else (NUM, pt(15))
        para = [
            Paragraph(f'<font size="{pt(7.6)}" color="#6b6b6b">{label}</font>', st["note"]),
            Spacer(1, 3),
            Paragraph(f'<font name="{font}" size="{size}" color="#1a1a1a">{value}</font>', st["body"]),
        ]
        if sub:
            para.append(Spacer(1, 2))
            para.append(Paragraph(f'<font size="{pt(7.4)}" color="#6b6b6b">{sub}</font>', st["note"]))
        return para

    casualty = [f"{label} {t[key]}"
                for key, label in (("dead", "사망"), ("missing", "실종"), ("injured", "부상"))
                if t.get(key)]
    head = casualty[0] if casualty else "확인된 피해 없음"
    tail = safe(" · ").join(casualty[1:])

    row = [
        cell("수집 기사", f"{s['collected']:,}"),
        cell("사건성 기사", f"{s['screened']:,}"),
        cell("정리된 사건", f"{s['events']}"),
        cell("인명피해", head, tail),
    ]

    # 인명피해 칸은 글자가 길어 더 넓게 잡는다.
    usable = A4[0] - 2 * MARGIN_X
    tbl = Table([row], colWidths=[usable * r for r in (0.22, 0.24, 0.20, 0.34)])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEAFTER", (0, 0), (-2, -1), 0.4, colors.HexColor("#dedbd6")),
    ]))
    return tbl


def event_block(ev: dict, st: dict) -> KeepTogether:
    cat = ev.get("category", "사고")
    cat_color = CATEGORY_COLOR.get(cat, INK)

    rank = Paragraph(f'{ev["rank"]:02d}', st["rank"])

    title = Paragraph(
        f'<font color="{cat_color.hexval()}">[{cat}]</font> {ev["title"]}',
        st["event_title"],
    )

    facts = []
    for key, label in (
        ("occurred", "발생"),
        ("location", "장소"),
        ("casualties", "인명피해"),
        ("property", "재산피해"),
        ("status", "상태"),
    ):
        val = ev.get(key)
        if val:
            facts.append(f'<font name="{HEAD_FONT}" size="{pt(8.2)}">{label}</font>   {val}')

    # 사실 확인용 대표 기사 링크. PDF에서 눌러 바로 열 수 있다.
    src = ev.get("source")
    if src and src.get("url"):
        name = src.get("outlet") or "기사 원문"
        facts.append(
            f'<font name="{HEAD_FONT}" size="{pt(8.2)}">관련 기사</font>   '
            f'<link href="{src["url"]}" color="{LINK.hexval()}">{name}</link>'
        )

    meta = Paragraph("<br/>".join(facts), st["meta"])

    body = Paragraph(ev["summary"], st["body"])

    mention = ev.get("mentions")
    count = Paragraph(f"{mention}건", st["count"]) if mention else Paragraph("", st["count"])

    rank_w, count_w = 13 * mm, 17 * mm
    inner = Table(
        [[rank, [title, Spacer(1, 5), body, Spacer(1, 6), meta], count]],
        colWidths=[rank_w, (A4[0] - 2 * MARGIN_X) - rank_w - count_w, count_w],
    )
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return KeepTogether([inner, Spacer(1, 9)])


def build(data: dict, out_path: Path) -> None:
    st = styles()
    meta = {
        "date_label": data["date_label"],
        "source_note": data.get("source_note", ""),
    }

    doc = BaseDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOT,
        title=f"재난·사고 일일 브리핑 {data['date_label']}",
        author="자동 생성",
    )
    frame = Frame(
        MARGIN_X, MARGIN_BOT,
        A4[0] - 2 * MARGIN_X, A4[1] - MARGIN_TOP - MARGIN_BOT,
        id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(
        id="main", frames=[frame],
        onPage=lambda c, d: header_footer(c, d, meta),
    )])

    story = [
        Paragraph(safe("재난·사고 일일 브리핑"), st["title"]),
        Paragraph(data["date_label"] + safe(" 보도분 · ") + data["scope_note"], st["subtitle"]),
        Spacer(1, 11),
        stat_band(data, st),
        Spacer(1, 6),
    ]

    if data.get("headline"):
        story += [Spacer(1, 5), Paragraph(data["headline"], st["body"]), Spacer(1, 4)]

    story.append(Paragraph("보도량 순 사건 목록", st["section"]))
    story.append(Spacer(1, 2))

    for ev in data["events"]:
        story.append(event_block(ev, st))

    if data.get("minor_events"):
        story.append(Paragraph("그 밖에 확인된 사건", st["section"]))
        rows = []
        for m in data["minor_events"]:
            detail = m["detail"]
            s = m.get("source")
            if s and s.get("url"):
                detail += (f'  <link href="{s["url"]}" color="{LINK.hexval()}">'
                           f'[{s.get("outlet") or "기사"}]</link>')
            rows.append([
                Paragraph(f'<font name="{HEAD_FONT}" size="{pt(8.6)}">{m["title"]}</font>', st["body"]),
                Paragraph(detail, st["meta"]),
            ])
        tbl = Table(rows, colWidths=[62 * mm, (A4[0] - 2 * MARGIN_X) - 62 * mm])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
        ]))
        story.append(tbl)

    if data.get("notes"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("일러두기", st["section"]))
        for n in data["notes"]:
            story.append(Paragraph(safe(f"· {n}"), st["note"]))
            story.append(Spacer(1, 2))

    doc.build(story)


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("사용법: python make_pdf.py brief.json 출력.pdf")
    data = safe(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    out = Path(sys.argv[2])
    build(data, out)
    print(f"생성: {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
