"""
aoi_source.py
Resolves an AOI definition from config into a list of search-ready features.

Accepts any of:
  - a feature source arcpy can read (shapefile, GeoJSON, file geodatabase feature class, layer file)
  - a GeoJSON file containing a Feature/FeatureCollection/bare geometry
  - a bare bounding box string "minx,miny,maxx,maxy" in WGS84

Every AOI feature is returned as a WGS84 GeoJSON geometry suitable for a STAC
`intersects` query, regardless of the input geometry type. Points and lines are
buffered into polygons; very complex polygons are reduced to their convex hull so
the search geometry stays inside the limits STAC servers accept.
"""

import os
import re
import json

import arcpy


# A STAC search geometry only needs to be a coarse superset of the AOI, and
# servers reject very large request bodies. Beyond this many vertices the
# geometry is reduced (see _reduce_vertices).
MAX_SEARCH_VERTICES = 1000

# Points and lines have no area, so they cannot be used as a search polygon.
# When the config does not set aoi_buffer_meters, pad them by this much.
DEFAULT_DEGENERATE_BUFFER_M = 100.0

_BBOX_RE = re.compile(
    r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,'
    r'\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$'
)

WGS84 = arcpy.SpatialReference(4326)


class AoiFeature(object):
    """One AOI: a name, a WGS84 GeoJSON geometry, and its bounding box."""

    def __init__(self, name, geojson, bbox):
        self.name = name
        self.geojson = geojson
        self.bbox = bbox

    @property
    def bbox_string(self):
        return ','.join(str(v) for v in self.bbox)


def safe_name(base_name):
    """Ensure a name is usable as a geodatabase / mosaic dataset name."""
    name = re.sub(r'[^A-Za-z0-9_]', '_', str(base_name))
    if name and name[0].isdigit():
        name = 'F_' + name
    return name


def _utm_epsg(lon, lat):
    """EPSG code of the UTM zone containing this point, for metric buffering."""
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def _ring_is_clockwise(coords):
    """Shoelace test. GeoJSON wants counter-clockwise exterior rings."""
    total = 0.0
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        total += (x2 - x1) * (y2 + y1)
    return total > 0


def _close_ring(coords):
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def _vertex_count(geometry):
    return sum(geometry.getPart(i).count for i in range(geometry.partCount))


def _densify(geometry, step_meters):
    """Replace true curves with line segments.

    buffer() returns curve-based geometry whose parts expose only the arc
    endpoints, so rings must be densified before their vertices can be read.
    """
    if not getattr(geometry, 'hasCurves', False):
        return geometry
    step = max(step_meters, 1.0)
    return geometry.densify('DISTANCE', step, step)


def _buffer_to_polygon(geometry, buffer_meters):
    """Buffer a geometry by a metric distance via its local UTM zone.

    Buffering in WGS84 degrees would distort badly with latitude, so the
    geometry is projected to the UTM zone under its own centroid first, and
    densified there while the units are still metres.
    """
    centroid = geometry.trueCentroid
    utm = arcpy.SpatialReference(_utm_epsg(centroid.X, centroid.Y))
    buffered = geometry.projectAs(utm).buffer(buffer_meters)
    return _densify(buffered, buffer_meters / 8.0).projectAs(WGS84)


def _extent_polygon(geometry):
    extent = geometry.extent
    return arcpy.Polygon(arcpy.Array([
        arcpy.Point(extent.XMin, extent.YMin),
        arcpy.Point(extent.XMax, extent.YMin),
        arcpy.Point(extent.XMax, extent.YMax),
        arcpy.Point(extent.XMin, extent.YMax),
    ]), WGS84)


