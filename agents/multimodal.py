"""
agents/multimodal.py — PDF text extraction and vision-based transcription.

Text-layer PDFs: extracted via pypdf.
Images/scans: sent to the vision LLM deployment for transcription.
"""

import base64
from pathlib import Path
from typing import Optional

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a text-layer PDF using pypdf.

    Returns:
        Extracted text string (empty string if extraction fails or pypdf unavailable).
    """
    if not PYPDF_AVAILABLE:
        return ""

    try:
        reader = pypdf.PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except Exception as e:
        return ""


def transcribe_image_via_vision(
    image_b64: str,
    llm_client,
    system_prompt: str = (
        "Tu es un assistant OCR spécialisé dans les documents comptables tunisiens. "
        "Transcris exactement le contenu du document visible dans l'image, "
        "en préservant tous les chiffres, dates, noms et montants."
    ),
) -> str:
    """
    Transcribe an image document using the vision LLM deployment.

    Args:
        image_b64: base64-encoded image bytes
        llm_client: LLMClient instance
        system_prompt: OCR system prompt

    Returns:
        Transcribed text string.
    """
    return llm_client.call(
        role="vision",
        system_prompt=system_prompt,
        user_message="Transcris intégralement le contenu de ce document comptable.",
        image_b64=image_b64,
    )


def transcribe_document_via_vision(file_path: str, image_b64: str, llm_client) -> str:
    """Transcribe an image file or the first pages of a scanned PDF."""
    path = Path(file_path)
    if path.suffix.lower() != ".pdf":
        return transcribe_image_via_vision(image_b64, llm_client)

    try:
        from pdf2image import convert_from_path
        import io

        pages = convert_from_path(file_path, first_page=1, last_page=2, dpi=160)
        transcripts = []
        for page in pages:
            image = io.BytesIO()
            page.save(image, format="PNG")
            page_b64 = base64.b64encode(image.getvalue()).decode("ascii")
            transcripts.append(transcribe_image_via_vision(page_b64, llm_client))
        return "\n".join(transcripts)
    except Exception as exc:
        raise RuntimeError(f"Could not prepare scanned PDF for OCR: {exc}") from exc


def detect_modality(file_path: str) -> str:
    """
    Detect whether a file is a text-layer PDF or an image.

    Logic:
    - If file extension is .pdf and pypdf extracts > 50 chars → "text"
    - Otherwise → "photo"

    Returns:
        "text" or "photo"
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
        if len(text.strip()) > 50:
            return "text"

    return "photo"


def file_to_b64(file_path: str) -> str:
    """Read a file and return its base64-encoded content."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
