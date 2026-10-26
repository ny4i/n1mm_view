# DXCC entity outlines

`world_dxcc.geojson` holds one polygon feature per piece of each DXCC entity,
tagged with the entity's DXCC prefix (`properties.dxcc`, e.g. `K`, `KH6`,
`CT3`) and name. n1mm_view uses it for the Countries Worked map
(`SHOW_COUNTRY_MAP`).

## Source

- Copied unchanged from TR4QT (https://github.com/ny4i/TR4QT),
  `resources/world_dxcc.geojson` at commit e61b7a1, built by its
  `scripts/combine_dxcc_geojson.py` from `resources/dxcc_geojson_mapping.json`.
- The boundary data comes from world-geojson by georgique
  (https://github.com/georgique/world-geojson).

## License

The boundary data is licensed under the **GNU General Public License v3.0**
(see `LICENSE` in this directory), unlike the rest of n1mm_view, which is
BSD 2-Clause. It is kept in its own directory as a separate data file that
n1mm_view reads at runtime.

## Prefix matching

Loggers send CTY.DAT primary prefixes. `graphics.dxcc_map_key()` strips the
`*` CTY.DAT puts on WAE-only entities (e.g. `*IT9`), matches case-insensitively,
and maps the few prefixes the geojson spells differently (`DXCC_MAP_ALIASES`:
HB->HB9, KL->KL7, IS->IS0, 3W->XV, 3Y/b->3Y). WAE pieces with no outline here
(GM/s Shetland, JW/b Bear Island, TA1 European Turkey) are listed on the
Countries Worked slide but not drawn.
