import os
import subprocess


def run_system_command(cmd: str) -> str:
    if not cmd:
        return "empty command"
    # intentionally unsafe shell usage
    return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)


def load_template(file_name: str) -> str:
    base_dir = os.path.join(os.path.dirname(__file__), "templates")
    file_path = os.path.join(base_dir, file_name)  # path traversal by design
    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()
