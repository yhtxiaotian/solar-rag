import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.core.config import settings


EXTENSION_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/html": ".html",
}


class UnsafeUrlError(ValueError):
    pass


@dataclass(slots=True)
class DownloadedFile:
    data: bytes
    filename: str
    content_type: str
    final_url: str


def validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("资料链接必须是无账号信息的 HTTPS 地址")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("无法解析资料链接域名") from exc
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise UnsafeUrlError("资料链接不能指向内网、本机或保留地址")


def download_public_file(url: str, redirects: int = 3) -> DownloadedFile:
    current_url = url
    with httpx.Client(timeout=settings.ai_timeout_seconds, follow_redirects=False) as client:
        for _ in range(redirects + 1):
            validate_public_https_url(current_url)
            with client.stream("GET", current_url, headers={"User-Agent": "SolarRAG/1.0"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeUrlError("资料链接重定向缺少目标地址")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length", "0") or 0)
                if declared > settings.max_file_size_bytes:
                    raise UnsafeUrlError("远程文件超过允许大小")
                body = bytearray()
                for chunk in response.iter_bytes(1024 * 1024):
                    body.extend(chunk)
                    if len(body) > settings.max_file_size_bytes:
                        raise UnsafeUrlError("远程文件超过允许大小")
                parsed = urlparse(current_url)
                content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
                filename = Path(unquote(parsed.path)).name or "download"
                if not Path(filename).suffix:
                    filename += EXTENSION_BY_CONTENT_TYPE.get(content_type, "")
                if not Path(filename).suffix:
                    raise UnsafeUrlError("远程链接没有可识别的文件类型")
                return DownloadedFile(
                    data=bytes(body),
                    filename=filename,
                    content_type=content_type,
                    final_url=current_url,
                )
    raise UnsafeUrlError("资料链接重定向次数过多")
