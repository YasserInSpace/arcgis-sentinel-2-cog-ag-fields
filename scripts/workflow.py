"""
workflow.py
The AOI -> mosaic -> raster templates pipeline, independent of how it is driven.

Both the command line runner and the ArcGIS Pro toolbox call build_mosaics(),
so they cannot drift apart. Callers pass a Reporter so progress goes to stdout
or to the geoprocessing messages as appropriate.
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess

import arcpy

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import aoi_source
import templates as template_packs


DEFAULT_MRF_CACHE = 'C:/mrfcache/cachingmrf'
VALID_SELECTION = ('all', 'best_scene_only', 'date_coherent')
COMMAND_CHAIN = 'CM+stacBuildSource+AF+AR+markduplicate+RRFMD+SP+CV'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)


class Reporter(object):
    """Default reporter: plain stdout, for the command line."""

    def message(self, text):
        print(text)

    def warning(self, text):
        print('  WARNING: %s' % text)

    def error(self, text):
        print('  ERROR: %s' % text)

    def detail(self, text):
        """Verbose per-line output from the MDCS subprocess."""
        print(text)

    def progress(self, done, total, label):
        pass


class Result(object):
    def __init__(self, status, name, item_count, mosaic_path):
        self.status = status            # OK | EMPTY | FAILED
        self.name = name
        self.item_count = item_count
        self.mosaic_path = mosaic_path


def python_executable():
    """Path to python.exe for the MDCS subprocess.

    sys.executable is ArcGISPro.exe when running inside Pro, so deriving the
    interpreter from the environment prefix is the only safe option.
    """
    candidate = os.path.join(sys.exec_prefix, 'python.exe')
    return candidate if os.path.exists(candidate) else sys.executable


def resolve_scene_selection(config, reporter=None):
    """Resolve the scene selection mode.

    'best_scene_only' used to be a true/false key of its own; it is now one of
    the scene_selection modes. Old configs are still read, with a note pointing
    at the replacement, rather than silently changing what they do.
    """
    reporter = reporter or Reporter()
    selection = str(config.get('scene_selection', '') or '').strip().lower()
    if not selection:
        legacy = config.get('best_scene_only')
        if legacy is None:
            selection = 'all'
        else:
            selection = 'best_scene_only' if legacy else 'all'
            reporter.warning('the best_scene_only true/false key is deprecated. '
                             'Set "scene_selection": "%s" instead.' % selection)
    if selection not in VALID_SELECTION:
        reporter.warning("unknown scene_selection '%s'; using 'all'. Valid: %s"
                         % (selection, ', '.join(VALID_SELECTION)))
        selection = 'all'
    return selection


def count_mosaic_items(mosaic_path):
    """Number of rows in the mosaic dataset, or -1 if it was never created."""
    try:
        if not arcpy.Exists(mosaic_path):
            return -1
        return int(arcpy.management.GetCount(mosaic_path)[0])
    except Exception:
        return -1


def _no_window_flags():
    """Keep the MDCS subprocess from opening its own console window.

    A GUI host such as ArcGIS Pro has no console, so Windows would allocate a
    new one per feature and MDCS output would vanish with it.
    """
    if os.name != 'nt':
        return {}
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)}


def _run_mdcs(config_xml, mosaic_path, feature, geojson_path, start_date,
              end_date, cloud_cover, scene_selection, mrf_cache, months,
              reporter=None):
    reporter = reporter or Reporter()
    command = [
        python_executable(),
        os.path.join(SCRIPT_DIR, 'MDCS.py'),
        '-i:%s' % config_xml,
        '-m:%s' % mosaic_path,
        '-c:%s' % COMMAND_CHAIN,
        '-p:%s$startDate' % start_date,
        '-p:%s$endDate' % end_date,
        '-p:%s$cloud' % cloud_cover,
        '-p:%s$coordinate' % feature.bbox_string,
        '-p:1$interval',
        '-p:%s$scene_selection' % scene_selection,
        '-p:%s$aoi_geojson' % geojson_path,
        '-p:%s$mrf_cache' % mrf_cache,
        '-p:%s$months' % (','.join(str(m) for m in months) if months else '#'),
    ]

    # Stream the output through the reporter rather than letting it go to a
    # console, so it reaches whichever surface is driving the run.
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding='utf-8', errors='replace',
        **_no_window_flags())

    with process.stdout as stream:
        for line in stream:
            line = line.rstrip()
            if line:
                reporter.detail(line)

    return process.wait() == 0


def build_mosaics(config, reporter=None):
    """Run the pipeline for every AOI feature. Returns a list of Result.

    Raises ValueError when the configuration itself cannot be used, so callers
    can report that differently from a per-feature failure.
    """
    reporter = reporter or Reporter()

    if not config.get('aoi') and config.get('aoi_shapefile'):
        config['aoi'] = config['aoi_shapefile']

    missing = [key for key in ('aoi', 'output_folder', 'start_date', 'end_date', 'cloud_cover')
               if not config.get(key) and config.get(key) != 0]
    if missing:
        raise ValueError('Missing required setting(s): %s' % ', '.join(missing))

    output_folder = config['output_folder']
    start_date = config['start_date']
    end_date = config['end_date']
    cloud_cover = int(config['cloud_cover'])
    area_name = aoi_source.safe_name(str(config.get('area_name', '')).strip())
    name_field = str(config.get('name_field', '')).strip()
    buffer_meters = float(config.get('aoi_buffer_meters', 0) or 0)
    months = config.get('months', []) or []
    mrf_cache = str(config.get('mrf_cache_folder', DEFAULT_MRF_CACHE)).strip().replace('\\', '/')
    scene_selection = resolve_scene_selection(config, reporter)
    packs = config.get('template_packs', ['all'])

    mdcs_script = os.path.join(SCRIPT_DIR, 'MDCS.py')
    if not os.path.exists(mdcs_script):
        raise ValueError('MDCS.py not found at %s' % mdcs_script)

    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(mrf_cache, exist_ok=True)

    # --- Stage 1: AOI ---
    features = aoi_source.resolve_aoi(config['aoi'], name_field, buffer_meters)
    reporter.message('AOI: %d feature(s) from %s' % (len(features), config['aoi']))
    reporter.message('Scene selection: %s' % scene_selection)

    # --- Stage 3 setup: templates, resolved once and shared by every feature ---
    templates_dir = os.path.join(REPO_ROOT, 'Parameter', 'RasterFunctionTemplates')
    resolved_templates, warnings = template_packs.resolve_templates(packs, templates_dir)
    for warning in warnings:
        reporter.warning(warning)
    if not resolved_templates:
        raise ValueError('No raster function templates resolved from: %s' % packs)
    reporter.message('Templates: %d from pack(s) %s (default: %s)'
                     % (len(resolved_templates), packs, resolved_templates[0]))

    source_xml = os.path.join(REPO_ROOT, 'Parameter', 'Config', 'mosaic_workflow.xml')
    run_dir = tempfile.mkdtemp(prefix='mdcs_run_')
    results = []

    try:
        run_xml = template_packs.write_run_config(
            source_xml, os.path.join(run_dir, 'run_config.xml'), resolved_templates)

        # --- Stage 2: one mosaic per AOI feature ---
        for index, feature in enumerate(features, 1):
            mosaic_name = '%s_%s' % (area_name, feature.name) if area_name else feature.name
            gdb_path = os.path.join(output_folder, '%s.gdb' % mosaic_name)
            mosaic_path = os.path.join(gdb_path, mosaic_name).replace('\\', '/')

            reporter.progress(index - 1, len(features), mosaic_name)
            reporter.message('\n%s' % ('=' * 60))
            reporter.message('Building %d/%d: %s' % (index, len(features), mosaic_path))
            reporter.message('AOI: %s (%s)' % (feature.name, feature.geojson['type']))
            reporter.message('%s' % ('=' * 60))

            if os.path.exists(gdb_path):
                reporter.warning('overwriting existing geodatabase: %s' % gdb_path)

            geojson_path = os.path.join(run_dir, '%s.geojson' % mosaic_name)
            with open(geojson_path, 'w', encoding='utf-8') as handle:
                json.dump(feature.geojson, handle)

            started = _run_mdcs(run_xml, mosaic_path, feature,
                                geojson_path.replace('\\', '/'), start_date, end_date,
                                cloud_cover, scene_selection, mrf_cache, months,
                                reporter)

            item_count = count_mosaic_items(mosaic_path)
            if not started:
                status = 'FAILED'
            elif item_count <= 0:
                # MDCS can report success while adding nothing, so an empty
                # mosaic is called out rather than counted as a win.
                status = 'EMPTY'
            else:
                status = 'OK'

            results.append(Result(status, mosaic_name, item_count, mosaic_path))
            reporter.message('[%s] %s (%s item(s))'
                             % (status, mosaic_name,
                                item_count if item_count >= 0 else 'no mosaic'))
        reporter.progress(len(features), len(features), 'done')
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

    return results


def summarise(results, output_folder, reporter=None):
    """Print the run summary. Returns a process exit code."""
    reporter = reporter or Reporter()
    ok = [r for r in results if r.status == 'OK']
    empty = [r for r in results if r.status == 'EMPTY']
    failed = [r for r in results if r.status == 'FAILED']

    reporter.message('\n%s' % ('=' * 60))
    reporter.message('Completed: %d built, %d empty, %d failed'
                     % (len(ok), len(empty), len(failed)))
    for result in results:
        if result.status != 'OK':
            reporter.message('  %-7s %s' % (result.status, result.name))
    if empty:
        reporter.message('\n"EMPTY" means no scenes matched. Try widening the date '
                         'range, raising cloud_cover, or clearing the months filter.')
    reporter.message('Output folder: %s' % output_folder)
    reporter.message('%s' % ('=' * 60))

    return 1 if (failed or empty) else 0
