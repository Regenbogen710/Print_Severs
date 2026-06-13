from pathlib import Path

from app.printer import _friendly_shell_error, _resolve_executable


def test_pdf_shell_association_error_is_actionable() -> None:
    detail = _friendly_shell_error(
        "Start-Process : This command cannot be run due to the error: "
        "No application is associated with the specified file for this operation.",
        ".pdf",
    )

    assert "SumatraPDF" in detail
    assert "sumatra_pdf_path" in detail


def test_resolve_executable_ignores_missing_candidates(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exe"

    assert _resolve_executable(None, [None, missing], []) is None
