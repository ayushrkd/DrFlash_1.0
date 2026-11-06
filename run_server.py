"""Dr. Flash — Server Runner.

Start the core API server on localhost only.
"""

import uvicorn
from services.config import settings


def main() -> None:
    uvicorn.run(
        "services.core_api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env == "development",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
