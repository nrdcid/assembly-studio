# (c) Copyright Riverlane 2025-2026. All rights reserved.
"""Download only the pinned, self-contained renderer and its licence notices."""

import argparse
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

VERSION = "0.7.0"
TARBALL_SHA256 = "34f5d55d88118ac3cd0629e65ce1791a7a81e212a0123b68b3af52b3bb2e865e"
DESTINATION = Path(__file__).resolve().parent / "vendor"
FILES = {
    "package/dist/deltakit-visualise.lite.umd.js": "deltakit-visualise.umd.js",
    "package/LICENSE": "LICENSE",
    "package/dist/THIRD-PARTY-NOTICES.txt": "THIRD-PARTY-NOTICES.txt",
}


def install(tarball: Path) -> None:
    """Verify the download and copy explicit files without extracting arbitrary paths."""
    if hashlib.sha256(tarball.read_bytes()).hexdigest() != TARBALL_SHA256:
        msg = "Renderer checksum mismatch; the downloaded bundle was not installed."
        raise ValueError(msg)
    DESTINATION.mkdir(exist_ok=True)
    with tarfile.open(tarball) as archive:
        for source, name in FILES.items():
            member = archive.getmember(source)
            if not member.isfile():
                msg = f"Expected a regular file for {source}."
                raise ValueError(msg)
            content = archive.extractfile(member)
            assert content is not None
            with (DESTINATION / name).open("wb") as target:
                shutil.copyfileobj(content, target)
    print(f"Installed deltakit-visualise@{VERSION} (lite renderer) into {DESTINATION}")


def main() -> None:
    """Fetch a package tarball with npm, avoiding its unused dependency tree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tarball", type=Path, help="Use an already downloaded package tarball.")
    args = parser.parse_args()
    if args.tarball:
        install(args.tarball)
        return
    if shutil.which("npm") is None:
        msg = "Install Node.js/npm to download the renderer, then run this script again."
        raise SystemExit(msg)
    with tempfile.TemporaryDirectory(prefix="assembly-studio-renderer-") as directory:
        subprocess.run(
            [
                "npm",
                "pack",
                f"deltakit-visualise@{VERSION}",
                "--registry=https://registry.npmjs.org/",
                "--pack-destination",
                directory,
                "--cache",
                str(Path(directory) / "npm-cache"),
            ],
            check=True,
        )
        install(Path(directory) / f"deltakit-visualise-{VERSION}.tgz")


if __name__ == "__main__":
    main()
