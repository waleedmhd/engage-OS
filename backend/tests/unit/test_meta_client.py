"""MetaWhatsAppClient: payload shaping + error classification."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.exceptions import MetaAPIError
from app.integrations.meta.client import MetaWhatsAppClient


def _client() -> MetaWhatsAppClient:
    from app.core.config import Settings

    s = Settings(
        META_ACCESS_TOKEN="tok",
        META_PHONE_NUMBER_ID="PN1",
        META_API_VERSION="v25.0",
    )
    return MetaWhatsAppClient(settings=s)


def _mock_response(status: int, json_body: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


def test_send_text_payload_shape() -> None:
    captured: dict = {}

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            captured["path"] = path
            captured["json"] = json
            return _mock_response(200, {"messages": [{"id": "wamid.OUT"}]})

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        result = client.send_text(to="111", body="hi")

    assert captured["path"] == "/PN1/messages"
    assert captured["json"]["messaging_product"] == "whatsapp"
    assert captured["json"]["to"] == "111"
    assert captured["json"]["type"] == "text"
    assert captured["json"]["text"] == {"body": "hi", "preview_url": False}
    assert MetaWhatsAppClient.extract_meta_message_id(result) == "wamid.OUT"


def test_4xx_raises_non_retryable() -> None:
    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            return _mock_response(400, {"error": "bad"})

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.send_text(to="111", body="hi")
    assert exc_info.value.details["status"] == 400
    assert exc_info.value.details["retryable"] is False


def test_5xx_raises_retryable() -> None:
    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            return _mock_response(503, {"error": "down"})

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.send_text(to="111", body="hi")
    assert exc_info.value.details["retryable"] is True


def test_429_is_retryable() -> None:
    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            return _mock_response(429, {"error": "rate limited"})

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.send_text(to="111", body="hi")
    assert exc_info.value.details["retryable"] is True


def test_timeout_classified_retryable() -> None:
    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            raise httpx.ConnectTimeout("slow")

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.send_text(to="111", body="hi")
    assert exc_info.value.details["retryable"] is True


def test_template_includes_components_when_provided() -> None:
    captured: dict = {}

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            captured["json"] = json
            return _mock_response(200, {"messages": [{"id": "wamid.X"}]})

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        client.send_template(
            to="111",
            template_name="welcome",
            language="en_US",
            components=[{"type": "body", "parameters": [{"type": "text", "text": "Bob"}]}],
        )

    template = captured["json"]["template"]
    assert template["name"] == "welcome"
    assert template["language"] == {"code": "en_US"}
    assert "components" in template


def test_error_body_pii_is_redacted() -> None:
    """M7: a Meta error body echoing the recipient phone number must NOT
    surface raw on the MetaAPIError (or, by extension, in the error log)."""

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            return _mock_response(
                400,
                {"error": {"message": "Invalid recipient +1 (555) 123-4567",
                            "details": "param 15551234567 failed"}},
            )

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.send_text(to="15551234567", body="hi")

    body = exc_info.value.details["body"]
    assert "[REDACTED]" in body
    assert "5551234567" not in body
    assert "123-4567" not in body
    # Status-based classification still intact.
    assert exc_info.value.details["status"] == 400
    assert exc_info.value.details["retryable"] is False


def test_pooled_client_reused_across_sends(monkeypatch) -> None:
    """M6: a single httpx.Client is built per MetaWhatsAppClient instance and
    reused across sends — no per-call construction / TLS handshake."""
    constructed: list[object] = []

    class FakeHttpx:
        def __init__(self, *a, **k):
            constructed.append(self)
            self.closed = False
        def post(self, path, json):
            return _mock_response(200, {"messages": [{"id": "wamid.P"}]})
        def close(self):
            self.closed = True

    monkeypatch.setattr("app.integrations.meta.client.httpx.Client", FakeHttpx)

    client = _client()
    client.send_text(to="111", body="a")
    client.send_text(to="111", body="b")
    assert len(constructed) == 1  # reused, not rebuilt per send

    pooled = constructed[0]
    client.close()
    assert pooled.closed is True

    # After close, the next send lazily builds a fresh client.
    client.send_text(to="111", body="c")
    assert len(constructed) == 2


def test_get_template_does_not_close_pooled_client(monkeypatch) -> None:
    """M6 regression: get_message_template must reuse the pooled client without
    closing it, so a subsequent send on the same instance still works."""
    constructed: list[object] = []

    class FakeHttpx:
        def __init__(self, *a, **k):
            constructed.append(self)
            self.closed = False
        def get(self, path, params):
            return _mock_response(200, {"status": "APPROVED"})
        def post(self, path, json):
            return _mock_response(200, {"messages": [{"id": "wamid.G"}]})
        def close(self):
            self.closed = True

    monkeypatch.setattr("app.integrations.meta.client.httpx.Client", FakeHttpx)

    client = _client()
    client.get_message_template(meta_template_id="remote-1")
    # The pooled client survives — not closed, and reused on the next call.
    assert constructed[0].closed is False
    client.send_text(to="111", body="after")
    assert len(constructed) == 1


def test_scrub_pii_helper() -> None:
    from app.integrations.meta.client import _scrub_pii

    assert _scrub_pii("call +1 555 123 4567 now") == "call [REDACTED] now"
    assert _scrub_pii("id=15551234567") == "id=[REDACTED]"
    assert _scrub_pii("no digits here") == "no digits here"
    # Short numbers (status codes, counts) are left alone.
    assert _scrub_pii("error 400 x 12") == "error 400 x 12"


def test_send_media_with_url_uses_link() -> None:
    captured: dict = {}

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def post(self, path, json):
            captured["json"] = json
            return _mock_response(200, {"messages": [{"id": "wamid.M"}]})

    client = _client()
    with patch.object(client, "_client", return_value=FakeClient()):
        client.send_media(
            to="111",
            media_type="image",
            media_id_or_url="https://example.com/cat.jpg",
            caption="kitty",
        )

    block = captured["json"]["image"]
    assert block == {"link": "https://example.com/cat.jpg", "caption": "kitty"}


def test_download_media_two_step_resolves_url_then_fetches_bytes():
    """download_media first gets JSON with download URL, then fetches binary."""

    class TwoStepClient:
        """Simulates the pooled httpx.Client with two different GET responses."""
        def __init__(self):
            self._call = 0
        def get(self, url):
            self._call += 1
            if self._call == 1:
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 200
                resp.json.return_value = {
                    "url": "https://lookaside.fbsbx.com/tmp/abc123",
                    "mime_type": "image/png",
                    "id": "media-1",
                }
                return resp
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.content = b"fake-png-binary"
            return resp

    client = _client()
    fake_http = TwoStepClient()
    with patch.object(client, "_client", return_value=fake_http):
        data, mime = client.download_media(media_id="media-1")

    assert data == b"fake-png-binary"
    assert mime == "image/png"
    assert fake_http._call == 2  # both steps called through _client()


def test_download_media_raises_when_no_url_in_json():
    """If Meta returns JSON without a url field, fail non-retryable."""
    class NoUrlClient:
        def get(self, url):
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"id": "media-1"}  # no 'url' key
            return resp

    client = _client()
    with patch.object(client, "_client", return_value=NoUrlClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.download_media(media_id="media-1")

    assert "no_url" in str(exc_info.value)
    assert exc_info.value.details["retryable"] is False


def test_download_media_handles_cdn_fetch_4xx():
    """When the CDN binary fetch returns 4xx, raise with status in details."""
    class Cdn4xxClient:
        def __init__(self):
            self._call = 0
        def get(self, url):
            self._call += 1
            if self._call == 1:
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 200
                resp.json.return_value = {
                    "url": "https://lookaside.fbsbx.com/expired",
                    "mime_type": "image/jpeg",
                }
                return resp
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 403
            resp.text = "expired link"
            return resp

    client = _client()
    with patch.object(client, "_client", return_value=Cdn4xxClient()):
        with pytest.raises(MetaAPIError) as exc_info:
            client.download_media(media_id="media-1")

    assert exc_info.value.details["status"] == 403
    assert exc_info.value.details["retryable"] is False
    assert "expired" in exc_info.value.details["body"]


def test_upload_media_filenotfound_raises_non_retryable():
    """FileNotFoundError → MetaAPIError with retryable=False so the Celery
    task terminates instead of retrying a missing file forever."""
    client = _client()

    class UploadClient:
        def post(self, url, *, files, data):
            return MagicMock(spec=httpx.Response)

    with patch.object(client, "_client", return_value=UploadClient()), \
         patch("builtins.open", side_effect=FileNotFoundError("no such file")):
        with pytest.raises(MetaAPIError) as exc_info:
            client.upload_media(
                file_path="/app/media/image/missing.jpeg",
                mime_type="image/jpeg",
            )

    assert exc_info.value.details["retryable"] is False
    assert exc_info.value.details["file_path"] == "/app/media/image/missing.jpeg"
