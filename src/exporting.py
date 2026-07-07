"""CSV export helper (UTF-8 with BOM so Excel opens Chinese correctly)."""
import csv
import io


def to_csv_bytes(rows: list) -> bytes:
    """Serialize a list of dicts to CSV bytes. Columns come from the first row."""
    if not rows:
        return b""
    cols = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue().encode("utf-8-sig")
