# reset_dev_data.py
# DEVELOPMENT TOOL ONLY -- never shipped in the zip sent to colleagues.
# Resets this folder back to a clean "nothing has been tagged yet" state.
#
# Normally run it by double-clicking reset.bat in the same folder.
# From a terminal:
#     python reset_dev_data.py          ask for confirmation first
#     python reset_dev_data.py --yes    delete without asking
#
# This file is in English because only the developer ever runs it. Everything
# a site worker or a colleague sees -- the Streamlit UI, control_panel.py,
# 安裝.bat, 說明.txt, the README files and the generated Word report -- stays
# in Chinese and must not be translated.
#
# Why the delete logic lives here in Python instead of directly in reset.bat:
# under chcp 65001, cmd.exe tracks how far it has read using BYTE offsets while
# counting CHARACTERS. Put much non-ASCII text in a .bat file and it eventually
# reads from the wrong position, then parses and EXECUTES its own text as
# commands. That is not theoretical -- an earlier version of reset.bat had a
# "copy ... config.json" line sitting inside an echo as help text, the parser
# desynced, and it overwrote the live config.json. So reset.bat stays a tiny
# pure-ASCII launcher and all real logic lives here, where UTF-8 just works.

import shutil
import socket
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# The two Streamlit servers, by port.
PORTS = {8501: "office version (app.py)", 8502: "mobile version (mobile_app.py)"}

# Delete ONLY these. An explicit allowlist, never "scan the folder and remove
# anything unrecognised" -- that guarantees the source files, config.json and
# format.docx can never be caught up in a reset.
DIRS_TO_CLEAR = ["incoming", "staging", "sorted", "ignored", "output"]
FILES_TO_DELETE = ["manifest.csv", "session_pending.csv"]
CACHE_DIRS = ["__pycache__"]

# Refuse to run unless this really is the project folder, so a stray copy of
# this script somewhere else can never wipe an unrelated directory.
PROJECT_MARKERS = ["app.py", "utils.py", "generate_report.py"]


def find_running_servers():
    """Return the servers currently still running, identified by open port."""
    running = []
    for port, name in PORTS.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                running.append(f"{name} on port {port}")
    return running


def count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.rglob("*") if p.is_file())


def main():
    assume_yes = "--yes" in sys.argv or "/Y" in sys.argv or "-y" in sys.argv

    missing = [m for m in PROJECT_MARKERS if not (BASE_DIR / m).exists()]
    if missing:
        print(f"[STOP] This does not look like the project folder (missing {', '.join(missing)}).")
        print(f"       Location: {BASE_DIR}")
        return 1

    # Deleting while a server runs goes wrong: Streamlit re-executes the whole
    # script on every interaction, so it can recreate folders mid-delete or keep
    # using files that have already been removed.
    running = find_running_servers()
    if running:
        print(f"[STOP] A server is still running: {', '.join(running)}")
        print()
        print("Stop it first, then run this again.")
        print("Open the control panel and press the two stop buttons, or close")
        print("the running server windows.")
        return 1

    print("=" * 60)
    print("  Reset development test data")
    print("=" * 60)
    print()
    print("This returns the folder to a clean 'nothing tagged yet' state.")
    print()
    print("Will be cleared:")
    for d in DIRS_TO_CLEAR:
        print(f"    {d}\\  -  {count_files(BASE_DIR / d)} file(s)")
    for f in FILES_TO_DELETE:
        suffix = "" if (BASE_DIR / f).exists() else "  (not present, skipped)"
        print(f"    {f}{suffix}")
    print()
    print("Will NOT be touched: all .py source, config.json, format.docx,")
    print("                     requirements.txt, packaging\\, distribute\\.")
    print()

    if not assume_yes:
        try:
            answer = input("Delete these? They cannot be recovered afterwards (Y/N): ").strip()
        except EOFError:
            answer = ""
        if answer.lower() != "y":
            print()
            print("Cancelled. Nothing was deleted.")
            return 0

    print()
    print("Clearing...")

    # manifest.csv and sorted\ must go together: delete only one and you get
    # either "photo not found" gaps in the report, or orphan image files that
    # never appear anywhere. session_pending.csv and staging\ are a pair for the
    # same reason -- delete only one and those rows fail forever on "finish this
    # session" and stay stuck in the pending list.
    errors = []
    for name in FILES_TO_DELETE:
        try:
            (BASE_DIR / name).unlink(missing_ok=True)
        except OSError as e:
            errors.append(f"{name}: {e}")

    for name in DIRS_TO_CLEAR + CACHE_DIRS:
        target = BASE_DIR / name
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:
                errors.append(f"{name}\\: {e}")

    # Clean up stray temp/lock files left behind if a program was force-killed.
    for pattern in ("*.tmp", "*.lock"):
        for leftover in BASE_DIR.glob(pattern):
            try:
                leftover.unlink()
            except OSError as e:
                errors.append(f"{leftover.name}: {e}")

    # Recreate the folders empty. utils.ensure_dirs would do this on the next
    # launch anyway; doing it now just makes the folder look normal right away.
    for name in DIRS_TO_CLEAR:
        (BASE_DIR / name).mkdir(parents=True, exist_ok=True)

    print()
    if errors:
        print("=" * 60)
        print("  Some items could not be removed")
        print("=" * 60)
        print()
        for e in errors:
            print(f"    {e}")
        print()
        print("Usually this means a file is open in another program (Explorer,")
        print("antivirus). Close it and run this again.")
        return 1

    print("=" * 60)
    print("  Reset complete")
    print("=" * 60)
    print()
    print("The folder is now in a clean state, ready for testing again.")
    print()
    print("Note: config.json was not touched -- the project name and contractor")
    print("      settings are still there. To also clear categories added during")
    print("      testing, overwrite config.json by hand with the template in the")
    print("      packaging folder, then re-enter those two settings.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
