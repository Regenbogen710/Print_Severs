from app.upload_validation import sanitize_filename, validate_printable_file


def test_accepts_pdf_header() -> None:
    result = validate_printable_file("report.pdf", [".pdf"], b"%PDF-1.7\n")

    assert result.is_valid
    assert result.extension == ".pdf"


def test_rejects_disallowed_extension() -> None:
    result = validate_printable_file("payload.exe", [".pdf"], b"MZ")

    assert not result.is_valid
    assert "不支持" in (result.reason or "")


def test_rejects_mismatched_pdf_header() -> None:
    result = validate_printable_file("report.pdf", [".pdf"], b"not a pdf")

    assert not result.is_valid


def test_sanitize_filename_removes_path_and_windows_reserved_chars() -> None:
    assert sanitize_filename(r"..\CON?.pdf") == "CON_file.pdf"
    assert sanitize_filename("  monthly report .pdf") == "monthly_report.pdf"
