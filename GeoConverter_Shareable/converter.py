# Geospatial Format Converter - ADP Team, TomTom
# (protected build - source not distributed)
import base64 as _b, zlib as _z, os as _o, sys as _s, types as _t
_d = _o.path.dirname(_o.path.abspath(__file__))
_src = _z.decompress(_b.b64decode(open(_o.path.join(_d, "converter.enc"), "rb").read()))
_m = _t.ModuleType(__name__); _m.__file__ = __file__
_s.modules[__name__] = _m
exec(compile(_src, __file__, "exec"), _m.__dict__)
