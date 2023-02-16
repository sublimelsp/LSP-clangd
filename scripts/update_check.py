import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from modules.github_utils import get_latest_release_version  # noqa: E402
from modules.version import CLANGD_VERSION  # noqa: E402


def main():
    latest = get_latest_release_version("clangd/clangd")
    latest_str = [str(s) for s in latest]
    with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:
        print(f'REQUIRES_UPDATE={int(latest > CLANGD_VERSION)}', file=fh)
        print(f'LATEST_TAG={".".join(latest_str)}', file=fh)
        print(f'BRANCH_NAME={"_".join(latest_str)}', file=fh)


if __name__ == "__main__":
    main()
