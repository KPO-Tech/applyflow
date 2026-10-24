"""Génère playground/sample_cv.pdf (PDF minimal valide, contenu fictif)."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = PROJECT_ROOT / "playground" / "sample_cv.pdf"

CONTENT = """BT
/F1 20 Tf
72 760 Td
(Camille Martin) Tj
0 -30 Td
/F1 12 Tf
(Data Engineer / Data Analyst - 2 ans d'experience) Tj
0 -20 Td
(Python, SQL, Airflow, dbt, Snowflake, Power BI) Tj
0 -20 Td
(Profil fictif fourni avec ApplyFlow pour les demonstrations.) Tj
ET"""


def build_pdf() -> bytes:
    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    stream = CONTENT.encode("latin-1")
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(output)


if __name__ == "__main__":
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(build_pdf())
    print(f"écrit : {TARGET} ({TARGET.stat().st_size} octets)")
