#!/usr/bin/env python3
"""
Auto-install MongoDB Community Server (tarball) + MongoDB Compass on macOS
Apple Silicon (M1/M2/M3) – tested workflow for macOS Tahoe (26)

Run from PyCharm Terminal or system terminal:
    python install_mongodb_macos.py

⚠️ Requires:
- Admin password (sudo)
- Internet connection
"""

import os
import subprocess
import sys
from pathlib import Path

MONGODB_VERSION = "8.2.2"
MONGODB_DIR = f"mongodb-macos-aarch64-{MONGODB_VERSION}"
MONGODB_TGZ = f"{MONGODB_DIR}.tgz"
MONGODB_URL = f"https://fastdl.mongodb.org/osx/{MONGODB_TGZ}"
COMPASS_URL = "https://downloads.mongodb.com/compass/mongodb-compass-1.45.0-darwin-arm64.dmg"

INSTALL_BASE = "/opt"
MONGO_INSTALL_PATH = f"{INSTALL_BASE}/mongodb"
DATA_DIR = "/data/db"
LOG_DIR = "/var/log/mongodb"
CONF_PATH = f"{MONGO_INSTALL_PATH}/mongod.conf"


def run(cmd: str, sudo=False):
    if sudo:
        cmd = f"sudo {cmd}"
    print(f"\n▶ {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def main():
    if sys.platform != "darwin":
        sys.exit("❌ This installer is for macOS only")

    home = Path.home()
    downloads = home / "Downloads"

    # 1. Download MongoDB
    run(f"curl -L -o {downloads}/{MONGODB_TGZ} {MONGODB_URL}")

    # 2. Extract
    run(f"tar -xzf {downloads}/{MONGODB_TGZ} -C {downloads}")

    # 3. Move to /opt
    run(f"rm -rf {MONGO_INSTALL_PATH}", sudo=True)
    run(f"mv {downloads}/{MONGODB_DIR} {MONGO_INSTALL_PATH}", sudo=True)

    # 4. PATH setup
    zshrc = home / ".zshrc"
    path_line = "export PATH=/opt/mongodb/bin:$PATH\n"
    if path_line not in zshrc.read_text():
        zshrc.write_text(zshrc.read_text() + "\n" + path_line)

    # 5. Create data & log dirs
    run(f"mkdir -p {DATA_DIR}", sudo=True)
    run(f"mkdir -p {LOG_DIR}", sudo=True)
    run(f"chown -R {os.getlogin()} {DATA_DIR}", sudo=True)
    run(f"chown -R {os.getlogin()} {LOG_DIR}", sudo=True)

    # 6. Create config
    conf = f"""
systemLog:
  destination: file
  path: {LOG_DIR}/mongod.log
  logAppend: true

storage:
  dbPath: {DATA_DIR}
  journal:
    enabled: true

net:
  bindIp: 127.0.0.1
  port: 27017

processManagement:
  fork: true
"""
    Path(CONF_PATH).write_text(conf)

    # 7. Start MongoDB
    run(f"{MONGO_INSTALL_PATH}/bin/mongod --config {CONF_PATH}")

    # 8. Download & mount Compass
    dmg_path = downloads / "mongodb-compass.dmg"
    run(f"curl -L -o {dmg_path} {COMPASS_URL}")
    run(f"hdiutil attach {dmg_path}")
    run("cp -R /Volumes/MongoDB\ Compass/MongoDB\ Compass.app /Applications", sudo=True)
    run("hdiutil detach /Volumes/MongoDB\\ Compass")

    print("\n✅ MongoDB Server + Compass installed successfully")
    print("Connect using: mongodb://localhost:27017")


if __name__ == "__main__":
    main()
