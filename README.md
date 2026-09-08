# arcgis-cog-mosaics

Builds ArcGIS Mosaic Datasets from Cloud-Optimized GeoTIFFs (COGs) for any area of
interest, streaming imagery on demand instead of downloading it.

The pipeline is **AOI → mosaic → raster templates**, and each stage is driven by
`config.json`:

1. **AOI** — any geometry, in any format arcpy reads, or a plain bounding box.
2. **Mosaic** — scenes discovered through the STAC API and assembled into a
   mosaic dataset that stores no pixels locally.
3. **Raster templates** — the on-the-fly renderings attached to the mosaic,
   chosen by template pack.

Imagery currently comes from Sentinel-2 L2A COGs on the AWS Open Data Registry
(<https://registry.opendata.aws/sentinel-2-l2a-cogs/>), giving a 12-band
spectral stack.

---

## Requirements

- ArcGIS Pro with `arcpy` (Python environment: `arcgispro-py3`)
- `pystac-client` — installed automatically by the batch file if missing
- Internet access to the AWS STAC API (`earth-search.aws.element84.com`)

---

## Quick start

There are two ways to run it. Both drive the same pipeline, so they behave
identically.

### From ArcGIS Pro (toolbox)

Add `CogMosaicTools.pyt` to the Catalog pane and open **Build Mosaics from AOI**.
The AOI can be any layer already in your map — including one with a selection,
so you can process just the features you have selected — and dates come from a
date picker rather than typed strings. Finished mosaics are returned as tool
output, ready to add to the map, and MDCS output appears in the geoprocessing
messages rather than a console window.

The toolbox takes a feature layer or feature class, so the bare bounding-box
string form of `aoi` is available from the command line only.

### From the command line

1. Copy `config.example.json` to `config.json` and fill in your values
2. Double-click `batchfiles/build_mosaics.bat`

The batch file validates the ArcGIS Pro installation, creates the required
folders, installs `pystac-client` if needed, runs pre-flight checks, and then
builds one mosaic per AOI feature.

To run a specific config directly:

```bash
"C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" scripts/run_workflow.py --config=C:/jobs/flood_survey.json
```

---

## Configuration

| Parameter | Description |
| --- | --- |
| `aoi` | The area of interest — see **AOI formats** below. Each feature produces its own mosaic. |
| `name_field` | Optional AOI field whose value names each mosaic |
| `aoi_buffer_meters` | Optional: expand every AOI by this many metres before searching |
| `area_name` | Prefix for output mosaic names (e.g. `KSA` → `KSA_Field_A`) |
| `start_date` / `end_date` | Search range (`YYYY-MM-DD`) |
| `cloud_cover` | Maximum scene cloud cover percentage (0–100) |
| `months` | Optional: restrict to given months, e.g. `[6,7,8]`. `[]` for all |
| `scene_selection` | `all`, `best_scene_only`, or `date_coherent` — see below |
| `template_packs` | Which raster templates to attach — see below |
| `output_folder` | Folder where geodatabases and mosaic datasets are written |
| `mrf_cache_folder` | Local folder for the MRF tile cache |

Earlier configs still work: `aoi_shapefile` is read as `aoi`, and a
`best_scene_only: true` / `false` key is read as `scene_selection` of
`best_scene_only` / `all`.

### AOI formats

`aoi` accepts any of:

- a shapefile, GeoJSON file, or feature class in a geodatabase
- a bounding box string, `"minx,miny,maxx,maxy"` in WGS84
- any geometry type — **points and lines are buffered into search areas
  automatically** (at least 100 m, or `aoi_buffer_meters` if larger)

Projected inputs are reprojected, and the search uses the true AOI outline
rather than its bounding box. For compact AOIs the difference is negligible; for
corridor-shaped ones — pipelines, rivers, coastlines, borders — searching by
bounding box typically pulls in around three times as many scenes as needed.

Very complex outlines are reduced to their convex hull (and, failing that, their
extent) so the search geometry stays within what STAC servers accept. Every
reduction is a superset of the original, so no scene is ever missed.

### Scene selection

| Mode | Behaviour | Use when |
| --- | --- | --- |
| `all` | Every scene in range | You want the full time series |
| `best_scene_only` | The best scene for each tile, whatever its date | You want the mosaic built from the clearest imagery available anywhere in the date range |
| `date_coherent` | A single acquisition day, chosen for widest tile coverage | The mosaic must represent one moment — change detection, flood mapping, fire progression, before/after comparison |

`best_scene_only` ranks scenes **purely on cloud cover, ignoring date
entirely**, so each tile contributes the clearest image found across the whole
range — even if that image is the oldest one available.
Date is used only to break ties between scenes of equal cloud cover, where the
more recent wins. Tiles therefore come from whichever dates were clearest, which
is the intent: the cleanest possible picture of the area.

`date_coherent` trades that clarity for temporal consistency, and is the right
choice only when the mosaic has to represent a single point in time.

### Template packs

`template_packs` selects which raster function templates are attached to the
mosaic, so a job only carries the renderings it needs:

| Pack | Contents |
| --- | --- |
| `imagery` | Natural Color, Color Infrared, Short-wave Infrared (with and without DRA) |
| `vegetation` | NDVI variants, Agriculture |
| `water` | NDWI variants, NDMI, Bathymetric |
| `fire` | Normalized Burn Ratio, Short-wave Infrared |
| `urban` | NDBI, Short-wave Infrared, Natural Color |
| `geology` | Geology, Short-wave Infrared |
| `snow` | NDSI, Natural Color |

Use `["all"]` for everything, or combine packs: `["imagery","water"]` for a
flood-mapping job. Overlapping packs are de-duplicated, and the first template
in the resolved list becomes the mosaic's default rendering.

### Display notes for ArcGIS Pro

The index templates come in two kinds, and it matters which you pick:

- **Raw** (`NDVI Raw`, `NDSI Raw`, `NDWI Raw`, ...) output the actual float index
  values, for analysis and extraction. They carry no colour table.
- **Colormap / Colorized** (`NDVI Colormap`, `NDVI - with VRE Colorized`, ...)
  carry their own colour ramp and render correctly with no further setup. Use
  these when you want to *look* at an index.

A Raw template added to a map can appear as a single flat colour, with the
legend reading `3.40282e+38` to `-3.40282e+38`. Those are the float32 type
limits: Pro defaults the layer to `statsType: Dataset`, finds no statistics for
the template's float output, and stretches across the whole theoretical float
range, so every real value collapses onto one colour.

To fix it, select the **Image** sublayer and set
**Symbology → Stretch → Statistics → From Current Display Extent**. The legend
snaps to the real index range and the image renders correctly.

This is a layer rendering setting, not a property of the mosaic. Calculating
statistics on the mosaic dataset does *not* change it — verified by comparing
the saved layer renderer for mosaics built with and without dataset statistics,
which came out identical.

---

## Output

For each AOI feature, a separate File Geodatabase and Mosaic Dataset:

```text
{output_folder}/{area_name}_{feature_name}.gdb/{area_name}_{feature_name}
```

The mosaic stores **no raster pixels locally** — imagery is streamed on demand
from S3 COGs through an MRF tile cache. Opening the mosaic in ArcGIS Pro lets
you switch between the attached processing templates.

Each feature is reported as `OK` (with its scene count), `EMPTY` (no scenes
matched), or `FAILED`, and the run exits non-zero if any feature did not
produce a mosaic.

---

## Repository structure

```text
├── CogMosaicTools.pyt               # ArcGIS Pro toolbox
├── batchfiles/
│   └── build_mosaics.bat           # Command line entry point
├── config.json                     # Your configuration
├── config.example.json             # Template with documentation for every key
├── Parameter/
│   ├── Config/mosaic_workflow.xml  # MDCS workflow configuration
│   ├── RasterFunctionTemplates/    # Raster function templates
│   └── Rastertype/                 # Raster type definition
├── scripts/
│   ├── workflow.py                 # The pipeline, shared by toolbox and CLI
│   ├── run_workflow.py             # Command line wrapper around workflow.py
│   ├── aoi_source.py               # AOI resolution and search geometry
│   ├── templates.py                # Template pack resolution
│   ├── preflight_check.py          # Pre-flight validation
│   ├── MDCS.py / MDCS_UC.py        # MDCS entry point and custom commands
│   └── ...                         # Supporting scripts
└── tests/
    ├── test_logic.py               # No ArcGIS licence needed
    └── test_aoi.py                 # Needs a licence; skips cleanly without one
```

---

## Tests

```bash
"C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" tests/test_logic.py
"C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" tests/test_aoi.py
```

`test_aoi.py --live` additionally checks every generated AOI geometry against
the live STAC API.
