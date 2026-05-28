#!/usr/bin/env python3
"""
Minecraft 1.12.2 Forge modpack helper launcher.

This tool installs Forge 1.12.2, creates a separate game directory for the
requested modpack, downloads mods from Modrinth when a public API download is
available, and opens the official Minecraft Launcher.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import html
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable


MINECRAFT_VERSION = "1.12.2"
FORGE_VERSION = os.environ.get("MC1122_FORGE_VERSION", "14.23.5.2859")
FORGE_ID = f"{MINECRAFT_VERSION}-forge-{FORGE_VERSION}"
PROFILE_ID = "mc1122_jp_modpack"
PROFILE_NAME = "MC 1.12.2 JP Modpack"
APP_TITLE = "MC 1.12.2 Forge MOD Launcher"
USER_AGENT = "mc1122-jp-mod-launcher/1.0 (personal modpack helper)"
MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"
CURSEFORGE_LEGACY_API = "https://addons-ecs.forgesvc.net/api/v2"
CURSEFORGE_MIRROR = "https://files.xmdhs.com/curseforge"
CURSEFORGE_GAME_ID = 432
CURSEFORGE_MODS_SECTION_ID = 6
CURSEFORGE_FORGE_LOADER = 1
FORGE_INSTALLER_URL = (
    "https://maven.minecraftforge.net/net/minecraftforge/forge/"
    f"{MINECRAFT_VERSION}-{FORGE_VERSION}/"
    f"forge-{MINECRAFT_VERSION}-{FORGE_VERSION}-installer.jar"
)
FORGE_SERVER_JAR = f"forge-{MINECRAFT_VERSION}-{FORGE_VERSION}.jar"

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "mods_manifest.json"
PLATFORM_KEY = {
    "Windows": "windows",
    "Darwin": "macos",
    "Linux": "linux",
}.get(platform.system(), platform.system().lower() or "unknown")
SETTINGS_PATH = ROOT / f"launcher_settings.{PLATFORM_KEY}.json"
LEGACY_SETTINGS_PATH = ROOT / "launcher_settings.json"
VENDOR_MODS_DIR = ROOT / "vendor" / "mods"
VENDOR_CONFIG_DIR = ROOT / "vendor" / "config"
MOD_FILE_EXTENSIONS = {".jar", ".zip", ".litemod"}
CONFIG_DOC_FILENAMES = {"README.md", "README.txt", ".gitkeep"}


class LauncherError(RuntimeError):
    pass


def log_console(message: str) -> None:
    print(message, flush=True)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_minecraft_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / ".minecraft"
        return Path.home() / "AppData" / "Roaming" / ".minecraft"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "minecraft"
    return Path.home() / ".minecraft"


def default_instance_dir() -> Path:
    return Path.home() / "MinecraftInstances" / "MC1122-JP-Modpack"


def default_server_dir(instance_dir: Path | None = None) -> Path:
    base = instance_dir or default_instance_dir()
    return base.with_name(f"{base.name}-Server")


def default_java_cmd() -> str:
    system = platform.system()
    executable = "java.exe" if platform.system() == "Windows" else "java"
    java_home = os.environ.get("JAVA_HOME")
    candidates: list[Path] = []
    if java_home:
        candidates.append(Path(java_home) / "bin" / executable)

    minecraft_dir = default_minecraft_dir()
    if system == "Windows":
        candidates.append(minecraft_dir / "runtime" / "jre-legacy" / "windows-x64" / "jre-legacy" / "bin" / "java.exe")
        candidates.append(minecraft_dir / "runtime" / "java-runtime-legacy" / "windows-x64" / "java-runtime-legacy" / "bin" / "java.exe")
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_name)
            if not root:
                continue
            root_path = Path(root)
            candidates.extend(sorted((root_path / "Java").glob("jre1.8*/bin/java.exe"), key=lambda path: str(path), reverse=True))
            candidates.extend(sorted((root_path / "Java").glob("jdk1.8*/bin/java.exe"), key=lambda path: str(path), reverse=True))
            candidates.append(root_path / "Minecraft Launcher" / "runtime" / "jre-x64" / "bin" / "java.exe")
            candidates.append(
                root_path
                / "Minecraft Launcher"
                / "runtime"
                / "java-runtime-alpha"
                / "windows-x64"
                / "java-runtime-alpha"
                / "bin"
                / "java.exe"
            )
    elif system == "Darwin":
        candidates.append(minecraft_dir / "runtime" / "jre-legacy" / "mac-os" / "jre-legacy" / "jre.bundle" / "Contents" / "Home" / "bin" / "java")
        candidates.append(minecraft_dir / "runtime" / "java-runtime-legacy" / "mac-os" / "java-runtime-legacy" / "jre.bundle" / "Contents" / "Home" / "bin" / "java")
    else:
        candidates.append(minecraft_dir / "runtime" / "jre-legacy" / "linux" / "jre-legacy" / "bin" / "java")
        candidates.append(minecraft_dir / "runtime" / "java-runtime-legacy" / "linux" / "java-runtime-legacy" / "bin" / "java")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return executable if system == "Windows" else "java"


def executable_arg(value: str) -> str:
    cleaned = (value or "").strip() or default_java_cmd()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1]
    return os.path.expandvars(os.path.expanduser(cleaned))


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise LauncherError(f"MODマニフェストが見つかりません: {MANIFEST_PATH}")
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def read_settings_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def load_settings() -> dict[str, Any]:
    if SETTINGS_PATH.exists():
        return read_settings_file(SETTINGS_PATH)
    if platform.system() != "Windows" and LEGACY_SETTINGS_PATH.exists():
        return read_settings_file(LEGACY_SETTINGS_PATH)
    return {}


def save_settings(settings: dict[str, Any]) -> None:
    with SETTINGS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def request_json(url: str, timeout: int = 45, headers: dict[str, str] | None = None) -> Any:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def request_text(url: str, timeout: int = 45, headers: dict[str, str] | None = None) -> str:
    req_headers = {"User-Agent": USER_AGENT, "Accept": "text/html, text/plain;q=0.9, */*;q=0.8"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def download_file(url: str, target: Path, log: Callable[[str], None], expected_sha1: str | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")

    if target.exists():
        if expected_sha1 and sha1_file(target) != expected_sha1.lower():
            log(f"既存ファイルのSHA1が違うため再取得します: {target.name}")
        else:
            log(f"既にあります: {target.name}")
            return target

    log(f"ダウンロード中: {target.name}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as response, tmp.open("wb") as fh:
        shutil.copyfileobj(response, fh)

    if expected_sha1:
        actual = sha1_file(tmp)
        if actual != expected_sha1.lower():
            tmp.unlink(missing_ok=True)
            raise LauncherError(f"SHA1が一致しません: {target.name} expected={expected_sha1} actual={actual}")

    tmp.replace(target)
    return target


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mods_dir(instance_dir: Path) -> Path:
    return instance_dir / "mods"


def config_dir(instance_dir: Path) -> Path:
    return instance_dir / "config"


def ensure_instance_dirs(instance_dir: Path) -> None:
    for child in ("mods", "config", "downloads", "logs", "saves", "resourcepacks"):
        (instance_dir / child).mkdir(parents=True, exist_ok=True)


def ensure_server_dirs(server_dir: Path) -> None:
    for child in ("mods", "config", "downloads", "logs", "world"):
        (server_dir / child).mkdir(parents=True, exist_ok=True)


def installed_forge(minecraft_dir: Path) -> bool:
    return (minecraft_dir / "versions" / FORGE_ID / f"{FORGE_ID}.json").exists()


def install_forge(minecraft_dir: Path, instance_dir: Path, java_cmd: str, log: Callable[[str], None] = log_console) -> None:
    minecraft_dir.mkdir(parents=True, exist_ok=True)
    ensure_instance_dirs(instance_dir)
    installer = instance_dir / "downloads" / f"forge-{FORGE_ID}-installer.jar"
    download_file(FORGE_INSTALLER_URL, installer, log)

    log("Forge installerを実行します。数分かかる場合があります。")
    java_executable = executable_arg(java_cmd)
    result = subprocess.run(
        [java_executable, "-jar", str(installer), "--installClient"],
        cwd=str(minecraft_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        log(result.stdout.strip())
    if result.returncode != 0:
        raise LauncherError(f"Forgeの導入に失敗しました。終了コード: {result.returncode}")
    if not installed_forge(minecraft_dir):
        raise LauncherError(f"Forge導入後のバージョンJSONが見つかりません: {FORGE_ID}")
    log(f"Forge導入済み: {FORGE_ID}")


def query_modrinth_versions(slug_or_id: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "loaders": json.dumps(["forge"]),
            "game_versions": json.dumps([MINECRAFT_VERSION]),
        }
    )
    return request_json(f"{MODRINTH_API}/project/{urllib.parse.quote(slug_or_id)}/version?{params}")


def query_modrinth_version(version_id: str) -> dict[str, Any]:
    return request_json(f"{MODRINTH_API}/version/{urllib.parse.quote(version_id)}")


def select_primary_file(version: dict[str, Any]) -> dict[str, Any]:
    files = version.get("files") or []
    jar_files = [item for item in files if str(item.get("filename", "")).lower().endswith(".jar")]
    if not jar_files:
        raise LauncherError(f"JARファイルが見つかりません: {version.get('name') or version.get('version_number')}")
    for item in jar_files:
        if item.get("primary"):
            return item
    return jar_files[0]


def curseforge_api_key() -> str:
    env_key = os.environ.get("CURSEFORGE_API_KEY", "").strip()
    if env_key:
        return env_key
    return str(load_settings().get("curseforge_api_key") or "").strip()


def curseforge_entry_id(entry: dict[str, Any]) -> str | None:
    value = entry.get("curseforge_project_id")
    return str(value) if value else None


def curseforge_entry_slug(entry: dict[str, Any]) -> str | None:
    page = entry.get("page") or ""
    parsed = urllib.parse.urlparse(page)
    if parsed.netloc.endswith("curseforge.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3 and parts[0] == "minecraft" and parts[1] == "mc-mods":
            return parts[2]
    return entry.get("curseforge_slug")


def file_matches_entry(filename: str, entry: dict[str, Any]) -> bool:
    lower = filename.lower()
    blocked = [pattern.lower() for pattern in entry.get("exclude_file_patterns", [])]
    if any(pattern in lower for pattern in blocked):
        return False
    required = [pattern.lower() for pattern in entry.get("file_patterns", [])]
    return all(pattern in lower for pattern in required)


def allowed_file_extensions(entry: dict[str, Any]) -> tuple[str, ...]:
    configured = entry.get("file_extensions")
    if configured:
        return tuple(str(ext).lower() if str(ext).startswith(".") else f".{str(ext).lower()}" for ext in configured)
    return (".jar", ".zip")


def entry_installed(entry: dict[str, Any], instance_dir: Path) -> bool:
    return bool(installed_entry_paths(entry, instance_dir))


def detect_patterns(entry: dict[str, Any]) -> list[str]:
    patterns = [pattern.lower() for pattern in entry.get("detect", [])]
    if not patterns:
        raw = entry.get("name", "").lower().replace(" ", "")
        patterns = [raw]
    return patterns


def installed_entry_paths(entry: dict[str, Any], instance_dir: Path) -> list[Path]:
    folder = mods_dir(instance_dir)
    if not folder.exists():
        return []

    exact_filename = entry.get("filename") if entry.get("replace_existing") else None
    if exact_filename:
        path = folder / str(exact_filename)
        return [path] if path.is_file() else []

    patterns = detect_patterns(entry)
    matches: list[Path] = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in MOD_FILE_EXTENSIONS:
            continue
        filename = path.name.lower()
        if any(pattern in filename for pattern in patterns):
            matches.append(path)
    return sorted(matches, key=lambda item: item.name.lower())


def disable_replaced_files(entry: dict[str, Any], instance_dir: Path, log: Callable[[str], None]) -> None:
    if not entry.get("replace_existing"):
        return
    folder = mods_dir(instance_dir)
    if not folder.exists():
        return
    target_filename = str(entry.get("filename") or "").lower()
    patterns = [str(pattern).lower() for pattern in entry.get("replace_patterns") or entry.get("detect", [])]
    if not target_filename or not patterns:
        return

    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in MOD_FILE_EXTENSIONS:
            continue
        filename = path.name.lower()
        if filename == target_filename:
            continue
        if not any(pattern in filename for pattern in patterns):
            continue

        disabled = path.with_name(f"{path.name}.disabled")
        counter = 1
        while disabled.exists():
            disabled = path.with_name(f"{path.name}.disabled{counter}")
            counter += 1
        path.rename(disabled)
        log(f"競合する既存MODを無効化: {path.name} -> {disabled.name}")


def select_curseforge_file(files: list[dict[str, Any]], entry: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    preferred: list[dict[str, Any]] = []
    extensions = allowed_file_extensions(entry)
    for item in files:
        filename = str(item.get("fileName") or item.get("fileNameOnDisk") or item.get("displayName") or item.get("file_name") or "")
        if not filename.lower().endswith(extensions):
            continue
        versions = [str(version) for version in item.get("gameVersions", item.get("gameVersion", []))]
        if MINECRAFT_VERSION not in versions:
            continue
        if not file_matches_entry(filename, entry):
            continue
        release_type = item.get("releaseType")
        candidates.append(item)
        if release_type in (None, 1, 2, "release", "beta"):
            preferred.append(item)

    if not candidates:
        raise LauncherError(f"CurseForgeにForge {MINECRAFT_VERSION}用ファイルが見つかりません: {entry.get('name')}")

    def sort_key(item: dict[str, Any]) -> tuple[str, int]:
        return (str(item.get("fileDate") or item.get("file_date") or ""), int(item.get("id") or 0))

    return sorted(preferred or candidates, key=sort_key, reverse=True)[0]


def curseforge_filename(item: dict[str, Any]) -> str:
    filename = item.get("fileName") or item.get("fileNameOnDisk") or item.get("displayName")
    if not filename:
        raise LauncherError("CurseForgeファイル名を取得できません")
    return str(filename)


def curseforge_sha1(item: dict[str, Any]) -> str | None:
    for hash_item in item.get("hashes") or []:
        if hash_item.get("algo") in (1, "sha1"):
            return str(hash_item.get("value"))
    return None


def curseforge_file_id(item: dict[str, Any]) -> int:
    file_id = item.get("id")
    if not file_id:
        raise LauncherError("CurseForge file idを取得できません")
    return int(file_id)


def official_curseforge_files(project_id: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "gameVersion": MINECRAFT_VERSION,
            "modLoaderType": CURSEFORGE_FORGE_LOADER,
            "pageSize": 50,
        }
    )
    key = curseforge_api_key()
    if not key:
        raise LauncherError("CURSEFORGE_API_KEY が未設定です")
    data = request_json(
        f"{CURSEFORGE_API}/mods/{urllib.parse.quote(project_id)}/files?{params}",
        headers={"x-api-key": key},
    )
    return data.get("data") or []


def official_curseforge_search(entry: dict[str, Any]) -> str:
    key = curseforge_api_key()
    if not key:
        raise LauncherError("CURSEFORGE_API_KEY が未設定です")
    slug = curseforge_entry_slug(entry)
    params = {
        "gameId": CURSEFORGE_GAME_ID,
        "classId": CURSEFORGE_MODS_SECTION_ID,
        "gameVersion": MINECRAFT_VERSION,
        "modLoaderType": CURSEFORGE_FORGE_LOADER,
        "pageSize": 20,
        "searchFilter": entry.get("curseforge_search") or entry.get("name", ""),
    }
    data = request_json(
        f"{CURSEFORGE_API}/mods/search?{urllib.parse.urlencode(params)}",
        headers={"x-api-key": key},
    )
    results = data.get("data") or []
    for item in results:
        links = item.get("links") or {}
        website = str(links.get("websiteUrl") or "")
        if slug and f"/minecraft/mc-mods/{slug}" in website:
            return str(item["id"])
    if results:
        return str(results[0]["id"])
    raise LauncherError(f"CurseForge検索で見つかりません: {entry.get('name')}")


def legacy_curseforge_search(entry: dict[str, Any]) -> str:
    if entry.get("curseforge_project_id"):
        return str(entry["curseforge_project_id"])
    slug = curseforge_entry_slug(entry)
    params = {
        "gameId": CURSEFORGE_GAME_ID,
        "pageSize": 20,
        "categoryId": 0,
        "sectionId": CURSEFORGE_MODS_SECTION_ID,
        "searchFilter": entry.get("curseforge_search") or entry.get("name", ""),
        "gameVersion": MINECRAFT_VERSION,
    }
    results = request_json(f"{CURSEFORGE_LEGACY_API}/addon/search?{urllib.parse.urlencode(params)}")
    for item in results:
        website = str(item.get("websiteUrl") or "")
        if slug and f"/minecraft/mc-mods/{slug}" in website:
            return str(item["id"])
    if results:
        return str(results[0]["id"])
    raise LauncherError(f"CurseForge旧API検索で見つかりません: {entry.get('name')}")


def legacy_curseforge_files(project_id: str) -> list[dict[str, Any]]:
    files = request_json(f"{CURSEFORGE_LEGACY_API}/addon/{urllib.parse.quote(project_id)}/files")
    return files if isinstance(files, list) else []


def mirror_curseforge_files(project_id: str) -> list[dict[str, Any]]:
    html_text = request_text(
        f"{CURSEFORGE_MIRROR}/history?id={urllib.parse.quote(project_id)}&ver={urllib.parse.quote(MINECRAFT_VERSION)}"
    )
    rows = re.findall(
        r'<tr class="c"><td><a href="([^"]+)"[^>]*>([^<]+)</a></td><td>([^<]+)</td><td>([^<]+)</td><td>(.*?)</td></tr>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    files: list[dict[str, Any]] = []
    for url, filename, release_type, file_date, dependencies in rows:
        url = html.unescape(url)
        filename = urllib.parse.unquote(html.unescape(filename))
        match = re.search(r"/files/(\d+)/(\d+)/", url)
        if not match:
            continue
        file_id = int(f"{match.group(1)}{match.group(2).zfill(3)}")
        files.append(
            {
                "id": file_id,
                "fileName": filename,
                "downloadUrl": url,
                "gameVersions": [MINECRAFT_VERSION],
                "releaseType": html.unescape(release_type).strip().lower(),
                "fileDate": file_date.strip(),
                "dependencies": html.unescape(dependencies).strip(),
            }
        )
    return files


def legacy_curseforge_download_url(project_id: str, file_id: int) -> str:
    url = f"{CURSEFORGE_LEGACY_API}/addon/{urllib.parse.quote(project_id)}/file/{file_id}/download-url"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8").strip().strip('"')


def curseforge_edge_url(file_id: int, filename: str) -> str:
    text = str(file_id)
    return f"https://edge.forgecdn.net/files/{text[:-3]}/{text[-3:]}/{urllib.parse.quote(filename)}"


def curseforge_download_url(project_id: str, file_info: dict[str, Any]) -> str:
    direct = file_info.get("downloadUrl") or file_info.get("downloadURL")
    if direct:
        return str(direct)
    file_id = curseforge_file_id(file_info)
    try:
        return legacy_curseforge_download_url(project_id, file_id)
    except Exception:
        return curseforge_edge_url(file_id, curseforge_filename(file_info))


def download_curseforge_entry(entry: dict[str, Any], instance_dir: Path, log: Callable[[str], None]) -> list[Path]:
    project_id = curseforge_entry_id(entry)
    files: list[dict[str, Any]] = []

    pinned_file_id = entry.get("curseforge_file_id")
    pinned_filename = entry.get("filename")
    if pinned_file_id and pinned_filename:
        filename = str(pinned_filename)
        url = curseforge_edge_url(int(pinned_file_id), filename)
        path = download_file(url, mods_dir(instance_dir) / filename, log, entry.get("sha1"))
        return [path]

    if curseforge_api_key():
        if not project_id:
            project_id = official_curseforge_search(entry)
        files = official_curseforge_files(project_id)

    if not files:
        try:
            project_id = project_id or legacy_curseforge_search(entry)
            files = legacy_curseforge_files(project_id)
        except Exception as exc:
            if not project_id:
                raise
            log(f"CurseForge旧APIに接続できないためCDN索引に切り替えます: {entry.get('name')}: {exc}")
            files = mirror_curseforge_files(project_id)

    file_info = select_curseforge_file(files, entry)
    filename = curseforge_filename(file_info)
    url = curseforge_download_url(project_id, file_info)
    path = download_file(url, mods_dir(instance_dir) / filename, log, curseforge_sha1(file_info))
    return [path]


def download_modrinth_entry(
    entry: dict[str, Any],
    instance_dir: Path,
    log: Callable[[str], None],
    seen_projects: set[str] | None = None,
) -> list[Path]:
    seen_projects = seen_projects or set()
    slug = entry.get("modrinth_slug")
    if not slug:
        raise LauncherError(f"Modrinth slugがありません: {entry.get('name')}")
    if slug in seen_projects:
        return []
    seen_projects.add(slug)

    versions = query_modrinth_versions(slug)
    if not versions:
        raise LauncherError(f"ModrinthにForge {MINECRAFT_VERSION}版が見つかりません: {entry.get('name')} ({slug})")

    version = versions[0]
    file_info = select_primary_file(version)
    filename = file_info["filename"]
    sha1 = (file_info.get("hashes") or {}).get("sha1")
    target = mods_dir(instance_dir) / filename
    path = download_file(file_info["url"], target, log, sha1)
    downloaded = [path]

    for dep in version.get("dependencies") or []:
        if dep.get("dependency_type") != "required":
            continue
        dep_name = dep.get("project_id") or dep.get("version_id")
        if not dep_name:
            continue
        try:
            if dep.get("version_id"):
                dep_version = query_modrinth_version(dep["version_id"])
                dep_file = select_primary_file(dep_version)
                dep_target = mods_dir(instance_dir) / dep_file["filename"]
                dep_sha1 = (dep_file.get("hashes") or {}).get("sha1")
                downloaded.append(download_file(dep_file["url"], dep_target, log, dep_sha1))
            elif dep.get("project_id"):
                dep_entry = {"name": dep_name, "modrinth_slug": dep["project_id"]}
                downloaded.extend(download_modrinth_entry(dep_entry, instance_dir, log, seen_projects))
        except Exception as exc:  # Keep the main mod install moving.
            log(f"依存MODの自動取得に失敗しました: {dep_name}: {exc}")

    return downloaded


def download_bundled_entry(entry: dict[str, Any], instance_dir: Path, log: Callable[[str], None]) -> list[Path]:
    filename = entry.get("filename")
    bundled_path = entry.get("bundled_path")
    if bundled_path:
        source_path = ROOT / str(bundled_path)
    elif filename:
        source_path = VENDOR_MODS_DIR / str(filename)
    else:
        raise LauncherError("bundled_pathまたはfilenameがありません")

    if not source_path.exists():
        raise LauncherError(f"同梱MODが見つかりません: {source_path}")
    if not source_path.is_file():
        raise LauncherError(f"同梱MODがファイルではありません: {source_path}")

    expected_sha1 = entry.get("sha1")
    if expected_sha1:
        actual = sha1_file(source_path)
        if actual != str(expected_sha1).lower():
            raise LauncherError(f"同梱MODのSHA1が一致しません: {source_path.name} expected={expected_sha1} actual={actual}")

    target_name = str(filename or source_path.name)
    target = mods_dir(instance_dir) / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if expected_sha1 and sha1_file(target) != str(expected_sha1).lower():
            log(f"既存ファイルのSHA1が違うため同梱MODで上書きします: {target.name}")
        else:
            log(f"既にあります: {target.name}")
            return [target]

    shutil.copy2(source_path, target)
    log(f"同梱MODをコピー: {target.name}")
    return [target]


def bundled_config_sources() -> list[Path]:
    if not VENDOR_CONFIG_DIR.exists():
        return []
    sources = [
        path
        for path in VENDOR_CONFIG_DIR.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name not in CONFIG_DOC_FILENAMES
    ]
    return sorted(sources, key=lambda path: path.relative_to(VENDOR_CONFIG_DIR).as_posix().lower())


def copy_bundled_configs(
    instance_dir: Path,
    log: Callable[[str], None] = log_console,
    *,
    overwrite: bool = False,
    log_empty: bool = False,
) -> list[Path]:
    ensure_instance_dirs(instance_dir)
    sources = bundled_config_sources()
    if not sources:
        if log_empty:
            log(f"配布configファイルはありません: {VENDOR_CONFIG_DIR}")
        return []

    copied: list[Path] = []
    for source in sources:
        relative = source.relative_to(VENDOR_CONFIG_DIR)
        target = config_dir(instance_dir) / relative
        label = relative.as_posix()
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() and target.is_dir():
            raise LauncherError(f"configコピー先がフォルダです: {target}")
        if target.exists() and not overwrite:
            log(f"config導入済み: {label}")
            continue
        if target.exists() and target.is_file() and sha1_file(target) == sha1_file(source):
            log(f"config導入済み: {label}")
            continue

        shutil.copy2(source, target)
        copied.append(target)
        log(f"configをコピー: {label}")

    if copied:
        log(f"配布configコピー完了: {len(copied)} ファイル")
    return copied


def download_manifest_mods(
    manifest: dict[str, Any],
    instance_dir: Path,
    log: Callable[[str], None] = log_console,
) -> tuple[list[Path], list[dict[str, Any]]]:
    ensure_instance_dirs(instance_dir)
    downloaded: list[Path] = []
    manual: list[dict[str, Any]] = []

    for entry in manifest.get("mods", []):
        source = entry.get("source")
        name = entry.get("name", "unknown")
        try:
            disable_replaced_files(entry, instance_dir, log)
            if entry_installed(entry, instance_dir):
                log(f"導入済みのためスキップ: {name}")
                continue
            if source == "modrinth":
                log(f"Modrinthから取得: {name}")
                downloaded.extend(download_modrinth_entry(entry, instance_dir, log))
            elif source == "curseforge":
                log(f"CurseForgeから取得: {name}")
                downloaded.extend(download_curseforge_entry(entry, instance_dir, log))
            elif source == "bundled":
                log(f"同梱MODを導入: {name}")
                downloaded.extend(download_bundled_entry(entry, instance_dir, log))
            elif source == "direct":
                url = entry.get("direct_url")
                filename = entry.get("filename") or Path(urllib.parse.urlparse(url).path).name
                if not url or not filename:
                    raise LauncherError("direct_urlまたはfilenameがありません")
                downloaded.append(download_file(url, mods_dir(instance_dir) / filename, log, entry.get("sha1")))
            else:
                manual.append(entry)
                log(f"手動導入が必要: {name}")
        except Exception as exc:
            manual.append(entry)
            log(f"自動取得できませんでした: {name}: {exc}")

    lock = {
        "updated_at": now_iso(),
        "minecraft_version": MINECRAFT_VERSION,
        "forge_version": FORGE_VERSION,
        "downloaded": [path.name for path in downloaded],
        "manual_required": [entry.get("name") for entry in manual],
    }
    with (instance_dir / "modpack.lock.json").open("w", encoding="utf-8") as fh:
        json.dump(lock, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    return downloaded, manual


def server_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    result["mods"] = [entry for entry in result.get("mods", []) if entry.get("side") != "client"]
    return result


def client_only_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in manifest.get("mods", []) if entry.get("side") == "client"]


def disable_path(path: Path, suffix: str, log: Callable[[str], None]) -> None:
    disabled = path.with_name(f"{path.name}{suffix}")
    counter = 1
    while disabled.exists():
        disabled = path.with_name(f"{path.name}{suffix}{counter}")
        counter += 1
    path.rename(disabled)
    log(f"サーバーから除外: {path.name} -> {disabled.name}")


def copy_server_mods(
    manifest: dict[str, Any],
    instance_dir: Path,
    server_dir: Path,
    log: Callable[[str], None] = log_console,
) -> tuple[list[Path], list[dict[str, Any]]]:
    ensure_server_dirs(server_dir)
    copied: list[Path] = []
    missing: list[dict[str, Any]] = []

    for entry in server_manifest(manifest).get("mods", []):
        paths = installed_entry_paths(entry, instance_dir)
        if not paths:
            missing.append(entry)
            continue
        source = paths[0]
        target = mods_dir(server_dir) / source.name
        if target.exists() and sha1_file(target) == sha1_file(source):
            log(f"server mods導入済み: {target.name}")
            continue
        shutil.copy2(source, target)
        copied.append(target)
        log(f"server modsへコピー: {target.name}")

    for entry in client_only_entries(manifest):
        for path in installed_entry_paths(entry, server_dir):
            disable_path(path, ".client-disabled", log)

    return copied, missing


def install_forge_server(server_dir: Path, java_cmd: str, log: Callable[[str], None] = log_console) -> Path:
    ensure_server_dirs(server_dir)
    forge_jar = server_dir / FORGE_SERVER_JAR
    if forge_jar.is_file():
        log(f"Forge server導入済み: {forge_jar.name}")
        return forge_jar

    installer = server_dir / "downloads" / f"forge-{FORGE_ID}-installer.jar"
    download_file(FORGE_INSTALLER_URL, installer, log)
    java_executable = executable_arg(java_cmd)
    log("Forge server installerを実行します。数分かかる場合があります。")
    result = subprocess.run(
        [java_executable, "-jar", str(installer.resolve()), "--installServer"],
        cwd=str(server_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        log(result.stdout.strip())
    if result.returncode != 0:
        raise LauncherError(f"Forge serverの導入に失敗しました。終了コード: {result.returncode}")
    if not forge_jar.is_file():
        matches = sorted(server_dir.glob(f"forge-{MINECRAFT_VERSION}-{FORGE_VERSION}*.jar"))
        if matches:
            return matches[0]
        raise LauncherError(f"Forge server jarが見つかりません: {forge_jar}")
    log(f"Forge server導入済み: {forge_jar.name}")
    return forge_jar


def write_text_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.write_text(content, encoding="utf-8", newline="\n")


def write_text_file(path: Path, content: str, executable: bool = False) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(path.stat().st_mode | 0o755)


def write_server_files(
    manifest: dict[str, Any],
    server_dir: Path,
    ram_gb: int,
    forge_jar: Path,
    java_cmd: str,
    log: Callable[[str], None] = log_console,
) -> None:
    write_text_if_missing(
        server_dir / "eula.txt",
        "# MojangのEULAに同意する場合だけ eula=true に変更してください。\n"
        "# https://aka.ms/MinecraftEULA\n"
        "eula=false\n",
    )
    write_text_if_missing(
        server_dir / "server.properties",
        "motd=MC 1.12.2 JP Modpack Server\n"
        "allow-flight=true\n"
        "view-distance=8\n"
        "server-port=25565\n"
        "use-native-transport=false\n"
        "max-tick-time=60000\n",
    )

    jar_name = forge_jar.name
    java_executable = executable_arg(java_cmd)
    bat_java = java_executable if platform.system() == "Windows" else "java"
    sh_java = java_executable if platform.system() != "Windows" else "java"
    write_text_file(
        server_dir / "start_server.bat",
        "@echo off\n"
        "cd /d \"%~dp0\"\n"
        f"if not defined JAVA_EXE set \"JAVA_EXE={bat_java}\"\n"
        "\"%JAVA_EXE%\" -version 2>&1 | findstr /C:\"version \\\"1.8\" >nul\n"
        "if ERRORLEVEL 1 (\n"
        "  echo Minecraft Forge 1.12.2 server requires Java 8.\n"
        "  echo Current Java:\n"
        "  \"%JAVA_EXE%\" -version\n"
        "  pause\n"
        "  exit /b 1\n"
        ")\n"
        f"\"%JAVA_EXE%\" -Xms1G -Xmx{ram_gb}G -jar \"{jar_name}\" nogui\n"
        "pause\n",
    )
    write_text_file(
        server_dir / "start_server.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cd \"$(dirname \"$0\")\"\n"
        "if [ -z \"${JAVA_EXE:-}\" ]; then\n"
        f"  JAVA_EXE={shlex.quote(sh_java)}\n"
        "fi\n"
        "if ! \"$JAVA_EXE\" -version 2>&1 | grep -q 'version \"1\\.8'; then\n"
        "  echo \"Minecraft Forge 1.12.2 server requires Java 8.\"\n"
        "  echo \"Current Java:\"\n"
        "  \"$JAVA_EXE\" -version\n"
        "  exit 1\n"
        "fi\n"
        f"exec \"$JAVA_EXE\" -Xms1G -Xmx{ram_gb}G -jar \"{jar_name}\" nogui\n",
        executable=True,
    )

    excluded = ", ".join(entry.get("name", "") for entry in client_only_entries(manifest)) or "なし"
    write_text_file(
        server_dir / "SERVER_README.txt",
        "MC 1.12.2 JP Modpack Server\n"
        "\n"
        "初回起動前に eula.txt を開き、MojangのEULAに同意する場合だけ eula=true に変更してください。\n"
        "Windows: start_server.bat\n"
        "macOS/Linux: ./start_server.sh\n"
        "別のJava 8を使う場合は JAVA_EXE 環境変数で指定できます。\n"
        "\n"
        f"クライアント専用として除外したMOD: {excluded}\n"
        "サーバーに参加する人は、通常のクライアント用ランチャーで同じMOD環境を作ってください。\n",
    )
    log("サーバー起動ファイルを作成しました。")


def export_server_folder(
    manifest: dict[str, Any],
    instance_dir: Path,
    server_dir: Path,
    java_cmd: str,
    ram_gb: int,
    log: Callable[[str], None] = log_console,
) -> Path:
    ensure_instance_dirs(instance_dir)
    ensure_server_dirs(server_dir)
    copy_bundled_configs(instance_dir, log)

    copied, missing = copy_server_mods(manifest, instance_dir, server_dir, log)
    if copied:
        log(f"server modsコピー: {len(copied)} ファイル")
    if missing:
        log(f"server mods不足分を自動取得します: {len(missing)} 件")
        _, manual = download_manifest_mods({"mods": missing}, server_dir, log)
        if manual:
            names = ", ".join(entry.get("name", "") for entry in manual)
            raise LauncherError(f"server用MODの取得に失敗しました: {names}")

    if config_dir(instance_dir).exists():
        shutil.copytree(config_dir(instance_dir), config_dir(server_dir), dirs_exist_ok=True)
        log("configをserverフォルダへコピーしました。")

    forge_jar = install_forge_server(server_dir, java_cmd, log)
    write_server_files(manifest, server_dir, ram_gb, forge_jar, java_cmd, log)
    log(f"serverフォルダ出力完了: {server_dir}")
    return server_dir


def detect_installed_mods(manifest: dict[str, Any], instance_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for entry in manifest.get("mods", []):
        installed = entry_installed(entry, instance_dir)
        rows.append(
            {
                "name": entry.get("name", ""),
                "kind": "追加依存" if entry.get("dependency") else "指定MOD",
                "source": entry.get("source", "manual"),
                "status": "導入済み" if installed else "未導入",
            }
        )
    return rows


def create_launcher_profile(
    minecraft_dir: Path,
    instance_dir: Path,
    ram_gb: int,
    log: Callable[[str], None] = log_console,
) -> None:
    ensure_instance_dirs(instance_dir)
    minecraft_dir.mkdir(parents=True, exist_ok=True)
    profiles_path = minecraft_dir / "launcher_profiles.json"

    if profiles_path.exists():
        try:
            with profiles_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise LauncherError(f"launcher_profiles.jsonを読めません: {exc}") from exc
        backup = profiles_path.with_name(f"launcher_profiles.backup-{int(time.time())}.json")
        shutil.copy2(profiles_path, backup)
        log(f"既存プロファイルをバックアップしました: {backup.name}")
    else:
        data = {"profiles": {}}

    data.setdefault("profiles", {})
    existing = data["profiles"].get(PROFILE_ID, {})
    created = existing.get("created") or now_iso()
    data["profiles"][PROFILE_ID] = {
        **existing,
        "name": PROFILE_NAME,
        "type": "custom",
        "created": created,
        "lastUsed": now_iso(),
        "lastVersionId": FORGE_ID,
        "gameDir": str(instance_dir),
        "javaArgs": f"-Xms1G -Xmx{ram_gb}G",
    }

    with profiles_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    log(f"公式ランチャー用プロファイルを作成/更新しました: {PROFILE_NAME}")


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def launch_official_launcher(log: Callable[[str], None] = log_console) -> None:
    system = platform.system()
    commands: list[list[str]] = []

    if system == "Windows":
        candidates: list[Path] = []
        for env_name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
            if not root:
                continue
            root_path = Path(root)
            candidates.append(root_path / "Minecraft Launcher" / "MinecraftLauncher.exe")
            candidates.append(root_path / "Programs" / "Minecraft Launcher" / "MinecraftLauncher.exe")
            candidates.append(root_path / "Packages" / "Microsoft.4297127D64EC6_8wekyb3d8bbwe" / "LocalCache" / "Local" / "game" / "MinecraftLauncher.exe")
        for candidate in candidates:
            if candidate.exists():
                subprocess.Popen([str(candidate)])
                log("公式Minecraft Launcherを起動しました。")
                return
        for uri in ("minecraft:", "minecraft://"):
            try:
                os.startfile(uri)
                log("Minecraft Launcher URIを開きました。")
                return
            except OSError:
                pass
    elif system == "Darwin":
        commands.append(["open", "-a", "Minecraft"])
    else:
        if command_exists("minecraft-launcher"):
            commands.append(["minecraft-launcher"])
        if command_exists("flatpak"):
            commands.append(["flatpak", "run", "com.mojang.Minecraft"])
        for path in ("/usr/bin/minecraft-launcher", "/snap/bin/minecraft-launcher"):
            if Path(path).exists():
                commands.append([path])

    errors: list[str] = []
    for command in commands:
        try:
            subprocess.Popen(command)
            log("公式Minecraft Launcherを起動しました。")
            return
        except Exception as exc:
            errors.append(f"{' '.join(command)}: {exc}")

    joined = "\n".join(errors)
    raise LauncherError("公式Minecraft Launcherを自動検出できませんでした。" + (f"\n{joined}" if joined else ""))


def open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))
    elif system == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def check_environment(minecraft_dir: Path, instance_dir: Path, java_cmd: str, log: Callable[[str], None] = log_console) -> None:
    log(f"Minecraftフォルダ: {minecraft_dir}")
    log(f"MOD環境フォルダ: {instance_dir}")
    log(f"Forge ID: {FORGE_ID}")
    log(f"Forge導入状況: {'導入済み' if installed_forge(minecraft_dir) else '未導入'}")
    java_executable = executable_arg(java_cmd)
    try:
        result = subprocess.run([java_executable, "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        first = (result.stdout or "").splitlines()[0] if result.stdout else "Java情報なし"
        log(f"Java: {first} ({java_executable})")
        if '"1.8' not in result.stdout and " 8" not in result.stdout:
            log("注意: Minecraft 1.12.2はJava 8が最も安定します。公式ランチャーの同梱Javaを使う場合は問題ないことがあります。")
    except FileNotFoundError:
        log(f"Javaが見つかりません: {java_executable}")
    profiles = minecraft_dir / "launcher_profiles.json"
    log(f"launcher_profiles.json: {'あり' if profiles.exists() else 'なし'}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minecraft 1.12.2 Forge MOD launcher helper")
    parser.add_argument("--minecraft-dir", type=Path, default=None, help="公式.minecraftフォルダ")
    parser.add_argument("--instance-dir", type=Path, default=None, help="このMOD環境のゲームフォルダ")
    parser.add_argument("--server-dir", type=Path, default=None, help="サーバー出力先フォルダ")
    parser.add_argument("--java", default=default_java_cmd(), help="Forge導入に使うJavaコマンド")
    parser.add_argument("--ram", type=int, default=4, help="公式ランチャープロファイル/サーバーに設定する最大RAM GB")
    parser.add_argument("--curseforge-api-key", default=None, help="CurseForge公式APIキー")
    parser.add_argument("--check", action="store_true", help="環境チェックだけ実行")
    parser.add_argument("--install-forge", action="store_true", help="Forge 1.12.2を導入")
    parser.add_argument("--download-mods", action="store_true", help="自動取得できるMODを導入")
    parser.add_argument("--install-configs", action="store_true", help="vendor/config のMOD設定をconfigへコピー")
    parser.add_argument("--overwrite-configs", action="store_true", help="config適用時に既存ファイルも上書き")
    parser.add_argument("--export-server", action="store_true", help="サーバー用フォルダを出力")
    parser.add_argument("--create-profile", action="store_true", help="公式Minecraft Launcherのプロファイルを作成")
    parser.add_argument("--launch", action="store_true", help="公式Minecraft Launcherを起動")
    parser.add_argument("--list", action="store_true", help="MOD導入状況を表示")
    parser.add_argument("--gui", action="store_true", help="GUIを起動")
    return parser


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    settings = load_settings()
    minecraft_dir = args.minecraft_dir or Path(settings.get("minecraft_dir") or default_minecraft_dir())
    instance_dir = args.instance_dir or Path(settings.get("instance_dir") or default_instance_dir())
    return minecraft_dir.expanduser(), instance_dir.expanduser()


def resolve_server_dir(args: argparse.Namespace, instance_dir: Path) -> Path:
    settings = load_settings()
    server_dir = args.server_dir or Path(settings.get("server_dir") or default_server_dir(instance_dir))
    return server_dir.expanduser()


def run_cli(args: argparse.Namespace) -> int:
    if args.curseforge_api_key:
        os.environ["CURSEFORGE_API_KEY"] = args.curseforge_api_key
    manifest = load_manifest()
    minecraft_dir, instance_dir = resolve_paths(args)
    server_dir = resolve_server_dir(args, instance_dir)
    ensure_instance_dirs(instance_dir)
    configs_installed = False

    if args.check:
        check_environment(minecraft_dir, instance_dir, args.java)
    if args.install_forge:
        install_forge(minecraft_dir, instance_dir, args.java)
    if args.download_mods:
        downloaded, manual = download_manifest_mods(manifest, instance_dir)
        copy_bundled_configs(instance_dir, overwrite=args.overwrite_configs)
        configs_installed = True
        log_console(f"自動取得完了: {len(downloaded)} ファイル")
        if manual:
            log_console("手動導入が必要なMOD:")
            for entry in manual:
                log_console(f" - {entry.get('name')}: {entry.get('page', 'URLなし')}")
    if args.install_configs and not configs_installed:
        copy_bundled_configs(instance_dir, overwrite=args.overwrite_configs, log_empty=True)
        configs_installed = True
    if args.export_server:
        if not configs_installed:
            copy_bundled_configs(instance_dir, overwrite=args.overwrite_configs)
            configs_installed = True
        export_server_folder(manifest, instance_dir, server_dir, args.java, args.ram)
    if args.create_profile:
        create_launcher_profile(minecraft_dir, instance_dir, args.ram)
    if args.list:
        for row in detect_installed_mods(manifest, instance_dir):
            log_console(f"{row['status']}\t{row['kind']}\t{row['source']}\t{row['name']}")
    if args.launch:
        launch_official_launcher()

    if not any((args.check, args.install_forge, args.download_mods, args.install_configs, args.export_server, args.create_profile, args.launch, args.list)):
        return run_gui()
    return 0


def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:
        raise LauncherError(f"tkinter GUIを起動できません。CLIを使ってください: {exc}") from exc

    manifest = load_manifest()
    settings = load_settings()

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(APP_TITLE)
            self.geometry("1060x720")
            self.minsize(880, 600)

            self.minecraft_var = tk.StringVar(value=str(Path(settings.get("minecraft_dir") or default_minecraft_dir())))
            self.instance_var = tk.StringVar(value=str(Path(settings.get("instance_dir") or default_instance_dir())))
            self.server_var = tk.StringVar(value=str(Path(settings.get("server_dir") or default_server_dir(Path(self.instance_var.get())))))
            self.java_var = tk.StringVar(value=settings.get("java_cmd") or default_java_cmd())
            self.curseforge_key_var = tk.StringVar(value=settings.get("curseforge_api_key") or "")
            self.ram_var = tk.IntVar(value=int(settings.get("ram_gb") or 4))
            self.busy = False

            self._build_ui(tk, ttk, filedialog)
            self.refresh_status()

        def _build_ui(self, tk: Any, ttk: Any, filedialog: Any) -> None:
            root = ttk.Frame(self, padding=12)
            root.pack(fill="both", expand=True)
            root.columnconfigure(0, weight=1)
            root.rowconfigure(2, weight=1)

            path_frame = ttk.LabelFrame(root, text="環境")
            path_frame.grid(row=0, column=0, sticky="ew")
            path_frame.columnconfigure(1, weight=1)

            ttk.Label(path_frame, text=".minecraft").grid(row=0, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(path_frame, textvariable=self.minecraft_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
            ttk.Button(path_frame, text="選択", command=lambda: self.choose_dir(self.minecraft_var)).grid(row=0, column=2, padx=8, pady=4)

            ttk.Label(path_frame, text="MOD環境").grid(row=1, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(path_frame, textvariable=self.instance_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
            ttk.Button(path_frame, text="選択", command=lambda: self.choose_dir(self.instance_var)).grid(row=1, column=2, padx=8, pady=4)

            ttk.Label(path_frame, text="server出力").grid(row=2, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(path_frame, textvariable=self.server_var).grid(row=2, column=1, sticky="ew", padx=8, pady=4)
            ttk.Button(path_frame, text="選択", command=lambda: self.choose_dir(self.server_var)).grid(row=2, column=2, padx=8, pady=4)

            ttk.Label(path_frame, text="Java").grid(row=3, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(path_frame, textvariable=self.java_var, width=24).grid(row=3, column=1, sticky="ew", padx=8, pady=4)
            ttk.Button(path_frame, text="選択", command=self.choose_java).grid(row=3, column=2, padx=8, pady=4)

            ram_frame = ttk.Frame(path_frame)
            ram_frame.grid(row=4, column=1, sticky="w", padx=8, pady=4)
            ttk.Label(path_frame, text="RAM").grid(row=4, column=0, sticky="w", padx=8, pady=4)
            ttk.Spinbox(ram_frame, from_=2, to=12, textvariable=self.ram_var, width=5).pack(side="left")
            ttk.Label(ram_frame, text="GB").pack(side="left", padx=(6, 0))

            ttk.Label(path_frame, text="CF API Key").grid(row=5, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(path_frame, textvariable=self.curseforge_key_var, show="*").grid(row=5, column=1, sticky="ew", padx=8, pady=4)

            actions = ttk.Frame(root)
            actions.grid(row=1, column=0, sticky="ew", pady=(10, 8))
            buttons = [
                ("環境チェック", self.action_check),
                ("Forge導入", self.action_install_forge),
                ("MOD自動DL", self.action_download_mods),
                ("config適用", self.action_install_configs),
                ("手動MOD追加", self.action_import_mods),
                ("server出力", self.action_export_server),
                ("プロファイル作成", self.action_create_profile),
                ("公式ランチャー起動", self.action_launch),
                ("modsフォルダ", self.action_open_mods),
            ]
            action_columns = 5
            for index in range(action_columns):
                actions.columnconfigure(index, weight=1)
            for index, (text, command) in enumerate(buttons):
                ttk.Button(actions, text=text, command=command).grid(row=index // action_columns, column=index % action_columns, sticky="ew", padx=3, pady=2)

            content = ttk.Panedwindow(root, orient="vertical")
            content.grid(row=2, column=0, sticky="nsew")

            table_frame = ttk.Frame(content)
            table_frame.columnconfigure(0, weight=1)
            table_frame.rowconfigure(0, weight=1)
            self.tree = ttk.Treeview(table_frame, columns=("status", "kind", "source"), show="tree headings", height=13)
            self.tree.heading("#0", text="MOD")
            self.tree.heading("status", text="状態")
            self.tree.heading("kind", text="種別")
            self.tree.heading("source", text="取得元")
            self.tree.column("#0", width=470, stretch=True)
            self.tree.column("status", width=100, anchor="center")
            self.tree.column("kind", width=100, anchor="center")
            self.tree.column("source", width=120, anchor="center")
            self.tree.grid(row=0, column=0, sticky="nsew")
            scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.bind("<Double-1>", self.open_selected_page)

            log_frame = ttk.Frame(content)
            log_frame.columnconfigure(0, weight=1)
            log_frame.rowconfigure(0, weight=1)
            self.log_text = tk.Text(log_frame, height=12, wrap="word")
            self.log_text.grid(row=0, column=0, sticky="nsew")
            log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
            log_scroll.grid(row=0, column=1, sticky="ns")
            self.log_text.configure(yscrollcommand=log_scroll.set)

            content.add(table_frame, weight=3)
            content.add(log_frame, weight=2)

            footer = ttk.Label(
                root,
                text="ダブルクリックで配布ページを開けます。自動取得できないMODだけ、配布元から落として「手動MOD追加」で取り込んでください。",
            )
            footer.grid(row=3, column=0, sticky="w", pady=(8, 0))

        def choose_dir(self, var: Any) -> None:
            selected = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
            if selected:
                var.set(selected)
                self.save_current_settings()
                self.refresh_status()

        def choose_java(self) -> None:
            current = executable_arg(self.java_var.get())
            initialdir = str(Path(current).parent) if current and Path(current).parent.exists() else str(Path.home())
            filetypes = [("Java executable", "*.exe"), ("All files", "*.*")] if platform.system() == "Windows" else [("Java executable", "java"), ("All files", "*.*")]
            selected = filedialog.askopenfilename(
                title="Java実行ファイルを選択",
                initialdir=initialdir,
                filetypes=filetypes,
            )
            if selected:
                self.java_var.set(selected)
                self.save_current_settings()

        def save_current_settings(self) -> None:
            save_settings(
                {
                    "minecraft_dir": self.minecraft_var.get(),
                    "instance_dir": self.instance_var.get(),
                    "server_dir": self.server_var.get(),
                    "java_cmd": self.java_var.get(),
                    "curseforge_api_key": self.curseforge_key_var.get(),
                    "ram_gb": self.ram_var.get(),
                }
            )

        def minecraft_dir(self) -> Path:
            return Path(self.minecraft_var.get()).expanduser()

        def instance_dir(self) -> Path:
            return Path(self.instance_var.get()).expanduser()

        def server_dir(self) -> Path:
            return Path(self.server_var.get()).expanduser()

        def log(self, message: str) -> None:
            self.after(0, self._append_log, message)

        def _append_log(self, message: str) -> None:
            self.log_text.insert("end", message.rstrip() + "\n")
            self.log_text.see("end")

        def refresh_status(self) -> None:
            self.tree.delete(*self.tree.get_children())
            for index, row in enumerate(detect_installed_mods(manifest, self.instance_dir())):
                self.tree.insert("", "end", iid=str(index), text=row["name"], values=(row["status"], row["kind"], row["source"]))

        def run_task(self, title: str, func: Callable[[], None]) -> None:
            if self.busy:
                messagebox.showinfo(APP_TITLE, "処理中です。完了まで待ってください。")
                return
            self.save_current_settings()
            self.busy = True
            self.log(f"--- {title} ---")

            def worker() -> None:
                try:
                    func()
                    self.log(f"完了: {title}")
                except Exception as exc:
                    self.log(f"エラー: {exc}")
                    self.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))
                finally:
                    self.busy = False
                    self.after(0, self.refresh_status)

            threading.Thread(target=worker, daemon=True).start()

        def action_check(self) -> None:
            self.run_task("環境チェック", lambda: check_environment(self.minecraft_dir(), self.instance_dir(), self.java_var.get(), self.log))

        def action_install_forge(self) -> None:
            self.run_task("Forge導入", lambda: install_forge(self.minecraft_dir(), self.instance_dir(), self.java_var.get(), self.log))

        def action_download_mods(self) -> None:
            def task() -> None:
                downloaded, manual = download_manifest_mods(manifest, self.instance_dir(), self.log)
                copy_bundled_configs(self.instance_dir(), self.log)
                self.log(f"自動取得: {len(downloaded)} ファイル")
                if manual:
                    self.log("手動導入が必要なMOD:")
                    for entry in manual:
                        self.log(f" - {entry.get('name')}: {entry.get('page', 'URLなし')}")

            self.run_task("MOD自動ダウンロード", task)

        def action_install_configs(self) -> None:
            overwrite = messagebox.askyesno(
                APP_TITLE,
                "既存のconfigも上書きしますか？\n「いいえ」は未導入ファイルだけコピーします。",
            )
            self.run_task(
                "config適用",
                lambda: copy_bundled_configs(self.instance_dir(), self.log, overwrite=overwrite, log_empty=True),
            )

        def action_export_server(self) -> None:
            self.run_task(
                "serverフォルダ出力",
                lambda: export_server_folder(manifest, self.instance_dir(), self.server_dir(), self.java_var.get(), int(self.ram_var.get()), self.log),
            )

        def action_import_mods(self) -> None:
            paths = filedialog.askopenfilenames(title="MOD jar/zip/litemodを選択", filetypes=[("Minecraft mods", "*.jar *.zip *.litemod"), ("All files", "*.*")])
            if not paths:
                return
            ensure_instance_dirs(self.instance_dir())
            for raw in paths:
                source = Path(raw)
                target = mods_dir(self.instance_dir()) / source.name
                shutil.copy2(source, target)
                self.log(f"取り込み: {source.name}")
            self.refresh_status()

        def action_create_profile(self) -> None:
            self.run_task(
                "プロファイル作成",
                lambda: create_launcher_profile(self.minecraft_dir(), self.instance_dir(), int(self.ram_var.get()), self.log),
            )

        def action_launch(self) -> None:
            self.run_task("公式ランチャー起動", lambda: launch_official_launcher(self.log))

        def action_open_mods(self) -> None:
            open_path(mods_dir(self.instance_dir()))

        def open_selected_page(self, _event: Any) -> None:
            selected = self.tree.selection()
            if not selected:
                return
            entry = manifest.get("mods", [])[int(selected[0])]
            page = entry.get("page")
            if page:
                webbrowser.open(page)
                self.log(f"配布ページを開きました: {entry.get('name')}")

    app = App()
    app.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.gui:
        return run_gui()
    return run_cli(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LauncherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
