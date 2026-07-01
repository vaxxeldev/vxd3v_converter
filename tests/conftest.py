from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def lottie_payload() -> dict[str, Any]:
    return {
        "v": "5.7.4",
        "fr": 60,
        "ip": 0,
        "op": 180,
        "w": 512,
        "h": 512,
        "nm": "moving circle",
        "ddd": 0,
        "assets": [],
        "layers": [
            {
                "ddd": 0,
                "ind": 1,
                "ty": 4,
                "nm": "circle",
                "sr": 1,
                "ks": {
                    "o": {"a": 0, "k": 100},
                    "r": {"a": 0, "k": 0},
                    "p": {
                        "a": 1,
                        "k": [
                            {
                                "t": 0,
                                "s": [128, 256, 0],
                                "h": 0,
                                "o": {"x": [0.333], "y": [0]},
                                "i": {"x": [0.667], "y": [1]},
                            },
                            {"t": 179, "s": [384, 256, 0]},
                        ],
                    },
                    "a": {"a": 0, "k": [0, 0, 0]},
                    "s": {"a": 0, "k": [100, 100, 100]},
                },
                "ao": 0,
                "shapes": [
                    {
                        "ty": "gr",
                        "nm": "Ellipse Group",
                        "it": [
                            {
                                "d": 1,
                                "ty": "el",
                                "p": {"a": 0, "k": [0, 0]},
                                "s": {"a": 0, "k": [160, 160]},
                                "nm": "Ellipse",
                            },
                            {
                                "ty": "fl",
                                "c": {"a": 0, "k": [1, 1, 1, 1]},
                                "o": {"a": 0, "k": 100},
                                "r": 1,
                                "nm": "Fill",
                            },
                            {
                                "ty": "tr",
                                "p": {"a": 0, "k": [0, 0]},
                                "a": {"a": 0, "k": [0, 0]},
                                "s": {"a": 0, "k": [100, 100]},
                                "r": {"a": 0, "k": 0},
                                "o": {"a": 0, "k": 100},
                                "sk": {"a": 0, "k": 0},
                                "sa": {"a": 0, "k": 0},
                                "nm": "Transform",
                            },
                        ],
                    },
                ],
                "ip": 0,
                "op": 180,
                "st": 0,
                "bm": 0,
            }
        ],
    }


@pytest.fixture
def tgs_file(tmp_path: Path, lottie_payload: dict[str, Any]) -> Path:
    path = tmp_path / "sticker.tgs"
    with gzip.open(path, "wb") as compressed:
        compressed.write(json.dumps(lottie_payload, separators=(",", ":")).encode())
    return path
