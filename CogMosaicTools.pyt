"""
CogMosaicTools.pyt
ArcGIS Pro toolbox for building mosaic datasets from COGs.

Wraps the same pipeline as scripts/run_workflow.py, so the toolbox and the
command line always behave identically. Drop this file's folder into the
Catalog pane, or add the toolbox directly, and the tool appears in Pro.
"""

import os
import sys
import datetime

import arcpy

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import workflow
import templates as template_packs


class Toolbox(object):
    def __init__(self):
        self.label = 'COG Mosaic Tools'
        self.alias = 'cogmosaic'
        self.tools = [BuildMosaics]


class _GpReporter(workflow.Reporter):
    """Sends pipeline output to the geoprocessing messages and progress bar."""

    def message(self, text):
        arcpy.AddMessage(text)

    def warning(self, text):
        arcpy.AddWarning(text)

    def error(self, text):
        arcpy.AddError(text)

    def progress(self, done, total, label):
        if total:
            arcpy.SetProgressorPosition(done)
            arcpy.SetProgressorLabel('Building %d of %d: %s' % (min(done + 1, total), total, label))


class BuildMosaics(object):

    def __init__(self):
        self.label = 'Build Mosaics from AOI'
        self.description = (
            'Searches the STAC API for scenes covering each AOI feature and builds '
            'a mosaic dataset per feature. Imagery is streamed from cloud-optimised '
            'GeoTIFFs rather than downloaded.')
        self.canRunInBackground = False

    def getParameterInfo(self):
        aoi = arcpy.Parameter(
            displayName='Area of interest',
            name='aoi', datatype=['GPFeatureLayer', 'DEFeatureClass'],
            parameterType='Required', direction='Input')
        aoi.description = ('Any geometry type. Points and lines are buffered into '
                           'search areas automatically. One mosaic per feature.')

        output_folder = arcpy.Parameter(
            displayName='Output folder',
            name='output_folder', datatype='DEFolder',
            parameterType='Required', direction='Input')

        start_date = arcpy.Parameter(
            displayName='Start date',
            name='start_date', datatype='GPDate',
            parameterType='Required', direction='Input')

        end_date = arcpy.Parameter(
            displayName='End date',
            name='end_date', datatype='GPDate',
            parameterType='Required', direction='Input')

        cloud_cover = arcpy.Parameter(
            displayName='Maximum cloud cover (%)',
            name='cloud_cover', datatype='GPLong',
            parameterType='Required', direction='Input')
        cloud_cover.filter.type = 'Range'
        cloud_cover.filter.list = [0, 100]
        cloud_cover.value = 10

        scene_selection = arcpy.Parameter(
            displayName='Scene selection',
            name='scene_selection', datatype='GPString',
            parameterType='Required', direction='Input')
        scene_selection.filter.type = 'ValueList'
        scene_selection.filter.list = list(workflow.VALID_SELECTION)
        scene_selection.value = 'best_scene_only'

        packs = arcpy.Parameter(
            displayName='Raster template packs',
            name='template_packs', datatype='GPString',
            parameterType='Required', direction='Input', multiValue=True)
        packs.filter.type = 'ValueList'
        packs.filter.list = ['all'] + template_packs.available_packs()
        packs.value = ['all']

        area_name = arcpy.Parameter(
            displayName='Output name prefix',
            name='area_name', datatype='GPString',
            parameterType='Optional', direction='Input', category='Naming')

        name_field = arcpy.Parameter(
            displayName='Name field',
            name='name_field', datatype='Field',
            parameterType='Optional', direction='Input', category='Naming')
        name_field.parameterDependencies = [aoi.name]

        buffer_meters = arcpy.Parameter(
            displayName='AOI buffer (metres)',
            name='aoi_buffer_meters', datatype='GPDouble',
            parameterType='Optional', direction='Input', category='Advanced')
        buffer_meters.value = 0

        months = arcpy.Parameter(
            displayName='Restrict to months',
            name='months', datatype='GPLong',
            parameterType='Optional', direction='Input',
            multiValue=True, category='Advanced')
        months.filter.type = 'ValueList'
        months.filter.list = list(range(1, 13))

        mrf_cache = arcpy.Parameter(
            displayName='MRF cache folder',
            name='mrf_cache_folder', datatype='DEFolder',
            parameterType='Optional', direction='Input', category='Advanced')
        mrf_cache.value = workflow.DEFAULT_MRF_CACHE

        out_mosaics = arcpy.Parameter(
            displayName='Mosaic datasets',
            name='out_mosaics', datatype='DEMosaicDataset',
            parameterType='Derived', direction='Output', multiValue=True)

        return [aoi, output_folder, start_date, end_date, cloud_cover,
                scene_selection, packs, area_name, name_field, buffer_meters,
                months, mrf_cache, out_mosaics]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        start, end = parameters[2], parameters[3]
        if start.value and end.value and start.value > end.value:
            end.setErrorMessage('End date must fall on or after the start date.')

        cloud = parameters[4]
        if cloud.value is not None and not 0 <= cloud.value <= 100:
            cloud.setErrorMessage('Cloud cover must be between 0 and 100.')
        return

    def execute(self, parameters, messages):
        values = {p.name: p for p in parameters}

        def date_string(parameter):
            value = parameter.value
            if isinstance(value, datetime.datetime):
                return value.strftime('%Y-%m-%d')
            return str(value)[:10]

        # A layer with a selection passes only the selected features through,
        # which is the natural way to run this for part of a dataset.
        aoi = values['aoi'].valueAsText

        config = {
            'aoi': aoi,
            'output_folder': values['output_folder'].valueAsText,
            'start_date': date_string(values['start_date']),
            'end_date': date_string(values['end_date']),
            'cloud_cover': values['cloud_cover'].value,
            'scene_selection': values['scene_selection'].valueAsText,
            'template_packs': (values['template_packs'].valueAsText or 'all').split(';'),
            'area_name': values['area_name'].valueAsText or '',
            'name_field': values['name_field'].valueAsText or '',
            'aoi_buffer_meters': values['aoi_buffer_meters'].value or 0,
            'months': [int(m) for m in (values['months'].valueAsText or '').split(';') if m.strip()],
            'mrf_cache_folder': values['mrf_cache_folder'].valueAsText or workflow.DEFAULT_MRF_CACHE,
        }

        reporter = _GpReporter()

        try:
            feature_count = int(arcpy.management.GetCount(aoi)[0])
        except Exception:
            feature_count = 0
        arcpy.SetProgressor('step', 'Building mosaics...', 0, max(feature_count, 1), 1)

        try:
            results = workflow.build_mosaics(config, reporter)
        except ValueError as exc:
            arcpy.AddError(str(exc))
            raise arcpy.ExecuteError(str(exc))
        finally:
            arcpy.ResetProgressor()

        workflow.summarise(results, config['output_folder'], reporter)

        built = [r.mosaic_path for r in results if r.status == 'OK']
        values['out_mosaics'].value = ';'.join(built)

        for result in results:
            if result.status == 'EMPTY':
                arcpy.AddWarning('%s: no scenes matched the search.' % result.name)
            elif result.status == 'FAILED':
                arcpy.AddError('%s: failed to build.' % result.name)

        if not built:
            raise arcpy.ExecuteError('No mosaic datasets were built.')
        return

    def postExecute(self, parameters):
        return
