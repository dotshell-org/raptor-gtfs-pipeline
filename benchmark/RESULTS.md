# Can raptor-kmp route over all of France?

**Yes, on the regional layer, with conditions.** On a GTFS of mainland France, the engine
loads in under half a second, holds 229 MB of heap, and answers a city trip in 4–7 ms
(median, desktop JVM). That meets every criterion set before the benchmark, for a phone
and for a server.

Three conditions come with that answer:

1. **Stops sharing a name must not be linked across France.** raptor-kmp links every
   pair of same-name stops with a 120 s transfer. With the producers' names, that is 15.8
   million links. City trips then become 5 to 10 times slower at the median and up to 32
   times slower at the 95th percentile, and itineraries are wrong:
   trips "teleport" between towns that each have a "Gare" or a "Mairie". The merge renames
   homonyms by place; the engine should stop needing it.
2. **A phone needs a large heap.** France loads at -Xmx384m but not at -Xmx256m, which is
   what many Android phones give an app without `android:largeHeap`.
3. **This is France without TGV, OUIGO or Intercités** (step 8). Regions are joined only
   by TER, so long trips are either missing or slow chains of regional trains. Adding the
   long-distance layer will make the graph connected and queries explore further. These
   numbers are a floor.

![Same trips, bigger network](results/engine_local_trips.png)

## Verdict against the criteria

The criteria were fixed in the plan before measuring. Desktop JVM, France, regional layer:

| Target | Criterion | Measured | |
|---|---|---|---|
| Phone | heap ≤ 512 MB | loads at 384 MB (out of memory at 256 MB); holds 229 MB | ✅ with `largeHeap` |
| Phone | load ≤ 3 s on desktop (≈ 10 s on a phone, ×3 estimated) | 0.44 s | ✅ |
| Phone | p95 ≤ 30 ms on desktop | worst p95 23.3 ms (Paris trips, arrive-by) | ✅ |
| Server | heap ≤ 4 GB | 229 MB | ✅ |
| Server | p95 ≤ 50 ms | 23.3 ms | ✅ |
| Server | p99 ≤ 200 ms | 91.4 ms (Paris trips, arrive-by) | ✅ |

