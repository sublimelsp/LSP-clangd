import json
import re
import urllib.request
from typing import Tuple

GITHUB_RELEASE_API_URL = "https://api.github.com/repos/{repository}/releases/latest"


def get_latest_release_tag(github_repo: str) -> str:
    """Returns the latest release tag for a Github repository 'username/reponame'.
    """
    api_url = GITHUB_RELEASE_API_URL.format(repository=github_repo)
    with urllib.request.urlopen(api_url) as f:
        str_data = f.read().decode("utf-8")
    json_data = json.loads(str_data)
    return json_data["tag_name"]


def get_latest_release_version(github_repo) -> Tuple[int, ...]:
    latest_tag = get_latest_release_tag(github_repo)
    return tuple(int(x) for x in re.findall(r"\d+", latest_tag))
