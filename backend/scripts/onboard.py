"""Backward-compat shim for the old ``./onboard`` entrypoint.

The actual logic now lives in ``app.setup_wizard``. This file exists so:
  * ``./onboard`` (the bash wrapper at ``services/coii/onboard``) keeps
    working without changes.
  * ``tests/test_onboard.py`` — which imports symbols from the ``onboard``
    module — keeps working.

New code should call ``coii setup --wizard`` instead, or import from
``app.setup_wizard`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `app.*` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.setup_wizard import (  # noqa: E402,F401
    ENV_KEYS,
    PROVIDER_CHOICES,
    ProviderChoice,
    _collect_non_interactive,
    apply_to_config,
    find_provider,
    generate_webhook_secret,
    main,
    merge_env,
    parse_env_file,
    render_env_file,
)


if __name__ == "__main__":
    sys.exit(main())
