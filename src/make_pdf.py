"""Xuất báo cáo Markdown của Research Radar thành PDF khổ A4.

Thể thức trình bày theo Nghị định 30/2020/NĐ-CP (Phụ lục I) về văn bản hành chính:
khổ A4, lề trên 20 mm, lề dưới 20 mm, lề trái 30 mm, lề phải 15 mm; phông chữ họ Times
(Times New Roman / Liberation Serif, có đủ dấu tiếng Việt); cỡ chữ nội dung 13 pt;
số trang ở chân trang.

Dùng: python src/make_pdf.py reports/latest.md reports/latest.pdf
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import markdown

CSS = """
@page { size: A4; margin: 20mm 15mm 20mm 30mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Times New Roman", "Liberation Serif", "Tinos", "Noto Serif", serif;
       font-size: 13pt; line-height: 1.4; color: #0b0b0b; text-align: justify; }
.masthead { border-top: 4px solid #2a78d6; border-bottom: 1px solid #c9c8c2; padding: 8pt 0 6pt;
            margin-bottom: 12pt; text-align: left; }
.masthead .kicker { font-size: 10pt; letter-spacing: .12em; text-transform: uppercase; color: #52514e; }
.masthead h1 { font-size: 22pt; margin: 2pt 0 4pt; border: 0; }
.masthead .meta { font-size: 11pt; color: #52514e; }
h1 { font-size: 20pt; margin: 0 0 6pt; }
h2 { font-size: 16pt; color: #0b0b0b; margin: 16pt 0 6pt; padding-bottom: 3pt;
     border-bottom: 1.5px solid #2a78d6; page-break-after: avoid; text-align: left; }
h2.topic { page-break-before: always; }
h3 { font-size: 14pt; margin: 12pt 0 4pt; page-break-after: avoid; text-align: left; }
h4 { font-size: 13pt; margin: 10pt 0 3pt; page-break-after: avoid; text-align: left; }
p, li { orphans: 3; widows: 3; }
ul, ol { margin: 3pt 0 6pt 16pt; padding: 0; }
li { margin: 1.5pt 0; }
blockquote { margin: 6pt 0; padding: 4pt 10pt; border-left: 3px solid #c9c8c2; color: #52514e; }
.summary { background: #f3f7fd; border: 1px solid #cfe0f6; border-left: 5px solid #2a78d6;
           padding: 6pt 12pt; margin: 8pt 0 10pt; page-break-inside: avoid; }
.summary h2 { border: 0; margin-top: 4pt; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 8pt; font-size: 11pt;
        page-break-inside: auto; text-align: left; }
tr { page-break-inside: avoid; }
th { background: #eef0f3; font-weight: bold; border-bottom: 1.5px solid #8f8e89; }
th, td { padding: 3pt 5pt; border-bottom: 0.5px solid #d6d5d0; vertical-align: top; }
img { width: 100%; height: auto; margin: 4pt 0; page-break-inside: avoid; }
code { font-family: "Liberation Mono", "DejaVu Sans Mono", monospace; font-size: 9.5pt; }
sub { font-size: 9.5pt; color: #52514e; vertical-align: baseline; }
p.src { font-size: 11pt; margin: 8pt 0 2pt; page-break-after: avoid; text-align: left; }
p.src + ul li { font-size: 10pt; line-height: 1.3; text-align: left; }
a { color: #1f5fae; text-decoration: none; word-break: break-word; }
hr { border: 0; border-top: 1px solid #c9c8c2; margin: 10pt 0; }
.backtop { display: none; }
"""

FOOTER = ('<div style="width:100%;font-family:\'Liberation Serif\',serif;font-size:9pt;color:#52514e;'
          'padding:0 15mm 0 30mm;display:flex;justify-content:space-between;">'
          '<span>{title}</span><span>Trang <span class="pageNumber"></span>/<span class="totalPages"></span></span></div>')


def md_to_html(md_path: Path) -> tuple[str, str]:
    text = md_path.read_text(encoding="utf-8")
    base = md_path.parent

    # Ảnh → nhúng base64 để PDF tự chứa
    def _img(m):
        alt, src = m.group(1), m.group(2)
        p = (base / src).resolve()
        if p.exists():
            data = base64.b64encode(p.read_bytes()).decode()
            return f'![{alt}](data:image/png;base64,{data})'
        return m.group(0)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+\.png)\)", _img, text)
    text = text.replace("[↑ Về đầu trang](#top)", "")
    # <details> → tiêu đề đậm + danh sách thường (PDF luôn mở đầy đủ)
    text = re.sub(r"<details><summary>(.*?)</summary>", lambda m: "\n<p class=\"src\">" + m.group(1) + "</p>\n",
                  text, flags=re.S)
    text = text.replace("</details>", "")
    # Markdown cần dòng trống trước danh sách; Gemini đôi khi bỏ qua
    lines, out = text.split("\n"), []
    for ln in lines:
        is_item = bool(re.match(r"^\s*([-*]|\d+\.)\s", ln))
        if is_item and out and out[-1].strip() and not re.match(r"^\s*([-*]|\d+\.)\s", out[-1]):
            out.append("")
        out.append(ln)
    text = "\n".join(out)
    text = re.sub(r"^\*\*Bản PDF khổ A4:\*\*[^\n]*\n", "", text, flags=re.M)

    title_m = re.search(r"^# (.+)$", text, re.M)
    title = title_m.group(1).strip() if title_m else "Research Radar"
    meta_m = re.search(r"^> (\*\*Ngày chạy:\*\*.+)$", text, re.M)
    meta = markdown.markdown(meta_m.group(1)) if meta_m else ""
    if title_m:
        text = text.replace(title_m.group(0), "", 1)
    if meta_m:
        text = text.replace(meta_m.group(0), "", 1)

    body = markdown.markdown(text, extensions=["tables", "sane_lists", "md_in_html"])
    body = re.sub(r"<hr\s*/?>\s*(?=(<p>)?<a id=\"[^\"]+\"></a>(</p>)?\s*<h2)", "", body)  # tránh trang trắng
    # Mỗi chủ đề sang trang mới; tóm tắt điều hành đóng khung
    body = re.sub(r"<h2>(\d+\. )", r'<h2 class="topic">\1', body)
    # Gộp neo <a id> vào tiêu đề để không sinh dòng trống (gây trang trắng trước ngắt trang)
    body = re.sub(r'(?:<p>)?<a id="([^"]+)"></a>(?:</p>)?\s*<h2 class="topic">', r'<h2 class="topic" id="\1">', body)
    body = re.sub(r'(?:<p>)?<a id="top"></a>(?:</p>)?', "", body)
    body = re.sub(r"(<h2>Tóm tắt điều hành</h2>)(.*?)(?=<h2>)", r'<div class="summary">\1\2</div>', body,
                  count=1, flags=re.S)
    head = (f'<div class="masthead"><div class="kicker">Bản tin xu hướng &amp; nghiên cứu</div>'
            f'<h1>{title}</h1><div class="meta">{meta}</div></div>')
    html = (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>{title}</title>'
            f'<style>{CSS}</style></head><body>{head}{body}</body></html>')
    return html, title


def render(md_path: Path, pdf_path: Path) -> Path:
    from playwright.sync_api import sync_playwright

    html, title = md_to_html(md_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True,
                 display_header_footer=True, header_template="<span></span>",
                 footer_template=FOOTER.format(title=title))
        browser.close()
    print(f"✓ Đã xuất {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/latest.md")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else src.with_suffix(".pdf"))
    render(src, dst)
