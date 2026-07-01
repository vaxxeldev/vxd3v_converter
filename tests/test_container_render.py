from __future__ import annotations

import gzip
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

IMAGE = "vxd3v-converter:local"
DOCKER = shutil.which("docker")


def _docker_available() -> bool:
    if DOCKER is None:
        return False
    result = subprocess.run(  # noqa: S603 - fixed Docker command for integration test
        [DOCKER, "image", "inspect", IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="local production image is not built")
def test_container_renders_smooth_reference_contract(
    tmp_path: Path,
    lottie_payload: dict[str, Any],
) -> None:
    source = tmp_path / "sticker.tgs"
    with gzip.open(source, "wb") as compressed:
        compressed.write(json.dumps(lottie_payload, separators=(",", ":")).encode())
    mount = f"{tmp_path.resolve()}:/work"

    assert DOCKER is not None
    subprocess.run(  # noqa: S603 - arguments are fixed except pytest's temp directory
        [
            DOCKER,
            "run",
            "--rm",
            "-v",
            mount,
            IMAGE,
            "vxd3v-render",
            "/work/sticker.tgs",
            "/work/result.mp4",
            "--format",
            "file",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    probe = subprocess.run(  # noqa: S603 - arguments are fixed except pytest's temp directory
        [
            DOCKER,
            "run",
            "--rm",
            "-v",
            mount,
            IMAGE,
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,profile,width,height,pix_fmt,avg_frame_rate,nb_read_frames,"
            "color_range,color_space,color_transfer,color_primaries:format=duration",
            "-of",
            "json",
            "/work/result.mp4",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(probe.stdout)
    stream = payload["streams"][0]

    assert stream["codec_name"] == "h264"
    assert stream["profile"] == "High"
    assert (stream["width"], stream["height"]) == (1920, 530)
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["avg_frame_rate"] == "60/1"
    assert stream["nb_read_frames"] == "180"
    assert stream["color_range"] == "tv"
    assert stream["color_space"] == "bt709"
    assert stream["color_transfer"] == "bt709"
    assert stream["color_primaries"] == "bt709"
    assert float(payload["format"]["duration"]) == pytest.approx(3.0, abs=0.01)
    assert (tmp_path / "result.mp4").stat().st_size > 10_000

    frame_hashes = subprocess.run(  # noqa: S603 - fixed integration-test command
        [
            DOCKER,
            "run",
            "--rm",
            "-v",
            mount,
            IMAGE,
            "ffmpeg",
            "-v",
            "error",
            "-i",
            "/work/result.mp4",
            "-f",
            "framemd5",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    unique_hashes = {
        line.rsplit(",", 1)[-1].strip()
        for line in frame_hashes.stdout.splitlines()
        if line and not line.startswith("#")
    }
    assert len(unique_hashes) >= 170
