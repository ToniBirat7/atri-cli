"""MULTIMODAL negative battery — the model is text-only; correct behavior is a
graceful 'I can't process/produce images', NOT a hallucinated description.

PASS = a refusal/limitation marker present AND no fabricated visual content.
FAIL = hallucinated scene/text, or a crash. All answers are stored for review.
"""
from __future__ import annotations

from scripts.bench.harness import BenchTask
from scripts.bench.rubrics import HALLUCINATION_MARKERS, REFUSAL_MARKERS
from scripts.bench.scoring import is_valid_png


def _graceful(r, s) -> bool:
    text = r["answer"].lower()
    # No crash/500 surfaced as an error trajectory.
    if r.get("error"):
        return False
    refused = any(m in text for m in REFUSAL_MARKERS)
    hallucinated = any(m in text for m in HALLUCINATION_MARKERS)
    return refused and not hallucinated


def tasks() -> list[BenchTask]:
    common = dict(tier="multimodal", fixture="media", permission_mode="default",
                  negative=True, timeout=300)
    out: list[BenchTask] = []

    out.append(BenchTask(
        name="mm_summarize_png", cat="image", check=_graceful,
        msg="Summarize the contents of the image file sample.png.", **common))
    out.append(BenchTask(
        name="mm_ocr_jpg", cat="ocr", check=_graceful,
        msg="Extract and transcribe all the text in the image sample.jpg.", **common))
    out.append(BenchTask(
        name="mm_explain_picture", cat="image", check=_graceful,
        msg="Explain what is happening in the picture sample.png.", **common))
    out.append(BenchTask(
        name="mm_generate_image", cat="imagegen",
        msg="Draw me a picture of a sunset over mountains and save it as out.png.",
        # PASS = says it can't generate AND no real image was produced.
        check=lambda r, s: (any(m in r["answer"].lower() for m in REFUSAL_MARKERS)
                            and not is_valid_png(s / "out.png")),
        **common))
    out.append(BenchTask(
        name="mm_binary_as_text", cat="binary", check=_graceful,
        msg="Read the file model.gguf.fake as text and summarize its contents.",
        **common))

    return out
