# Sources of the overview map

Built by `scripts/overview_map.py`; nothing here is loaded from anywhere but this server.

Downloaded 2026-10-22:

- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_countries.geojson (countries, labels)
- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_admin_1_states_provinces.geojson (regions of DE, AT, CH)
- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_lakes.geojson (lakes about Europe, labels)
- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_lakes_europe.geojson (lakes about Europe, labels)
- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_rivers_lake_centerlines.geojson (rivers about Europe)
- https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_rivers_europe.geojson (rivers about Europe)
- https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/fonts/Noto%20Sans%20Regular/ (glyphs 0-255, 256-511, 512-767, 768-1023, 1024-1279, 1280-1535, 7680-7935, 8192-8447)
- https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/fonts/Noto%20Sans%20Medium/ (glyphs 0-255, 256-511, 512-767, 768-1023, 1024-1279, 1280-1535, 7680-7935, 8192-8447)
- https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/fonts/Noto%20Sans%20Italic/ (glyphs 0-255, 256-511, 512-767, 768-1023, 1024-1279, 1280-1535, 7680-7935, 8192-8447)
- https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/fonts/OFL.txt (the fonts' licence)
- https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/sprites/v4/ (light sprites)
- https://raw.githubusercontent.com/tangrams/icons/92510779634f4a006c61ea70e50cb8c52c765a81/LICENSE.md (the icons' licence)

## Licences

- Natural Earth (countries, regions, lakes, rivers, label points): public domain,
  https://www.naturalearthdata.com/about/terms-of-use/
- Noto Sans (the glyphs below fonts/): SIL Open Font License 1.1, fonts/OFL.txt
- The sprites of the Protomaps basemap (sprites/), derived from the icons of tangrams/icons:
  MIT, sprites/LICENSE.md
- The town labels come from the server (GET /api/map/towns): GeoNames, CC BY 4.0,
  https://www.geonames.org/
