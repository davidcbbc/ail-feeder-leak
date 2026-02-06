from __future__ import annotations

import sys
from pathlib import Path

import configargparse

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.feeder import FeederConfig, LeakFeeder


def build_config() -> FeederConfig:
    args_parser = configargparse.ArgParser(default_config_files=["config.yaml"])
    args_parser.add("-g", "--config", is_config_file=True, help="Configuration file path.")
    args_parser.add("-n", "--name", required=True, help="Name of the feeder.")
    args_parser.add("-l", "--leaks_folder", required=True, help="Leaks Folder to parse and send to AIL.")
    args_parser.add("-r", "--out_folder", required=True, help="Output Folder of unprocessed split files.")
    args_parser.add("-a", "--unprocessed_folder", required=True, help="Output Folder of file that cannot be processed.")
    args_parser.add(
        "-c",
        "--chunks",
        type=int,
        required=True,
        env_var="FEEDER_LEAKS_CHUNKS",
        help="Chunks size of split files.",
    )
    args_parser.add("-k", "--api_key", required=True, help="API key for AIL authentication.")
    args_parser.add("-u", "--ail_url", required=True, help="AIL API URL.")
    args_parser.add("-i", "--uuid", required=True, help="Uniq identifier of the feeder.")
    args_parser.add("-w", "--wait", type=float, default=0.0, help="Time sleep between API calls in seconds.")

    options = args_parser.parse_args()
    return FeederConfig(
        name=options.name,
        leaks_folder=options.leaks_folder,
        out_folder=options.out_folder,
        unprocessed_folder=options.unprocessed_folder,
        chunks=options.chunks,
        api_key=options.api_key,
        ail_url=options.ail_url,
        uuid=options.uuid,
        wait=options.wait,
    )


def main() -> None:
    config = build_config()
    feeder = LeakFeeder(config)
    feeder.run()


if __name__ == "__main__":
    main()
