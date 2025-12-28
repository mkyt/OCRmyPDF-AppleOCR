#!/usr/bin/env python3
import itertools
import os
import subprocess
from pathlib import Path

basedir = Path(__file__).resolve().parent
print(f"Basedir: {basedir}")
tests = list((basedir / "examples").glob("*.pdf"))

if __name__ == "__main__":
    env = os.environ.copy()
    os.makedirs("./test_outputs", exist_ok=True)
    for test in tests:
        test_name = test.stem
        lang = test_name.split("_")[0]
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
            ["accurate", "fast", "livetext"], ["sandwich", "hocr"]
        ):
            env["TMPDIR"] = "./tmp/" + f"{test_name}_{mode}_{renderer}"
            os.makedirs(env["TMPDIR"], exist_ok=True)
            if lang != "eng" and mode == "fast":
                # Skip unsupported combination
                continue
            args = arg_base + [
                "--appleocr-recognition-mode",
                mode,
                "--pdf-renderer",
                renderer,
                str(test),
                f"./test_outputs/{test_name}_{mode}_{renderer}.pdf",
            ]
            print(f"Running test: {' '.join(args)}")
            subprocess.run(args, check=True, env=env)
    print("All tests completed.")
