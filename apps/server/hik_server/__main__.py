import os
import sys
from pathlib import Path

import uvicorn

from .config import load_config_from_environment


def main() -> None:
    config = load_config_from_environment()
    # --reload is for development (npm run dev); production runs a single process.
    reload = "--reload" in sys.argv[1:]
    uvicorn.run(
        "hik_server.app:create_app_from_environment",
        factory=True,
        reload=reload,
        reload_dirs=[str(Path(__file__).parent)] if reload else None,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=config.env.PORT,
        # Keep the real peer address: TRUST_LOCAL_NETWORK must not trust a spoofed X-Forwarded-For.
        proxy_headers=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
