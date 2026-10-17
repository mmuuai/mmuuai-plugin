"""Save an already received MMUU result from JSON stdin; never fetch a task."""
import argparse
import base64
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
from shutil import which
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_to_bytes, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid
from datetime import datetime, timezone
from platform_download_name import output_entries, result_download_name

TASK_ID = re.compile(r"^tsk_[A-Za-z0-9_-]{16,80}$")
MIME = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$", re.I)


class SaveFailure(Exception):
    def __init__(self, code, http_status=None):
        super().__init__(code)
        self.code, self.http_status = code, http_status


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        raise SaveFailure("MMUU_SAVE_ARGUMENTS_INVALID")


def windows_downloads():
    pointer = ctypes.c_wchar_p()
    folder = (ctypes.c_ubyte * 16).from_buffer_copy(
        uuid.UUID("374de290-123f-4565-9164-39c4925e467b").bytes_le)
    shell = ctypes.windll.shell32.SHGetKnownFolderPath
    shell.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_wchar_p)]
    shell.restype = ctypes.c_long
    try:
        if shell(ctypes.byref(folder), 0, None, ctypes.byref(pointer)) == 0 and pointer.value:
            return Path(pointer.value)
    finally:
        if pointer:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))
    return None


def downloads_directory(*, platform=None, home=None, environ=None, known_folder=None):
    platform, home = platform or sys.platform, Path(home or Path.home())
    environ = os.environ if environ is None else environ
    if platform == "win32":
        try:
            folder = (known_folder or windows_downloads)()
            if folder:
                return Path(folder)
        except (OSError, AttributeError):
            pass
    elif platform.startswith("linux"):
        value = environ.get("XDG_DOWNLOAD_DIR")
        if value is None:
            config = Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
            try:
                for line in config.read_text(encoding="utf-8").splitlines():
                    match = re.fullmatch(r'\s*XDG_DOWNLOAD_DIR\s*=\s*"(.*)"\s*', line)
                    if match:
                        value = match[1]
                        break
            except OSError:
                pass
        if value:
            value = value.strip('"').replace("${HOME}", str(home)).replace("$HOME", str(home))
            value = value.replace(r'\"', '"').replace("\\\\", "\\")
            if "$" not in value and Path(value).is_absolute():
                return Path(value)
    return home / "Downloads"


def mime_type(value):
    value = value.split(";", 1)[0].strip().lower() if isinstance(value, str) else ""
    return value if MIME.fullmatch(value) else None


def remote_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or re.search(r"[\x00-\x20]", value)):
            raise ValueError
        parsed.port
    except (TypeError, ValueError):
        raise SaveFailure("MMUU_SAVE_URL_INVALID") from None
    return value


class ResultRedirect(HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, newurl):
        return Request(remote_url(newurl), method="GET",
                       headers={"User-Agent": "MMUU-AI-result-saver"})


def data_source(value):
    try:
        header, encoded = value.split(",", 1)
        options = header[5:].split(";")
        mime = mime_type(options[0]) or "text/plain"
        raw = unquote_to_bytes(encoded)
        if "base64" in options[1:]:
            raw = base64.b64decode(raw, validate=True)
        return io.BytesIO(raw), mime
    except (ValueError, TypeError):
        raise SaveFailure("MMUU_SAVE_DATA_URL_INVALID") from None


def write_stream(directory, name_for_mime, mime, source, expected_bytes=None):
    name = name_for_mime(mime)
    suffix = re.search(r"\.[a-z0-9]{1,8}$", name, re.I | re.ASCII)
    stem, extension = (name[:suffix.start()], suffix[0]) if suffix else (name, "")
    target = None
    try:
        for number in range(1, 10_001):
            candidate = directory / f"{stem}{'' if number == 1 else '-' + str(number)}{extension}"
            try:
                output = candidate.open("xb")
                target = candidate
                break
            except FileExistsError:
                continue
        if target is None:
            raise SaveFailure("MMUU_SAVE_NAME_CONFLICT")
        digest, size = hashlib.sha256(), 0
        with output:
            while True:
                chunk = source.read(65_536)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if expected_bytes is not None and size != expected_bytes:
            raise SaveFailure("MMUU_SAVE_DOWNLOAD_INCOMPLETE")
        return {"path": str(target), "mimeType": mime, "byteSize": size,
                "sha256": digest.hexdigest()}
    except Exception:
        if target is not None:
            try:
                target.unlink()
            except OSError:
                pass
        raise


