"""Meta WhatsApp Cloud API client.

Synchronous httpx client used by Celery dispatcher tasks. Inbound webhook
handling never calls Meta directly — outbound sends always go through the
queue, so a single sync client is sufficient.

All non-2xx responses surface as `MetaAPIError` with `details.retryable`
set so the dispatcher can decide between scheduled retry and terminal failure.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import MetaAPIError
from app.core.logging import get_logger

logger = get_logger(__name__)

# 408 Request Timeout, 425 Too Early, 429 Too Many Requests, 5xx — retryable.
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

# M7 PII redaction: Meta error bodies for template / personalized sends echo
# back the recipient phone number and substituted parameters (customer names,
# order ids, etc.). Logging the raw body leaks that into structured logs.
# Redact any run of 7+ digits (WhatsApp numbers are 10-15) — covering bare,
# +-prefixed and separator-spaced forms — before the body is logged OR stored
# on the MetaAPIError. Status-based retry classification is unaffected.
_PII_DIGIT_RUN = re.compile(r"\+?\d[\d\s\-().]{5,}\d")


def _scrub_pii(text: str) -> str:
    """Replace phone-number-like digit runs with a redaction marker."""
    return _PII_DIGIT_RUN.sub("[REDACTED]", text)


class _SendRateLimiter:
    """Sliding-window outbound rate limiter — thread-safe.

    Enforces ``META_SEND_RATE_LIMIT`` (messages/second) by spacing
    ``_post()`` calls.  Uses ``time.sleep()`` rather than
    ``asyncio.sleep()`` because the Meta client is synchronous and runs
    inside Celery *prefork* worker processes — a sleep in a child
    process does not block the main (heartbeat) process.

    A value of 0 or negative disables rate limiting entirely.
    """

    def __init__(self, max_rate: float) -> None:
        self._min_interval: float = 1.0 / max_rate if max_rate > 0 else 0.0
        self._last_send: float = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a send token is available."""
        interval = self._min_interval
        if interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._last_send + interval - now
            if wait > 0:
                time.sleep(wait)
                # Re-measure after sleeping so drift does not accumulate.
                self._last_send = time.monotonic()
            else:
                self._last_send = now


