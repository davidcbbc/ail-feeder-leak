"""AIL LeakFeeder - modernized implementation."""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional

import requests
import yaml
from filesplit.filesplit import Filesplit
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from service.utils import get_list_of_files

CURRENT_LEAK_FILENAME = "current_leak.txt"
MANIFEST_FILENAME = "fs_manifest.csv"
LEAK_LIST_FILENAME = "leak_list.csv"

LOG = logging.getLogger("ail_leakfeeder")


@dataclass
class FeederConfig:
    name: str = "LeakFeeder"
    leaks_folder: str = "Leaks_Folder"
    out_folder: str = "Unprocessed_Leaks"
    unprocessed_folder: str = "Unprocessed_files"
    chunks: int = 100000
    api_key: str = ""
    ail_url: str = ""
    uuid: str = ""
    wait: float = 1.0

    def to_paths(self, base_dir: Path) -> Dict[str, Path]:
        return {
            "leaks": base_dir / self.leaks_folder,
            "out": base_dir / self.out_folder,
            "unprocessed": base_dir / self.unprocessed_folder,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIL LeakFeeder")
    parser.add_argument("-g", "--config", default="config.yaml", help="Configuration file path.")
    parser.add_argument("-n", "--name", help="Name of the feeder.")
    parser.add_argument("-l", "--leaks_folder", help="Leaks Folder to parse and send to AIL.")
    parser.add_argument("-r", "--out_folder", help="Output Folder of unprocessed split files.")
    parser.add_argument("-a", "--unprocessed_folder", help="Output Folder of file that cannot be processed.")
    parser.add_argument("-c", "--chunks", type=int, help="Chunk size of split files.")
    parser.add_argument("-k", "--api_key", help="API key for AIL authentication.")
    parser.add_argument("-u", "--ail_url", help="AIL API URL.")
    parser.add_argument("-i", "--uuid", help="Unique identifier of the feeder.")
    parser.add_argument("-w", "--wait", type=float, help="Time sleep between API calls in seconds.")
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> FeederConfig:
    config = FeederConfig()
    config_path = Path(args.config)
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)

    for field_name in config.__dataclass_fields__:
        override = getattr(args, field_name, None)
        if override is not None:
            setattr(config, field_name, override)

    return config


def request_sleep(wait: float) -> None:
    if wait > 0:
        time.sleep(wait)


def check_ail(config: FeederConfig) -> Optional[str]:
    try:
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        response = requests.get(
            f"{config.ail_url}/ping",
            headers={"Content-Type": "application/json", "Authorization": config.api_key},
            verify=False,
            timeout=30,
        )
        data = response.json()
        if data.get("status") == "pong":
            return None
        return data.get("reason", "AIL ping failed")
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def publish_to_ail(config: FeederConfig, payload: dict) -> Optional[str]:
    try:
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        response = requests.post(
            f"{config.ail_url}/import/json/item",
            headers={"Content-Type": "application/json", "Authorization": config.api_key},
            data=json.dumps(payload, indent=2, sort_keys=True, default=str),
            verify=False,
            timeout=60,
        )
        data = response.json()
        if data.get("status") == "success":
            return None
        return data.get("reason", "AIL publish failed")
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def remove_manifest_row(manifest_file: Path, filename: str) -> None:
    try:
        if not manifest_file.exists():
            return
        with manifest_file.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows = [row for row in rows if row.get("filename") != filename]
        with manifest_file.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["filename", "filesize"])
            writer.writeheader()
            writer.writerows(rows)
    except Exception as exc:  # noqa: BLE001
        LOG.error("Failed to update manifest %s: %s", manifest_file, exc)


def iter_manifest(manifest_file: Path) -> Iterable[dict]:
    with manifest_file.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("filename"):
                yield row


def split_leak(leak_path: Path, chunk_size: int) -> None:
    LOG.info("Splitting leak: %s", leak_path)
    Filesplit().split(file=str(leak_path), split_size=chunk_size, output_dir=str(leak_path.parent), newline=True)


def prepare_payload(config: FeederConfig, leak_name: str, file_name: str, file_sha256: str, content: str) -> dict:
    compressed = base64.b64encode(gzip.compress(content.encode("utf-8"))).decode()
    return {
        "source": config.name,
        "source-uuid": config.uuid,
        "default-encoding": "UTF-8",
        "meta": {
            "Leaked:FileName": os.path.basename(leak_name),
            "Leaked:Chunked": file_name,
        },
        "data-sha256": file_sha256,
        "data": compressed,
    }


