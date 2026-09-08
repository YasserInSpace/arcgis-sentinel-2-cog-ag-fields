"""
preflight_check.py
Runs before the main workflow. Validates config, license, AOI and templates,
and warns about overwrites.
Exits with code 1 on hard errors, code 2 on overwrite prompt declined, 0 on success.
"""

import os
import sys
import json

import arcpy

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import aoi_source
import templates as template_packs


def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as handle:
        config = json.load(handle)
    if not config.get('aoi') and config.get('aoi_shapefile'):
        config['aoi'] = config['aoi_shapefile']
    return config


def check_license():
    status = arcpy.CheckProduct('arcinfo')
    # CheckProduct returns one of: AlreadyInitialized, Available, Unavailable,
    # NotLicensed, Failed, NotInitialized
    if status in ('AlreadyInitialized', 'Available'):
        return True
    for product in ('arceditor', 'arcview'):
        if arcpy.CheckProduct(product) in ('AlreadyInitialized', 'Available'):
            return True
    return False


def find_existing_gdbs(config, features):
    output_folder = str(config.get('output_folder', '')).strip()
    area_name = aoi_source.safe_name(str(config.get('area_name', '')).strip())

    if not output_folder or not os.path.exists(output_folder):
        return []

    existing = []
    for feature in features:
        mosaic_name = '%s_%s' % (area_name, feature.name) if area_name else feature.name
        gdb_path = os.path.join(output_folder, '%s.gdb' % mosaic_name)
        if os.path.exists(gdb_path):
            existing.append(gdb_path)
    return existing


def resolve_config_path(repo_root, argv):
    for arg in argv[1:]:
        if arg.startswith('--config='):
            return arg.split('=', 1)[1]
        if not arg.startswith('-'):
            return arg
    return os.path.join(repo_root, 'config.json')


def main(argv=None):
    argv = sys.argv if argv is None else argv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    config_path = resolve_config_path(repo_root, argv)

    try:
        config = load_config(config_path)
    except (IOError, OSError, json.JSONDecodeError) as exc:
        print('  ERROR: could not read config.json: %s' % exc)
        return 1

    errors = []
    features = []

    # --- Check 1: ArcGIS Pro license ---
    print('  Checking ArcGIS Pro license...')
    if not check_license():
        errors.append(
            'ArcGIS Pro license is not available or not checked out.\n'
            '  Make sure ArcGIS Pro is licensed and you are connected to the\n'
            '  license server (or using a named-user license that is signed in).'
        )
    else:
        print('  OK - ArcGIS Pro license available.')

    # --- Check 2: AOI resolves to usable search geometry ---
    aoi = str(config.get('aoi', '')).strip()
    print('  Checking AOI: %s' % (aoi or '(not set)'))
    try:
        features = aoi_source.resolve_aoi(
            aoi,
            str(config.get('name_field', '')).strip(),
            float(config.get('aoi_buffer_meters', 0) or 0),
        )
        types = sorted({f.geojson['type'] for f in features})
        print('  OK - %d AOI feature(s) resolved (%s).' % (len(features), ', '.join(types)))
    except ValueError as exc:
        errors.append(str(exc))
    except Exception as exc:
        errors.append('AOI could not be read: %s' % exc)

    # --- Check 3: output folder drive is reachable ---
    output_folder = str(config.get('output_folder', '')).strip()
    if output_folder:
        drive = os.path.splitdrive(output_folder)[0]
        if drive and not os.path.exists(drive + '\\'):
            errors.append(
                'Output folder drive not accessible: %s\\\n'
                '  Check that the drive letter in output_folder (config.json) is\n'
                '  correct and the drive is connected.' % drive
            )
        else:
            print('  OK - Output drive accessible (%s).' % (drive or 'current'))

    # --- Check 4: template packs resolve ---
    packs = config.get('template_packs', ['all'])
    resolved, warnings = template_packs.resolve_templates(
        packs, os.path.join(repo_root, 'Parameter', 'RasterFunctionTemplates'))
    for warning in warnings:
        print('  WARNING: %s' % warning)
    if not resolved:
        errors.append('No raster function templates resolved from template_packs: %s' % packs)
    else:
        print('  OK - %d raster template(s) selected.' % len(resolved))

    if errors:
        print()
        print('=' * 60)
        print('  PRE-FLIGHT FAILED')
        print('=' * 60)
        for index, error in enumerate(errors, 1):
            print('\n  ERROR %d: %s' % (index, error))
        print()
        return 1

    # --- Check 5: existing output warning ---
    existing_gdbs = find_existing_gdbs(config, features)
    if existing_gdbs:
        print()
        print('=' * 60)
        print('  WARNING: The following output GDBs already exist and will')
        print('  be OVERWRITTEN if you continue:')
        print('=' * 60)
        for gdb in existing_gdbs:
            print('    %s' % gdb)
        print()
        answer = input('  Type YES to overwrite and continue, or press Enter to cancel: ').strip().upper()
        if answer != 'YES':
            print('\n  Cancelled. No files were changed.\n')
            return 2

    print('\n  Pre-flight checks passed.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
