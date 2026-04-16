import sys
import os

# Must be set before importing streamlit — it checks __file__ to detect dev mode
os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

from streamlit.web import cli as stcli
import streamlit.file_util as _file_util


if __name__ == "__main__":
    # When bundled by PyInstaller, data files are extracted to sys._MEIPASS
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    app_path = os.path.join(base_path, "streamlit_app.py")
    static_path = os.path.join(base_path, "streamlit", "static")

    # Monkey-patch so Tornado serves the correct static folder from the bundle
    _file_util.get_static_dir = lambda: static_path

    sys.argv = [
        "streamlit", "run", app_path,
        "--server.headless=true",
    ]
    raise SystemExit(stcli.main())