def process_manifest(config: FeederConfig, leak_path: Path) -> bool:
    manifest_file = leak_path.parent / MANIFEST_FILENAME
    if not manifest_file.exists():
        LOG.error("Manifest file missing: %s", manifest_file)
        return False

    ail_error = check_ail(config)
    if ail_error:
        LOG.error("AIL ping failed: %s", ail_error)
        return False

    for row in iter_manifest(manifest_file):
        file_name = row["filename"]
        file_size = int(row.get("filesize", 0))
        chunk_path = leak_path.parent / file_name
        if not chunk_path.exists():
            LOG.warning("Missing chunk file: %s", chunk_path)
            remove_manifest_row(manifest_file, file_name)
            continue

        LOG.info("Processing chunk: %s", file_name)
        request_sleep(config.wait)
        with chunk_path.open("rb") as handle:
            data = handle.read(file_size)
        file_sha256 = hashlib.sha256(data).hexdigest()
        text_content = data.decode("utf-8", errors="ignore")
        payload = prepare_payload(config, str(leak_path), file_name, file_sha256, text_content)

        publish_error = publish_to_ail(config, payload)
        if publish_error:
            LOG.error("Failed to publish %s: %s", file_name, publish_error)
            return False

        LOG.info("Published %s", file_name)
        request_sleep(config.wait)
        remove_manifest_row(manifest_file, file_name)
        chunk_path.unlink(missing_ok=True)

    return True


def cleanup_leak(out_dir: Path) -> None:
    if not out_dir.exists():
        return
    for entry in out_dir.iterdir():
        if entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)


def write_current_leak(leak_path: Path) -> None:
    Path(CURRENT_LEAK_FILENAME).write_text(str(leak_path), encoding="utf-8")


def read_current_leak() -> Optional[Path]:
    current = Path(CURRENT_LEAK_FILENAME)
    if current.exists():
        return Path(current.read_text(encoding="utf-8").strip())
    return None


def remove_current_leak_marker() -> None:
    marker = Path(CURRENT_LEAK_FILENAME)
    if marker.exists():
        marker.unlink()


def update_leak_list(leaks_dir: Path, unprocessed_dir: Path) -> bool:
    if not leaks_dir.exists():
        leaks_dir.mkdir(parents=True, exist_ok=True)

    list_of_files = get_list_of_files(str(leaks_dir), str(unprocessed_dir))
    if not list_of_files:
        return False

    with Path(LEAK_LIST_FILENAME).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Leaks"])
        for leak in list_of_files:
            writer.writerow([leak])
    return True


def move_next_leak(leaks_dir: Path, out_dir: Path, unprocessed_dir: Path) -> Optional[Path]:
    if not update_leak_list(leaks_dir, unprocessed_dir):
        return None

    leak_list = Path(LEAK_LIST_FILENAME)
    with leak_list.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        first = next(reader, None)
    if not first:
        return None

    source = leaks_dir / first["Leaks"]
    if not source.exists():
        return None

    destination = out_dir / source.name
    moved = shutil.move(str(source), str(destination))
    leak_path = Path(moved)
    write_current_leak(leak_path)
    return leak_path


def process_leaks(config: FeederConfig) -> None:
    base_dir = Path(__file__).resolve().parent
    paths = config.to_paths(base_dir)

    for directory in paths.values():
        directory.mkdir(parents=True, exist_ok=True)

    while True:
        current_leak = read_current_leak()
        if current_leak is None:
            current_leak = move_next_leak(paths["leaks"], paths["out"], paths["unprocessed"])
            if current_leak is None:
                LOG.info("No more leaks to process.")
                break

        manifest_file = current_leak.parent / MANIFEST_FILENAME
        if not manifest_file.exists():
            split_leak(current_leak, config.chunks)

        if process_manifest(config, current_leak):
            cleanup_leak(paths["out"])
            remove_current_leak_marker()
            continue

        LOG.warning("Stopping due to processing error. Resolve and rerun to resume.")
        break


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    configure_logging()
    args = parse_args()
    config = load_config(args)

    if not config.ail_url or not config.api_key:
        LOG.error("AIL URL and API key must be provided via config or CLI.")
        return 2

    process_leaks(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
