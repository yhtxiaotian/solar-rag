import socket

import pytest

from app.core.config import settings
from app.services.url_safety import UnsafeUrlError, validate_public_https_url


def test_rejects_http_url():
    with pytest.raises(UnsafeUrlError):
        validate_public_https_url("http://example.com/file.pdf")


def test_rejects_private_dns_result(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(UnsafeUrlError):
        validate_public_https_url("https://example.com/file.pdf")


def test_accepts_public_dns_result(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    validate_public_https_url("https://example.com/file.pdf")


def test_accepts_allowlisted_host_behind_proxy_fake_ip(monkeypatch):
    monkeypatch.setattr(settings, "url_host_allowlist", "example.com")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.10", 443))])

    validate_public_https_url("https://example.com/file.pdf")


def test_allowlist_does_not_permit_private_literal_ip(monkeypatch):
    monkeypatch.setattr(settings, "url_host_allowlist", "127.0.0.1")

    with pytest.raises(UnsafeUrlError):
        validate_public_https_url("https://127.0.0.1/file.pdf")
