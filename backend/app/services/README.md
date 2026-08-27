# `app/services/`

This directory is **only** for services that span multiple modules and cannot
sensibly live in any one of them (e.g., a cross-domain orchestrator).

If a service belongs to a single domain, put it in that module's `service.py`.
Avoid creating `services/misc.py`. As the repository structure doc puts it:
"misc is where architecture goes to die."