class MetaWhatsAppClient:
    def __init__(self, settings: Settings | None = None, *, timeout: float = 10.0) -> None:
        self._settings = settings or get_settings()
        self._timeout = timeout
        # M6: one pooled httpx.Client per MetaWhatsAppClient instance, created
        # lazily and reused across every send. Previously a fresh client (and
        # TLS handshake) was built per `_post` call. Closed via close() /
        # context manager — the sync analogue of the asyncio.run/aclose
        # discipline used for the AI async client (architectural
        # invariant #12).
        self._http: httpx.Client | None = None
        self._rate_limiter = _SendRateLimiter(self._settings.META_SEND_RATE_LIMIT)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self._settings.META_API_VERSION}"

    def _client(self) -> httpx.Client:
        """Return the pooled httpx client, creating it on first use."""
        if self._http is None:
            self._http = httpx.Client(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self._settings.META_ACCESS_TOKEN}",
                },
                timeout=self._timeout,
            )
        return self._http

    def close(self) -> None:
        """Close the pooled connection. Safe to call multiple times."""
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> MetaWhatsAppClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def _send_path(self) -> str:
        return f"/{self._settings.META_PHONE_NUMBER_ID}/messages"

    def _post(self, path: str, payload: dict[str, Any], *, action: str) -> dict[str, Any]:
        self._rate_limiter.acquire()
        try:
            # M6: reuse the pooled client (do NOT close per call).
            response = self._client().post(path, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("meta_api_timeout", action=action)
            raise MetaAPIError(
                f"meta_{action}_timeout",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc
        except httpx.TransportError as exc:
            logger.warning("meta_api_transport_error", action=action, error=str(exc))
            raise MetaAPIError(
                f"meta_{action}_transport_error",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise(response, action, payload)
        return response.json()

    def send_text(self, *, to: str, body: str, preview_url: bool = False) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": body, "preview_url": preview_url},
        }
        return self._post(self._send_path, payload, action="send_text")

    def send_template(
        self,
        *,
        to: str,
        template_name: str,
        language: str = "en",
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        template_block: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language},
        }
        if components:
            template_block["components"] = components
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": template_block,
        }
        return self._post(self._send_path, payload, action="send_template")

    def send_media(
        self,
        *,
        to: str,
        media_type: str,
        media_id_or_url: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        if media_type not in ("image", "audio", "video", "document", "sticker"):
            raise MetaAPIError(
                "meta_send_media_unsupported_type",
                details={"media_type": media_type, "retryable": False},
            )
        media_block: dict[str, Any] = {}
        if media_id_or_url.startswith(("http://", "https://")):
            media_block["link"] = media_id_or_url
        else:
            media_block["id"] = media_id_or_url
        if caption and media_type in ("image", "video", "document"):
            media_block["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": media_type,
            media_type: media_block,
        }
        return self._post(self._send_path, payload, action="send_media")

    @property
    def _template_path(self) -> str:
        return f"/{self._settings.META_WABA_ID}/message_templates"

    def submit_message_template(
        self,
        *,
        name: str,
        language: str,
        category: str,
        body: str,
    ) -> dict[str, Any]:
        """Submit a template to Meta for approval.

        Returns the raw Meta response, which includes the remote template
        `id` and an initial `status` (typically PENDING / APPROVED).
        """
        payload = {
            "name": name,
            "language": language,
            "category": category.upper(),
            "components": [{"type": "BODY", "text": body}],
        }
        return self._post(self._template_path, payload, action="submit_template")

    def get_message_template(self, *, meta_template_id: str) -> dict[str, Any]:
        """Fetch a single template's current state (status + body) from Meta."""
        path = f"/{meta_template_id}"
        try:
            # M6: reuse the pooled client (do NOT use `with`, which would close
            # it on exit and break the next call on this instance).
            response = self._client().get(
                path, params={"fields": "status,name,category,language,components"}
            )
        except httpx.TimeoutException as exc:
            logger.warning("meta_api_timeout", action="get_template")
            raise MetaAPIError(
                "meta_get_template_timeout",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc
        except httpx.TransportError as exc:
            logger.warning("meta_api_transport_error", action="get_template", error=str(exc))
            raise MetaAPIError(
                "meta_get_template_transport_error",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc
        if response.status_code >= 400:
            self._raise(response, "get_template")
        return response.json()

    def get_message_templates(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch ALL templates registered on this WABA from Meta.

        Uses cursor-based pagination — follows ``paging.next`` until exhausted.
        Each item includes: id, name, status, category, language, components.

        Returns a flat list of raw template dicts.
        """
        results: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "fields": "id,name,status,category,language,components",
            "limit": limit,
        }
        path = self._template_path
        while True:
            try:
                response = self._client().get(path, params=params)
            except httpx.TimeoutException as exc:
                logger.warning("meta_api_timeout", action="list_templates")
                raise MetaAPIError(
                    "meta_list_templates_timeout",
                    details={"retryable": True, "exception": exc.__class__.__name__},
                ) from exc
            except httpx.TransportError as exc:
                logger.warning("meta_api_transport_error", action="list_templates", error=str(exc))
                raise MetaAPIError(
                    "meta_list_templates_transport_error",
                    details={"retryable": True, "exception": exc.__class__.__name__},
                ) from exc
            if response.status_code >= 400:
                self._raise(response, "list_templates")
            data = response.json()
            results.extend(data.get("data") or [])
            # Follow cursor pagination until no ``next`` link is present.
            next_cursor = (
                data.get("paging", {}).get("cursors", {}).get("after")
            )
            if not next_cursor or "next" not in data.get("paging", {}):
                break
            # Switch to cursor-based params for subsequent pages.
            params = {
                "fields": "id,name,status,category,language,components",
                "limit": limit,
                "after": next_cursor,
            }
        return results

    def register_phone_number(self, *, pin: str | None = None) -> dict[str, Any]:
        """Register the phone number with Meta.

        Required after a display-name change is approved — re-registering
        before the ``phone_number_name_update`` webhook confirms APPROVED
        has no effect.

        ``pin`` is required only if two-step verification is enabled on the
        WABA. Meta docs: POST /{PHONE_NUMBER_ID}/register.
        """
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
        }
        if pin:
            payload["pin"] = pin
        path = f"/{self._settings.META_PHONE_NUMBER_ID}/register"
        return self._post(path, payload, action="register_phone")
    def send_contact(
        self,
        *,
        to: str,
        contact_name: str,
        contact_phones: list[str],
    ) -> dict[str, Any]:
        """Send a contact card via the Meta Send API."""
        from app.core.phone import format_phone_for_display

        phones_payload = [
            {"phone": format_phone_for_display(p)}
            for p in contact_phones
        ]
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "contacts",
            "contacts": [
                {
                    "name": {
                        "formatted_name": contact_name,
                        "first_name": contact_name,
                    },
                    "phones": phones_payload,
                }
            ],
        }
        return self._post(self._send_path, payload, action="send_contact")

    def mark_as_read(self, *, message_id: str) -> dict[str, Any]:
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return self._post(self._send_path, payload, action="mark_as_read")

    def delete_message(self, *, meta_message_id: str) -> dict[str, Any]:
        """Request deletion of a message via the Meta Cloud API.
        WhatsApp limits this to ~1 hour after sending."""
        payload = {
            "messaging_product": "whatsapp",
            "id": meta_message_id,
        }
        try:
            # httpx.Client.delete() does not accept a `json` kwarg — use
            # request() instead which accepts the same parameters as other methods.
            response = self._client().request(
                method="DELETE", url=self._send_path, json=payload
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("meta_delete_message_error", meta_message_id=meta_message_id, error=str(exc))
            raise MetaAPIError(
                "meta_delete_message_failed",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc
        if response.status_code >= 400:
            self._raise(response, "delete_message")
        return response.json()

    @property
    def _media_upload_path(self) -> str:
        return f"/{self._settings.META_PHONE_NUMBER_ID}/media"

    def upload_media(self, *, file_path: str, mime_type: str) -> str:
        """Upload a media file to Meta and return the media ID."""
        import os

        filename = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                response = self._client().post(
                    self._media_upload_path,
                    files={"file": (filename, f, mime_type)},
                    data={"messaging_product": "whatsapp"},
                )
        except FileNotFoundError as exc:
            raise MetaAPIError(
                "meta_media_file_missing",
                details={"retryable": False, "file_path": file_path},
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("meta_media_upload_error", file=file_path, error=str(exc))
            raise MetaAPIError(
                "meta_media_upload_failed",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise(response, "upload_media")
        media_id = response.json().get("id")
        if not media_id:
            raise MetaAPIError(
                "meta_media_upload_no_id",
                details={"retryable": False},
            )
        return str(media_id)

    def download_media(self, *, media_id: str) -> tuple[bytes, str]:
        """Download media from Meta. Returns (binary_data, mime_type).

        Meta's GET /{media-id} returns JSON with a temporary download URL, not
        the binary. We follow the two-step flow: resolve the URL, then fetch
        the bytes from that URL (a signed lookaside.fbsbx.com link that does
        not need the Bearer token).
        """
        path = f"/{media_id}"
        try:
            response = self._client().get(path)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("meta_media_download_error", media_id=media_id, error=str(exc))
            raise MetaAPIError(
                "meta_media_download_failed",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc

        if response.status_code >= 400:
            self._raise(response, "download_media")

        meta = response.json()
        download_url = meta.get("url")
        if not download_url:
            raise MetaAPIError(
                "meta_media_download_no_url",
                details={"media_id": media_id, "retryable": False},
            )

        mime_type = meta.get("mime_type", "application/octet-stream")

        # The download URL is a signed, short-lived lookaside link. Fetch it
        # through the pooled client so the Bearer token is included — the URL
        # is an absolute HTTPS link which overrides base_url, so resolution
        # is correct. Without the auth header the CDN may 403 on the worker.
        try:
            dl_response = self._client().get(download_url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("meta_media_download_error", media_id=media_id, error=str(exc))
            raise MetaAPIError(
                "meta_media_download_failed",
                details={"retryable": True, "exception": exc.__class__.__name__},
            ) from exc

        if dl_response.status_code >= 400:
            raise MetaAPIError(
                "meta_media_download_failed",
                details={
                    "status": dl_response.status_code,
                    "body": (dl_response.text or "")[:200],
                    "retryable": dl_response.status_code in _RETRYABLE_STATUS,
                },
            )

        return dl_response.content, mime_type

    @staticmethod
    def extract_meta_message_id(response: dict[str, Any]) -> str | None:
        messages = response.get("messages") if isinstance(response, dict) else None
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            mid = messages[0].get("id")
            return str(mid) if mid else None
        return None

    def _raise(self, response: httpx.Response, action: str, payload: dict[str, Any] | None = None) -> None:
        # M7: scrub phone numbers / personalized params out of the Meta error
        # body BEFORE it is logged or stored on the exception. Retry
        # classification depends only on status, so this is behavior-safe.
        safe_body = _scrub_pii((response.text or "")[:2000])
        retryable = response.status_code in _RETRYABLE_STATUS
        # Scrub the request payload too so we can see what was sent vs returned.
        safe_payload = _scrub_pii(json.dumps(payload, default=str)) if payload else "<no payload>"
        logger.error(
            "meta_api_error",
            action=action,
            status=response.status_code,
            request_payload=safe_payload,
            response_body=safe_body,
            retryable=retryable,
        )
        raise MetaAPIError(
            f"meta_{action}_failed",
            details={
                "status": response.status_code,
                "body": safe_body,
                "retryable": retryable,
            },
        )
