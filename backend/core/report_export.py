from __future__ import annotations

import csv
import time
from pathlib import Path

from .models import TestParameter, TestRun


def export_csv(run: TestRun, parameters: list[TestParameter], path: str | Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Run ID", run.run_id])
        writer.writerow(["Start", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.start_time))])
        if run.end_time:
            writer.writerow(["End", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.end_time))])
        writer.writerow(["Charger Part Number", run.charger_part_number or ""])
        for key, value in (run.qr_values or {}).items():
            writer.writerow([key, value])
        writer.writerow([])
        writer.writerow(["Parameter", "Unit", "Expected", "Tolerance", "Measured", "Deviation", "Deviation %", "Status"])
        for p in parameters:
            writer.writerow([
                p.name, p.unit, p.expected_value, p.tolerance,
                p.measured_value if p.measured_value is not None else "",
                p.deviation_value if p.deviation_value is not None else "",
                f"{p.deviation_pct:.2f}" if p.deviation_pct is not None else "",
                p.status.value,
            ])


_NAVY = "#101A2E"
_BLUE = "#3987E5"
_MUTED = "#5B6B85"
_LINE = "#C7CEDB"
_PASS_BG = "#E4F7E9"
_PASS_TX = "#0CA30C"
_FAIL_BG = "#FBE7E7"
_FAIL_TX = "#D03B3B"
_PEND_BG = "#F0F1F4"
_PEND_TX = "#5B6B85"

_BLANK = ""


