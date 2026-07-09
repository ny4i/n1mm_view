#!/usr/bin/env python3
"""
extract_zones.py

Harvest amateur-radio zone geometry embedded in the Leaflet.ITUzones /
Leaflet.CQzones projects (https://github.com/ha8tks) and turn the boundary
LineStrings into filled polygons that our Cartopy choropleth can draw.

Both Leaflet sources store each zone as:
  - one GeoJSON LineString  (the zone boundary; closed or nearly-closed rings)
  - one GeoJSON Point       (the label position)

We only need the boundaries. We close any open rings, then normalise the
antimeridian: the source coordinates deliberately run outside +/-180 (roughly
-205 .. +192) so that zones straddling the date line trace as one continuous
ring. Left as-is those pieces would draw off the edge of a [-180, 180] world
map instead of wrapping to the far side, so for each zone we clip the polygon
(and copies shifted by +/-360) back into the world box and union the pieces.
The result is a geographically correct Polygon / MultiPolygon fully inside
[-180, 180].

Output: shapes/<kind>_zones.geojson  (FeatureCollection, one feature per zone,
property "zone" = the zone number as a string). draw_map() loads this the same
way it loads the per-section shapefiles.

Usage:
    python3 extract_zones.py                 # regenerate both itu and cq
    python3 extract_zones.py --kind itu      # just ITU zones (90)
    python3 extract_zones.py --kind cq       # just CQ zones (40)
    python3 extract_zones.py --kind cq --src path/to/L.CQzones.js -o out.geojson

Re-run this only when the upstream zone data changes; the generated GeoJSON is
what the dashboard consumes at runtime.
"""

import argparse
import json
import logging
import os
import sys

from shapely.geometry import (MultiPolygon, Polygon, box, mapping)
from shapely.affinity import translate
from shapely.ops import unary_union

# Per-zone-kind defaults. src is where the upstream Leaflet checkout lives;
# override with --src if yours is elsewhere.
KINDS = {
    'itu': {'src': '~/Leaflet.ITUzones/src/L.ITUzones.js',
            'out': 'shapes/itu_zones.geojson', 'count': 90},
    'cq':  {'src': '~/projects/Leaflet.CQzones/src/L.CQzones.js',
            'out': 'shapes/cq_zones.geojson', 'count': 40},
}

WORLD = box(-180, -90, 180, 90)


def parse_line_features(js_text):
    """Yield the GeoJSON LineString features (one per zone) from the JS source.

    Each feature sits on its own line as a JSON object literal, so we scan
    line-by-line rather than trying to JSON-parse the whole (comma-trailing,
    non-strict) FeatureCollection blobs.
    """
    for raw in js_text.splitlines():
        line = raw.strip().rstrip(',')
        if not line.startswith('{"type":"Feature"'):
            continue
        try:
            feat = json.loads(line)
        except json.JSONDecodeError:
            continue
        if feat.get('geometry', {}).get('type') == 'LineString':
            yield feat


def ring_to_polygon(coords):
    """Close the boundary ring (if needed) and build a cleaned Polygon."""
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    poly = Polygon(coords)
    if not poly.is_valid:
        # buffer(0) is the standard trick to repair self-touching rings
        poly = poly.buffer(0)
    return poly


def normalise_antimeridian(poly):
    """Clip poly and its +/-360 shifted copies into the world box, union them.

    Returns a geometry guaranteed to lie within [-180, 180] longitude, with
    date-line-straddling zones split into the correct east/west pieces.
    """
    pieces = []
    for shift in (-360, 0, 360):
        candidate = poly if shift == 0 else translate(poly, xoff=shift)
        clipped = candidate.intersection(WORLD)
        if not clipped.is_empty:
            pieces.append(clipped)
    merged = unary_union(pieces)
    if not merged.is_valid:
        merged = merged.buffer(0)
    return polygonal_only(merged)


def polygonal_only(geom):
    """Keep only the (Multi)Polygon parts of a geometry.

    Clipping at +/-180 can leave zero-area line/point slivers where a ring
    runs exactly along the world box edge, yielding a GeometryCollection.
    Those can't be filled, so drop everything that isn't a polygon.
    """
    if geom.geom_type in ('Polygon', 'MultiPolygon'):
        return geom
    polys = [g for g in getattr(geom, 'geoms', [])
             if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_empty]
    flat = []
    for g in polys:
        flat.extend(g.geoms if g.geom_type == 'MultiPolygon' else [g])
    if not flat:
        return geom  # nothing polygonal; caller will warn on empty/degenerate
    return flat[0] if len(flat) == 1 else MultiPolygon(flat)


def build_feature_collection(src_path):
    with open(src_path, 'r') as fh:
        js_text = fh.read()

    features = []
    zones_seen = []
    for feat in parse_line_features(js_text):
        zone = str(feat['properties'].get('name', '')).strip()
        coords = feat['geometry']['coordinates']
        if not zone or len(coords) < 4:
            logging.warning('skipping zone %r with %d coords', zone, len(coords))
            continue
        geom = normalise_antimeridian(ring_to_polygon(coords))
        if geom.is_empty:
            logging.warning('zone %s produced empty geometry, skipping', zone)
            continue
        features.append({
            'type': 'Feature',
            'properties': {'zone': zone},
            'geometry': mapping(geom),
        })
        zones_seen.append(zone)

    # numeric sort so the output reads 1..N rather than lexical 1,10,11..
    features.sort(key=lambda f: int(f['properties']['zone'])
                  if f['properties']['zone'].isdigit() else 1 << 30)
    return {'type': 'FeatureCollection', 'features': features}, zones_seen


def extract_kind(kind, src=None, out=None):
    """Extract one zone kind. Returns 0 on success, 1 on failure."""
    spec = KINDS[kind]
    src_path = os.path.expanduser(src or spec['src'])
    out_path = out or spec['out']

    if not os.path.exists(src_path):
        logging.error('%s source not found: %s', kind, src_path)
        return 1

    fc, zones = build_feature_collection(src_path)
    if not fc['features']:
        logging.error('%s: no zone features extracted; aborting', kind)
        return 1
    if len(fc['features']) != spec['count']:
        logging.warning('%s: expected %d zones, extracted %d',
                        kind, spec['count'], len(fc['features']))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'w') as fh:
        json.dump(fc, fh)
    logging.info('wrote %d %s zones -> %s', len(fc['features']), kind.upper(), out_path)
    logging.info('%s zones: %s', kind, ' '.join(zones))
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--kind', choices=('itu', 'cq', 'both'), default='both',
                    help='which zone set to extract (default: both)')
    ap.add_argument('--src', default=None,
                    help='override the Leaflet .js source path (single --kind only)')
    ap.add_argument('-o', '--out', default=None,
                    help='override the output GeoJSON path (single --kind only)')
    args = ap.parse_args(argv)

    if args.kind == 'both' and (args.src or args.out):
        ap.error('--src/--out only apply with a single --kind (itu or cq)')

    kinds = ('itu', 'cq') if args.kind == 'both' else (args.kind,)
    rc = 0
    for kind in kinds:
        rc |= extract_kind(kind, src=args.src, out=args.out)
    return rc


if __name__ == '__main__':
    sys.exit(main())
