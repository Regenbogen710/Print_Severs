from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from app.config import Settings
from app.schemas import PrinterStatusOut


PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".rtf", ".txt"}


@dataclass(frozen=True)
class PrintResult:
    success: bool
    detail: str


class WindowsPrinter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> PrinterStatusOut:
        if self.settings.dry_run:
            return PrinterStatusOut(
                ready=True,
                name=self.settings.printer_name,
                message="dry-run 模式：跳过真实打印机状态检查",
                raw_status={"dry_run": True},
            )
        if platform.system().lower() != "windows":
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message="当前系统不是 Windows，无法检查 Windows 打印机状态",
            )

        script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$name = $env:PRINT_SERVER_TARGET_PRINTER
$printer = $null
try {
    $printer = Get-Printer -Name $name -ErrorAction Stop
} catch {
    $printer = $null
}
$wmi = Get-CimInstance Win32_Printer | Where-Object { $_.Name -eq $name } | Select-Object -First 1
if (-not $printer -and -not $wmi) {
    throw "Printer not found: $name"
}
$result = [ordered]@{
    Name = $name
    PrinterStatus = if ($printer) { [string]$printer.PrinterStatus } else { $null }
    WorkOffline = if ($printer) { [bool]$printer.WorkOffline } else { $false }
    DetectedErrorState = if ($printer) { [string]$printer.DetectedErrorState } else { $null }
    JobCount = if ($printer) { [int]$printer.JobCount } else { $null }
    WmiPrinterStatus = if ($wmi) { [int]$wmi.PrinterStatus } else { $null }
    WmiPrinterState = if ($wmi) { [int]$wmi.PrinterState } else { $null }
}
$result | ConvertTo-Json -Compress
"""
        completed = self._run_powershell(script, timeout=20)
        if completed.returncode != 0:
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message=_clean_output(completed.stderr or completed.stdout) or "打印机状态检查失败",
            )

        try:
            raw = json.loads(completed.stdout.strip())
        except json.JSONDecodeError:
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message=f"打印机状态输出无法解析：{_clean_output(completed.stdout)}",
            )
        return self._interpret_status(raw)

    def print_file(self, file_path: Path) -> PrintResult:
        if self.settings.dry_run:
            return PrintResult(True, f"dry-run 模式：已模拟提交 {file_path.name}")

        extension = file_path.suffix.lower()
        if extension in PDF_EXTENSIONS:
            return self._print_with_sumatra(file_path)
        if extension in IMAGE_EXTENSIONS:
            return self._print_with_mspaint(file_path)
        if extension in OFFICE_EXTENSIONS:
            return self._print_with_libreoffice(file_path)
        return self._print_with_windows_shell(file_path)

    def _interpret_status(self, raw: dict[str, object]) -> PrinterStatusOut:
        status_text = str(raw.get("PrinterStatus") or "").strip()
        detected_error = str(raw.get("DetectedErrorState") or "").strip()
        work_offline = bool(raw.get("WorkOffline"))
        wmi_status = raw.get("WmiPrinterStatus")

        error_statuses = {
            "Error",
            "Offline",
            "PaperOut",
            "PaperJam",
            "DoorOpen",
            "NoToner",
            "NotAvailable",
            "Unknown",
            "OutputBinFull",
            "Paused",
        }
        ok_error_states = {"", "0", "None", "NoError"}

        if work_offline:
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message="打印机处于脱机状态",
                raw_status=raw,
            )
        if status_text in error_statuses:
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message=f"打印机状态异常：{status_text}",
                raw_status=raw,
            )
        if detected_error not in ok_error_states:
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message=f"打印机错误状态：{detected_error}",
                raw_status=raw,
            )
        if isinstance(wmi_status, int) and wmi_status in {2, 7, 8, 9}:
            return PrinterStatusOut(
                ready=False,
                name=self.settings.printer_name,
                message=f"WMI 打印机状态异常：{wmi_status}",
                raw_status=raw,
            )

        return PrinterStatusOut(
            ready=True,
            name=self.settings.printer_name,
            message=status_text or "打印机可用",
            raw_status=raw,
        )

    def _print_with_sumatra(self, file_path: Path) -> PrintResult:
        executable = self._resolve_sumatra_path()
        if executable is None:
            if self.settings.sumatra_pdf_path:
                return PrintResult(False, f"配置的 SumatraPDF 路径不存在：{self.settings.sumatra_pdf_path}")
            return PrintResult(
                False,
                "PDF 打印需要 SumatraPDF。请安装 SumatraPDF，或在 config.ini 的 [printer] 中设置 "
                "sumatra_pdf_path = C:\\Program Files\\SumatraPDF\\SumatraPDF.exe",
            )
        args = [
            str(executable),
            "-print-to",
            self.settings.printer_name,
            "-silent",
            "-exit-when-done",
            str(file_path),
        ]
        return self._run_print_command(args, "SumatraPDF")

    def _print_with_mspaint(self, file_path: Path) -> PrintResult:
        executable = self._resolve_mspaint_path()
        if executable is None:
            return self._print_with_windows_shell(file_path)
        args = [
            str(executable),
            "/pt",
            str(file_path),
            self.settings.printer_name,
        ]
        result = self._run_print_command(args, "Windows 画图")
        if result.success:
            return result
        return self._print_with_windows_shell(file_path)

    def _print_with_libreoffice(self, file_path: Path) -> PrintResult:
        executable = self._resolve_libreoffice_path()
        if executable is None:
            if self.settings.libreoffice_path:
                return PrintResult(False, f"配置的 LibreOffice 路径不存在：{self.settings.libreoffice_path}")
            return PrintResult(
                False,
                "Office/文本文件打印需要 LibreOffice。请安装 LibreOffice，或在 config.ini 的 [printer] 中设置 "
                "libreoffice_path = C:\\Program Files\\LibreOffice\\program\\soffice.exe",
            )
        args = [
            str(executable),
            "--headless",
            "--pt",
            self.settings.printer_name,
            str(file_path),
        ]
        return self._run_print_command(args, "LibreOffice")

    def _print_with_windows_shell(self, file_path: Path) -> PrintResult:
        script = r"""
