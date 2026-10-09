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


# Issue #380: the image installs and the workflow verifies license notices.

DOCKERFILE = REPO_ROOT / "Dockerfile"
DOC_DIR = "/usr/share/doc/memanga"


def _is_notices_check(step):
    return "Verify third-party notices" in step.get("name", "")


def test_dockerfile_installs_notices_and_license():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY pyproject.toml README.md LICENSE ./" in text
    assert "COPY packaging/third_party_notices.py ./packaging/" in text
    assert "COPY packaging/licenses ./packaging/licenses" in text
    assert "packaging/third_party_notices.py generate" in text
    assert "--requirements requirements-docker.txt" in text
    # pip ships in the image but no requirement reaches it.
    assert "--package pip" in text
    assert "--require pip" in text
    assert '--browsers-dir "$PLAYWRIGHT_BROWSERS_PATH"' in text
    assert f"--output {DOC_DIR}/THIRD_PARTY_NOTICES.txt" in text
    assert "packaging/third_party_notices.py check" in text
    # The build fails unless Chromium and Firefox have complete entries.
    assert "--require-browser chromium --require-browser firefox" in text
    assert text.index("playwright install --with-deps firefox chromium") < text.index(
        "--require-browser chromium")
    assert f"install -m 0644 LICENSE {DOC_DIR}/LICENSE" in text
    # Generated as root, before the image drops to the runtime user.
    assert text.index("third_party_notices.py generate") < text.index("USER memanga")


def test_notices_check_runs_on_smoke_image_before_publish():
    idx = _index(_is_notices_check)
    assert idx != -1, "notices check missing from the Docker workflow"
    step = _steps()[idx]
    assert "if" not in step
    run = step["run"]
    assert "--entrypoint sh memanga:smoke" in run
    assert f"test -s {DOC_DIR}/THIRD_PARTY_NOTICES.txt" in run
    assert f"test -s {DOC_DIR}/LICENSE" in run
    assert "MeManga third-party notices" in run
    # The image keeps the notices tool in /app/packaging; rerun its gate,
    # including the Playwright browser entries, on the built image.
    words = " ".join(run.replace("\\\n", " ").split())
    assert (f"python packaging/third_party_notices.py check {DOC_DIR}/THIRD_PARTY_NOTICES.txt"
            " --require playwright --require pip"
            " --require-browser chromium --require-browser firefox") in words
    assert _index(_is_smoke_build) < idx
    assert all(idx < i for i in _publish_build_indices())