def _reduce_vertices(geometry, max_vertices, fallback_buffer_m):
    """Shrink a search geometry to a vertex count the STAC server will accept.

    Every step must produce a *superset* of the input — under-covering would
    silently drop scenes near the AOI edge. The convex hull satisfies that and
    handles realistic AOIs; a hull that is still too complex falls back to the
    extent rectangle, which is coarse but always safe.
    """
    if _vertex_count(geometry) <= max_vertices:
        return geometry

    hull = geometry.convexHull()
    # convexHull can return a point or line for degenerate input.
    if hull.type != 'polygon':
        hull = _buffer_to_polygon(hull, fallback_buffer_m)

    if _vertex_count(hull) <= max_vertices:
        return hull

    return _extent_polygon(hull)


def _needs_buffer(geometry):
    """True for geometry that cannot serve as a search polygon on its own."""
    if geometry.type in ('point', 'multipoint', 'polyline'):
        return True
    # A polygon collapsed to zero area (or a degenerate extent) is equally unusable.
    if geometry.area == 0:
        return True
    extent = geometry.extent
    return extent.XMin == extent.XMax or extent.YMin == extent.YMax


def geometry_to_geojson(geometry, buffer_meters=0.0, max_vertices=MAX_SEARCH_VERTICES):
    """Convert an arcpy geometry into a WGS84 GeoJSON Polygon/MultiPolygon.

    Holes are dropped: the search geometry only has to be a superset of the AOI,
    and keeping interior rings would risk missing scenes for no benefit.
    """
    if geometry.spatialReference is None or geometry.spatialReference.factoryCode != 4326:
        geometry = geometry.projectAs(WGS84)

    if _needs_buffer(geometry):
        distance = buffer_meters if buffer_meters > 0 else DEFAULT_DEGENERATE_BUFFER_M
        geometry = _buffer_to_polygon(geometry, distance)
    elif buffer_meters > 0:
        geometry = _buffer_to_polygon(geometry, buffer_meters)

    # An input polygon may itself carry true curves (common in geodatabases).
    if getattr(geometry, 'hasCurves', False):
        centroid = geometry.trueCentroid
        utm = arcpy.SpatialReference(_utm_epsg(centroid.X, centroid.Y))
        extent = geometry.projectAs(utm).extent
        span = max(extent.width, extent.height, 8.0)
        geometry = _densify(geometry.projectAs(utm), span / 100.0).projectAs(WGS84)

    geometry = _reduce_vertices(geometry, max_vertices,
                                buffer_meters or DEFAULT_DEGENERATE_BUFFER_M)

    polygons = []
    for part_index in range(geometry.partCount):
        ring = []
        for point in geometry.getPart(part_index):
            if point is None:
                # A None separates an exterior ring from its holes; we keep only
                # the exterior, so stop at the first one.
                break
            ring.append([point.X, point.Y])
        if len(ring) < 3:
            continue
        ring = _close_ring(ring)
        if _ring_is_clockwise(ring):
            ring.reverse()
        polygons.append([ring])

    if not polygons:
        raise ValueError('AOI geometry produced no usable rings')

    if len(polygons) == 1:
        return {'type': 'Polygon', 'coordinates': polygons[0]}
    return {'type': 'MultiPolygon', 'coordinates': polygons}


def geojson_bbox(geojson):
    """Bounding box of a GeoJSON Polygon/MultiPolygon as [minx, miny, maxx, maxy]."""
    if geojson['type'] == 'Polygon':
        rings = geojson['coordinates']
    else:
        rings = [ring for polygon in geojson['coordinates'] for ring in polygon]

    xs = [pt[0] for ring in rings for pt in ring]
    ys = [pt[1] for ring in rings for pt in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_to_geojson(minx, miny, maxx, maxy):
    return {
        'type': 'Polygon',
        'coordinates': [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny],
        ]],
    }


def parse_bbox(text):
    """Parse "minx,miny,maxx,maxy" into ordered floats, or None if it is not one.

    Callers use this to tell a bounding box apart from a dataset path before
    deciding how to read the AOI.
    """
    match = _BBOX_RE.match(str(text or ''))
    if not match:
        return None
    minx, miny, maxx, maxy = (float(v) for v in match.groups())
    if minx > maxx:
        minx, maxx = maxx, minx
    if miny > maxy:
        miny, maxy = maxy, miny
    return [minx, miny, maxx, maxy]


