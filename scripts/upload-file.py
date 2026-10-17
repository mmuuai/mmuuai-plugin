#!/usr/bin/env python3
"""Upload one file to MMUUAI without retrying or printing its bytes or Key."""
import argparse
from datetime import datetime
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import (HTTPRedirectHandler, ProxyHandler, Request,
                            build_opener, getproxies_environment)

UPLOAD_URL = "https://api.mmuu.ai/v1/uploads"
API_BASE_URL = "https://api.mmuu.ai"
MAX_METADATA_BYTES = 16_384
REF_PATTERN = re.compile(r"^upl_[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9_-]+$")
REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class UploadFailure(Exception):
    def __init__(self, code, http_status=None, request_id=None, transport_reason=None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.request_id = request_id
        self.transport_reason = transport_reason


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        raise UploadFailure("MMUU_UPLOAD_ARGUMENTS_INVALID")


def delegated_upload_url(value, api_base_url=API_BASE_URL):
    try:
        base, target = urlsplit(api_base_url), urlsplit(value)
        public = api_base_url == API_BASE_URL
        local = base.hostname in {"localhost", "127.0.0.1", "::1"}
        valid_base = (public or local) and base.scheme in {"http", "https"}
        base_port = base.port if base.port is not None else (443 if base.scheme == "https" else 80)
        target_port = target.port if target.port is not None else (443 if target.scheme == "https" else 80)
        valid = (valid_base and not base.username and not base.password
                 and base.path in {"", "/"} and not base.query and not base.fragment
                 and target.scheme == base.scheme and target.hostname == base.hostname
                 and target_port == base_port and not target.username and not target.password
                 and not target.query and not target.fragment
                 and re.fullmatch(r"/v1/uploads/delegated/mmuu_up_[A-Za-z0-9_-]{43}", target.path))
        if not valid:
            raise ValueError
    except (TypeError, ValueError):
        raise UploadFailure("MMUU_UPLOAD_URL_INVALID") from None
    return value


def request_identity(headers):
    value = headers.get("X-Request-Id", "") if headers else ""
    return value if REQUEST_ID_PATTERN.fullmatch(value) else None


def transport_reason(error):
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "tls_verification"
    if isinstance(reason, TimeoutError):
        return "timeout"
    if isinstance(reason, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(reason, socket.gaierror):
        return "name_resolution"
    if isinstance(reason, ConnectionResetError):
        return "connection_reset"
    return "network_error"


def upload_metadata(payload, byte_size, parameter):
    try:
        ref = payload["ref"]
        kind, name, mime = (payload[key] for key in ("mediaKind", "fileName", "mimeType"))
        expires = payload["expiresAt"]
        valid = (
            isinstance(ref, str) and len(ref) <= 4096 and REF_PATTERN.fullmatch(ref)
            and kind in {"image", "video", "audio", "file"}
            and isinstance(name, str) and 1 <= len(name) <= 180
            and isinstance(mime, str) and 1 <= len(mime) <= 120
            and type(payload["byteSize"]) is int and payload["byteSize"] == byte_size
            and isinstance(expires, str)
            and datetime.fromisoformat(expires.replace("Z", "+00:00")).tzinfo is not None
        )
        if not valid:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise UploadFailure("MMUU_UPLOAD_RESPONSE_INVALID") from None
    file = {"source": {"type": "upload", "ref": ref}, "mediaKind": kind,
            "fileName": name, "mimeType": mime, "parameter": parameter}
    return {"file": file, "byteSize": byte_size, "expiresAt": expires}


def upload_file(file_path, media_kind="image", mime_type=None, parameter="image", *,
                environ=None, opener=None, upload_url=None, api_base_url=API_BASE_URL):
    # Delegated mode never reads a host OAuth token or API Key, even if one exists.
    if upload_url is not None:
        destination = delegated_upload_url(upload_url, api_base_url)
        authorization = {}
    else:
        key = (os.environ if environ is None else environ).get("MMUU_API_KEY", "").strip()
        if not key:
            raise UploadFailure("MMUU_API_KEY_ENV_REQUIRED")
        destination = UPLOAD_URL
        authorization = {"Authorization": "Bearer " + key}
    path = Path(file_path)
    mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        source = path.open("rb")
    except OSError:
        raise UploadFailure("MMUU_UPLOAD_LOCAL_FILE_UNAVAILABLE") from None
    with source:
        byte_size = os.fstat(source.fileno()).st_size
        metadata_headers = {} if upload_url is not None else {
            "X-MMUU-Media-Kind": media_kind,
            "X-MMUU-File-Name": quote(path.name, safe=""),
            "X-MMUU-Mime-Type": mime,
        }
        request = Request(destination, data=source, method="POST", headers={
            **authorization,
            **metadata_headers,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(byte_size),
        })
        # Match the Node/MCP transport: use explicit proxy environment only.
        # urllib's default otherwise silently reads a separate Windows proxy.
        proxies = getproxies_environment()
        if "https" not in proxies and proxies.get("http"):
            proxies["https"] = proxies["http"]
        transport = opener or build_opener(ProxyHandler(proxies), NoRedirect())
        try:
            with transport.open(request, timeout=140) as response:
                if response.status != 201:
                    raise UploadFailure("MMUU_UPLOAD_HTTP_FAILED", response.status,
                                        request_identity(response.headers))
                raw = response.read(MAX_METADATA_BYTES + 1)
                if len(raw) > MAX_METADATA_BYTES:
                    raise UploadFailure("MMUU_UPLOAD_RESPONSE_INVALID", 201)
                payload = json.loads(raw)
        except HTTPError as error:
            # No raw response/error body, URL, request headers, or traceback.
            identity = request_identity(error.headers)
            error.close()
            raise UploadFailure("MMUU_UPLOAD_HTTP_FAILED", error.code, identity) from None
        except (URLError, OSError) as error:
            raise UploadFailure("MMUU_UPLOAD_TRANSPORT_UNKNOWN",
                                transport_reason=transport_reason(error)) from None
        except (TypeError, ValueError):
            raise UploadFailure("MMUU_UPLOAD_RESPONSE_INVALID") from None
    if upload_url is not None and (not isinstance(payload, dict) or payload.get("fileName") != path.name
                                  or payload.get("mimeType") != mime
                                  or payload.get("mediaKind") != media_kind):
        raise UploadFailure("MMUU_UPLOAD_RESPONSE_INVALID")
    return upload_metadata(payload, byte_size, parameter)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = SafeArgumentParser(description="一次上传本地文件，输出可绑定 input.files 的临时引用。")
    parser.add_argument("file")
    parser.add_argument("--parameter", default="image", help="模型目录中的公开文件参数 name")
    parser.add_argument("--media-kind", choices=("image", "video", "audio", "file"), default="image")
    parser.add_argument("--mime-type", help="省略时按文件名推导，无法推导则 application/octet-stream")
    parser.add_argument("--upload-url", help="mmuu_prepare_upload 返回的短期一次性上传地址；此模式不读取 API Key")
    try:
        args = parser.parse_args(argv)
        result = upload_file(args.file, args.media_kind, args.mime_type, args.parameter,
                             upload_url=args.upload_url)
    except UploadFailure as error:
        failure = {"status": "failed", "code": error.code, "retryAttempted": False}
        if error.http_status is not None:
            failure["httpStatus"] = error.http_status
        if error.request_id is not None:
            failure["request_id"] = error.request_id
        if error.transport_reason is not None:
            failure["transportReason"] = error.transport_reason
        print(json.dumps(failure), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('{"status":"failed","code":"MMUU_UPLOAD_INTERRUPTED_UNKNOWN","retryAttempted":false}', file=sys.stderr)
        return 1
    except Exception:
        print('{"status":"failed","code":"MMUU_UPLOAD_UNEXPECTED_FAILURE","retryAttempted":false}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
