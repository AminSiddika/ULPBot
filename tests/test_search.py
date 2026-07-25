import pytest

from src.services.search import _extract_section


class TestExtractSection:
    def test_mail_pass_format(self) -> None:
        result = _extract_section("https://example.com:user@gmail.com:pass123", "mail_pass")
        assert result == "user@gmail.com:pass123"

    def test_mail_pass_rejects_non_email(self) -> None:
        result = _extract_section("https://example.com:johndoe:pass123", "mail_pass")
        assert result is None

    def test_user_pass_format(self) -> None:
        result = _extract_section("https://example.com:johndoe:pass123", "user_pass")
        assert result == "johndoe:pass123"

    def test_number_pass_format(self) -> None:
        result = _extract_section("https://example.com:+1234567890:pass123", "number_pass")
        assert result == "+1234567890:pass123"

    def test_number_pass_rejects_bad_login(self) -> None:
        result = _extract_section("https://example.com:abc123:pass123", "number_pass")
        assert result is None

    def test_raw_format(self) -> None:
        result = _extract_section("https://example.com:login:pass", None)
        assert result == "https://example.com:login:pass"

    def test_invalid_line(self) -> None:
        assert _extract_section("no_colons", "mail_pass") is None
        assert _extract_section("only:two", "mail_pass") is None