def _from_bbox_string(text):
    bounds = parse_bbox(text)
    if bounds is None:
        return None
    geojson = _bbox_to_geojson(*bounds)
    return [AoiFeature('AOI', geojson, geojson_bbox(geojson))]


def _from_geojson_file(path, name_field, buffer_meters):
    """Read a .geojson/.json file directly, without going through arcpy."""
    with open(path, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)

    if payload.get('type') == 'FeatureCollection':
        raw_features = payload.get('features', [])
    elif payload.get('type') == 'Feature':
        raw_features = [payload]
    else:
        raw_features = [{'geometry': payload, 'properties': {}}]

    features = []
    for index, raw in enumerate(raw_features):
        geometry = raw.get('geometry')
        if not geometry:
            continue

        name = None
        if name_field:
            value = (raw.get('properties') or {}).get(name_field)
            if value:
                name = safe_name(value)
        if not name:
            name = 'Feature_%d' % (index + 1)

        # Round-trip through arcpy so buffering, winding and hull reduction all
        # take the same path as every other input format.
        arcpy_geometry = arcpy.AsShape(geometry)
        reference = arcpy_geometry.spatialReference
        if reference is None or reference.factoryCode == 0:
            # GeoJSON coordinates are WGS84 by specification, but AsShape leaves
            # the spatial reference unset, which would break reprojection later.
            arcpy_geometry = arcpy.FromWKT(arcpy_geometry.WKT, WGS84)

        converted = geometry_to_geojson(arcpy_geometry, buffer_meters)
        features.append(AoiFeature(name, converted, geojson_bbox(converted)))

    return features


def _from_feature_source(path, name_field, buffer_meters):
    """Read any feature source arcpy understands."""
    if name_field:
        available = [field.name for field in arcpy.ListFields(path)]
        if name_field not in available:
            raise ValueError(
                "name_field '%s' not found. Available fields: %s"
                % (name_field, ', '.join(available))
            )

    fields = ['SHAPE@'] + ([name_field] if name_field else [])

    features = []
    with arcpy.da.SearchCursor(path, fields) as cursor:
        for index, row in enumerate(cursor):
            geometry = row[0]
            if geometry is None:
                continue

            name = None
            if name_field and row[1]:
                name = safe_name(row[1])
            if not name:
                name = 'Feature_%d' % (index + 1)

            converted = geometry_to_geojson(geometry, buffer_meters)
            features.append(AoiFeature(name, converted, geojson_bbox(converted)))

    return features


def resolve_aoi(aoi, name_field='', buffer_meters=0.0):
    """Resolve a config AOI value into a list of AoiFeature.

    Raises ValueError with an actionable message if the AOI cannot be read.
    """
    aoi = (aoi or '').strip()
    if not aoi:
        raise ValueError('aoi is empty in config.json — set it to a feature '
                         'source path or a "minx,miny,maxx,maxy" bounding box.')

    bbox_features = _from_bbox_string(aoi)
    if bbox_features is not None:
        return bbox_features

    if not arcpy.Exists(aoi) and not os.path.exists(aoi):
        raise ValueError(
            'AOI not found: %s\n'
            '  Set "aoi" in config.json to a shapefile, GeoJSON file, feature class,\n'
            '  or a bounding box like "44.0,22.0,48.0,26.0". Use forward slashes.' % aoi
        )

    if os.path.isfile(aoi) and os.path.splitext(aoi)[1].lower() in ('.geojson', '.json'):
        features = _from_geojson_file(aoi, name_field, buffer_meters)
    else:
        features = _from_feature_source(aoi, name_field, buffer_meters)

    if not features:
        raise ValueError('AOI %s contains no usable features.' % aoi)

    return features
