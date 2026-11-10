"""Deploy to a Hugging Face Docker Space: push the tracked files and set secrets/variables via the HF API.

    set -a && . ./.env && set +a && python scripts/deploy_hf.py [--space <user>/hunar-delivery-agent]

Needs HF_TOKEN (write), GEMINI_API_KEY and DATABASE_URL in the environment. Secrets go to the Space's secret
store, never into the uploaded files.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
HEADER = """---
title: Hunar Delivery Agent
emoji: 🛵
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8080
pinned: false
short_description: Voice + chat agent for delivery-partner applications
---

"""


def main() -> None:
    api = HfApi(token=os.environ["HF_TOKEN"])
    user = api.whoami()["name"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default=f"{user}/hunar-delivery-agent")
    args = ap.parse_args()
    space = args.space
    url = f"https://{space.replace('/', '-').replace('_', '-').lower()}.hf.space"

    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    api.add_space_secret(space, "GEMINI_API_KEY", os.environ["GEMINI_API_KEY"])
    api.add_space_secret(space, "DATABASE_URL", os.environ["DATABASE_URL"])
    for key, value in {
        "PUBLIC_BASE_URL": url,
        "RECORD_WEBHOOK_URL": "http://127.0.0.1:8080/sink/records",
        "INACTIVITY_SECONDS": "600",
    }.items():
        api.add_space_variable(space, key, value)

    # Upload exactly what git tracks (so .env and local data can never be included), plus the HF header.
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    with tempfile.TemporaryDirectory() as tmp:
        for rel in files:
            dst = Path(tmp) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dst)
        readme = Path(tmp) / "README.md"
        readme.write_text(HEADER + readme.read_text())
        api.upload_folder(folder_path=tmp, repo_id=space, repo_type="space", delete_patterns="*",
                          commit_message="Deploy from local repo")
    print(f"Space: https://huggingface.co/spaces/{space}\nApp:   {url}")


if __name__ == "__main__":
    main()