def save_media(part, directory, name_for_mime, *, opener=None, timeout=120):
    url = part.get("url")
    if not isinstance(url, str):
        raise SaveFailure("MMUU_SAVE_PART_INVALID")
    if url.startswith("data:"):
        source, mime = data_source(url)
        with source:
            return write_stream(directory, name_for_mime, mime, source)
    request = Request(remote_url(url), method="GET", headers={"User-Agent": "MMUU-AI-result-saver"})
    transport = opener or build_opener(ResultRedirect())
    try:
        response = transport.open(request, timeout=timeout)
    except URLError as error:
        # A host's native certificate store may work when Python's TLS does not.
        # GET is safe to repeat; this never resubmits or claims a generated task.
        if opener is None and isinstance(error.reason, ssl.SSLError) and which("curl.exe" if sys.platform == "win32" else "curl"):
            return save_with_native_curl(part, directory, name_for_mime, timeout)
        raise
    with response:
        if response.status != 200:
            raise SaveFailure("MMUU_SAVE_HTTP_FAILED", response.status)
        supplied = mime_type(part.get("mimeType"))
        actual = mime_type(response.headers.get("Content-Type"))
        mime = actual if actual and actual != "application/octet-stream" else supplied or actual
        mime = mime or "application/octet-stream"
        length = response.headers.get("Content-Length", "")
        expected = int(length) if re.fullmatch(r"[0-9]+", length) else None
        return write_stream(directory, name_for_mime, mime, response, expected)


def save_with_native_curl(part, directory, name_for_mime, timeout):
    program = which("curl.exe" if sys.platform == "win32" else "curl")
    args = [program, "--disable", "--silent", "--fail", "--location",
            "--disallow-username-in-url", "--max-redirs", "10",
            "--proto", "=http,https", "--proto-redir", "=http,https",
            "--max-time", str(timeout), "--user-agent", "MMUU-AI-result-saver",
            "--write-out", "%{stderr}%{http_code}", "--config", "-"]
    # Signed URLs stay on stdin, not in shell source, process arguments or logs.
    config = 'url = ' + json.dumps(remote_url(part["url"]), ensure_ascii=False) + '\n'
    child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}))
    saved = None
    try:
        child.stdin.write(config.encode("utf-8"))
        child.stdin.close()
        mime = mime_type(part.get("mimeType")) or "application/octet-stream"
        saved = write_stream(directory, name_for_mime, mime, child.stdout)
        status = child.stderr.read(16)
        if child.wait(timeout=5) != 0 or status.strip() != b"200":
            raise SaveFailure("MMUU_SAVE_TRANSPORT_FAILED")
        return saved
    except Exception:
        if saved is not None:
            Path(saved["path"]).unlink(missing_ok=True)
        raise
    finally:
        if not child.stdin.closed:
            child.stdin.close()
        if child.poll() is None:
            child.kill()
        child.wait()
        child.stdout.close()
        child.stderr.close()


def result_body(payload):
    body = payload
    for _ in range(4):
        if not isinstance(body, dict):
            break
        if any(body.get(name) not in (None, False) for name in ("isError", "is_error")):
            raise SaveFailure("MMUU_SAVE_TOOL_ERROR")
        field = next((name for name in ("receivedResult", "structuredContent", "structured_content") if name in body), None)
        if field:
            body = body[field]
            continue
        content = body.get("content")
        if isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
            try:
                nested = json.loads(content[0].get("text", ""))
            except (TypeError, ValueError):
                break
            if isinstance(nested, dict) and any(nested.get(name) not in (None, False) for name in ("isError", "is_error")):
                raise SaveFailure("MMUU_SAVE_TOOL_ERROR")
            if not isinstance(nested, dict) or not any(name in nested for name in ("structuredContent", "structured_content")):
                break
            body = nested
            continue
        return body
    raise SaveFailure("MMUU_SAVE_RESULT_INVALID")


