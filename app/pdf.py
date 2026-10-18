import io
import sys
from pathlib import Path

from .config import offline, settings
from .security import check_approval, enable_reviewed_imports
from .storage import timestamp


def make_pdf(snapshot, test=False):
    check_approval()
    offline()
    enable_reviewed_imports()  # Never execute .pth hooks or unreviewed extras.
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from xml.sax.saxutils import escape

    font = Path("C:/Windows/Fonts/arial.ttf")
    if not font.is_file():
        raise FileNotFoundError("La police locale Arial est absente.")
    if "LocalArial" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("LocalArial", str(font)))
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "LocalArial"
    styles["BodyText"].leading = 16
    styles["BodyText"].splitLongWords = 1
    styles.add(ParagraphStyle("Timecode", fontName="LocalArial", fontSize=8, leading=11, textColor=colors.HexColor("#647383")))
    styles["Timecode"].keepWithNext = True
    buffer = io.BytesIO()
    title = ("TEST — NON VALIDÉ PAR L’UTILISATEUR — " if test else "") + snapshot["title"]
    document = SimpleDocTemplate(buffer, title=title, author="LocalASR", leftMargin=48, rightMargin=48, topMargin=65, bottomMargin=55)
    blocks = [Paragraph(escape(title), styles["Title"]),
              Paragraph(escape(snapshot["source_name"]), styles["BodyText"]),
              Paragraph(escape("Export : " + snapshot["exported_at"] + " · Version " + str(snapshot["version"])), styles["BodyText"])]
    if snapshot.get("transcription_created_at"):
        blocks.append(Paragraph(escape("Transcription : " + snapshot["transcription_created_at"]), styles["BodyText"]))
    if snapshot.get("duration_seconds") is not None:
        blocks.append(Paragraph(escape("Durée : " + timestamp(snapshot["duration_seconds"])), styles["BodyText"]))
    if snapshot.get("participants"):
        blocks.append(Paragraph(escape(snapshot["participants"]), styles["BodyText"]))
    blocks.append(Spacer(1, 18))
    for segment in snapshot["segments"]:
        blocks.append(Paragraph(escape(timestamp(segment["start"]) + " — " + timestamp(segment["end"])), styles["Timecode"]))
        blocks.append(Paragraph(escape(segment["text"]).replace("\n", "<br/>"), styles["BodyText"]))
        blocks.append(Spacer(1, 9))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("LocalArial", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(48, 28, "TEST — NON VALIDÉ PAR L’UTILISATEUR" if test else "LocalASR · Transcription validée")
        canvas.drawRightString(doc.pagesize[0] - 48, 28, str(doc.page))
        canvas.restoreState()

    document.build(blocks, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
