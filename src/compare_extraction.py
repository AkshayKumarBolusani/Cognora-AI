from pathlib import Path
import pypdfium2 as pdfium

root = Path(".")
pdf_path = root / "data/pdfs/tcs-annual-report-fy2025-26.pdf"
output_dir = root / "data/processed"
image_dir = root / "data/figures"

output_dir.mkdir(parents=True, exist_ok=True)
image_dir.mkdir(parents=True, exist_ok=True)

pdf = pdfium.PdfDocument(str(pdf_path))

for page_number in (166, 167):
    page = pdf[page_number - 1]

    # 1. Extract the PDF's embedded text.
    text_page = page.get_textpage()
    text = text_page.get_text_range()
    text_page.close()

    text_path = output_dir / f"pdfium-page-{page_number}.txt"
    text_path.write_text(text, encoding="utf-8")

    # 2. Render the original page for visual verification.
    bitmap = page.render(scale=2)
    image_path = image_dir / f"tcs-page-{page_number}.png"
    bitmap.to_pil().save(image_path)

    print(f"\nPDF page {page_number}")
    print(f"Text characters: {len(text):,}")
    print(f"Text saved: {text_path}")
    print(f"Image saved: {image_path}")
    print("Text preview:")
    print(text[:500].replace("\r", "\n"))

    page.close()

pdf.close()

print("\nPASS: Both pages have text extracts and visual references.")
