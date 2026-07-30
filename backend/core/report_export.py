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


def export_pdf(run: TestRun, parameters: list[TestParameter], path: str | Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    elements = [
        Paragraph("Charger Testing JIG — Test Report", styles["Title"]),
        Paragraph(f"Run ID: {run.run_id}", styles["Normal"]),
        Paragraph(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(run.start_time))}", styles["Normal"]),
    ]
    if run.end_time:
        elements.append(Paragraph(f"End: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(run.end_time))}", styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))

    header = ["Parameter", "Unit", "Expected", "Tolerance", "Measured", "Deviation %", "Status"]
    rows = [header]
    for p in parameters:
        rows.append([
            p.name, p.unit, f"{p.expected_value:.3f}", f"±{p.tolerance:.3f}",
            f"{p.measured_value:.3f}" if p.measured_value is not None else "--",
            f"{p.deviation_pct:+.2f}%" if p.deviation_pct is not None else "--",
            p.status.value,
        ])

    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#101A2E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)
    doc.build(elements)
