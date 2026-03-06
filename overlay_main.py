import logging

from dotenv import load_dotenv

from desktop_app.overlay_app import OverlayApp

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    app = OverlayApp()
    app.run()


if __name__ == "__main__":
    main()
