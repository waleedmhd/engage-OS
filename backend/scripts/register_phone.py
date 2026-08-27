"""Register the WhatsApp phone number with Meta.

Required after a display-name change is approved. Must be run AFTER the
``phone_number_name_update`` webhook confirms APPROVED — re-registering
before approval has no effect.

Usage (from backend/):
  python scripts/register_phone.py                # PIN from META_TWO_FACTOR_PIN env var
  python scripts/register_phone.py 123456         # PIN as positional arg (takes precedence)

On Railway:
  railway run --service engageos-api "python scripts/register_phone.py 123456"
"""

from __future__ import annotations

import os
import sys

from app.core.config import get_settings
from app.integrations.meta.client import MetaWhatsAppClient


def main() -> int:
    pin = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("META_TWO_FACTOR_PIN", "")
    if not pin:
        print(
            "No PIN provided. If two-step verification is enabled, pass the "
            "6-digit PIN as an argument or set META_TWO_FACTOR_PIN:\n"
            "  python scripts/register_phone.py 123456\n"
            "  railway run --service engageos-api \"python scripts/register_phone.py 123456\""
        )

    settings = get_settings()
    print(f"Phone Number ID: {settings.META_PHONE_NUMBER_ID}")
    print(f"WABA ID:          {settings.META_WABA_ID or '(not set)'}")
    if pin:
        print("PIN:              ******")

    print("Registering with Meta...")
    try:
        with MetaWhatsAppClient(settings) as client:
            result = client.register_phone_number(pin=pin or None)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if result.get("success"):
        print("SUCCESS — phone number registered.")
    else:
        print(f"Meta response (not success): {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
