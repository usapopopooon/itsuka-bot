"""`python -m src.web` で uvicorn を起動するためのエントリ。"""

from src.web.app import run

if __name__ == "__main__":
    run()
