"""Extract bounded text in memory; never execute or serve uploaded files."""

import io
import zipfile
from pathlib import PurePosixPath

from docx import Document
from pypdf import PdfReader

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_CHARS = 40_000
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx"}


class DocumentError(ValueError):
    pass


def label_excerpts(text, size=1400):
    """Give text/Word sources stable passage labels without inventing page numbers."""
    blocks = []
    remaining = text
    while remaining:
        end = min(len(remaining), size)
        if end < len(remaining):
            boundary = remaining.rfind("\n", 0, end)
            if boundary < end // 2:
                boundary = remaining.rfind(" ", 0, end)
            if boundary > end // 2:
                end = boundary
        blocks.append(remaining[:end].strip())
        remaining = remaining[end:].lstrip()
    return "\n\n".join(f"[Extrait {i}]\n{block}" for i, block in enumerate(blocks, 1))


def extract_document(upload):
    filename = PurePosixPath((upload.filename or "").replace("\\", "/")).name
    filename = "".join(c for c in filename if c.isprintable())[:180]
    extension = PurePosixPath(filename).suffix.lower()
    if not filename or extension not in ALLOWED_EXTENSIONS:
        raise DocumentError("Format non pris en charge. Choisissez un PDF, DOCX, TXT, MD ou CSV.")
    data = upload.stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError("Le fichier dépasse la limite de 5 Mo.")
    if not data:
        raise DocumentError("Ce fichier est vide.")
    try:
        if extension == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentError("Ce PDF est protégé. Envoyez une copie sans mot de passe.")
            if len(reader.pages) > 50:
                raise DocumentError("Le PDF dépasse 50 pages. Envoyez un extrait plus court.")
            parts = []
            length = 0
            readable = False
            for number, page in enumerate(reader.pages, 1):
                part = page.extract_text() or ""
                readable = readable or bool(part.strip())
                length += len(part)
                if length > MAX_DOCUMENT_CHARS:
                    raise DocumentError("Le document dépasse 40 000 caractères. Envoyez un extrait.")
                parts.append(f"[Page {number}]\n{part.strip()}" if part.strip() else f"[Page {number}]\n[Texte non extractible sur cette page]")
            if not readable:
                raise DocumentError("Aucun texte extractible. Pour un PDF scanné, utilisez d'abord un outil OCR.")
            text = "\n\n".join(parts)
        elif extension == ".docx":
            # A small ZIP can otherwise expand into an unbounded XML document.
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 20 * 1024 * 1024:
                    raise DocumentError("Ce document Word est trop volumineux une fois décompressé.")
            document = Document(io.BytesIO(data))
            parts = [p.text for p in document.paragraphs]
            parts.extend(" | ".join(c.text for c in row.cells)
                         for table in document.tables for row in table.rows)
            text = "\n".join(parts)
        else:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("cp1252")
            if "\x00" in text or any(ord(c) < 9 for c in text):
                raise DocumentError("Ce fichier ne contient pas du texte lisible.")
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError("Impossible de lire ce document. Vérifiez qu'il n'est pas endommagé.") from error
    text = text.strip()
    if not text:
        raise DocumentError("Aucun texte extractible. Pour un PDF scanné, utilisez d'abord un outil OCR.")
    if len(text) > MAX_DOCUMENT_CHARS:
        raise DocumentError("Le document dépasse 40 000 caractères. Envoyez un extrait plus court.")
    return filename, text if extension == ".pdf" else label_excerpts(text)
