"""Private JSON protocol worker for native JSX analysis."""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

from ._isolation import _analysis_to_data
from .extractor import extract_file
from .models import ScannedFile
from .parser import parse_file


def _analyze_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("protocol_version") != 1 or not isinstance(request.get("files"), list):
        raise ValueError("Invalid worker request.")
    analyses = []
    for item in request["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Invalid worker source entry.")
        encoded_source = item.get("source_base64")
        if not isinstance(encoded_source, str):
            raise ValueError("Invalid worker source data.")
        source = base64.b64decode(encoded_source, validate=True)
        scanned_file = ScannedFile(path=item["path"], source=source)
        analyses.append(_analysis_to_data(extract_file(parse_file(scanned_file))))
    return {"protocol_version": 1, "analyses": analyses}


def main() -> int:
    try:
        request = json.load(sys.stdin)
        response = _analyze_request(request)
    except Exception as error:
        sys.stdout.write(
            json.dumps(
                {
                    "protocol_version": 1,
                    "error": type(error).__name__,
                },
                separators=(",", ":"),
            )
        )
        return 1
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
