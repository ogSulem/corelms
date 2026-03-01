from __future__ import annotations

import sys

from app.launcher import main as launcher_main


def main() -> None:
    launcher_main(["worker"])


if __name__ == "__main__":
    main()
