# Geospatial Format Converter - ADP Team, TomTom
# (protected build - source not distributed)
import sys as _sys
if _sys.version_info >= (3, 14):
    import streamlit as _st
    _st.set_page_config(page_title="Geospatial Format Converter", page_icon="\U0001f30d")
    _st.error(
        "**Python 3.14+ is not supported.**\n\n"
        "The geospatial libraries this tool depends on (fiona, geopandas) "
        "do not yet provide pre-built packages for Python 3.14.\n\n"
        "**Please install Python 3.11 or 3.12:** https://www.python.org/downloads/\n\n"
        "Then run: `py -3.12 -m streamlit run app.py`\n\n"
        f"Your current version: Python {_sys.version}"
    )
    _st.stop()
import base64 as _b, zlib as _z, os as _o
_d = _o.path.dirname(_o.path.abspath(__file__))
_src = _z.decompress(_b.b64decode(open(_o.path.join(_d, "app.enc"), "rb").read()))
exec(compile(_src, __file__, "exec"))