The same France **with the producers' stop names fails all three latency criteria**:
p95 up to 562 ms and p99 up to 836 ms, with wrong itineraries (see
[Same-name links](#same-name-links)).

## What was measured

- **Data:** the 225 included feeds of [`catalog/gtfs_france.csv`](catalog/gtfs_france.csv):
  urban, interurban, regional aggregates and TER from the national SNCF feed. They were
  downloaded on 18 November 2026; every version is in
  [`results/feeds_used.csv`](results/feeds_used.csv).
- **Reference day:** Tuesday 24 November 2026, chosen from the calendars as the school
  Tuesday the most feeds run on (220 of 225).
- **Merge:** the merge keeps that day's week; the pipeline converts the day alone.
- **Tiers:** 22 métropoles ⊂ 13 regions ⊂ mainland France, 36 networks in all.
- **Pipeline:** `main` at the start of the branch, unmodified, JDK 21, `-Xmx12g`.
- **Engine:** `eu.dotshell:raptor-kmp-jvm` 2.2.0 from Maven Central, JDK 21, one fresh
  JVM per network, `maxRounds = 5` (the default the apps use).
- **Machine:** Intel Core Ultra 5 135H, 15 GB, Windows 11.

Query sets:

- **random:** 1,000 seeded pairs over all of a network's stops, departures 6:00–21:59,
  forward and arrive-by. This is the same generator as raptor-kmp's JMH benchmark.
- **local:** 300 seeded trips drawn inside Lyon and inside Paris. Each endpoint is the set
  of stops within 400 m. The same places are replayed on every network that holds the
  city.
- **named:** fixed trips from Bellecour → Part-Dieu to Brest → Strasbourg.

**Cross-check:** on Lyon, a random forward query takes 0.46 ms on average here.
raptor-kmp's README gives 0.35 ms on average, on an older, larger TCL export.

## The engine

### Memory

| Network | 256 MB | 384 MB | 512 MB | 1 GB | Heap held | Peak during the run |
|---|---|---|---|---|---:|---:|
| Métropole de Lyon | fits | fits | fits | fits | 9 MB | 20 MB |
| Auvergne-Rhône-Alpes | fits | fits | fits | fits | 38 MB | 95 MB |
| Île-de-France | fits | fits | fits | fits | 38 MB | 87 MB |
| France métropolitaine | **out of memory** (build) | fits | fits | fits | 232 MB | 431 MB |

The heap held grows in step with the network: about 0.8 KB per stop, from about 1 MB
for Brest to 229 MB for France ([`results/engine_heap.png`](results/engine_heap.png)).

France runs out at 256 MB during construction, not at rest. While the network is built,
three things are alive at once:

- the file bytes (64 MB);
- the intermediate `Stop` and `Transfer` objects (1.14 M transfers);
- the network's own arrays.

On top of that, each query state sizes its arrays for every stop: `bestArrival` and a
seven-int `parentData` entry per stop and round. For France, with the default five rounds
(six round slots), that is 56 MB.

### Speed

| Trips | Network loaded | Stops | Found | Forward p50 / p95 / p99 | Arrive-by p50 / p95 / p99 | Median trip |
|---|---|---:|---:|---:|---:|---:|
| Lyon | Métropole de Lyon | 9 625 | 290/300 | 0.44 / 1.02 / 1.36 ms | 1.17 / 2.67 / 10.95 ms | 34 min |
| Lyon | Auvergne-Rhône-Alpes | 54 223 | 290/300 | 0.72 / 1.94 / 4.37 ms | 2.62 / 6.46 / 21.43 ms | 33 min |
| Lyon | France métropolitaine | 293 369 | 290/300 | 4.24 / 6.34 / 9.46 ms | 10.90 / 16.91 / 65.46 ms | 33 min |
| Paris | Métropole du Grand Paris | 35 364 | 289/300 | 1.61 / 4.42 / 7.38 ms | 5.01 / 11.42 / 28.14 ms | 36 min |
| Paris | Île-de-France | 35 401 | 289/300 | 1.41 / 3.73 / 6.69 ms | 4.45 / 9.43 / 27.07 ms | 36 min |
| Paris | France métropolitaine | 293 369 | 289/300 | 6.50 / 9.88 / 12.77 ms | 16.01 / 23.34 / 91.42 ms | 36 min |

- **The answers do not change.** The same trips are found, with the same median length,
  whichever network is loaded. Lyon's trips are half a minute shorter on the regional
  network, where TER and regional coaches add options inside the city.
- **The cost does change, and by about the same amount in both cities.** France adds
  roughly 4–5 ms to a forward query, whether the trip is in Lyon or in Paris.

That constant comes from `RaptorState.reset()` in raptor-kmp. Before every query, it
refills `bestArrival` and `parentData` for every stop of the network and every round the
previous query used. On France that is up to 293,369 stops × 6 rounds × 8 ints, about
56 MB written, however small the part of the network the query actually explores.

Random trips (table below, [`results/engine_latency.png`](results/engine_latency.png))
mostly measure how far a query has to look before giving up. Without the long-distance
layer, only 51 of 1,000 random French pairs are joined within five rounds.

### Named trips

On France:

| Trip | Found | Query | Arrives | Duration | Legs |
|---|---|---:|---|---:|---|
| Bellecour → Part-Dieu | yes | 4.0 ms | 08:10 | 10 min | D, B |
| Châtelet → La Défense | yes | 5.6 ms | 08:21 | 21 min | 1 |
| Gare du Nord → Montparnasse | yes | 5.2 ms | 08:20 | 20 min | 4 |
| Vieux-Port → Aix-en-Provence | yes | 6.6 ms | 08:58 | 58 min | M1, 50 |
| Lyon Part-Dieu → Grenoble | yes | 7.1 ms | 09:39 | 99 min | K6 |
| Toulouse → Montpellier | yes | 6.7 ms | 11:08 | 188 min | C3, K8 |
| Lyon Part-Dieu → Paris Gare de Lyon | yes | 24.3 ms | 17:30 | 630 min | K7, P5, P31, 14 |
| Brest → Strasbourg | no | 13.0 ms | — | — | no journey within 5 rounds |
| Lille Flandres → Marseille St-Charles | no | 19.2 ms | — | — | no journey within 5 rounds |
| Bordeaux St-Jean → Nice-Ville | no | 10.1 ms | — | — | no journey within 5 rounds |

Every trip found on a smaller network is found on France with the same arrival and the
same lines, at 4–7 ms instead of 0.2–2 ms
([`results/engine_scenarios.csv`](results/engine_scenarios.csv)).

Lyon → Paris takes ten and a half hours of TER. Three cross-country trips find nothing.
That is the missing long-distance layer, not the engine.

## Same-name links

The merge renames stops whose name is shared by distant places ("Mairie (Vénissieux)").
It is the one change made to the data that the engine needs, so it was measured: the same
France, merged with the producers' names, converted and timed the same way
([`results/engine_same_name_links.csv`](results/engine_same_name_links.csv)).

| | Renamed (benchmark) | Producers' names |
|---|---:|---:|
| Same-name links built by the engine (Σ k·(k−1)) | 318 110 | **15 787 962** |
| Largest group of stops with one name | 23 | 2 669 |
| Load | 436 ms | 573 ms |
| Heap held | 229 MB | 282 MB |
| Random pairs joined | 51 / 1,000, median 328 min | **518 / 1,000, median 78 min** |
| Lyon trips, forward p50 / p95 | 4.2 / 6.3 ms | 37.1 / 70.7 ms |
| Lyon trips, arrive-by p50 / p95 / p99 | 10.9 / 16.9 / 65.5 ms | 110.4 / 538.5 / 835.5 ms |
| Paris trips, forward p50 / p95 | 6.5 / 9.9 ms | 30.0 / 59.3 ms |
| Paris trips, arrive-by p50 / p95 / p99 | 16.0 / 23.3 / 91.4 ms | 103.7 / 561.7 / 678.6 ms |
| Median Paris trip | 36 min | **20 min** |

The time is only half of it. With producers' names, ten times more random pairs across
France are "joined", in a median of 78 minutes, and Paris trips get 16 minutes shorter.
Neither is possible: the itineraries jump between same-name stops in different towns,
120 s apart in the engine's eyes.

Even on Lyon alone, 21 stops share one name. Within one network that is how a station's
platforms are tied together, which is why the merge keeps same-name stops within 500 m
of each other linked.

## The pipeline

| Network | Pipeline | Peak memory | Trips written / found that day | `.bin` |
|---|---:|---:|---:|---:|
| Métropole de Lyon | 7 s | 0.8 GB | 19 976 / 21 983 (91 %) | 2.7 MB |
| Île-de-France | 38 s | 2.8 GB | 122 766 / 144 742 (85 %) | 15.0 MB |
| Auvergne-Rhône-Alpes | 16 s | 1.8 GB | 51 272 / 61 583 (83 %) | 9.1 MB |
| France métropolitaine | 136 s | 9.3 GB | 397 477 / 481 003 (83 %) | 64.2 MB |

All 36 networks convert with the pipeline as it is ([`results/pipeline.csv`](results/pipeline.csv)).
Two findings concern the pipeline rather than the engine:

- **Memory.** France needs a heap between 6 and 8 GB: it runs out at -Xmx6g and passes at
  -Xmx8g ([`results/pipeline_france_heap.csv`](results/pipeline_france_heap.csv)). The
  pipeline reads the whole merged week (26.8 M stop_times) and builds all its routes and
  trips before keeping the one day it writes
  ([`results/pipeline.png`](results/pipeline.png)).
- **Trips.** It keeps 70–96 % of a day's trips, 83 % for France. `RouteBuilder` keeps one
  stop sequence per route and direction, and `TripBuilder` drops the trips that do not
  cover it. That is `main`'s behaviour for every network, Lyon in production included
  (91 %). The unmerged `feat/toulon-school-year-profile` branch makes one route per
  sequence: the engine would then load more routes and every trip.

## Limits

- **No phone was measured.** Heap figures carry over to Android: the same arrays and
  objects are allocated. Times do not: ART on a phone core is slower than HotSpot on this
  laptop. The ×3 in the criteria is an estimate.
- **One day, one week.** Every number is for Tuesday 24 November 2026. A weekend or a
  holiday runs fewer trips.
- **Regional layer only.** No TGV, OUIGO, Intercités, international trains, coaches or
  ferries. Corsica has no train either (the CFC feed had expired).
- **Five rounds.** At most four changes, as in the apps. Long trips over TER need more,
  which a higher `maxRounds` would allow at a cost not measured here.
- **The trips the pipeline drops** (17 % on France) are missing from what the engine
  loads.

## What to do with this

**Engine (raptor-kmp):**

- **Stop linking same-name stops without a distance limit.** This is the change that
  matters most: it makes a merged network correct as well as fast. Restrict implicit
  transfers to stops a few hundred metres apart, or drop them in favour of
  `transfers.txt`. The renaming done by this benchmark's merge is the workaround until
  then.
- **Reset only what the previous query touched.** `RaptorState.reset()` costs O(stops ×
  rounds) per query whatever the query explores. Recording the written indices, or
  stamping entries with a query number, should bring a city trip on France close to its
  regional cost. That is an estimate, to be measured once changed.
- **Lower the construction peak.** The France peak is 431 MB for 232 MB held. Building
  the flat arrays straight from the file buffer, without the intermediate
  `Stop`/`Transfer` objects, is the likely way to fit a 256 MB phone. That is not
  measured either.

**Pipeline:**

- Convert one day rather than a week when one day is all that is written. Merging or
  reading only the reference day should take France well under the 8 GB it needs today.
- Decide on the one-route-per-direction rule (the Toulon branch). Then convert again,
  benchmark again, and compare.
- `./gradlew` fails on a JDK 25 Gradle daemon: Kotlin 2.1.0 cannot parse Java 25's version
  string. Pin the daemon JVM to 21, or move to a Kotlin version that knows Java 25.

**Benchmark, step 8:** add the long-distance layer and measure a connected France. That
is where the "yes" above either holds or does not.

## Every network

| Tier | Stops | Trips written / found | Pipeline | Pipeline peak | `.bin` | Engine load | Engine heap | Random trip p50 / p95 | Arrive-by p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Métropole du Grand Paris | 35 364 | 122 489 / 144 434 | 41 s | 2.9 GB | 14.9 MB | 128 ms | 37 MB | 4.23 / 7.71 ms | 6.76 / 14.34 ms |
| Métropole de Lyon | 9 625 | 19 976 / 21 983 | 7 s | 0.8 GB | 2.7 MB | 56 ms | 9 MB | 0.48 / 1.04 ms | 0.99 / 2.46 ms |
| Aix-Marseille-Provence | 9 848 | 22 071 / 24 350 | 8 s | 0.9 GB | 3.0 MB | 60 ms | 9 MB | 0.59 / 1.36 ms | 1.20 / 2.76 ms |
| Métropole européenne de Lille | 3 314 | 7 321 / 9 001 | 4 s | 0.6 GB | 1.1 MB | 36 ms | 3 MB | 0.24 / 0.39 ms | 0.62 / 1.09 ms |
| Bordeaux Métropole | 3 911 | 5 770 / 7 035 | 5 s | 0.8 GB | 1.3 MB | 36 ms | 4 MB | 0.26 / 0.41 ms | 0.77 / 1.60 ms |
| Toulouse Métropole | 3 811 | 12 184 / 12 640 | 4 s | 0.7 GB | 1.5 MB | 37 ms | 4 MB | 0.28 / 0.44 ms | 0.75 / 1.52 ms |
| Nantes Métropole | 2 479 | 8 125 / 8 958 | 8 s | 0.8 GB | 1.0 MB | 26 ms | 2 MB | 0.15 / 0.28 ms | 0.43 / 0.83 ms |
| Métropole Nice Côte d'Azur | 2 821 | 6 109 / 6 757 | 4 s | 0.5 GB | 0.9 MB | 31 ms | 3 MB | 0.17 / 0.34 ms | 0.41 / 1.00 ms |
| Eurométropole de Strasbourg | 1 335 | 4 759 / 6 103 | 3 s | 0.5 GB | 0.5 MB | 26 ms | 1 MB | 0.08 / 0.22 ms | 0.23 / 0.51 ms |
| Montpellier Méditerranée Métropole | 1 453 | 3 750 / 4 389 | 2 s | 0.5 GB | 0.4 MB | 23 ms | 1 MB | 0.07 / 0.14 ms | 0.20 / 0.40 ms |
| Rennes Métropole | 1 774 | 5 763 / 6 173 | 4 s | 0.9 GB | 0.7 MB | 23 ms | 2 MB | 0.14 / 0.25 ms | 0.36 / 0.75 ms |
| Grenoble-Alpes Métropole | 2 173 | 4 704 / 5 385 | 2 s | 0.4 GB | 0.7 MB | 25 ms | 2 MB | 0.10 / 0.21 ms | 0.20 / 0.56 ms |
| Métropole Rouen Normandie | 2 481 | 5 276 / 5 711 | 3 s | 0.5 GB | 0.8 MB | 27 ms | 2 MB | 0.13 / 0.26 ms | 0.32 / 0.79 ms |
| Toulon Provence Méditerranée | 2 013 | 3 139 / 3 689 | 2 s | 0.4 GB | 0.6 MB | 26 ms | 2 MB | 0.17 / 0.31 ms | 0.41 / 0.84 ms |
| Saint-Étienne Métropole | 2 279 | 3 653 / 4 263 | 2 s | 0.4 GB | 0.6 MB | 23 ms | 2 MB | 0.11 / 0.24 ms | 0.22 / 0.63 ms |
| Tours Métropole Val de Loire | 1 496 | 2 641 / 2 827 | 2 s | 0.4 GB | 0.5 MB | 24 ms | 2 MB | 0.10 / 0.21 ms | 0.28 / 0.60 ms |
| Orléans Métropole | 1 346 | 1 741 / 2 323 | 4 s | 0.5 GB | 0.3 MB | 18 ms | 1 MB | 0.07 / 0.16 ms | 0.18 / 0.40 ms |
| Dijon Métropole | 1 095 | 3 201 / 3 634 | 2 s | 0.4 GB | 0.4 MB | 19 ms | 1 MB | 0.08 / 0.16 ms | 0.23 / 0.43 ms |
| Metz Métropole | 1 086 | 2 400 / 2 702 | 2 s | 0.5 GB | 0.3 MB | 22 ms | 1 MB | 0.08 / 0.19 ms | 0.21 / 0.41 ms |
| Métropole du Grand Nancy | 962 | 1 990 / 2 070 | 2 s | 0.5 GB | 0.4 MB | 22 ms | 1 MB | 0.08 / 0.23 ms | 0.23 / 0.47 ms |
| Clermont Auvergne Métropole | 1 360 | 2 182 / 2 641 | 2 s | 0.3 GB | 0.4 MB | 22 ms | 1 MB | 0.07 / 0.20 ms | 0.18 / 0.43 ms |
| Brest Métropole | 1 052 | 2 077 / 2 294 | 2 s | 0.3 GB | 0.3 MB | 21 ms | 1 MB | 0.11 / 0.25 ms | 0.27 / 0.63 ms |
| Île-de-France | 35 401 | 122 766 / 144 742 | 38 s | 2.8 GB | 15.0 MB | 136 ms | 37 MB | 3.14 / 6.18 ms | 5.74 / 11.78 ms |
| Centre-Val de Loire | 11 372 | 9 295 / 11 417 | 7 s | 0.8 GB | 2.0 MB | 57 ms | 8 MB | 0.13 / 0.69 ms | 0.30 / 0.84 ms |
| Bourgogne-Franche-Comté | 10 496 | 11 465 / 13 891 | 5 s | 0.9 GB | 1.9 MB | 55 ms | 7 MB | 0.15 / 0.58 ms | 0.31 / 0.78 ms |
| Normandie | 12 518 | 15 329 / 17 677 | 7 s | 0.7 GB | 2.5 MB | 60 ms | 9 MB | 0.22 / 0.77 ms | 0.46 / 1.09 ms |
| Hauts-de-France | 31 392 | 26 564 / 35 703 | 10 s | 1.2 GB | 5.6 MB | 110 ms | 23 MB | 0.38 / 2.13 ms | 0.97 / 2.91 ms |
| Grand Est | 26 374 | 29 776 / 38 343 | 13 s | 1.4 GB | 4.8 MB | 93 ms | 20 MB | 0.25 / 1.33 ms | 0.53 / 1.64 ms |
| Pays de la Loire | 13 820 | 18 438 / 21 293 | 12 s | 1.1 GB | 3.2 MB | 62 ms | 11 MB | 0.29 / 0.84 ms | 0.52 / 1.09 ms |
| Bretagne | 17 217 | 16 839 / 19 764 | 7 s | 1.2 GB | 2.9 MB | 65 ms | 12 MB | 0.24 / 1.08 ms | 0.43 / 1.29 ms |
| Nouvelle-Aquitaine | 28 914 | 23 977 / 34 011 | 11 s | 1.0 GB | 5.1 MB | 110 ms | 20 MB | 0.26 / 1.69 ms | 0.65 / 1.99 ms |
| Occitanie | 24 051 | 29 249 / 34 271 | 9 s | 1.1 GB | 4.6 MB | 80 ms | 17 MB | 0.41 / 1.51 ms | 0.74 / 1.91 ms |
| Auvergne-Rhône-Alpes | 54 223 | 51 272 / 61 583 | 16 s | 1.8 GB | 9.1 MB | 118 ms | 38 MB | 0.39 / 3.69 ms | 1.03 / 4.43 ms |
| Provence-Alpes-Côte d'Azur | 26 942 | 42 150 / 47 974 | 14 s | 1.5 GB | 6.9 MB | 108 ms | 24 MB | 0.92 / 2.54 ms | 1.77 / 3.46 ms |
| Corse | 731 | 1 329 / 1 387 | 1 s | 0.2 GB | 0.2 MB | 15 ms | 1 MB | 0.02 / 0.05 ms | 0.03 / 0.10 ms |
| France métropolitaine | 293 369 | 397 477 / 481 003 | 136 s | 9.3 GB | 64.2 MB | 436 ms | 229 MB | 4.03 / 11.53 ms | 6.20 / 15.03 ms |

The Grand Paris métropole and Île-de-France are both IDFM's feed. They differ only by
the few TER trips clipped into the region.

## Reproducing

From `benchmark/`, with the environment of [README.md](README.md):

```bash
JAVA_HOME=~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2 ../gradlew -p .. :cli:installDist :benchmark-engine:installDist
```

```bash
cd notebooks && ../.venv/Scripts/python -m jupyter nbconvert --to notebook --execute gtfs_france.ipynb --output out.ipynb
```

```bash
.venv/Scripts/python -m gtfs_bench.variants   # same-name links, optional; from benchmark/
```

Feeds update every day. A rerun picks another reference day and other versions, and
`results/feeds_used.csv` records which.
