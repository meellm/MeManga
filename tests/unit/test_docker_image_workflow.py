"""Static checks for the Docker image workflow smoke gate.

The built image must be loaded and run before any multi-platform
build or publish step, for both tag pushes and manual dispatches.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker-image.yml"

SMOKE_TAG = "memanga:smoke"


def _steps():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]["build"]["steps"]


def _index(predicate):
    for i, step in enumerate(_steps()):
        if predicate(step):
            return i
    return -1


def _is_smoke_build(step):
    with_ = step.get("with") or {}
    return (
        str(step.get("uses", "")).startswith("docker/build-push-action@")
        and with_.get("tags") == SMOKE_TAG
    )


def _is_smoke_run(step):
    return "docker run --rm memanga:smoke --help" in str(step.get("run", ""))


def _publish_build_indices():
    return [
        i
        for i, step in enumerate(_steps())
        if str(step.get("uses", "")).startswith("docker/build-push-action@")
        and (step.get("with") or {}).get("tags") != SMOKE_TAG
    ]


def test_smoke_build_loads_single_amd64_image():
    step = _steps()[_index(_is_smoke_build)]
    with_ = step["with"]
    assert with_["context"] == "."
    assert with_["platforms"] == "linux/amd64"
    assert with_["load"] is True
    assert with_["push"] is False
    assert "if" not in step


def test_smoke_run_follows_smoke_build_unconditionally():
    build = _index(_is_smoke_build)
    run = _index(_is_smoke_run)
    assert build != -1 and run != -1
    assert build < run
    assert "if" not in _steps()[run]


def test_smoke_gate_precedes_every_publish_build():
    run = _index(_is_smoke_run)
    publish = _publish_build_indices()
    assert len(publish) == 2
    assert all(run < i for i in publish)


def test_publish_steps_keep_multi_platform_targets():
    steps = _steps()
    platforms = [steps[i]["with"]["platforms"] for i in _publish_build_indices()]
    assert "${{ inputs.platforms }}" in platforms
    assert "${{ inputs.platforms || 'linux/amd64,linux/arm64' }}" in platforms
