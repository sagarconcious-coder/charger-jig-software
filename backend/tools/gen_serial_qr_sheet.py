"""Pre-print QR + serial number sheet for a batch of chargers.

Generates the NEXT N serial numbers for a lot by computing them entirely
LOCALLY - no server round-trip at all. You supply the same 6 traceability
codes used on the Lot page (voltage/amp, variant, connector, EMS/ms_id,
month, year) plus the lot's own lot-code (from the Lot page's table /
"Create Lot" response), and the script builds the prefix itself using
core/charger_code_tables.py - a local mirror of the server's
bms/charger_code_tables.py, so validation and the prefix format exactly
match what the server would produce, without needing the server reachable.

This does NOT call POST /api/charger-serial - nothing is reserved/consumed
server-side. These are a PREVIEW/pre-print only: the real serial for a given
unit is still whatever the server actually hands out when that unit is
tested and "Generate Serial Number" is clicked on the Report page. Pass
--next-seq (the Lot page's "Next Serial No." column for this exact part
config) so the script can refuse to print anything that would collide with
a serial the server might already have issued or might issue before you use
these labels - it's on the operator to keep this number current (check the
Lot page right before generating) and to use the sheet promptly, since any
real testing on this same part-config between generating and using it can
still cause a collision the script has no way to detect on its own.

Usage:
    .venv\\Scripts\\python.exe backend\\tools\\gen_serial_qr_sheet.py \\
        --voltage-amp 5825 --variant B --connector A --ms-id G \\
        --month H --year B --lot-code 1 \\
        --next-seq 1 --start-seq 1 --count 100

Output: a single PDF at backend/tools/output/<prefix><lot_code>_<start>-<end>.pdf -
every serial laid out on a grid (QR code, serial text underneath, a thin
cut-line border around each cell), ready to print and cut.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# Make `backend` importable when run directly (python backend/tools/x.py),
# same pattern main.py's sibling scripts use.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from core import charger_code_tables

# QR encoding density (pixels, at this scale) - only affects the intermediate
# in-memory image; the PDF re-lays it out to physical mm regardless.
_QR_BOX_SIZE = 8
_QR_BORDER = 2

# PDF grid layout: 7 columns x 10 rows per A4 page (70 labels/page), page
# margin for a paper cutter, plus a GUTTER of blank space between every
# cell so bordered labels read as distinct tiles instead of one solid grid.
# Cell size is derived from the page/margin/gutter/grid below (not fixed),
# and the QR/font size within each cell scale off that - so changing
# _COLS/_ROWS/_GUTTER always fits instead of risking overflow/overlap.
_COLS = 7
_ROWS = 10
_MARGIN = 10 * mm
_GUTTER = 3 * mm
# Fraction of the cell's WIDTH the QR code occupies (cell height is derived
# separately - see build_pdf - to give the QR more room than a square cell
# would, since the row pitch has headroom the column pitch doesn't).
_QR_FRACTION_OF_CELL = 0.90


def build_serial(prefix: str, lot_code: int, seq: int) -> str:
    """Mirrors the server's own format exactly (see ChargerSerialNumberView /
    ChargerReportView._create_pass_report in aeidthocpp/bms/rest_view.py):
    prefix + lot_code:02d + seq:05d - both are MINIMUM widths, not truncating,
    so lot 100+/seq 100000+ still print in full rather than being cut off."""
    return f"{prefix}{lot_code:02d}{seq:05d}"


def make_qr_image(serial: str) -> Image.Image:
    """Bare QR code encoding the serial string - no text baked in. The PDF
    sheet draws its own (properly-sized, grid-aware) serial text and cell
    border separately (see build_pdf) - baking text into this image too
    would print each serial twice per label."""
    qr = qrcode.QRCode(box_size=_QR_BOX_SIZE, border=_QR_BORDER)
    qr.add_data(serial)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def build_pdf(labels: list[tuple[str, Image.Image]], out_path: Path) -> None:
    """Grid-lays every label onto A4 pages, _COLS x _ROWS per page. Cell size
    is computed from the page/margin/grid (not fixed), and the QR size plus
    the serial text's font size both scale off that computed cell - so a
    denser grid (more cols/rows) always shrinks to fit instead of overflowing
    into neighboring cells."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth

    page_w, page_h = A4
    c = pdf_canvas.Canvas(str(out_path), pagesize=A4)

    usable_w = page_w - 2 * _MARGIN
    usable_h = page_h - 2 * _MARGIN
    # The gutter is spent (_COLS-1)/(_ROWS-1) times across the grid (between
    # cells only, not around the outer edge - _MARGIN already handles that);
    # what's left tiles evenly into the actual bordered cell width.
    slot_w = usable_w / _COLS
    slot_h = usable_h / _ROWS
    cell_w = slot_w - _GUTTER * (_COLS - 1) / _COLS
    # Cell height uses nearly the full row slot (not the same gutter-derived
    # width formula) - the row pitch already has headroom the width doesn't,
    # so this is a taller/more-rectangular cell that fits a visibly bigger
    # QR + a tight text row, rather than being squeezed to match cell_w.
    cell_h = slot_h - _GUTTER * 0.5

    qr_size = cell_w * _QR_FRACTION_OF_CELL
    text_line_h = qr_size * 0.14  # just enough vertical room for the bold serial text
    text_y_offset = min((cell_h - qr_size) * 0.4, text_line_h * 1.8)

    # Shrink the font until the longest serial fits within the cell width
    # (with a little breathing room), instead of a fixed size that could
    # overflow into the next column on a dense grid / long serial. Bold is
    # measured here too (it's wider than regular at the same point size),
    # so the fit check matches what's actually drawn below.
    font_name = "Helvetica-Bold"
    longest = max((s for s, _ in labels), key=len, default="")
    font_size = 9.0
    while font_size > 4.0 and stringWidth(longest, font_name, font_size) > cell_w * 0.94:
        font_size -= 0.5

    per_page = _COLS * _ROWS
    for page_start in range(0, len(labels), per_page):
        page_labels = labels[page_start : page_start + per_page]
        for i, (serial, img) in enumerate(page_labels):
            col = i % _COLS
            row = i // _COLS
            # Slot origin tiles the full usable area; the cell itself is
            # inset by nothing extra - it's already smaller than the slot by
            # construction, so the leftover slot space IS the gutter.
            x = _MARGIN + col * slot_w
            # PDF origin is bottom-left; fill rows top-to-bottom.
            y = page_h - _MARGIN - (row + 1) * slot_h

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            qr_x = x + (cell_w - qr_size) / 2
            qr_y = y + cell_h - qr_size - text_y_offset
            c.drawImage(ImageReader(buf), qr_x, qr_y, width=qr_size, height=qr_size)
            c.setFont(font_name, font_size)
            # Baseline sits above the cell's bottom edge (not centered in the
            # QR-to-border gap) - nudges the text up, closer to the QR.
            c.drawCentredString(x + cell_w / 2, y + text_y_offset * 0.7, serial)

            # Cut-line border around just the cell (not the slot/gutter), so
            # each label reads as a distinct tile with visible white space
            # between it and its neighbors.
            c.setLineWidth(0.3)
            c.setStrokeColorRGB(0.55, 0.55, 0.55)
            c.rect(x, y, cell_w, cell_h, stroke=1, fill=0)
        c.showPage()

    c.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voltage-amp", required=True, choices=[c for c, _ in charger_code_tables.VOLTAGE_AMP_CHOICES])
    parser.add_argument("--variant", required=True, choices=[c for c, _ in charger_code_tables.VARIANT_CHOICES])
    parser.add_argument("--connector", required=True, choices=[c for c, _ in charger_code_tables.CONNECTOR_CHOICES])
    parser.add_argument("--ms-id", required=True, choices=[c for c, _ in charger_code_tables.MS_ID_CHOICES], help="EMS Identification code")
    parser.add_argument("--month", required=True, choices=charger_code_tables.MONTH_CODES, help="Month code (A=Jan..L=Dec) - use the lot's own month, not necessarily the current one")
    parser.add_argument("--year", required=True, help="Year code (A=2025, B=2026, ...) - use the lot's own year")
    parser.add_argument("--lot-code", type=int, required=True, help="The lot's own lot_code (e.g. from the Lot page's table / Create Lot response) - NOT the DB id")
    parser.add_argument("--start-seq", type=int, required=True, help="First running seq number to generate")
    parser.add_argument("--next-seq", type=int, default=None, help="The server's current 'Next Serial No.' for this exact part-config (Lot page column) - if given, --start-seq below it is refused to avoid colliding with real server-issued serials")
    parser.add_argument("--count", type=int, default=100, help="How many serials to generate (default 100)")
    args = parser.parse_args()

    error = charger_code_tables.validate_codes(
        args.voltage_amp, args.variant, args.connector, args.ms_id, args.month, args.year
    )
    if error:
        parser.error(error)

    if args.lot_code < 1:
        parser.error("--lot-code must be >= 1")
    if args.start_seq < 1:
        parser.error("--start-seq must be >= 1")
    if args.count < 1:
        parser.error("--count must be >= 1")
    if args.next_seq is not None and args.start_seq < args.next_seq:
        parser.error(
            f"--start-seq {args.start_seq} is BELOW --next-seq {args.next_seq} - these labels "
            f"would duplicate serials already issued for real units. Re-check the Lot page's "
            f"'Next Serial No.' column and re-run with --start-seq {args.next_seq} or higher."
        )

    prefix = charger_code_tables.build_prefix(
        args.voltage_amp, args.variant, args.connector, args.ms_id, args.month, args.year
    )
    lot_code = args.lot_code
    end_seq = args.start_seq + args.count - 1

    print(f"Lot {lot_code:02d} ({prefix}) - generating seq {args.start_seq:05d}..{end_seq:05d}"
          + (f" (server's next_seq was {args.next_seq})" if args.next_seq is not None else " (--next-seq not given, no collision check performed)"))

    serials = [build_serial(prefix, lot_code, seq) for seq in range(args.start_seq, end_seq + 1)]

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = [(serial, make_qr_image(serial)) for serial in serials]

    pdf_path = out_dir / f"{prefix}{lot_code:02d}_{args.start_seq:05d}-{end_seq:05d}.pdf"
    build_pdf(labels, pdf_path)

    print(f"Generated {len(serials)} serials: {serials[0]} .. {serials[-1]}")
    print(f"PDF sheet written to: {pdf_path}")


if __name__ == "__main__":
    main()
