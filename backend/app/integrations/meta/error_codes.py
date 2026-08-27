"""Meta Cloud API error code → human-readable description.

Sources: Meta for Developers — WhatsApp Business Management API error codes
and WhatsApp Cloud API error codes.
"""

META_ERROR_CODES: dict[int, str] = {
    # --- WhatsApp Cloud API ---
    131000: "An unknown error occurred on Meta's side",
    131005: "Non-valid WhatsApp account",
    131008: "Required message parameter is missing",
    131009: "Message parameter structure is incorrect",
    131016: "Message could not be delivered in time (expired)",
    131021: "Recipient contact limit reached — too many messages to this contact",
    131025: "Message failed due to the recipient's account status",
    131026: "Message undeliverable — the recipient may not have WhatsApp or may have deleted the app",
    131030: "Meta server temporarily unavailable — retry later",
    131031: "Message content too long for the message type",
    131040: "WhatsApp Business Account is in maintenance mode",
    131042: "WhatsApp Business Account has been banned",
    131045: "Media download failed — file may be inaccessible or too large",
    131046: "Phone number does not match the WABA",
    131047: "Recipient has opted out of receiving messages from this business",
    131048: "Spam rate limit exceeded — too many messages in a short window",
    131049: "Structured message parameter does not match the expected format",
    131051: "Unsupported message type for this recipient or account",
    131052: "Recipient is not on WhatsApp",
    131053: "Unable to deliver message — recipient unreachable",
    131056: "Message blocked by WhatsApp quality filter (spam or policy violation suspected)",
    131057: "Message expired or cannot be delivered — user may have reinstalled or changed phone",
    131079: "Template has not been approved by Meta",
    # --- Template validation ---
    132000: "Template parameter count does not match the template definition",
    132001: "Template parameter value is invalid for its type",
    132003: "Template component limit exceeded",
    132008: "Template sending throttled — too many template messages in a short window",
    # --- Account / payment ---
    136000: "Sender account is limited — contact Meta support",
    136002: "Invalid authentication credentials — check the access token",
    136003: "Session invalid — re-authenticate",
    136008: "Two-factor authentication is required",
    136009: "Payment method is required to use this feature",
    136010: "Payment method is invalid",
    136011: "Payment method is not available in this country",
    136012: "Payment method is pending verification",
    136013: "Payment method has expired",
    136014: "Payment method was declined",
    136015: "Payment failed — update billing information",
    136020: "Credit line exhausted — top up or wait for the next billing cycle",
    136021: "Payment limit exceeded",
    136022: "Payment account suspended",
    # --- Facebook Graph API (generic) ---
    1: "Unknown error — retry later",
    2: "Service temporarily unavailable — retry later",
    4: "Rate limit exceeded — slow down requests",
    17: "User request limit reached — too many API calls",
    100: "Invalid parameter — check the request payload",
    190: "Invalid or expired access token",
    200: "Permission denied — the app or token lacks required permissions",
    368: "Account temporarily blocked — retry later",
    800: "Message rate limit exceeded — reduce sending frequency",
    # --- HTTP-level captures ---
    408: "Request timed out — Meta may be experiencing issues",
    429: "Too many requests — Meta rate limit hit, retry later",
    500: "Meta internal server error — retry later",
    502: "Meta bad gateway — retry later",
    503: "Meta service unavailable — retry later",
    504: "Meta gateway timeout — retry later",
}


def describe_error(error_code: int | None) -> str | None:
    """Return a human-readable description for a Meta error code, or None."""
    if error_code is None:
        return None
    return META_ERROR_CODES.get(error_code)
