"""启动入口：python run.py（自动打开浏览器）。"""
import threading
import webbrowser

import uvicorn

from app.config import settings


def main() -> None:
    url = f"http://{settings.host}:{settings.port}"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Video2Guide 已启动：{url} （Ctrl+C 退出）")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
