from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


PRINTABLE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".doc",
    ".docx",
    ".rtf",
    ".txt",
}

WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    extension: str
    reason: str | None = None


def sanitize_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name)
    name = re.sub(r"\s+", "_", name).strip(" ._")
    if not name:
        name = "upload"

    stem = Path(name).stem.strip(" ._") or "upload"
    suffix = Path(name).suffix.lower()
    if stem.lower() in WINDOWS_RESERVED_NAMES:
        stem = f"{stem}_file"
    stem = stem[:96]
    return f"{stem}{suffix}" if suffix else stem


def validate_printable_file(
    filename: str,
    allowed_extensions: list[str],
    head: bytes,
) -> ValidationResult:
    safe_name = sanitize_filename(filename)
    extension = Path(safe_name).suffix.lower()
    allowed = set(allowed_extensions) & PRINTABLE_EXTENSIONS

    if not extension:
        return ValidationResult(False, extension, "文件缺少扩展名，无法判断是否可打印")
    if extension not in allowed:
        return ValidationResult(False, extension, f"不支持的文件类型：{extension}")
    if not head:
        return ValidationResult(False, extension, "文件为空")

    if extension == ".pdf":
        return _check(head.startswith(b"%PDF"), extension, "PDF 文件头无效")
    if extension in {".png"}:
        return _check(head.startswith(b"\x89PNG\r\n\x1a\n"), extension, "PNG 文件头无效")
    if extension in {".jpg", ".jpeg"}:
        return _check(head.startswith(b"\xff\xd8\xff"), extension, "JPEG 文件头无效")
    if extension == ".gif":
        return _check(head.startswith((b"GIF87a", b"GIF89a")), extension, "GIF 文件头无效")
    if extension == ".bmp":
        return _check(head.startswith(b"BM"), extension, "BMP 文件头无效")
    if extension in {".tif", ".tiff"}:
        return _check(head.startswith((b"II*\x00", b"MM\x00*")), extension, "TIFF 文件头无效")
    if extension == ".docx":
        return _check(head.startswith(b"PK\x03\x04"), extension, "DOCX 文件头无效")
    if extension == ".doc":
        return _check(head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), extension, "DOC 文件头无效")
    if extension == ".rtf":
        return _check(head.lstrip().startswith(b"{\\rtf"), extension, "RTF 文件头无效")
    if extension == ".txt":
        if b"\x00" in head:
            return ValidationResult(False, extension, "TXT 文件疑似二进制内容")
        return ValidationResult(True, extension)

    return ValidationResult(False, extension, "暂不支持该文件类型")


def _check(condition: bool, extension: str, reason: str) -> ValidationResult:
    if condition:
        return ValidationResult(True, extension)
    return ValidationResult(False, extension, reason)
