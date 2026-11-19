# Feed catalogue

| File | What it is | Edited by |
|---|---|---|
| `candidates.csv` | Every GTFS resource published on [transport.data.gouv.fr](https://transport.data.gouv.fr) (the PAN), with the facts needed to decide about it | nobody: generated |
| `gtfs_france.csv` | **The catalogue.** One row per decision, including the feeds left out and why. The rest of the benchmark reads only this file | hand |

```bash
python -m gtfs_bench.catalog candidates   # rewrite candidates.csv from the PAN API
python -m gtfs_bench.catalog check        # gtfs_france.csv against the PAN today
```

`check` reports four kinds of problem:

- an included feed whose resource has left the PAN;
- an included feed that has expired or become unavailable;
- an included feed whose URL changed;
- any valid PAN resource the catalogue has no row for, which is how a new feed gets noticed.

## First version, 18 November 2026

- **482 rows, 225 included.** The 247 other regional rows are refused, each with its reason in `notes`.
- **10 rows** are the long-distance layer, kept with `include=false` until step 8.

**Step 8, 19 November 2026:** the 10 long-distance rows were checked against the PAN again
(all still valid, same URLs, no new national or cross-region candidate) and switched to
`include=true`. The regional tiers ignore them: `tiers_from_catalog` keeps
`layer=regional` by default, and only the `france-connexe` variant
(`gtfs_bench/connected.py`) reads both layers.

What each row adds on the reference day (Tuesday 24 November 2026), once normalization has
dropped the stops outside mainland France and the trips left with fewer than two stops:

| Row | What it carries | Trips on 24 Nov | Stops served that week |
|---|---|---:|---:|
| `sncf-grandes-lignes` | TGV INOUI (538), coaches "à réservation" (120), OUIGO (71), Intercités day and night (72), Lyria (34), ICE (26); same zip as `sncf-ter`, without its TER stop points | 862 | 445 |
| `flixbus` | FlixBus and FlixTrain, French part of the European network | 323 | 184 |
| `blablacar-bus` | BlaBlaCar Bus | 100 | 103 |
| `trenitalia-france` | Paris ↔ Lyon ↔ Marseille, Paris ↔ Chambéry ↔ Modane | 26 | 13 |
| `renfe-ave` | Marseille, Lyon ↔ Spain, French part | 8 | 9 |
| `corsica-linea` | Marseille ↔ Ajaccio, Bastia, L'Île-Rousse, Propriano | 5 | 5 |
| `eurostar` | none that day: every train has one French stop (Paris-Nord, Lille…) but for 8 Roissy ↔ Marne-la-Vallée runs over the week | 0 | 2 |
| `corsica-ferries` | none that week: its late-November crossings are Corsica ↔ Italy | 0 | 0 |
| `brittany-ferries`, `transmanche-ferries` | none: one French port per crossing (England, Ireland, Spain) | 0 | 0 |

SNCF reuses one `trip_id` across many dates, so its trip counts per week are counts of
distinct trains, not of runs.

The pipeline ignores pickup and drop-off restrictions, so the engine may use a coach or an
international train for a domestic hop its operator does not sell (cabotage rules).

| Region | Included | Refused | Source of the regional layer |
|---|---:|---:|---|
| 11 Île-de-France | 1 | 2 | IDFM (whole region) |
| 24 Centre-Val de Loire | 5 | 12 | JV Malin aggregate + Fil Bleu, TAO + 2 small networks missing from it |
| 27 Bourgogne-Franche-Comté | 24 | 1 | no aggregate: urban networks + Mobigo per département |
| 28 Normandie | 2 | 27 | Atoumod aggregate + Astuce |
| 32 Hauts-de-France | 48 | 7 | no aggregate: urban networks + regional coaches per département |
| 44 Grand Est | 7 | 45 | Grand Est aggregate + CTS, Le Met', Stan + TCAT and ELSA (carried by the aggregate as TRO and CCSelestat, taken out of it) + Neobus |
| 52 Pays de la Loire | 8 | 13 | Destineo aggregate + Naolib + SETRAM and 5 small networks missing from it |
| 53 Bretagne | 8 | 28 | Korrigo aggregate + STAR, Bibus + Glazgo (carried by Korrigo as Auray Bus, taken out of it) + 4 networks missing from it |
| 75 Nouvelle-Aquitaine | 9 | 48 | NA Mobilités aggregate + TBM + 7 networks missing from it |
| 76 Occitanie | 36 | 3 | no aggregate: urban networks + liO coaches |
| 84 Auvergne-Rhône-Alpes | 27 | 53 | Oùra aggregate + TCL, STAS, M TAG, T2C, SIBRA, Citéa and others missing from it |
| 93 Provence-Alpes-Côte d'Azur | 43 | 7 | no aggregate: the 14 AMP networks, Lignes d'Azur, Mistral, ZOU, urban networks |
| 94 Corse | 6 | 1 | urban networks + Via Strada coaches |
| FR National | 1 | 10 | SNCF, TER trips only |

The row counts come from the PAN's `metadata.stats`. Those count trips over a feed's whole validity, which can be weeks or years, so they say nothing about one day's service. The size of each tier is measured on the merged feeds in step 4.

## Columns

| Column | Meaning |
|---|---|
| `feed_id` | Unique slug. Every GTFS id of the feed is prefixed with it when merging, so keep it stable once data has been built |
| `include` | `true` / `false` |
| `layer` | `regional` (steps 1–7) or `longue_distance` (step 8) |
| `region_code`, `region_name` | INSEE region, or `FR` for a national feed |
| `metropole` | One of the 22 keys in `gtfs_bench.catalog.METROPOLES`, or empty. A feed with a métropole belongs to that métropole's tier |
| `level` | `urbain`, `interurbain`, `agregat_regional`, `ferroviaire` or `national` |
| `name`, `modes` | For people. `modes` comes from the PAN validator |
| `url` | Stable link to the latest version: the PAN's `url` field, which redirects to the producer's current file |
| `auth` | Credentials key (see `../.env.example`), empty if public |
| `keep_agencies` / `drop_agencies` | Regex on `agency_name`. Takes a network out of a feed that carries it when it comes from somewhere else |
| `keep_stop_ids` / `drop_stop_ids` | Regex on `stop_id`. Keeps only the trips whose every stop matches, or drops the trips with any stop that matches |
| `clip` | `true`: a tier keeps only the part of the feed inside its own area. Used for national and cross-border feeds |
| `priority` | When the same trip comes from two feeds, the lower value wins. Defaults: urban 10, rail and national 15, interurban 20, aggregate 30 |
| `pan_dataset_id`, `pan_resource_id` | Where the row comes from on the PAN; empty for other sources |
| `licence`, `stats_trips`, `stats_stops`, `valid_from`, `valid_to` | Copied from the PAN when the row was written, for reference |
| `notes` | Why the row is what it is |

The regexes are RE2 (DuckDB) and Python compatible. Only metacharacters are escaped: `^(STAR \(Rennes Métropole\)|TER BreizhGo)$`.

## How the first version was decided

**Each network comes from exactly one source.** The other copies are refused, or filtered out of the feed that carries them:

- **Métropoles: the producer's own feed.** The 22 métropole networks are taken from the network's own publication. Where a regional aggregate carries them too, they are removed from it with `drop_agencies`. That is what keeps the tiers nested: a métropole tier is exactly a subset of its region tier.
- **TER: the national SNCF feed, every region.** That feed mixes every SNCF product, but each trip uses a single commercial mode, and the mode is part of every `stop_id` (`StopPoint:OCETrain TER-87571000`, `StopPoint:OCETGV INOUI-…`). So `sncf-ter` keeps the trips whose stops are all `Train TER`, `Car TER`, `TramTrain` or `Navette`: 39,813 train trips, 5,524 coach trips and 773 tram-train trips in the 18 November export. TER is removed wherever else it appears:
  - Korrigo, Destineo, Atoumod and Grand Est (`drop_agencies`);
  - IDFM's `TER` network;
  - the standalone Hauts-de-France and BreizhGo TER feeds.
- **Regional aggregates over their parts.** Seven regions publish one. A standalone feed whose network the aggregate already carries is refused, `In the regional aggregate (…)`. The match on network names was automatic and then checked by hand, and the notes record every correction:
  - four automatic matches were wrong and the feeds are included after all: the Philibert lines, the Savoie tourist lines, Tempo Bus, and the Bordeaux airport shuttle;
  - three duplicates the match missed are refused by hand: J'ybus, L'va and l'Bus.
- **Several resources for one network:** the current, regular-service resource is kept. That means STAR's current version, Ametis's GTFS-RT companion, Mobigo per département, Sankéo's LR & TSR, and Sillages' urban resource.

**Refused outright:**

- school-only feeds;
- on-demand (TAD) and zonal on-demand services;
- feeds with no trips;
- carpooling lines;
- Monaco's buses (foreign) and every overseas network.

**Checked on the data, after the merge (step 3).** `gtfs_bench.merge.pattern_overlaps` compares
the stop patterns of every pair of feeds, times ignored, so it catches two versions of the
same timetable. Exact-trip deduplication would miss them.

On the 30 November 2026 week, it found three networks the name matching had missed:

| Network | Carried by the aggregate as | Patterns found there |
|---|---|---|
| TCAT (Troyes) | TRO, Grand Est | 207 of 210 |
| ELSA (Sélestat) | CCSelestat, Grand Est | 9 of 10 |
| Glazgo (Auray) | Auray Bus, Korrigo | 9 of 9 |

All three now come from their producer's feed and are dropped from the aggregates. The
only other pair is Compiègne's urban and interurban TIC networks, which share 5 of 86
patterns. That is legitimate, and trip deduplication handles it.

## Open points for review

- **Uncertain duplicates:** Isibus and Pass'O are published under the generic network name `KEOLIS`. C'Bus is published as `ALEOP`. All three are refused as probably already in their region's aggregate. The Bordeaux airport shuttle is included although it may be in NA Mobilités. Trip deduplication during the merge (step 3) is the safety net, and its report will show whether they really overlapped.
- **`drop_agencies` assumes the PAN's network names are the feeds' `agency_name` values.** This held on the 18 November 2026 download: all 20 names match an agency of their feed exactly. Step 3 reports the match count for every filter, so a name that changes later shows up instead of silently letting a duplicate through.
- **Gaps:**
  - The Corsican railway (CFC) feed expired in March 2026, so Corsica has no train.
  - TCL needs Data Grand Lyon credentials: without them, the Lyon métropole has no network.
- **Reference week:** these included feeds stop before Christmas:
  - IDFM and Le Met' on 17 December;
  - Pays de Gex on 12 December;
  - Pastel on 3 December;
  - three ski shuttles even earlier.

  From the PAN dates, Tuesday 1 December 2026 is covered by every included feed except the ski shuttles. The real choice is made in step 4, on the downloaded calendars.
- **Seasonal feeds** (ski shuttles, the Arcs funicular) are included. The week filter of the merge empties the ones that do not run that week.
