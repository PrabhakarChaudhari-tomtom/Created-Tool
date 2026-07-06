# Geospatial Format Converter

Streamlit app for converting geospatial data between GeoPackage, GeoParquet, GeoJSON, Shapefile, CSV, Avro, and ESRI FileGDB. Developed by the ADP Team, TomTom.

## Run

```
start.bat
```

This installs dependencies (`requirements.txt`) and launches the app at `http://localhost:8501`.

## Notes

- `app.py` / `converter.py` are loader stubs; the actual application source is stored compressed+encoded in `app.enc` / `converter.enc` and decoded in memory at runtime.
- Requires Python 3.13 (or any version supported by the pinned dependencies) with GDAL 3.6+ / OpenFileGDB support for FileGDB read/write.
