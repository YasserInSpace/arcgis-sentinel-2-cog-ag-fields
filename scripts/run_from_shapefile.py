"""
run_from_shapefile.py
Reads config.json, iterates over features in the AOI shapefile,
and runs the MDCS workflow for each feature to create a mosaic dataset.
"""

import os
import sys
import json
import subprocess
import re
import arcpy


def load_config(config_path):
    with open(config_path, 'r') as f:
        config = json.load(f)

    required = ['aoi_shapefile', 'output_folder', 'start_date', 'end_date', 'cloud_cover']
    for key in required:
        if key not in config:
            raise ValueError(f"Missing required key in config.json: '{key}'")

    return config


def get_feature_bbox(shapefile, feature_index, name_field):
    """Returns (bbox_str, mosaic_name) for a single feature using arcpy."""
    bbox = None
    mosaic_name = None

    fields = ['SHAPE@']
    if name_field:
        fields.append(name_field)

    current_index = 0
    with arcpy.da.SearchCursor(shapefile, fields) as cursor:
        for row in cursor:
            if current_index == feature_index:
                geom = row[0]
                ext = geom.extent
                # Project extent to WGS84 if needed
                sr_wgs84 = arcpy.SpatialReference(4326)
                if geom.spatialReference.factoryCode != 4326:
                    projected = geom.projectAs(sr_wgs84)
                    ext = projected.extent
                bbox = f"{ext.XMin},{ext.YMin},{ext.XMax},{ext.YMax}"
                if name_field and row[1]:
                    # Sanitize: keep only alphanumeric and underscores
                    raw_name = str(row[1])
                    mosaic_name = re.sub(r'[^A-Za-z0-9_]', '_', raw_name)
                break
            current_index += 1

    return bbox, mosaic_name


def count_features(shapefile):
    return int(arcpy.GetCount_management(shapefile)[0])


def safe_mosaic_name(base_name):
    """Ensure name starts with a letter and has no special chars."""
    name = re.sub(r'[^A-Za-z0-9_]', '_', base_name)
    if name and name[0].isdigit():
        name = 'F_' + name
    return name


def run_mdcs(python_exe, mdcs_script, config_xml, mosaic_path, bbox, start_date, end_date, cloud_cover, best_scene_only=False, mrf_cache='C:/mrfcache/cachingmrf', months=None):
    cmd = [
        python_exe,
        mdcs_script,
        f'-i:{config_xml}',
        f'-m:{mosaic_path}',
        '-c:CM+sentinelModifySrc+AF+AR+markduplicate+RRFMD+SP+CV',
        f'-p:{start_date}$startDate',
        f'-p:{end_date}$endDate',
        f'-p:{cloud_cover}$cloud',
        f'-p:{bbox}$coordinate',
        '-p:1$interval',
        f'-p:{"1" if best_scene_only else "0"}$best_scene_only',
        f'-p:{mrf_cache}$mrf_cache',
        f'-p:{",".join(str(m) for m in months) if months else "#"}$months'
    ]

    print(f"\n{'='*60}")
    print(f"Running MDCS for: {mosaic_path}")
    print(f"BBox: {bbox}")
    print(f"{'='*60}")

    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode == 0


def main():
    # Resolve paths relative to this script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    config_path = os.path.join(repo_root, 'config.json')

    if not os.path.exists(config_path):
        print(f"ERROR: config.json not found at {config_path}")
        sys.exit(1)

    config = load_config(config_path)

    shapefile    = config['aoi_shapefile']
    output_folder = config['output_folder']
    start_date   = config['start_date']
    end_date     = config['end_date']
    cloud_cover  = int(config['cloud_cover'])
    area_name       = safe_mosaic_name(config.get('area_name', '').strip())
    name_field      = config.get('name_field', '').strip()
    best_scene_only = config.get('best_scene_only', False)
    mrf_cache       = config.get('mrf_cache_folder', 'C:/mrfcache/cachingmrf').strip().replace('\\', '/')
    months          = config.get('months', [])

    python_exe  = sys.executable
    mdcs_script = os.path.join(script_dir, 'MDCS.py')
    config_xml  = os.path.join(repo_root, 'Parameter', 'Config', 'DEA.xml')

    # Validate inputs
    if not os.path.exists(shapefile):
        print(f"ERROR: Shapefile not found: {shapefile}")
        sys.exit(1)

    if not os.path.exists(mdcs_script):
        print(f"ERROR: MDCS.py not found at {mdcs_script}")
        sys.exit(1)

    # Create required directories
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(mrf_cache, exist_ok=True)

    # Validate name_field exists in shapefile
    if name_field:
        existing_fields = [f.name for f in arcpy.ListFields(shapefile)]
        if name_field not in existing_fields:
            print(f"WARNING: name_field '{name_field}' not found in shapefile fields: {existing_fields}")
            print("Falling back to index-based naming.")
            name_field = ''

    feature_count = count_features(shapefile)
    print(f"Found {feature_count} feature(s) in {shapefile}")

    if feature_count == 0:
        print("WARNING: Shapefile has no features. Nothing to process.")
        sys.exit(0)

    success_count = 0
    fail_count = 0
    skip_count = 0

    for i in range(feature_count):
        bbox, name_from_field = get_feature_bbox(shapefile, i, name_field)

        if bbox is None:
            print(f"WARNING: Could not get bbox for feature {i}, skipping.")
            skip_count += 1
            continue

        if name_from_field:
            base_name = safe_mosaic_name(name_from_field)
        else:
            base_name = f"Feature_{i + 1}"

        mosaic_name = f"{area_name}_{base_name}" if area_name else base_name

        gdb_name    = f"{mosaic_name}.gdb"
        gdb_path    = os.path.join(output_folder, gdb_name)
        mosaic_path = os.path.join(gdb_path, mosaic_name)
        # Use forward slashes for arcpy compatibility
        mosaic_path = mosaic_path.replace('\\', '/')

        if os.path.exists(gdb_path):
            print(f"WARNING: GDB already exists, it will be overwritten: {gdb_path}")

        ok = run_mdcs(python_exe, mdcs_script, config_xml,
                      mosaic_path, bbox, start_date, end_date, cloud_cover, best_scene_only, mrf_cache, months)

        if ok:
            print(f"[OK] {mosaic_name} -> {mosaic_path}")
            success_count += 1
        else:
            print(f"[FAILED] {mosaic_name} -> {mosaic_path}")
            fail_count += 1

    print(f"\n{'='*60}")
    print(f"Completed: {success_count} succeeded, {fail_count} failed, {skip_count} skipped")
    print(f"Output folder: {output_folder}")
    print(f"{'='*60}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