def save_results(payload, *, output_dir=None, downloads=None, opener=None, timeout=120):
    body = result_body(payload)
    task_id = body.get("taskId") if isinstance(body, dict) else None
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise SaveFailure("MMUU_SAVE_RESULT_INVALID")
    result = body.get("result", {"parts": body.get("parts")})
    if not isinstance(result, dict):
        raise SaveFailure("MMUU_SAVE_RESULT_INVALID")
    directory = (Path(output_dir).expanduser() if output_dir is not None else
                 Path(downloads or downloads_directory()) / "MMUUAI").resolve()
    context = payload.get("downloadContext", {}) if "receivedResult" in payload else {}
    context = context if isinstance(context, dict) else {}
    skipped = payload.get("skipPartIndexes", []) if "receivedResult" in payload else []
    if (not isinstance(skipped, list) or
            any(type(index) is not int or index < -1 for index in skipped) or
            len(set(skipped)) != len(skipped)):
        raise SaveFailure("MMUU_SAVE_SKIP_INDEXES_INVALID")
    skipped = set(skipped)
    saved, failures, batch_time = [], [], datetime.now(timezone.utc)
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return {"status": "failed", "taskId": task_id, "directory": str(directory), "saved": [],
                "failures": [{"code": "MMUU_SAVE_DIRECTORY_UNAVAILABLE"}], "resultRefetchAttempted": False}
    parts = result.get("parts", [])
    if not isinstance(parts, list):
        raise SaveFailure("MMUU_SAVE_RESULT_INVALID")
    for index, part, ordinal, total in output_entries(result):
        if index in skipped:
            continue
        try:
            if not isinstance(part, dict):
                raise SaveFailure("MMUU_SAVE_PART_INVALID")
            kind = part.get("type")
            name_for_mime = lambda mime: result_download_name(part, context, ordinal, total, mime, now=batch_time)
            if kind == "text" and isinstance(part.get("text"), str):
                record = write_stream(directory, name_for_mime, "text/plain", io.BytesIO(part["text"].encode("utf-8")))
            elif kind in {"image", "audio", "video", "file"}:
                record = save_media(part, directory, name_for_mime, opener=opener, timeout=timeout)
            else:
                raise SaveFailure("MMUU_SAVE_PART_UNSUPPORTED")
            saved.append({"partIndex": index, "type": kind, **record})
        except Exception as error:
            if isinstance(error, HTTPError):
                error.close()
            code = error.code if isinstance(error, SaveFailure) else (
                "MMUU_SAVE_HTTP_FAILED" if isinstance(error, HTTPError) else
                "MMUU_SAVE_TLS_FAILED" if isinstance(error, URLError) and isinstance(error.reason, ssl.SSLError) else
                "MMUU_SAVE_TRANSPORT_FAILED" if isinstance(error, URLError) else "MMUU_SAVE_FAILED")
            failure = {"partIndex": index, "code": code}
            status = error.code if isinstance(error, HTTPError) else getattr(error, "http_status", None)
            if isinstance(status, int) and 100 <= status <= 599:
                failure["httpStatus"] = status
            failures.append(failure)
    return {"status": "partial" if failures and saved else "failed" if failures else "saved" if saved else "empty",
            "taskId": task_id, "directory": str(directory), "saved": saved, "failures": failures,
            "resultRefetchAttempted": False, "generationAttempted": False,
            "retrySavingFromOriginalResult": bool(failures), "mediaDecoded": False}


def main(argv=None):
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8-sig")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = SafeArgumentParser(description="从JSON stdin保存已领取的结果，默认系统下载目录/MMUUAI。")
    parser.add_argument("--output-dir", help="用户指定的本次保存目录，优先于系统下载目录")
    try:
        args = parser.parse_args(argv)
        result = save_results(json.load(sys.stdin), output_dir=args.output_dir)
    except SaveFailure as error:
        result = {"status": "failed", "code": error.code, "resultRefetchAttempted": False}
    except KeyboardInterrupt:
        result = {"status": "failed", "code": "MMUU_SAVE_INTERRUPTED", "resultRefetchAttempted": False}
    except Exception:
        result = {"status": "failed", "code": "MMUU_SAVE_FAILED", "resultRefetchAttempted": False}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "saved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
