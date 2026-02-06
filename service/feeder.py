from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Iterable, Iterator


try:
    from service.utils import get_list_of_files
except ModuleNotFoundError:
    from .utils import get_list_of_files

CURRENT_LEAK_FILENAME = "current_leak.txt"
MANIFEST_FILENAME = "fs_manifest.csv"
LEAK_LIST_FILENAME = "leak_list.csv"


@dataclass(frozen=True)
class FeederConfig:
    name: str
    leaks_folder: str
    out_folder: str
    unprocessed_folder: str
    chunks: int
    api_key: str
    ail_url: str
    uuid: str
    wait: float


class LeakFeeder:
    def __init__(self, config: FeederConfig) -> None:
        self.config = config
        self.start_time = time.time()
        self.base_dir = Path(__file__).resolve().parent.parent

    def _resolve_path(self, path_value: str) -> Path:
        candidate = Path(path_value)
        return candidate if candidate.is_absolute() else self.base_dir / candidate

    def _wait(self) -> None:
        Event().wait(self.config.wait)

    def _check_ail(self) -> bool | str:
        try:
            import requests
            from requests.packages.urllib3.exceptions import InsecureRequestWarning

            ail_ping = f"{self.config.ail_url}/ping"
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            response = requests.get(
                ail_ping,
                headers={"Content-Type": "application/json", "Authorization": self.config.api_key},
                verify=False,
                timeout=30,
            )
            data = response.json()
            if "status" in response.text:
                if data.get("status") == "pong":
                    return True
                if data.get("status") == "error":
                    return data.get("reason", "unknown error")
        except Exception as exc:
            return str(exc)
        return "unexpected response"

    def _publish(self, manifest_file: Path, file_name: str, data: str) -> bool:
        try:
            import requests
            from requests.packages.urllib3.exceptions import InsecureRequestWarning

            ail_url = f"{self.config.ail_url}/import/json/item"
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            response = requests.post(
                ail_url,
                headers={"Content-Type": "application/json", "Authorization": self.config.api_key},
                data=data,
                verify=False,
                timeout=60,
            )
            payload = response.json()
            self._wait()
            if "status" in response.text:
                if payload.get("status") == "success":
                    print(f"{file_name}: Successfully Pushed to AIL")
                    file_by_number = re.findall(r"[-+]?\d*\.\d+|\d+", file_name.split("_")[1])
                    file_to_del = f"{file_name.split('_')[0]}_{int(file_by_number[0]) - 1}"
                    file_path = manifest_file.parent / file_to_del
                    if file_path.exists():
                        file_path.unlink()
                    remove_split_manifest(manifest_file, "filename", file_name)
                    return True
                if payload.get("status") == "error":
                    print(payload.get("reason"))
        except Exception as exc:
            print(exc)
        return False

    def _prepare_payload(
        self, leak_name: Path, file_name: str, file_sha256: str, file_content: Iterable[str]
    ) -> dict:
        li2str = "".join(str(entry) for entry in file_content)
        compressed_b64 = base64.b64encode(gzip.compress(li2str.encode("utf-8"))).decode()
        return {
            "source": self.config.name,
            "source-uuid": self.config.uuid,
            "default-encoding": "UTF-8",
            "meta": {
                "Leaked:FileName": leak_name.name,
                "Leaked:Chunked": file_name,
            },
            "data-sha256": file_sha256,
            "data": compressed_b64,
        }

    def _send_to_ail(
        self,
        leak_name: Path,
        file_name: str,
        file_sha256: str,
        file_content: Iterable[str],
        manifest_file: Path,
    ) -> bool | str:
        print("Checking AIL API...")
        check_resp = self._check_ail()
        if check_resp is True:
            print(f"Starting to process content of: {file_name}")
            print(f"The sha256 of {file_name} content is : {file_sha256}")
            output = self._prepare_payload(leak_name, file_name, file_sha256, file_content)
            self._wait()
            return self._publish(manifest_file, file_name, data=json_dumps(output))
        return check_resp

    def _split_file(self, leak_path: Path) -> None:
        dir_path = leak_path.parent
        manifest_file = dir_path / MANIFEST_FILENAME
        if manifest_file.exists():
            print("Resuming from the last task")
            self._file_worker(leak_path, dir_path)
            return

        print("Splitting the file now")
        split_entries = split_to_manifest(leak_path, dir_path, self.config.chunks)
        if not split_entries:
            print("No content split, skipping.")
            return
        print("File split successfully")
        self._file_worker(leak_path, dir_path)

    def _file_worker(self, leak_name: Path, dir_path: Path) -> None:
        print("Starting to process splits")
        manifest_file = dir_path / MANIFEST_FILENAME
        if not dir_path.is_dir():
            print("Input directory is not a valid directory")
            return

        if not manifest_file.exists():
            print("Unable to locate manifest file")
            return

        print("Processing data from splits")
        for manifest_row in read_manifest(manifest_file):
            file_name = manifest_row["filename"]
            file_content_path = dir_path / file_name
            file_size = int(manifest_row["filesize"])
            with file_content_path.open(encoding="utf8", errors="ignore") as file_reader:
                self._wait()
                file_lines = file_reader.readlines()
            with file_content_path.open("rb") as file_reader:
                file_sha256 = hashlib.sha256(file_reader.read(file_size)).hexdigest()
            self._send_to_ail(leak_name, file_name, file_sha256, file_lines, manifest_file)
            self._wait()
        self.run()

    def _update_leak_list(self) -> bool:
        cur_dir = self._resolve_path(self.config.leaks_folder)
        unprocessed_folder = self._resolve_path(self.config.out_folder)

        if not cur_dir.exists():
            print(f"Leaks folder does not exist: {cur_dir}")
            return False

        if not list(cur_dir.iterdir()):
            manifest_file = unprocessed_folder / MANIFEST_FILENAME
            if manifest_file.exists():
                rows = list(read_manifest(manifest_file))
                return bool(rows)

        list_of_files = get_list_of_files(cur_dir, unprocessed_folder)
        print(f"list_of_files: {list_of_files}")

        with open(LEAK_LIST_FILENAME, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Leaks"])
            for file_name in list_of_files:
                writer.writerow([file_name])
        return True

    def _end_time(self) -> None:
        run_time = time.time() - self.start_time
        print(f"Run time(s): {run_time}")

    def _move_new_leak(self) -> bool:
        if self._update_leak_list():
            leak_list = self.base_dir / LEAK_LIST_FILENAME
            with leak_list.open(encoding="utf-8") as leak_file:
                reader = csv.DictReader(leak_file)
                first_row = next(reader, None)
            if not first_row:
                return False
            file_name = first_row["Leaks"]
            leak_source_path = self._resolve_path(self.config.leaks_folder) / file_name
            leak_destination_path = self._resolve_path(self.config.out_folder)
            if leak_source_path.exists():
                new_location = shutil.move(str(leak_source_path), str(leak_destination_path))
                with open(self.base_dir / CURRENT_LEAK_FILENAME, "w", encoding="utf-8") as file:
                    file.write(new_location)
                return True
        return False

    def run(self) -> None:
        leaks_folder = self._resolve_path(self.config.leaks_folder)
        unprocessed_leaks = self._resolve_path(self.config.out_folder)
        unprocessed_folder = self._resolve_path(self.config.unprocessed_folder)
        manifest_file = unprocessed_leaks / MANIFEST_FILENAME

        leaks_folder.mkdir(exist_ok=True)
        unprocessed_leaks.mkdir(exist_ok=True)
        unprocessed_folder.mkdir(exist_ok=True)

        if self._update_leak_list():
            current_leak_path = self.base_dir / CURRENT_LEAK_FILENAME
            if not current_leak_path.exists():
                print("Starting a new process")
                self._move_new_leak()
                leak_name = Path(current_leak_path.read_text(encoding="utf-8"))
                self._split_file(leak_name)
            else:
                if manifest_file.exists():
                    if not list(read_manifest(manifest_file)):
                        print("Cleaning from the last task")
                        folder_cleaner(unprocessed_leaks)
                        self.run()
                    else:
                        print("Processing from the last task")
                        leak_name = Path(current_leak_path.read_text(encoding="utf-8"))
                        self._split_file(leak_name)
                else:
                    if self._move_new_leak():
                        print("Processing new task")
                        leak_name = Path(current_leak_path.read_text(encoding="utf-8"))
                        self._split_file(leak_name)
                    else:
                        if current_leak_path.exists():
                            current_leak_path.unlink()
                        leak_list_txt = self.base_dir / "leak_list.txt"
                        if leak_list_txt.exists():
                            leak_list_txt.unlink()
                        print("No more leaks to process")
                        self._end_time()
        else:
            print("Leaks folder is empty !")
            self._end_time()


def json_dumps(payload: dict) -> str:
    return json.dumps(payload, indent=4, sort_keys=True, default=str)


def split_to_manifest(leak_path: Path, output_dir: Path, chunk_size: int) -> list[tuple[str, int]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")

    manifest_file = output_dir / MANIFEST_FILENAME
    manifest_entries: list[tuple[str, int]] = []
    with manifest_file.open("w", newline="", encoding="utf-8") as manifest:
        writer = csv.writer(manifest)
        writer.writerow(["filename", "filesize"])
        for index, chunk in enumerate(iter_split_lines(leak_path, chunk_size), start=1):
            chunk_name = f"{leak_path.name}_{index}"
            chunk_path = output_dir / chunk_name
            chunk_path.write_bytes(chunk)
            writer.writerow([chunk_name, len(chunk)])
            manifest_entries.append((chunk_name, len(chunk)))
    return manifest_entries


def iter_split_lines(file_path: Path, chunk_size: int) -> Iterator[bytes]:
    buffer = bytearray()
    with file_path.open("rb") as file_reader:
        while True:
            line = file_reader.readline()
            if not line:
                break
            if buffer and len(buffer) + len(line) > chunk_size:
                yield bytes(buffer)
                buffer.clear()
            buffer.extend(line)
        if buffer:
            yield bytes(buffer)


def read_manifest(manifest_file: Path) -> Iterable[dict[str, str]]:
    with manifest_file.open(encoding="utf-8") as reader:
        yield from csv.DictReader(reader)


def remove_split_manifest(file_path: Path, column_name: str, *values: str) -> None:
    rows = list(read_manifest(file_path))
    filtered_rows = [row for row in rows if row.get(column_name) not in values]
    with file_path.open("w", newline="", encoding="utf-8") as writer_file:
        writer = csv.DictWriter(writer_file, fieldnames=["filename", "filesize"])
        writer.writeheader()
        writer.writerows(filtered_rows)


def folder_cleaner(path: Path) -> None:
    """
    Will clean all folders and files in given path
    """
    for root, dirs, files in os.walk(path):
        for file_name in files:
            os.unlink(os.path.join(root, file_name))
        for dir_name in dirs:
            shutil.rmtree(os.path.join(root, dir_name))
