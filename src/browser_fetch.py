from __future__ import annotations

import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

CHROME_INFO_PLIST = "/Applications/Google Chrome.app/Contents/Info.plist"
CHROME_EXECUTABLE = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _detect_chrome_major() -> int | None:
    if sys.platform != "darwin":
        return None
    version = ""
    try:
        with open(CHROME_INFO_PLIST, "rb") as file:
            version = str(plistlib.load(file).get("CFBundleShortVersionString", ""))
    except Exception:
        version = ""
    if not version and os.path.exists(CHROME_EXECUTABLE):
        try:
            completed = subprocess.run(
                [CHROME_EXECUTABLE, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                close_fds=False,
            )
            version = (completed.stdout or completed.stderr or "").strip()
        except Exception:
            version = ""
    match = re.search(r"(\d+)\.", version)
    return int(match.group(1)) if match else None


def _codesign_adhoc(path: str) -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return
    codesign = "/usr/bin/codesign"
    if not os.path.exists(codesign) or not os.path.exists(path):
        return
    try:
        subprocess.run(
            [codesign, "--force", "--sign", "-", path],
            check=False,
            timeout=30,
            close_fds=False,
            capture_output=True,
        )
    except Exception:
        pass


def _prepare_chromedriver() -> None:
    if platform.machine() != "arm64":
        return
    try:
        from undetected_chromedriver import Patcher
    except Exception:
        return
    if getattr(Patcher, "_arm64_patched", False):
        return

    original_set_platform = Patcher._set_platform_name
    original_patch_exe = Patcher.patch_exe

    def _set_platform_name(self) -> None:
        original_set_platform(self)
        if self.platform.endswith("darwin") and not self.is_old_chromedriver:
            self.platform_name = "mac-arm64"

    def patch_exe(self):
        result = original_patch_exe(self)
        # Patching the binary in place invalidates its code signature; arm64 macOS
        # then kills the unsigned driver (SIGKILL, status -9) on launch.
        _codesign_adhoc(self.executable_path)
        return result

    Patcher._set_platform_name = _set_platform_name
    Patcher.patch_exe = patch_exe
    Patcher._arm64_patched = True


def _remove_profile_dir(path: str) -> None:
    if not path:
        return
    for _ in range(10):
        if not os.path.exists(path):
            return
        try:
            shutil.rmtree(path)
            return
        except Exception:
            time.sleep(0.3)


def _kill_orphan_chrome(user_data_dir: str) -> None:
    if not user_data_dir:
        return
    pkill = "/usr/bin/pkill"
    if not os.path.exists(pkill):
        return
    try:
        subprocess.run(
            [pkill, "-f", user_data_dir],
            check=False,
            timeout=10,
            close_fds=False,
        )
    except Exception:
        pass


def _worker(url: str, output_path: str, headless: bool, timeout_seconds: int) -> None:
    import traceback

    error_path = output_path + ".err"
    error_text = ""

    _prepare_chromedriver()
    version_main = _detect_chrome_major()

    import undetected_chromedriver as uc

    timeout_seconds = max(timeout_seconds, 1)
    options = uc.ChromeOptions()
    options.add_argument("--no-first-run")
    options.add_argument("--disable-extensions")
    user_data_dir = tempfile.mkdtemp(prefix="aoty-browser-")
    driver = None
    html = ""
    try:
        driver = uc.Chrome(
            options=options,
            headless=headless,
            use_subprocess=False,
            user_data_dir=user_data_dir,
            version_main=version_main,
        )
        try:
            driver.set_page_load_timeout(timeout_seconds)
        except Exception:
            pass
        try:
            driver.get(url)
        except Exception:
            pass

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            time.sleep(1.0)
            try:
                html = driver.page_source or ""
            except Exception:
                html = ""
            if "albumblock" in html.lower():
                break
    except Exception:
        error_text = traceback.format_exc()
    finally:
        try:
            with open(output_path, "w", encoding="utf-8") as file:
                file.write(html)
        except Exception:
            pass
        if error_text:
            try:
                with open(error_path, "w", encoding="utf-8") as file:
                    file.write(error_text)
            except Exception:
                pass
            try:
                sys.stderr.write(error_text)
                sys.stderr.flush()
            except Exception:
                pass
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass
        _kill_orphan_chrome(user_data_dir)
        _remove_profile_dir(user_data_dir)
        # Skip interpreter finalization; undetected-chromedriver segfaults during
        # shutdown on macOS and would otherwise crash this worker process.
        os._exit(0)


def fetch_with_browser(url: str, *, headless: bool, timeout_seconds: int) -> str:
    timeout_seconds = max(timeout_seconds, 1)
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = os.path.join(temp_dir, "page.html")
        error_path = output_path + ".err"
        command = [
            sys.executable,
            "-m",
            "src.browser_fetch",
            url,
            output_path,
            "1" if headless else "0",
            str(timeout_seconds),
        ]
        try:
            completed = subprocess.run(
                command,
                timeout=timeout_seconds + 30,
                check=False,
                close_fds=False,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            print(f"[browser_fetch] subprocess failed: {exc!r}", file=sys.stderr)
            return ""
        if completed.returncode != 0:
            tail = (completed.stderr or "").strip()[-800:]
            print(
                f"[browser_fetch] worker exited with {completed.returncode}: {tail}",
                file=sys.stderr,
            )
        if os.path.exists(error_path):
            try:
                with open(error_path, "r", encoding="utf-8") as file:
                    tail = file.read().strip()[-2000:]
                if tail:
                    print(f"[browser_fetch] worker error:\n{tail}", file=sys.stderr)
            except Exception:
                pass
        if not os.path.exists(output_path):
            return ""
        try:
            with open(output_path, "r", encoding="utf-8") as file:
                return file.read()
        except Exception:
            return ""


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2], sys.argv[3] == "1", int(sys.argv[4]))
