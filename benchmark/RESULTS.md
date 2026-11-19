# Can raptor-kmp route over all of France?

## The short answer

**Yes.** The benchmark built one GTFS for the whole of mainland France: every city network,
the regional coaches and TER, and the long-distance layer (TGV, OUIGO, Intercités,
international trains, FlixBus, BlaBlaCar Bus, the Corsica ferries). That is 294,130 stops
and 481,983 trips on one day. raptor-kmp loads it in half a second, holds it in 257 MB,
and reaches every one of the 95 préfectures from Paris within the day.

- **On a server, it passes every target we set**, with a wide margin.
- **On a phone, memory and loading pass**, provided the app asks for a large heap.
  Everyday trips are quick too: half of the trips inside Lyon or Paris take under 8 ms.
  The slowest 5 % of searches take 40–45 ms, against a 30 ms target, so that target is
  missed. Those are long cross-country searches and "arrive by" searches. The fix belongs
  in the engine (see [What makes a search slower](#what-makes-a-search-slower)).

![From Paris to every préfecture](results/reachability.png)

*From Châtelet at 07:00, raptor-kmp searches for every préfecture. Left: the regional
networks only. Middle: the same, once the pipeline stops dropping trips. Right: with the
long-distance layer.*

### At a glance

France connexe, desktop JVM, four runs. The targets were set before measuring.

| | Measured | Phone target | Server target |
|---|---|---|---|
| Loading the network | 0.49–0.57 s | ≤ 3 s ✅ | — |
| Memory held once loaded | 257 MB | ≤ 512 MB ✅ (with `largeHeap`) | ≤ 4 GB ✅ |
| Smallest heap it loads in | 384 MB (fails at 320 MB) | | |
| A trip inside Lyon / Paris, typical (median) | 4.6–5.0 ms / 7.6–7.9 ms | | |
| Slowest 5 % of searches (p95) | 38–46 ms | ≤ 30 ms ❌ | ≤ 50 ms ✅ |
| Slowest 1 % of searches (p99) | 115–123 ms | — | ≤ 200 ms ✅ |

**How to read it:**
- **p95** is the time under which 95 % of searches finish. **p99** is the same for 99 %.
- These are times on a laptop (Intel Core Ultra 5). A phone is slower; ×3 is our estimate,
  not a measurement.
- **`largeHeap`** is the Android manifest flag that lets an app use more memory than the
  default 192–256 MB.

## What "all of France" covers

**In:** 235 feeds, taken on 18 and 19 November 2026, timetables of Tuesday 24 November
2026:
- every métropole's network and most urban networks;
- the regional coach networks and aggregates;
- every TER, from the national SNCF feed;
- TGV INOUI, OUIGO, Intercités (day and night), Lyria and ICE;
- Trenitalia and Renfe on their French sections;
- FlixBus and BlaBlaCar Bus;
- Corsica Linea between Marseille and Corsica.

The catalogue and the reason for every feed kept or left out are in
[`catalog/`](catalog/README.md).

**Out:**
- **Overseas regions.** They are not linked to the mainland and run on other time zones.
- **On-demand transport.** It has no fixed timetable to route on.
- **School-only networks.**
- **A handful of networks whose open data has expired or vanished:** Ruban
  (Bourgoin-Jallieu), TAC, Ogalo, EVA'D, Mobilité en Velay, and the Corsican railway.
- **Eurostar and the Channel ferries.** They add nothing within France: each of their
  trips stops only once in France.

## Three problems fixed on the way

A whole-France network did not work out of the box. Three things had to be fixed. Each
one was measured, and the first two are not specific to France: they affect any city.

### 1. Stops that share a name

raptor-kmp links every pair of stops with exactly the same name by a 2-minute walk. In
one city that is how the platforms of a station get tied together. Across France, every
"Gare", "Mairie" or "Église" is linked to all the others: 15.8 million links.

That made searches 5 to 10 times slower. Worse, the itineraries were wrong: a trip could
"walk" from the Mairie of one town to the Mairie of another, 200 km away.

**Fix, in the data:** stops sharing a name but far apart get the name of their commune
("Mairie (Vénissieux)"). It is a workaround. The engine should limit these links by
distance. → [details](#a-same-name-links)

### 2. Trips the pipeline throws away

The pipeline keeps one stop sequence per line and direction, the most frequent one. A
trip that skips one of its stops is dropped: an express TER, a TGV that does not stop at
Mâcon, a Sunday bus taking another way. On France, that is **17 % of the day's trips**.

**Fix:** give each stop sequence its own route. The benchmark does it in the merge.
Commit `273aac0` of the Toulon branch does the same in the pipeline itself. Both were
measured on France and give the same network, trip for trip, and the same itineraries
to all 95 préfectures. Effects:
- 99.9 % of the trips kept;
- on the regional networks alone, 88 préfectures reachable from Paris instead of 68;
- cost: about 25 MB of memory.

### 3. A France without long-distance trains

At first, the regions were only joined by TER. As a graph, France was already in one
piece: 99.7 % of the stops could reach one another, since TER lines cross every regional
border. But it was slow. Lyon → Paris took ten and a half hours, and Bordeaux → Nice could
not be done in a day.

**Fix:** add the long-distance layer, with wider walking links around stations, so that
a TGV platform connects to the metro outside.

| From 07:00 | Regional only | Regional, every trip kept | France connexe |
|---|---|---|---|
| Préfectures reachable from Paris | 68 / 95 | 88 / 95 | **95 / 95** |
| Typical time to a préfecture (median) | 8 h 53 | 6 h 29 | **3 h 40** |
| Lyon Part-Dieu → Paris Gare de Lyon | 10 h 30 | 8 h 27 | **2 h 02**, direct TGV |
| Lille Flandres → Marseille St-Charles | none | none | **5 h 14** |
| Brest → Strasbourg | none | none | **7 h 30** |
| Bordeaux St-Jean → Nice-Ville | none | none | **9 h 06** |

Corsica is reached by the overnight ferry, arriving at 07:00 the next day.

What is left apart is tiny: 0.07 % of the stops. It is a few rural or school networks
with no walkable link to anything, and the Pays de Gex, whose link is Geneva's network
across the border. → [details](#b-the-three-france-networks)

## What makes a search slower

Three things weigh on the time of a search. Only the first one is a weakness of the
engine.

**1. A fixed cost that grows with the network.** Before every search, raptor-kmp
resets its working memory for *every* stop of the network. It does so even when the trip
only crosses one city. A trip inside Lyon takes 0.4 ms on the Lyon network, 0.7 ms on
Auvergne-Rhône-Alpes and 4.2 ms on France: the same trip, with the same answer. About 4 ms
of that is the reset. Resetting only what the previous search touched should remove most
of it. This is the main lever for phones.

![Same trips, bigger network](results/engine_local_trips.png)

**2. More answers to find.** On the regional France, most random pairs of stops across
the country have no answer, and the search gives up early. On France connexe, 3.6 times
as many pairs are joined, so searches go further before they settle. That is why the
slowest 5 % went from 12 ms to 40 ms. It is the price of a network that actually works
end to end.

**3. More changes allowed.** The apps allow 4 changes (5 "rounds" in RAPTOR terms). We
tried 7 changes: the slowest 5 % of searches doubled again (94 ms). None of the long trips
needed it, as all four were already found with 4 changes. **Keep the default.**

## Memory

Memory grows in step with the network: about 0.9 KB per stop. A city takes a few MB, a
region up to 40 MB, France 257 MB once loaded.

Loading needs more than that: about 400 MB at the peak, because the file and the
network being built are in memory at the same time. So France connexe loads with a
384 MB heap but not with 320 MB. Without `largeHeap`, many Android phones give an app
192–256 MB, which is not enough. Building the network straight from the file, without
intermediate objects, could bring the peak down.

## The pipeline

The pipeline converts the whole of France in about 2.5 minutes, unmodified. It needs
about 10 GB of memory to do so. It reads the whole week the merge hands it, although it
writes only one day. Reading only the day it writes would cut that a lot.

| | Regional France | France connexe |
|---|---:|---:|
| Conversion time | 136 s | 157 s |
| Peak memory | 9.3 GB | 9.6 GB |
| Output (`stops.bin` + `routes.bin`) | 64 MB | 76 MB |

## Limits

- **No phone was measured.** Memory figures carry over to Android, since the same data
  is allocated. Times do not.
- **One day.** Everything is for Tuesday 24 November 2026. A trip that needs two days (a
  night ferry, then a morning connection) cannot be found. Weekends and holidays have
  fewer trips.
- **No booking rules.** The pipeline ignores pick-up and drop-off restrictions. FlixBus
  and BlaBlaCar declare none, so nothing is lost there. A coach "à réservation" is
  treated like any other.
- **The 36 smaller networks of the size curve** (22 métropoles, 13 regions) were measured
  before fix 2. They miss 4–30 % of their trips. Their times and memory are still right
  for what they hold.

## What to do next

**In raptor-kmp:**
1. **Limit same-name links by distance**, or drop them in favour of `transfers.txt`. Then
   no merged network needs the renaming workaround.
2. **Reset only what the previous search touched.** This brings a city trip on France back
   close to its cost on the city alone. It is the change that should get phones under
   30 ms. That is an estimate, to measure once done.
3. **Build the network without intermediate objects**, to load France in less than
   384 MB.

**In the pipeline:**
1. **Merge the "one route per stop sequence" fix** (commit `273aac0`), after checking that
   the apps do not read a line's routes as its two directions. That is a breaking change,
   which is why the commit bumps the version to 0.5.0.
2. **Read only the day being converted**, to bring France well under 10 GB.
3. Pin the Gradle daemon to JDK 21: Kotlin 2.1.0 fails on JDK 25.

**In the benchmark:** measure on a real phone, with France connexe and `largeHeap`.

## How it was measured

- **Data:** the catalogue's included feeds ([`catalog/gtfs_france.csv`](catalog/gtfs_france.csv)),
  downloaded on 18–19 November 2026. Every version used is in
  [`results/feeds_used.csv`](results/feeds_used.csv).
- **Day:** Tuesday 24 November 2026, the school Tuesday the most feeds run on (220 of
  225). The merge keeps its week; the pipeline converts the day.
- **Merge** (`gtfs_bench/`):
  - every id prefixed by its feed;
  - trips carried twice removed;
  - far-apart homonyms renamed;
  - walking transfers generated (300 m, and 500 m around stations).
- **Networks:**
  - 22 métropoles ⊂ 13 regions ⊂ France (the size curve, regional layer);
  - three versions of France for step 8: regional only, every trip kept, connexe.
- **Pipeline:** `main`, unmodified, JDK 21.
- **Engine:** `eu.dotshell:raptor-kmp-jvm` 2.2.0 from Maven Central, a fresh JVM per run,
  4 changes allowed (the apps' default).
- **Searches:**
  - 1,000 random pairs of stops across the network (forward and arrive-by);
  - 300 trips inside Lyon and 300 inside Paris, replayed on every network that contains
    the city;
  - ten named trips;
  - Paris → every préfecture.
- **Cross-check:** on Lyon, a random search takes 0.46 ms on average. raptor-kmp's own
  benchmark gives 0.35 ms, on an older TCL export.
- **Machine:** Intel Core Ultra 5 135H, 15 GB, Windows 11.

## Appendix: the detail

Every figure above comes from a file in [`results/`](results/). The tables below are the
ones worth reading; the CSV files have everything.

### A. Same-name links

The same France, merged with the producers' stop names, converted and timed the same way
([`engine_same_name_links.csv`](results/engine_same_name_links.csv)).

| Regional France | Renamed (benchmark) | Producers' names |
|---|---:|---:|
| Same-name links built by the engine | 318 110 | 15 787 962 |
| Largest group of stops with one name | 23 | 2 669 |
| Memory held | 229 MB | 282 MB |
| Lyon trips, median / p95 | 4.2 / 6.3 ms | 37.1 / 70.7 ms |
| Paris trips arrive-by, p95 / p99 | 23.3 / 91.4 ms | 561.7 / 678.6 ms |
| Random pairs "joined" | 51 / 1,000 | 518 / 1,000 |
| Typical Paris trip | 36 min | 20 min |

The last two rows are the wrong itineraries: ten times more pairs "joined", and Paris trips
16 minutes shorter, by jumping between towns that share a stop name.

### B. The three France networks

([`connected_france.csv`](results/connected_france.csv),
[`connected_scenarios.csv`](results/connected_scenarios.csv),
[`connectivity_islands.csv`](results/connectivity_islands.csv),
[`reachability_prefectures.csv`](results/reachability_prefectures.csv))

| | Regional only | Every trip kept | France connexe |
|---|---:|---:|---:|
| Feeds | 225 | 225 | 235 |
| Trips kept by the pipeline | 397 477 (83 %) | 480 669 (99.9 %) | 481 983 (99.9 %) |
| Routes loaded | 35 453 | 72 641 | 73 493 |
| Stops in the largest connected piece | 99.71 % | 99.71 % | 99.93 % |
| Loading | 436 ms | 563 ms | 571 ms |
| Memory held | 229 MB | 254 MB | 257 MB |
| Random pairs joined (of 1,000) | 51 | 78 | 183 |
| Random search, median / p95 / p99 | 4.0 / 11.5 / 14.6 ms | 5.8 / 20.7 / 27.4 ms | 10.7 / 40.4 / 54.7 ms |
| Arrive-by, median / p95 / p99 | 6.2 / 15.0 / 18.4 ms | 8.8 / 26.1 / 34.4 ms | 15.2 / 45.6 / 63.8 ms |
| Lyon trips, median / p95 | 4.2 / 6.3 ms | 4.7 / 7.8 ms | 5.0 / 11.6 ms |
| Paris trips, median / p95 | 6.5 / 9.9 ms | 8.2 / 14.6 ms | 7.9 / 15.6 ms |
| Random search with 7 changes, p95 | 27.9 ms | 56.1 ms | 94.3 ms |

The long-distance layer on 24 November is 1,324 trips:
- 862 SNCF: 538 TGV INOUI, 120 reservation coaches, 71 OUIGO, 72 Intercités, 34 Lyria,
  26 ICE;
- 323 FlixBus;
- 100 BlaBlaCar Bus;
- 26 Trenitalia;
- 8 Renfe;
- 5 Corsica Linea crossings.

France connexe was run four times. Between runs, loading varied by 0.08 s and the
random p95 by 2.5 ms ([`engine/variants/runs/`](results/engine/variants/runs/)).

**The Toulon branch's fix, checked.** France connexe was merged without the benchmark's
split, then converted by `main` + `273aac0`. It gives the same 481,983 trips and 73,493
routes, the same times to all 95 préfectures and the same long trips. It holds 6 MB less
memory. With `main` alone, 17 % of the trips go and Corsica is out of reach.

### C. Every network of the size curve

The 36 networks of the regional layer, before fix 2.

| Network | Stops | Loading | Memory | Random search, median / p95 |
|---|---:|---:|---:|---:|
| Métropole du Grand Paris | 35 364 | 128 ms | 37 MB | 4.23 / 7.71 ms |
| Métropole de Lyon | 9 625 | 56 ms | 9 MB | 0.48 / 1.04 ms |
| Aix-Marseille-Provence | 9 848 | 60 ms | 9 MB | 0.59 / 1.36 ms |
| Métropole européenne de Lille | 3 314 | 36 ms | 3 MB | 0.24 / 0.39 ms |
| Bordeaux Métropole | 3 911 | 36 ms | 4 MB | 0.26 / 0.41 ms |
| Toulouse Métropole | 3 811 | 37 ms | 4 MB | 0.28 / 0.44 ms |
| Nantes Métropole | 2 479 | 26 ms | 2 MB | 0.15 / 0.28 ms |
| Métropole Nice Côte d'Azur | 2 821 | 31 ms | 3 MB | 0.17 / 0.34 ms |
| Eurométropole de Strasbourg | 1 335 | 26 ms | 1 MB | 0.08 / 0.22 ms |
| Montpellier Méditerranée Métropole | 1 453 | 23 ms | 1 MB | 0.07 / 0.14 ms |
| Rennes Métropole | 1 774 | 23 ms | 2 MB | 0.14 / 0.25 ms |
| Grenoble-Alpes Métropole | 2 173 | 25 ms | 2 MB | 0.10 / 0.21 ms |
| Métropole Rouen Normandie | 2 481 | 27 ms | 2 MB | 0.13 / 0.26 ms |
| Toulon Provence Méditerranée | 2 013 | 26 ms | 2 MB | 0.17 / 0.31 ms |
| Saint-Étienne Métropole | 2 279 | 23 ms | 2 MB | 0.11 / 0.24 ms |
| Tours Métropole Val de Loire | 1 496 | 24 ms | 2 MB | 0.10 / 0.21 ms |
| Orléans Métropole | 1 346 | 18 ms | 1 MB | 0.07 / 0.16 ms |
| Dijon Métropole | 1 095 | 19 ms | 1 MB | 0.08 / 0.16 ms |
| Metz Métropole | 1 086 | 22 ms | 1 MB | 0.08 / 0.19 ms |
| Métropole du Grand Nancy | 962 | 22 ms | 1 MB | 0.08 / 0.23 ms |
| Clermont Auvergne Métropole | 1 360 | 22 ms | 1 MB | 0.07 / 0.20 ms |
| Brest Métropole | 1 052 | 21 ms | 1 MB | 0.11 / 0.25 ms |
| Île-de-France | 35 401 | 136 ms | 37 MB | 3.14 / 6.18 ms |
| Centre-Val de Loire | 11 372 | 57 ms | 8 MB | 0.13 / 0.69 ms |
| Bourgogne-Franche-Comté | 10 496 | 55 ms | 7 MB | 0.15 / 0.58 ms |
| Normandie | 12 518 | 60 ms | 9 MB | 0.22 / 0.77 ms |
| Hauts-de-France | 31 392 | 110 ms | 23 MB | 0.38 / 2.13 ms |
| Grand Est | 26 374 | 93 ms | 20 MB | 0.25 / 1.33 ms |
| Pays de la Loire | 13 820 | 62 ms | 11 MB | 0.29 / 0.84 ms |
| Bretagne | 17 217 | 65 ms | 12 MB | 0.24 / 1.08 ms |
| Nouvelle-Aquitaine | 28 914 | 110 ms | 20 MB | 0.26 / 1.69 ms |
| Occitanie | 24 051 | 80 ms | 17 MB | 0.41 / 1.51 ms |
| Auvergne-Rhône-Alpes | 54 223 | 118 ms | 38 MB | 0.39 / 3.69 ms |
| Provence-Alpes-Côte d'Azur | 26 942 | 108 ms | 24 MB | 0.92 / 2.54 ms |
| Corse | 731 | 15 ms | 1 MB | 0.02 / 0.05 ms |
| France métropolitaine | 293 369 | 436 ms | 229 MB | 4.03 / 11.53 ms |

## Reproducing

From `benchmark/`, with the environment of [README.md](README.md):

```bash
JAVA_HOME=~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2 ../gradlew -p .. :cli:installDist :benchmark-engine:installDist
```

```bash
cd notebooks && ../.venv/Scripts/python -m jupyter nbconvert --to notebook --execute gtfs_france.ipynb --output out.ipynb
```

```bash
.venv/Scripts/python -m gtfs_bench.variants   # same-name links, optional
.venv/Scripts/python -m gtfs_bench.connected  # the three France networks (step 8), ~20 min
```

Feeds change every day. A rerun picks another reference day and other versions, and
`results/feeds_used.csv` records which.
