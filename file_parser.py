from pathlib import Path


def extract_text(path: str | Path, file_type: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT files."""
    path = Path(path)
    ft = file_type.lower().strip(".")

    if ft == "pdf":
        return _extract_pdf(path)
    elif ft == "docx":
        return _extract_docx(path)
    elif ft == "txt":
        return _extract_txt(path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def _extract_pdf(path: Path) -> str:
    try:
        import pdfplumber

        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {e}") from e


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document

        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        raise ValueError(f"Failed to parse DOCX: {e}") from e


def _extract_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise ValueError(f"Failed to read TXT: {e}") from e