def export_pdf(run: TestRun, parameters: list[TestParameter], path: str | Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=15, leading=18,
        textColor=colors.HexColor(_NAVY), spaceAfter=0,
    )
    sub_style = ParagraphStyle(
        "ReportSub", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor(_MUTED), alignment=TA_RIGHT,
    )
    section_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=9.5, leading=11,
        textColor=colors.white, spaceAfter=0, spaceBefore=0,
    )
    result_style = ParagraphStyle(
        "ResultBadge", parent=styles["Title"], fontSize=15, alignment=TA_CENTER,
        leading=17,
        textColor=colors.HexColor(_PASS_TX if run.overall_pass else _FAIL_TX if run.overall_pass is False else _MUTED),
    )

    def section_bar(text: str, width: float = 170):
        t = Table([[Paragraph(text, section_style)]], colWidths=[width * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(_NAVY)),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    def info_table(rows: list[tuple[str, str]], label_w: float = 44, value_w: float = 39):
        label_style = ParagraphStyle("InfoLabel", parent=styles["Normal"], fontSize=7.8, leading=13, textColor=colors.HexColor(_MUTED))
        value_style = ParagraphStyle("InfoValue", parent=styles["Normal"], fontSize=8.4, leading=13, textColor=colors.HexColor(_NAVY))
        data = [[Paragraph(f"<b>{label}</b>", label_style), Paragraph(str(value), value_style)] for label, value in rows]
        t = Table(data, colWidths=[label_w * mm, value_w * mm], rowHeights=6.5 * mm)
        style_cmds = [
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(_LINE)),
        ]
        for i, (_, value) in enumerate(rows):
            if value == "":
                style_cmds.append(("LINEBELOW", (1, i), (1, i), 0.6, colors.HexColor(_MUTED)))
        t.setStyle(TableStyle(style_cmds))
        return t

    start_str = time.strftime("%Y-%m-%d", time.localtime(run.start_time))
    time_str = time.strftime("%H:%M:%S", time.localtime(run.start_time))

    qr_values = run.qr_values or {}
    dut_info_rows = [("Charger Part Number", run.charger_part_number or _BLANK)]
    if qr_values:
        dut_info_rows.extend((label, value or _BLANK) for label, value in qr_values.items())
    else:
        dut_info_rows.append(("QR Code", _BLANK))

    # Sections 1 & 2 side by side to save vertical space.
    side_by_side = Table(
        [[
            [section_bar("1. DUT / Charger Information", width=83),
             info_table(dut_info_rows, label_w=44, value_w=39)],
            [section_bar("2. JIG Information", width=83),
             info_table([
                 ("Jig Hardware Version", run.jig_hardware_version or "--"),
                 ("Jig Firmware Version", run.jig_firmware_version or "--"),
                 ("Tested By", "Automated Jig"),
                 ("Report No.", run.run_id),
             ], label_w=44, value_w=39)],
        ]],
        colWidths=[83 * mm, 83 * mm], hAlign="LEFT",
    )
    side_by_side.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    elements = [
        Table(
            [[Paragraph("DC Charger Test Report", title_style),
              Paragraph(f"Charger Testing JIG<br/>Run ID: {run.run_id}  |  {start_str} {time_str}", sub_style)]],
            colWidths=[100 * mm, 66 * mm],
        ),
        Spacer(1, 2 * mm),
        HRFlowable(width="100%", thickness=1.1, color=colors.HexColor(_BLUE)),
        Spacer(1, 3 * mm),

        side_by_side,
        Spacer(1, 3 * mm),

        section_bar("3. Test Conditions"),
        info_table([
            ("Input Supply", _BLANK),
            ("Ambient Temperature", _BLANK),
            ("Test Setup / Fixture", "Charger Test JIG"),
            ("Reference Instruments", "NA"),
        ], label_w=44, value_w=122),
        Spacer(1, 3 * mm),

        section_bar("4. Test Parameters"),
        Spacer(1, 1.5 * mm),
    ]

    header = ["#", "Parameter", "Unit", "Expected", "Tolerance", "Measured", "Dev %", "Status"]
    rows = [header]
    status_rows: list[tuple[int, str]] = []
    for idx, p in enumerate(parameters, start=1):
        rows.append([
            str(idx), p.name, p.unit, f"{p.expected_value:.3f}", f"±{p.tolerance:.3f}",
            f"{p.measured_value:.3f}" if p.measured_value is not None else "--",
            f"{p.deviation_pct:+.2f}%" if p.deviation_pct is not None else "--",
            p.status.value,
        ])
        status_rows.append((idx, p.status.value))

    table = Table(rows, repeatRows=1, colWidths=[9 * mm, 42 * mm, 14 * mm, 24 * mm, 22 * mm, 24 * mm, 20 * mm, 20 * mm])
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(_LINE)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FB")]),
    ]
    for row_idx, status in status_rows:
        bg = _PASS_BG if status == "PASS" else _FAIL_BG if status == "FAIL" else _PEND_BG
        fg = _PASS_TX if status == "PASS" else _FAIL_TX if status == "FAIL" else _PEND_TX
        style_cmds.append(("BACKGROUND", (-1, row_idx), (-1, row_idx), colors.HexColor(bg)))
        style_cmds.append(("TEXTCOLOR", (-1, row_idx), (-1, row_idx), colors.HexColor(fg)))
        style_cmds.append(("FONTNAME", (-1, row_idx), (-1, row_idx), "Helvetica-Bold"))
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)
    elements.append(Spacer(1, 4 * mm))

    elements.append(section_bar("5. Final Result"))
    elements.append(Spacer(1, 4 * mm))

    result_text = "PASS" if run.overall_pass else "FAIL" if run.overall_pass is False else "PENDING"
    badge_bg = _PASS_BG if run.overall_pass else _FAIL_BG if run.overall_pass is False else _PEND_BG
    badge = Table([[Paragraph(f"Overall Status: {result_text}", result_style)]], colWidths=[170 * mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(badge_bg)),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(_LINE)),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(badge)
    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor(_LINE)))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "Generated by Charger Testing JIG — CAN Monitor &amp; Test System",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor(_MUTED), alignment=TA_CENTER),
    ))

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        topMargin=12 * mm, bottomMargin=12 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
    )
    doc.build(elements)
