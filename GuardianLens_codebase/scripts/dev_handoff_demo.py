"""Developer helper: play the browser extension's part of the session handoff.

Why it exists: the handoff (extension session -> website cookie) is hard to see without the
extension and a real listing. This script does what the extension does against a running API:

  1. mints an anonymous session token (POST /api/v1/session),
  2. submits a stub assessment identified by that token in the X-Session-Token header,
  3. prints the URL the extension would open for "See full explanation".

Open the printed URL in a browser (website running on port 3000). The website asks you to confirm
linking the browser to the session; after you accept, the explanation page should load with no
login, and "#st=..." should disappear from the address bar.

Usage, with the API running on port 8000:
    python scripts/dev_handoff_demo.py [--api http://localhost:8000] [--site http://localhost:3000]
"""

from __future__ import annotations

import argparse
import io

import httpx2
from PIL import Image


def make_photo() -> bytes:
    """A small valid JPEG, so the upload passes the API's image validation."""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 210, 220)).save(buffer, format="JPEG")
    return buffer.getvalue()


def main() -> int:
    """Creates the session and the stub assessment, then prints the website handoff URL."""
    parser = argparse.ArgumentParser(
        description="Print a website handoff URL for a stub assessment."
    )
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--site", default="http://localhost:3000", help="website base URL")
    args = parser.parse_args()

    with httpx2.Client(base_url=args.api, timeout=30) as client:
        # Step 1: the extension's first call, creating an anonymous session.
        token = client.post("/api/v1/session").raise_for_status().json()["session_token"]
        # Step 2: a submission owned by that token (no cookie involved).
        response = client.post(
            "/api/v1/assess",
            headers={"X-Session-Token": token},
            data={
                "platform": "carousell",
                "title": "Demo laptop",
                "description": "Demo listing created by scripts/dev_handoff_demo.py.",
                "price": "RM 1,250",
                "category": "Laptops",
                "source": "extension",
            },
            files=[("images", ("photo.jpg", make_photo(), "image/jpeg"))],
        )
        response.raise_for_status()
        assessment_id = response.json()["assessment_id"]

    # Step 3: the URL the extension opens. The token is in the fragment, so it never reaches a
    # server log.
    print(f"{args.site.rstrip('/')}/assess/{assessment_id}/explanation#st={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
