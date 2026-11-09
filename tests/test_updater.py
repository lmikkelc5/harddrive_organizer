"""The app shell's remote code updates (app_shell/). No network: releases are local files."""

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import zipfile

import pytest

from app_shell import SHELL_API, launch, updater

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_spec = importlib.util.spec_from_file_location("make_code_zip", os.path.join(ROOT, "packaging", "make_code_zip.py"))
make_code_zip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_code_zip)

import photo_organizer

BUNDLED = updater.parse_version(photo_organizer.__version__)


@pytest.fixture(autouse=True)
def restore_imports():
    """Loading downloaded code swaps photo_organizer modules; put the originals back."""
    saved_meta = list(sys.meta_path)
    saved_mods = {k: v for k, v in sys.modules.items() if k == "photo_organizer" or k.startswith("photo_organizer.")}
    yield
    sys.meta_path[:] = saved_meta
    for k in [k for k in sys.modules if k == "photo_organizer" or k.startswith("photo_organizer.")]:
        del sys.modules[k]
    sys.modules.update(saved_mods)


def release(tmp_path, version, broken=False, tamper=False, requires_shell=None):
    """Build a local release; return (source url, fake fetch)."""
    out = tmp_path / f"rel-{version}"
    zpath = make_code_zip.build(str(out), version, broken)
    if requires_shell is not None:
        # rewrite update.json with a different requires_shell
        with zipfile.ZipFile(zpath) as z:
            files = {n: z.read(n) for n in z.namelist()}
        files["update.json"] = json.dumps({"version": version, "requires_shell": requires_shell}).encode()
        with zipfile.ZipFile(zpath, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
        with open(zpath, "rb") as f:
            open(zpath + ".sha256", "w").write(hashlib.sha256(f.read()).hexdigest() + "\n")
    if tamper:
        with open(zpath + ".sha256", "w") as f:
            f.write("0" * 64 + "\n")
    src = make_code_zip.write_local_release(str(out), "v" + version)
    files = {
        "LATEST": open(src, "rb").read(),
    }
    data = json.loads(files["LATEST"])
    for a in data["assets"]:
        local = os.path.join(str(out), a["name"])
        files[a["browser_download_url"]] = open(local, "rb").read()

    calls = []

    def fetch(url, timeout):
        calls.append(url)
        key = "LATEST" if url == "LATEST" else url
        if key not in files:
            raise updater.UpdateError(f"no such url {url}")
        return files[key]

    fetch.calls = calls
    return src, fetch


def bump(n=1):
    major, minor, patch = BUNDLED
    return f"{major}.{minor}.{patch + n}"


def test_parse_version():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.10.0") > updater.parse_version("1.9.9")
    assert updater.parse_version("v1.2") is None
    assert updater.parse_version("latest") is None


def test_newer_release_is_installed_and_runs(tmp_path):
    v = bump()
    _, fetch = release(tmp_path, v)
    home = str(tmp_path / "home")
    main, version, source = launch.load_main(home, fetch=lambda u, t: fetch("LATEST" if "api.github.com" in u else u, t))
    assert (version, source) == (v, "update")
    assert sys.modules["photo_organizer"].__version__ == v
    assert sys.modules["photo_organizer"].__file__.startswith(os.path.join(home, "code"))
    assert callable(main)


def test_downloaded_code_actually_sorts(tmp_path):
    """The updated code is a full working organizer, not just an importable package."""
    from conftest import make_image

    v = bump()
    _, fetch = release(tmp_path, v)
    home = str(tmp_path / "home")
    main, version, _ = launch.load_main(home, fetch=lambda u, t: fetch("LATEST" if "api.github.com" in u else u, t))
    drive = tmp_path / "drive"
    make_image(str(drive / "Put new photos here" / "a.jpg"), "2024:07:14 15:30:22")
    assert main(["--drive", str(drive)]) == 0
    assert (drive / "My photos" / "By date" / "2024" / "2024-07-14_15-30-22.jpg").exists()


def _latest(fetch):
    return lambda u, t: fetch("LATEST" if "api.github.com" in u else u, t)


def test_same_or_older_release_does_nothing(tmp_path):
    _, fetch = release(tmp_path, ".".join(map(str, BUNDLED)))
    home = str(tmp_path / "home")
    _, version, source = launch.load_main(home, fetch=_latest(fetch))
    assert source == "built-in"
    assert len(fetch.calls) == 1  # only the release lookup, no download


def test_bad_checksum_is_rejected(tmp_path):
    _, fetch = release(tmp_path, bump(), tamper=True)
    home = str(tmp_path / "home")
    _, _, source = launch.load_main(home, fetch=_latest(fetch))
    assert source == "built-in"
    assert updater.installed_versions(home) == {}


def test_broken_update_falls_back_and_is_not_retried(tmp_path):
    v = bump()
    _, fetch = release(tmp_path, v, broken=True)
    home = str(tmp_path / "home")
    _, version, source = launch.load_main(home, fetch=_latest(fetch))
    assert source == "built-in"
    assert v in updater.State.load(home).bad
    assert sys.modules["photo_organizer"].__version__ == photo_organizer.__version__
    # Next launch: the bad version is skipped, not downloaded again.
    fetch.calls.clear()
    _, _, source = launch.load_main(home, fetch=_latest(fetch))
    assert source == "built-in" and len(fetch.calls) == 1


def test_fixed_release_after_a_bad_one_is_used(tmp_path):
    home = str(tmp_path / "home")
    _, broken = release(tmp_path, bump(1), broken=True)
    launch.load_main(home, fetch=_latest(broken))
    _, fixed = release(tmp_path, bump(2))
    _, version, source = launch.load_main(home, fetch=_latest(fixed))
    assert (version, source) == (bump(2), "update")


def test_needs_newer_shell_is_not_installed(tmp_path):
    _, fetch = release(tmp_path, bump(), requires_shell=SHELL_API + 1)
    home = str(tmp_path / "home")
    _, _, source = launch.load_main(home, fetch=_latest(fetch))
    assert source == "built-in"
    assert updater.installed_versions(home) == {}


def test_offline_uses_what_it_has(tmp_path):
    home = str(tmp_path / "home")
    _, fetch = release(tmp_path, bump())
    launch.load_main(home, fetch=_latest(fetch))      # online once: installs

    def offline(url, timeout):
        raise updater.UpdateError("no internet")

    _, version, source = launch.load_main(home, fetch=offline)
    assert (version, source) == (bump(), "update")   # keeps using the downloaded code


def test_disable_switch(tmp_path, monkeypatch):
    monkeypatch.setenv(updater.ENV_DISABLE, "1")
    _, fetch = release(tmp_path, bump())
    _, _, source = launch.load_main(str(tmp_path / "home"), fetch=_latest(fetch))
    assert source == "built-in" and fetch.calls == []


def test_unsafe_zip_is_rejected(tmp_path):
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("update.json", json.dumps({"version": bump(), "requires_shell": 1}))
        z.writestr("photo_organizer/__init__.py", f'__version__ = "{bump()}"\n')
        z.writestr("../../escape.txt", "nope")
    data = zpath.read_bytes()
    with pytest.raises(updater.UpdateError):
        updater.install(str(tmp_path / "home"), "v" + bump(), data, hashlib.sha256(data).hexdigest())
    assert not (tmp_path / "escape.txt").exists()


def test_old_versions_are_cleaned_up(tmp_path):
    home = str(tmp_path / "home")
    for n in range(1, 6):
        _, fetch = release(tmp_path, bump(n))
        updater.check_for_update(BUNDLED, home, fetch=_latest(fetch))
    assert sorted(updater.installed_versions(home)) == [updater.parse_version(bump(n)) for n in (3, 4, 5)]


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl not installed")
def test_real_curl_with_local_release(tmp_path):
    """The real download path (system curl), against a release made of local files."""
    v = bump()
    src, _ = release(tmp_path, v)
    home = str(tmp_path / "home")
    updater.check_for_update(BUNDLED, home, source="file:///" + src.replace(os.sep, "/").lstrip("/"))
    assert updater.parse_version(v) in updater.installed_versions(home)


def test_broken_newest_falls_back_to_previous_good_download(tmp_path):
    home = str(tmp_path / "home")
    _, good = release(tmp_path, bump(1))
    launch.load_main(home, fetch=_latest(good))
    _, broken = release(tmp_path, bump(2), broken=True)
    _, version, source = launch.load_main(home, fetch=_latest(broken))
    assert (version, source) == (bump(1), "update")
    assert bump(2) in updater.State.load(home).bad


def test_shell_never_crashes_if_code_cant_load(tmp_path, monkeypatch):
    def broken(home=None, **kw):
        raise ImportError("built-in code missing")

    shown = []
    monkeypatch.setattr(launch, "load_main", broken)
    # Record the dialog instead of showing it: on a Mac it would wait for a click forever.
    monkeypatch.setattr(launch, "_show_crash", lambda: shown.append(True))
    monkeypatch.setenv(updater.ENV_HOME, str(tmp_path / "home"))
    assert launch.main() == 1
    assert shown == [True]
    assert "none of your photos were lost" in launch._CRASH_MESSAGE
