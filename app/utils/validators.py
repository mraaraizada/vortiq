"""URL validation with SSRF protection.

Validates that a submitted URL is a well-formed http(s) URL, then resolves its
hostname and rejects anything that points at a private, loopback, link-local,
multicast, or otherwise reserved IP address — the spec explicitly requires this
("prevent access to private or internal network addresses (SSRF protection)").
Resolution happens here, synchronously, before any HTTP request is made, so a
malicious hostname can never reach the actual fetch step.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class URLValidationError(ValueError):
    """Raised with a human-readable reason the submitted URL was rejected."""


def _is_private_or_reserved(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(raw_url: str) -> str:
    """Returns the normalized URL if it's a valid, publicly-routable http(s) URL, or
    raises URLValidationError explaining why it was rejected."""
    stripped = raw_url.strip()
    if not stripped:
        raise URLValidationError("url must not be empty")

    parsed = urlparse(stripped)
    if parsed.scheme not in ("http", "https"):
        raise URLValidationError(f"url must use http or https, got scheme {parsed.scheme!r}")
    if not parsed.hostname:
        raise URLValidationError("url must include a hostname")

    hostname = parsed.hostname

    try:
        # Covers the common case of a bare IP literal (e.g. http://127.0.0.1/).
        ipaddress.ip_address(hostname)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False

    if is_ip_literal:
        if _is_private_or_reserved(hostname):
            raise URLValidationError(f"url resolves to a private/internal address: {hostname}")
        return stripped

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise URLValidationError(f"url hostname could not be resolved: {hostname}") from exc

    for family, _, _, _, sockaddr in resolved:
        ip_str = sockaddr[0]
        if _is_private_or_reserved(ip_str):
            raise URLValidationError(f"url resolves to a private/internal address ({ip_str}): {hostname}")

    return stripped
