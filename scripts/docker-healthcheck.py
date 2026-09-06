"""Docker health check script for the FastAPI container.

Called by Docker's HEALTHCHECK instruction. Exits with:
    0 = healthy (HTTP 200 from /health)
    1 = unhealthy (connection refused, timeout, non-200 status)

Why a Python script instead of curl?
    - Python is already installed in the container
    - No need to install curl in the final image
    - More control over timeout and error handling
"""

import sys
import urllib.error
import urllib.request


def main() -> int:
    try:
        req = urllib.request.Request("http://localhost:8000/health")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return 0
            return 1
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
