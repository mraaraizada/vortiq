"""SSRF-protection and URL validation tests. No network calls — getaddrinfo on
localhost/well-known public hostnames resolves locally/via DNS without needing a
live site to be reachable."""
from __future__ import annotations

import pytest

from app.utils.validators import URLValidationError, validate_public_url


def test_valid_https_url_passes():
    assert validate_public_url("https://example.com") == "https://example.com"


def test_empty_url_rejected():
    with pytest.raises(URLValidationError):
        validate_public_url("")


def test_invalid_scheme_rejected():
    with pytest.raises(URLValidationError, match="scheme"):
        validate_public_url("ftp://example.com")


def test_missing_hostname_rejected():
    with pytest.raises(URLValidationError, match="hostname"):
        validate_public_url("https:///path")


def test_loopback_ip_literal_rejected():
    with pytest.raises(URLValidationError, match="private/internal"):
        validate_public_url("http://127.0.0.1/")


def test_localhost_hostname_rejected():
    with pytest.raises(URLValidationError, match="private/internal"):
        validate_public_url("http://localhost/")


def test_private_ip_literal_rejected():
    with pytest.raises(URLValidationError, match="private/internal"):
        validate_public_url("http://10.0.0.5/")


def test_link_local_ip_literal_rejected():
    # The AWS/GCP/Azure metadata-service IP — a classic real SSRF target.
    with pytest.raises(URLValidationError, match="private/internal"):
        validate_public_url("http://169.254.169.254/latest/meta-data/")


def test_unresolvable_hostname_rejected():
    with pytest.raises(URLValidationError, match="could not be resolved"):
        validate_public_url("https://this-domain-should-not-exist-vortiq-test.invalid/")
