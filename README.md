# arcgis-sentinel-2-cog-ag-fields

This repository automates creation of Sentinel-2 L2A Mosaic Datasets from Cloud-Optimized GeoTIFFs (COGs) hosted on AWS Open Data Registry: <https://registry.opendata.aws/sentinel-2-l2a-cogs/>

Each mosaic includes all 15 Sentinel-2 L2A bands along with 24 pre-configured processing templates for rendering imagery composites and spectral indices on-the-fly in ArcGIS Pro (Agriculture, NDVI, NDWI, NDMI, Color Infrared, etc.).

---

## Requirements

- ArcGIS Pro with `arcpy` (Python environment: `arcgispro-py3`)
- `pystac-client` — installed automatically by the batch file if missing
- Internet access to AWS STAC API (`earth-search.aws.element84.com`)

---

## Quick Start

1. Edit `config.json` with your AOI shapefile, date range, and settings
2. Double-click `batchfiles/build_sentinel2_mosaics.bat`

The batch file will automatically:

- Validate ArcGIS Pro Python installation
- Create required folders (`output_folder`, `mrf_cache_folder`)
- Install `pystac-client` if not present
- Run the workflow for each feature in your shapefile

---

## Configuration

All settings are managed through `config.json`:

| Parameter | Description |
| --- | --- |
| `aoi_shapefile` | Path to input shapefile. Each feature creates a separate mosaic. |
| `name_field` | Optional shapefile field to use as mosaic name |
| `area_name` | Prefix for output mosaic names (e.g. `KSA` → `KSA_Feature_1`) |
| `start_date` | Start of Sentinel-2 search range (`YYYY-MM-DD`) |
| `end_date` | End of Sentinel-2 search range (`YYYY-MM-DD`) |
| `cloud_cover` | Maximum cloud cover percentage (0–100) |
| `best_scene_only` | If `true`, keeps only the best scene per Sentinel-2 tile (lowest cloud cover, non-overlapping) |
| `output_folder` | Folder where GDB and mosaic datasets are saved |
| `mrf_cache_folder` | Local folder for MRF tile cache |

---

## Output

For each feature in the shapefile, a separate File Geodatabase and Mosaic Dataset is created at:

```text
{output_folder}/{area_name}_{feature_name}.gdb/{area_name}_{feature_name}
```

The mosaic stores **no raster pixels locally** — imagery is streamed on-demand from AWS S3 COGs. Opening the mosaic in ArcGIS Pro allows switching between all 24 processing templates.

---

## Processing Templates

| Template | Bands | Purpose |
| --- | --- | --- |
| Natural Color | B4-B3-B2 | True color |
| Agriculture | B11-B8-B2 | Crop vigor |
| Color Infrared | B8-B4-B3 | Vegetation health |
| Short-wave Infrared | B12-B11-B4 | Geological mapping |
| NDVI | (B8-B4)/(B8+B4) | Vegetation index |
| NDWI | (B3-B8)/(B3+B8) | Water bodies |
| NDMI | (B8-B11)/(B8+B11) | Moisture content |
| NBR | (B8-B12)/(B8+B12) | Burned areas |
| NDBI | (B11-B8)/(B11+B8) | Built-up areas |

---

## Repository Structure

```text
├── batchfiles/
│   └── build_sentinel2_mosaics.bat   # Entry point — double-click to run
├── config.json                        # User configuration
├── Parameter/
│   ├── Config/DEA.xml                 # MDCS workflow configuration
│   ├── RasterFunctionTemplates/       # 24 processing templates
│   └── Rastertype/                    # Sentinel-2 raster type definition
├── scripts/
│   ├── run_from_shapefile.py          # Shapefile AOI workflow runner
│   ├── MDCS_UC.py                     # Custom MDCS user commands
│   ├── MDCS.py                        # MDCS main entry point
│   └── ...                            # Supporting scripts
└── Requirements.txt
```
