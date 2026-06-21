"""
preflight_check.py
Runs before the main workflow. Validates config, license, and warns about overwrites.
Exits with code 1 on hard errors, code 2 on overwrite prompt declined, 0 on success.
"""

import os
import sys
import json
import re
import arcpy


def load_config(config_path):
    with open(config_path, 'r') as f:
        return json.load(f)


def safe_mosaic_name(name):
    name = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if name and name[0].isdigit():
        name = 'F_' + name
    return name


def check_license():
    status = arcpy.CheckProduct("arcinfo")
    # CheckProduct returns one of: AlreadyInitialized, Available, Unavailable, NotLicensed, Failed, NotInitialized
    if status in ("AlreadyInitialized", "Available"):
        return True
    # Try lower-tier licenses
    for product in ("arceditor", "arcview"):
        status = arcpy.CheckProduct(product)
        if status in ("AlreadyInitialized", "Available"):
            return True
    return False


def find_existing_gdbs(config):
    output_folder = config.get('output_folder', '').strip()
    area_name = safe_mosaic_name(config.get('area_name', '').strip())
    shapefile = config.get('aoi_shapefile', '').strip()
    name_field = config.get('name_field', '').strip()

    if not os.path.exists(output_folder):
        return []  # folder doesn't exist yet, nothing to overwrite

    existing = []

    try:
        feature_count = int(arcpy.GetCount_management(shapefile)[0])
    except Exception:
        return []

    fields = ['SHAPE@']
    if name_field:
        try:
            existing_fields = [f.name for f in arcpy.ListFields(shapefile)]
            if name_field not in existing_fields:
                name_field = ''
        except Exception:
            name_field = ''
    if name_field:
        fields.append(name_field)

    try:
        with arcpy.da.SearchCursor(shapefile, fields) as cursor:
            for i, row in enumerate(cursor):
                if name_field and len(row) > 1 and row[1]:
                    base_name = safe_mosaic_name(str(row[1]))
                else:
                    base_name = f"Feature_{i + 1}"

                mosaic_name = f"{area_name}_{base_name}" if area_name else base_name
                gdb_path = os.path.join(output_folder, f"{mosaic_name}.gdb")
                if os.path.exists(gdb_path):
                    existing.append(gdb_path)
    except Exception:
        pass

    return existing


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    config_path = os.path.join(repo_root, 'config.json')

    config = load_config(config_path)

    errors = []
    warnings = []

    # --- Check 1: ArcGIS Pro license ---
    print("  Checking ArcGIS Pro license...")
    if not check_license():
        errors.append(
            "ArcGIS Pro license is not available or not checked out.\n"
            "  Make sure ArcGIS Pro is licensed and you are connected to the\n"
            "  license server (or using a named-user license that is signed in)."
        )
    else:
        print("  OK - ArcGIS Pro license available.")

    # --- Check 2: Shapefile exists ---
    shapefile = config.get('aoi_shapefile', '').strip()
    print(f"  Checking shapefile: {shapefile}")
    if not shapefile:
        errors.append(
            "aoi_shapefile is empty in config.json.\n"
            "  Open config.json and set aoi_shapefile to the path of your shapefile."
        )
    elif not os.path.exists(shapefile):
        errors.append(
            f"Shapefile not found: {shapefile}\n"
            "  Open config.json and update aoi_shapefile to the correct path.\n"
            "  Use forward slashes, e.g.: C:/data/my_fields/fields.shp"
        )
    else:
        print("  OK - Shapefile found.")

    # --- Check 3: Output folder path is on a reachable drive ---
    output_folder = config.get('output_folder', '').strip()
    if output_folder:
        drive = os.path.splitdrive(output_folder)[0]
        if drive and not os.path.exists(drive + '\\'):
            errors.append(
                f"Output folder drive not accessible: {drive}\\\n"
                "  Check that the drive letter in output_folder (config.json) is correct\n"
                "  and the drive is connected."
            )
        else:
            print(f"  OK - Output drive accessible ({drive or 'current'}).")

    # --- Hard errors: stop here ---
    if errors:
        print()
        print("=" * 60)
        print("  PRE-FLIGHT FAILED")
        print("=" * 60)
        for i, err in enumerate(errors, 1):
            print(f"\n  ERROR {i}: {err}")
        print()
        sys.exit(1)

    # --- Check 4: Existing GDB overwrite warning ---
    if os.path.exists(shapefile):
        existing_gdbs = find_existing_gdbs(config)
        if existing_gdbs:
            print()
            print("=" * 60)
            print("  WARNING: The following output GDBs already exist and will")
            print("  be OVERWRITTEN if you continue:")
            print("=" * 60)
            for gdb in existing_gdbs:
                print(f"    {gdb}")
            print()
            answer = input("  Type YES to overwrite and continue, or press Enter to cancel: ").strip().upper()
            if answer != "YES":
                print()
                print("  Cancelled. No files were changed.")
                print()
                sys.exit(2)

    print()
    print("  Pre-flight checks passed.")
    print()
    sys.exit(0)


if __name__ == '__main__':
    main()