$ErrorActionPreference = 'Stop'
$file = $env:PRINT_SERVER_PRINT_FILE
$printer = $env:PRINT_SERVER_TARGET_PRINTER
try {
    $process = Start-Process -FilePath $file -Verb PrintTo -ArgumentList "`"$printer`"" -PassThru -ErrorAction Stop
    if ($process) {
        Wait-Process -Id $process.Id -Timeout 30 -ErrorAction SilentlyContinue
    }
    Write-Output "submitted with PrintTo"
} catch {
    $process = Start-Process -FilePath $file -Verb Print -PassThru -ErrorAction Stop
    if ($process) {
        Wait-Process -Id $process.Id -Timeout 30 -ErrorAction SilentlyContinue
    }
    Write-Output "submitted with Print fallback"
}
"""
        completed = self._run_powershell(
            script,
            timeout=self.settings.print_command_timeout_seconds,
            extra_env={"PRINT_SERVER_PRINT_FILE": str(file_path)},
        )
        if completed.returncode != 0:
            detail = _friendly_shell_error(completed.stderr or completed.stdout, file_path.suffix.lower())
            return PrintResult(False, detail or "Windows Shell 打印命令失败")
        detail = _clean_output(completed.stdout) or "已提交到 Windows 打印系统"
        return PrintResult(True, detail)

    def _resolve_sumatra_path(self) -> Path | None:
        return _resolve_executable(
            self.settings.sumatra_pdf_path,
            [
                _env_path("ProgramFiles", "SumatraPDF", "SumatraPDF.exe"),
                _env_path("ProgramFiles(x86)", "SumatraPDF", "SumatraPDF.exe"),
                _env_path("LOCALAPPDATA", "SumatraPDF", "SumatraPDF.exe"),
                Path("tools") / "SumatraPDF.exe",
            ],
            ["SumatraPDF.exe", "sumatrapdf.exe"],
        )

    def _resolve_libreoffice_path(self) -> Path | None:
        return _resolve_executable(
            self.settings.libreoffice_path,
            [
                _env_path("ProgramFiles", "LibreOffice", "program", "soffice.exe"),
                _env_path("ProgramFiles(x86)", "LibreOffice", "program", "soffice.exe"),
            ],
            ["soffice.exe"],
        )

    def _resolve_mspaint_path(self) -> Path | None:
        return _resolve_executable(
            None,
            [
                _env_path("SystemRoot", "System32", "mspaint.exe"),
                _env_path("SystemRoot", "SysWOW64", "mspaint.exe"),
            ],
            ["mspaint.exe"],
        )

    def _run_print_command(self, args: list[str], label: str) -> PrintResult:
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.settings.print_command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return PrintResult(False, f"{label} 打印命令超时")
        except OSError as exc:
            return PrintResult(False, f"{label} 打印命令无法启动：{exc}")

        if completed.returncode != 0:
            detail = _clean_output(completed.stderr or completed.stdout)
            return PrintResult(False, f"{label} 打印命令失败：{detail}")
        detail = _clean_output(completed.stdout) or f"{label} 已提交打印任务"
        return PrintResult(True, detail)

    def _run_powershell(
        self,
        script: str,
        *,
        timeout: int,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PRINT_SERVER_TARGET_PRINTER"] = self.settings.printer_name
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )


def _clean_output(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(line.strip() for line in value.splitlines() if line.strip())


def _env_path(name: str, *parts: str) -> Path | None:
    base = os.environ.get(name, "")
    return Path(base, *parts) if base else None


def _resolve_executable(
    configured_path: str | None,
    candidates: list[Path | None],
    names: list[str],
) -> Path | None:
    if configured_path:
        configured = Path(os.path.expandvars(configured_path)).expanduser()
        return configured if configured.is_file() else None

    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate

    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)

    return None


def _friendly_shell_error(value: str | None, extension: str) -> str:
    cleaned = _clean_output(value)
    if "No application is associated" not in cleaned:
        return cleaned

    if extension in PDF_EXTENSIONS:
        return (
            "Windows 没有关联可打印的 PDF 程序。请安装 SumatraPDF，或在 config.ini 的 [printer] 中设置 "
            "sumatra_pdf_path = C:\\Program Files\\SumatraPDF\\SumatraPDF.exe"
        )
    if extension in OFFICE_EXTENSIONS:
        return (
            "Windows 没有关联可打印的 Office/文本程序。请安装 LibreOffice，或在 config.ini 的 [printer] 中设置 "
            "libreoffice_path = C:\\Program Files\\LibreOffice\\program\\soffice.exe"
        )
    return f"Windows 没有关联可打印的 {extension or '该'} 文件程序，请安装支持打印该格式的默认应用。"
