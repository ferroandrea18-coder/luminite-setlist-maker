from streamlit.web import cli as stcli
import sys


if __name__ == "__main__":
    sys.argv = ["streamlit", "run", "streamlit_app.py"]
    raise SystemExit(stcli.main())
