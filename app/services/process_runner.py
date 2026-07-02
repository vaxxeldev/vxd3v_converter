from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.services.errors import ProcessExecutionError

logger = logging.getLogger(__name__)
_RENDER_PATH_RE = re.compile(r"render-\d+-[A-Za-z0-9_-]+")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_stderr(stderr: bytes, limit: int = 4000) -> str:
    decoded = stderr.decode("utf-8", errors="replace")[-limit:]
    decoded = _RENDER_PATH_RE.sub("render-[redacted]", decoded)
    return _CONTROL_CHAR_RE.sub("?", decoded)


@dataclass(slots=True, frozen=True)
class ProcessResult:
    stdout: bytes
    stderr: bytes


class ProcessRunner:
    async def run(
        self,
        arguments: list[str],
        *,
        timeout_seconds: int,
        cwd: Path | None = None,
    ) -> ProcessResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise ProcessExecutionError("Не удалось запустить медиаконвертер.") from error
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError as error:
            process.kill()
            _, stderr = await process.communicate()
            logger.error(
                "process timed out executable=%s stderr=%s",
                Path(arguments[0]).name,
                sanitize_stderr(stderr),
            )
            raise ProcessExecutionError("Превышено время обработки медиа.") from error
        if process.returncode != 0:
            logger.error(
                "process failed executable=%s return_code=%s stderr=%s",
                Path(arguments[0]).name,
                process.returncode,
                sanitize_stderr(stderr),
            )
            raise ProcessExecutionError("Медиаконвертер не смог обработать этот файл.")
        return ProcessResult(stdout=stdout, stderr=stderr)
