#!/usr/bin/env python3
import itertools
import os
import subprocess
from pathlib import Path

from draw_livetext_bbox import annotate as annotate_livetext
from draw_text_bbox import annotate_pdf_file

from ocrmypdf_appleocr.common import lang_code_to_locale, unsegmented_languages
from ocrmypdf_appleocr.livetext import livetext_supported

basedir = Path(__file__).resolve().parent
print(f"Basedir: {basedir}")
tests = list((basedir / "examples").glob("*.pdf"))


def draw_livetext_boxes(test: Path, lang: str, output_pdf: str) -> None:
    """Overlay the raw LiveText recognition boxes on the *original* PDF.

    This bypasses ocrmypdf entirely, so the boxes show what the engine
    reported, independent of how the text layer was rendered.
    """
    # LiveText does not segment words for languages that aren't written with
    # spaces, so only ask for lines there (mirrors ocrmypdf_appleocr.perform_ocr).
    unit = "line" if lang in unsegmented_languages else "word"
    lines, words = annotate_livetext(
        test,
        Path(output_pdf),
        locales=[lang_code_to_locale.get(lang, lang)],
        unit=unit,
        draw_lines=True,
        draw_words=unit == "word",
        dpi=300.0,
        line_width=0.5,
        page_spec=None,
        save_images=None,
        verbose=False,
    )
    print(f"Drew {lines} line and {words} word box(es) on {output_pdf}")


if __name__ == "__main__":
    env = os.environ.copy()
    os.makedirs("./test_outputs", exist_ok=True)
    for f in Path("./test_outputs").glob("*.pdf"):
        f.unlink()
    for test in tests:
        test_name = test.stem
        lang = test_name.split("_")[0]
        if livetext_supported:
            draw_livetext_boxes(test, lang, f"./test_outputs/{test_name}_livetext_bbox.pdf")
        else:
            print("Skipping LiveText bbox overlay: requires macOS 13 (Ventura) or later.")
        arg_base = [
            "python3",
            "-m",
            "ocrmypdf",
            "--plugin",
            "ocrmypdf_appleocr",
            "--keep-temporary-files",
            "--optimize",
            "2",
            "-l",
            lang,
        ]
        for mode, renderer in itertools.product(
            ["accurate", "fast", "livetext"], ["sandwich", "fpdf2"]
        ):
            env["TMPDIR"] = "./tmp/" + f"{test_name}_{mode}_{renderer}"
            os.makedirs(env["TMPDIR"], exist_ok=True)
            if lang != "eng" and mode == "fast":
                # Skip unsupported combination
                continue
            output_pdf = f"./test_outputs/{test_name}_{mode}_{renderer}.pdf"
            args = arg_base + [
                "--appleocr-recognition-mode",
                mode,
                "--pdf-renderer",
                renderer,
                str(test),
                output_pdf,
            ]
            print(f"Running test: {' '.join(args)}")
            subprocess.run(args, check=True, env=env)
            # Lines in red, then the words within them in blue.
            line_count = annotate_pdf_file(output_pdf, level="line")
            word_count = annotate_pdf_file(output_pdf, level="word", box_color=(0.0, 0.0, 1.0))
            print(f"Drew {line_count} line and {word_count} word box(es) on {output_pdf}")
    print("All tests completed.")
