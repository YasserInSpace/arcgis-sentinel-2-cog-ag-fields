"""
test_aoi.py
Covers AOI resolution across geometry types and input formats. Needs a working
ArcGIS licence; exits 0 with a notice if one is not available.

Pass --live to additionally check every generated geometry against the STAC API.

  "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" tests/test_aoi.py
"""

import math
import os
import sys
import json
import shutil
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))

try:
    import arcpy
except RuntimeError as exc:
    print('SKIPPED: ArcGIS licence unavailable (%s)' % exc)
    sys.exit(0)

import aoi_source

failures = []


def check(label, got, want):
    ok = got == want
    print('  %-56s %s' % (label, 'ok' if ok else 'FAIL got=%r want=%r' % (got, want)))
    if not ok:
        failures.append(label)


def check_true(label, got):
    check(label, bool(got), True)


WGS84 = arcpy.SpatialReference(4326)


def circle_points(count, cx, cy, radius):
    return [arcpy.Point(cx + radius * math.cos(i / float(count) * 2 * math.pi),
                        cy + radius * math.sin(i / float(count) * 2 * math.pi))
            for i in range(count)]


def make_fc(folder, name, geometry_type, geometries, spatial_reference=None):
    arcpy.management.CreateFeatureclass(
        folder, name, geometry_type,
        spatial_reference=spatial_reference or WGS84)
    path = os.path.join(folder, name)
    with arcpy.da.InsertCursor(path, ['SHAPE@']) as cursor:
        for geometry in geometries:
            cursor.insertRow([geometry])
    return path


def vertices(feature):
    geojson = feature.geojson
    if geojson['type'] == 'Polygon':
        return len(geojson['coordinates'][0])
    return sum(len(polygon[0]) for polygon in geojson['coordinates'])


def main():
    arcpy.env.overwriteOutput = True
    workspace = tempfile.mkdtemp(prefix='aoi_test_')

    try:
        print('=== geometry types ===')
        point_fc = make_fc(workspace, 'pt.shp', 'POINT',
                           [arcpy.PointGeometry(arcpy.Point(46.1, 24.1), WGS84)])
        feature = aoi_source.resolve_aoi(point_fc, '', 0)[0]
        check('point resolves to a polygon', feature.geojson['type'], 'Polygon')
        check_true('point gets a default buffer', vertices(feature) > 4)
        check_true('point bbox has real extent', feature.bbox[2] > feature.bbox[0])

        wide = aoi_source.resolve_aoi(point_fc, '', 1000)[0]
        check_true('larger buffer gives a larger bbox',
                   (wide.bbox[2] - wide.bbox[0]) > (feature.bbox[2] - feature.bbox[0]))

        line_fc = make_fc(workspace, 'ln.shp', 'POLYLINE', [arcpy.Polyline(
            arcpy.Array([arcpy.Point(44, 22), arcpy.Point(46, 24), arcpy.Point(48, 26)]), WGS84)])
        line = aoi_source.resolve_aoi(line_fc, '', 2000)[0]
        check('polyline resolves to a polygon', line.geojson['type'], 'Polygon')

        print('\n=== formats ===')
        bbox = aoi_source.resolve_aoi('44.0,22.0,48.0,26.0')
        check('bbox string -> one feature', len(bbox), 1)
        check('bbox string bbox', [round(v, 2) for v in bbox[0].bbox], [44.0, 22.0, 48.0, 26.0])
        check('reversed bbox is normalised',
              [round(v, 2) for v in aoi_source.resolve_aoi('48,26,44,22')[0].bbox],
              [44.0, 22.0, 48.0, 26.0])

        geojson_path = os.path.join(workspace, 'aoi.geojson')
        with open(geojson_path, 'w', encoding='utf-8') as handle:
            json.dump({'type': 'FeatureCollection', 'features': [{
                'type': 'Feature', 'properties': {'label': 'Basin'},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [46.0, 24.0], [46.4, 24.0], [46.4, 24.4], [46.0, 24.4], [46.0, 24.0]]]}}]},
                handle)
        gj = aoi_source.resolve_aoi(geojson_path, 'label', 0)
        check('geojson file name_field is used', gj[0].name, 'Basin')

        shp = os.path.join(REPO, 'aoi', 'ksa_agri_fields.shp')
        if os.path.exists(shp):
            feats = aoi_source.resolve_aoi(shp, 'name', 0)
            check_true('shapefile resolves features', len(feats) > 0)
            check('no ring is clockwise',
                  [f.name for f in feats
                   if aoi_source._ring_is_clockwise(f.geojson['coordinates'][0])], [])

        print('\n=== reprojection and reduction ===')
        utm = arcpy.SpatialReference(32638)
        utm_fc = make_fc(workspace, 'utm.shp', 'POLYGON', [arcpy.Polygon(arcpy.Array([
            arcpy.Point(600000, 2670000), arcpy.Point(610000, 2670000),
            arcpy.Point(610000, 2680000), arcpy.Point(600000, 2680000)]), utm)], utm)
        projected = aoi_source.resolve_aoi(utm_fc, '', 0)[0]
        check_true('projected input comes back in lon/lat',
                   -180 <= projected.bbox[0] <= 180 and -90 <= projected.bbox[1] <= 90)

        big_fc = make_fc(workspace, 'big.shp', 'POLYGON',
                         [arcpy.Polygon(arcpy.Array(circle_points(3000, 46, 24, 0.5)), WGS84)])
        reduced = aoi_source.resolve_aoi(big_fc, '', 0)[0]
        check_true('over-complex AOI is reduced',
                   vertices(reduced) <= aoi_source.MAX_SEARCH_VERTICES)
        check_true('reduction still covers the original',
                   reduced.bbox[0] <= 45.51 and reduced.bbox[2] >= 46.49)

        print('\n=== error handling ===')
        for bad, label in ((' ', 'empty aoi'), ('C:/nope/missing.shp', 'missing path')):
            try:
                aoi_source.resolve_aoi(bad)
                check(label + ' raises', 'no error', 'ValueError')
            except ValueError:
                check(label + ' raises ValueError', True, True)

        if '--live' in sys.argv:
            print('\n=== live STAC acceptance ===')
            from pystac_client import Client
            client = Client.open('https://earth-search.aws.element84.com/v1')
            for label, feats in (('point', aoi_source.resolve_aoi(point_fc, '', 0)),
                                 ('polyline', aoi_source.resolve_aoi(line_fc, '', 2000)),
                                 ('reduced polygon', aoi_source.resolve_aoi(big_fc, '', 0))):
                try:
                    client.search(collections=['sentinel-2-l2a'],
                                  intersects=feats[0].geojson,
                                  datetime='2026-06-01/2026-06-15').matched()
                    check(label + ' accepted by STAC', True, True)
                except Exception as exc:
                    check(label + ' accepted by STAC', str(exc)[:60], 'accepted')
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print('\n%s' % ('-' * 60))
    print('FAILURES: %s' % (failures if failures else 'none'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
