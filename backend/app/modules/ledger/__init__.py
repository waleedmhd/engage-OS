"""ledger — double-entry engine, COA, periods, journals, PostingService (bridge core).

Bridge handlers are registered when this module is imported, typically via
import_all_models() during app startup.
"""

from app.modules.ledger.bridge import register_bridge_handlers

register_bridge_handlers()
