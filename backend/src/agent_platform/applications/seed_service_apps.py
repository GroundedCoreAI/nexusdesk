"""Deprecated alias for the demo pack seed.

``consumer-service`` is retired; this command now installs and promotes the four
demo industry packs so existing entry points keep working:

    python -m agent_platform.applications.seed_demo_packs
"""

import asyncio

from .seed_demo_packs import main

if __name__ == "__main__":
    asyncio.run(main())
