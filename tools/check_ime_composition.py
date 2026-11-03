"""Observe foreground edit composition using a specified package's native binary."""
import argparse
import hashlib
import importlib.util
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--hwnd", type=lambda value: int(value, 0),
                        help="query this window instead of following OS focus (decimal or 0x hex)")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    if args.hwnd is not None and args.hwnd < 1:
        parser.error("--hwnd must be positive")
    binary = args.package.resolve() / "lib/pyautocore.pyd"
    spec = importlib.util.spec_from_file_location("pyautocore", binary)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(f"Native binary: {module.__file__}", flush=True)
    print(f"Native SHA256: {hashlib.sha256(binary.read_bytes()).hexdigest()}", flush=True)
    print("Focus a foreign editor; compose, convert, commit, then cancel. Ctrl+C stops.", flush=True)
    previous = None
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        target = None
        try:
            target = (module.Window.fromHWND(args.hwnd) if args.hwnd is not None
                      else module.Window.getFocus())
            state = "No focus" if target is None else target.isImeConverting(500)
            label = "Unsupported" if state is None else str(state)
        except (OSError, ValueError) as error:
            label = f"{type(error).__name__}: {error}"
        details = ""
        if target is not None:
            try:
                details = f"process={target.getProcessName()} class={target.getClassName()}"
            except OSError as error:
                details = f"target metadata unavailable: {error}"
        current = (target.getHWND() if target is not None else 0, label, details)
        if current != previous:
            print(f"HWND={current[0]:#x}: {label} {details}".rstrip(), flush=True)
            previous = current
        time.sleep(0.25)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
