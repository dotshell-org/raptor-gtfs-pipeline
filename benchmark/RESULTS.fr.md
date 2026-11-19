# raptor-kmp peut-il calculer des itinéraires sur toute la France ?

*[English version](RESULTS.md)*

## La réponse courte

**Oui.** Le benchmark a construit un seul GTFS pour toute la France métropolitaine :

- tous les réseaux urbains ;
- les cars régionaux et les TER ;
- la couche longue distance : TGV, OUIGO, Intercités, trains internationaux, FlixBus,
  BlaBlaCar Bus et ferries vers la Corse.

Cela fait 294 130 arrêts et 481 983 courses sur une journée. raptor-kmp le charge en une
demi-seconde, le tient en 257 Mo et atteint dans la journée chacune des 95 préfectures
depuis Paris.

- **Sur un serveur, il passe tous les objectifs fixés**, avec une large marge.
- **Sur un téléphone, la mémoire et le chargement passent**, à condition que l'appli
  demande un grand tas.
  - Les trajets du quotidien sont rapides aussi : la moitié des trajets dans Lyon ou dans
    Paris prennent moins de 8 ms.
  - Les 5 % de recherches les plus lentes prennent 40 à 45 ms, pour un objectif de 30 ms :
    cet objectif n'est donc pas atteint. Ce sont les longues recherches à travers le pays
    et les recherches « arriver avant ».
  - La correction relève du moteur (voir
    [Ce qui ralentit une recherche](#ce-qui-ralentit-une-recherche)).

![De Paris à chaque préfecture](results/reachability.png)

*Depuis Châtelet à 07:00, raptor-kmp cherche un itinéraire vers chaque préfecture.
À gauche : les réseaux régionaux seuls. Au milieu : les mêmes, une fois que le pipeline
ne perd plus de courses. À droite : avec la couche longue distance.*

### En un coup d'œil

France connexe, JVM de bureau, quatre exécutions. Les objectifs ont été fixés avant de
mesurer.

| | Mesuré | Objectif téléphone | Objectif serveur |
|---|---|---|---|
| Chargement du réseau | 0,49–0,57 s | ≤ 3 s ✅ | — |
| Mémoire occupée une fois chargé | 257 Mo | ≤ 512 Mo ✅ (avec `largeHeap`) | ≤ 4 Go ✅ |
| Plus petit tas qui permet de le charger | 384 Mo (échec à 320 Mo) | | |
| Un trajet dans Lyon / dans Paris, cas typique (médiane) | 4,6–5,0 ms / 7,6–7,9 ms | | |
| 5 % de recherches les plus lentes (p95) | 38–46 ms | ≤ 30 ms ❌ | ≤ 50 ms ✅ |
| 1 % de recherches les plus lentes (p99) | 115–123 ms | — | ≤ 200 ms ✅ |

**Comment lire ce tableau :**

- **p95** est la durée en dessous de laquelle se terminent 95 % des recherches. **p99**,
  la même chose pour 99 %.
- Ces temps sont mesurés sur un ordinateur portable (Intel Core Ultra 5). Un téléphone est
  plus lent : notre estimation est ×3, sans mesure.
- **`largeHeap`** est l'option du manifeste Android qui permet à une appli d'utiliser plus
  de mémoire que les 192–256 Mo par défaut.

## Ce que couvre « toute la France »

**Inclus :** 235 sources, récupérées les 18 et 19 novembre 2026, avec les horaires du
mardi 24 novembre 2026 :

- le réseau de chaque métropole et la plupart des réseaux urbains ;
- les réseaux de cars régionaux et les agrégats régionaux ;
- tous les TER, tirés du flux national de la SNCF ;
- TGV INOUI, OUIGO, Intercités (jour et nuit), Lyria et ICE ;
- Trenitalia et Renfe, sur leurs portions françaises ;
- FlixBus et BlaBlaCar Bus ;
- Corsica Linea entre Marseille et la Corse.

Le catalogue, avec la raison de chaque source retenue ou écartée, est dans
[`catalog/`](catalog/README.md).

**Exclus :**

- **L'outre-mer.** Il n'est pas relié à la métropole et vit sur d'autres fuseaux horaires.
- **Le transport à la demande.** Il n'a pas d'horaires fixes sur lesquels calculer.
- **Les réseaux uniquement scolaires.**
- **Une poignée de réseaux dont les données ouvertes ont expiré ou disparu :** Ruban
  (Bourgoin-Jallieu), TAC, Ogalo, EVA'D, Mobilité en Velay et le chemin de fer corse.
- **Eurostar et les ferries transmanche.** Ils n'apportent rien à l'intérieur de la
  France : chacune de leurs courses ne s'arrête qu'une fois en France.

## Trois problèmes corrigés en chemin

Un réseau de toute la France ne fonctionnait pas tel quel. Il a fallu corriger trois
choses. Chacune a été mesurée, et les deux premières ne sont pas propres à la France :
elles touchent n'importe quelle ville.

### 1. Les arrêts qui portent le même nom

raptor-kmp relie par une marche de 2 minutes chaque paire d'arrêts au nom strictement
identique. Dans une ville, c'est ce qui relie entre eux les quais d'une gare. À l'échelle
de la France, chaque « Gare », « Mairie » ou « Église » se retrouve reliée à toutes les
autres : 15,8 millions de liens.

Les recherches devenaient 5 à 10 fois plus lentes. Pire, les itinéraires étaient faux :
un trajet pouvait « marcher » de la mairie d'une ville à celle d'une autre, à 200 km.

**Correction, dans les données :** les arrêts de même nom mais éloignés prennent le nom
de leur commune (« Mairie (Vénissieux) »). C'est un contournement : le moteur devrait
limiter ces liens à une distance. → [détails](#a-les-arrêts-de-même-nom)

### 2. Les courses que le pipeline jette

Le pipeline garde une seule suite d'arrêts par ligne et par sens, la plus fréquente. Une
course qui saute l'un de ces arrêts est écartée : un TER direct, un TGV qui ne s'arrête
pas à Mâcon, un bus du dimanche qui passe ailleurs. Sur la France, cela représente
**17 % des courses de la journée**.

**Correction :** donner à chaque suite d'arrêts sa propre route.

- Le benchmark le fait lors de la fusion.
- Le commit `273aac0` de la branche Toulon fait la même chose dans le pipeline lui-même.
- Les deux ont été mesurés sur la France : même réseau, course pour course, et mêmes
  itinéraires vers les 95 préfectures.

Effets :

- 99,9 % des courses conservées ;
- avec les seuls réseaux régionaux, 88 préfectures accessibles depuis Paris au lieu
  de 68 ;
- coût : environ 25 Mo de mémoire.

### 3. Une France sans trains longue distance

Au départ, les régions n'étaient reliées que par les TER. En tant que graphe, la France
formait déjà un seul bloc : 99,7 % des arrêts pouvaient s'atteindre les uns les autres,
puisque des lignes TER franchissent chaque frontière régionale. Mais c'était lent :
Lyon → Paris prenait dix heures et demie, et Bordeaux → Nice était impossible dans la
journée.

**Correction :** ajouter la couche longue distance, avec des liaisons à pied plus larges
autour des gares, pour qu'un quai de TGV rejoigne le métro qui est devant.

| Départ 07:00 | Régional seul | Régional, toutes les courses | France connexe |
|---|---|---|---|
| Préfectures accessibles depuis Paris | 68 / 95 | 88 / 95 | **95 / 95** |
| Durée typique vers une préfecture (médiane) | 8 h 53 | 6 h 29 | **3 h 40** |
| Lyon Part-Dieu → Paris Gare de Lyon | 10 h 30 | 8 h 27 | **2 h 02**, TGV direct |
| Lille Flandres → Marseille St-Charles | aucun | aucun | **5 h 14** |
| Brest → Strasbourg | aucun | aucun | **7 h 30** |
| Bordeaux St-Jean → Nice-Ville | aucun | aucun | **9 h 06** |

La Corse est atteinte par le ferry de nuit, qui arrive à 07:00 le lendemain.

Ce qui reste isolé est minuscule : 0,07 % des arrêts. Ce sont quelques réseaux ruraux ou
scolaires sans aucune liaison à pied vers le reste, et le Pays de Gex, dont la liaison
passe par le réseau de Genève, de l'autre côté de la frontière.
→ [détails](#b-les-trois-réseaux-france)

## Ce qui ralentit une recherche

Trois choses pèsent sur la durée d'une recherche. Seule la première est une faiblesse du
moteur.

**1. Un coût fixe qui grandit avec le réseau.** Avant chaque recherche, raptor-kmp remet
à zéro sa mémoire de travail pour *tous* les arrêts du réseau, même quand le trajet ne
traverse qu'une ville. Un même trajet dans Lyon, avec la même réponse, prend :

- 0,4 ms sur le réseau lyonnais ;
- 0,7 ms sur Auvergne-Rhône-Alpes ;
- 4,2 ms sur la France.

Environ 4 ms viennent de cette remise à zéro. Ne remettre à zéro que ce que la recherche
précédente a touché devrait en supprimer l'essentiel. C'est le principal levier pour les
téléphones.

![Mêmes trajets, réseau plus grand](results/engine_local_trips.png)

**2. Plus de réponses à trouver.** Sur la France régionale, la plupart des paires
d'arrêts tirées au hasard à travers le pays n'ont pas de réponse, et la recherche
abandonne tôt. Sur la France connexe, 3,6 fois plus de paires sont reliées : les
recherches vont donc plus loin avant de conclure. C'est pourquoi les 5 % les plus lentes
sont passées de 12 ms à 40 ms. C'est le prix d'un réseau qui marche vraiment de bout en
bout.

**3. Plus de correspondances permises.** Les applis autorisent 4 correspondances
(5 « tours » dans le vocabulaire de RAPTOR). Nous en avons essayé 7 :

- les 5 % de recherches les plus lentes ont encore doublé (94 ms) ;
- aucun des longs trajets n'en avait besoin : les quatre étaient déjà trouvés avec
  4 correspondances.

**Gardez la valeur par défaut.**

## La mémoire

La mémoire grandit au même rythme que le réseau : environ 0,9 Ko par arrêt. Une ville
occupe quelques Mo, une région jusqu'à 40 Mo, la France 257 Mo une fois chargée.

Le chargement demande davantage : environ 400 Mo au plus haut, parce que le fichier et le
réseau en construction sont en mémoire en même temps. La France connexe se charge donc
avec un tas de 384 Mo, mais pas avec 320 Mo.

- Sans `largeHeap`, beaucoup de téléphones Android donnent 192–256 Mo à une appli, ce qui
  ne suffit pas.
- Construire le réseau directement depuis le fichier, sans objets intermédiaires, pourrait
  faire baisser ce pic.

## Le pipeline

Le pipeline convertit toute la France en environ 2 minutes 30, sans modification. Il lui
faut pour cela environ 10 Go de mémoire : il lit toute la semaine que lui fournit la
fusion, alors qu'il n'en écrit qu'un jour. Ne lire que le jour converti réduirait
beaucoup ce besoin.

| | France régionale | France connexe |
|---|---:|---:|
| Durée de conversion | 136 s | 157 s |
| Pic de mémoire | 9,3 Go | 9,6 Go |
| Sortie (`stops.bin` + `routes.bin`) | 64 Mo | 76 Mo |

## Limites

- **Aucun téléphone n'a été mesuré.** Les chiffres de mémoire valent pour Android,
  puisque les mêmes données y sont allouées. Pas les temps.
- **Un seul jour.**
  - Tout porte sur le mardi 24 novembre 2026.
  - Un trajet qui demande deux jours (un ferry de nuit, puis une correspondance le matin)
    est introuvable.
  - Les week-ends et les vacances comptent moins de courses.
- **Pas de règles de réservation.** Le pipeline ignore les restrictions de montée et de
  descente. FlixBus et BlaBlaCar n'en déclarent aucune, donc rien n'est perdu de ce côté.
  Un car « à réservation » est traité comme n'importe quel autre.
- **Les 36 petits réseaux de la courbe de taille** (22 métropoles, 13 régions) ont été
  mesurés avant la correction n° 2. Il leur manque 4 à 30 % de leurs courses. Leurs temps
  et leur mémoire restent justes pour ce qu'ils contiennent.

## Et maintenant

**Dans raptor-kmp :**

1. **Limiter à une distance les liens entre arrêts de même nom**, ou les abandonner au
   profit de `transfers.txt`. Plus aucun réseau fusionné n'aurait alors besoin du
   contournement par renommage.
2. **Ne remettre à zéro que ce que la recherche précédente a touché.**
   - Un trajet urbain sur la France reviendrait alors près de son coût sur la ville seule.
   - C'est le changement qui devrait faire passer les téléphones sous 30 ms : une
     estimation, à mesurer une fois fait.
3. **Construire le réseau sans objets intermédiaires**, pour charger la France avec moins
   de 384 Mo.

**Dans le pipeline :**

1. **Fusionner la correction « une route par suite d'arrêts »** (commit `273aac0`), après
   avoir vérifié que les applis ne lisent pas les routes d'une ligne comme ses deux sens.
   C'est un changement cassant : le commit passe d'ailleurs la version à 0.5.0.
2. **Ne lire que le jour converti**, pour faire passer la France bien sous 10 Go.
3. Fixer le démon Gradle sur le JDK 21 : Kotlin 2.1.0 échoue avec le JDK 25.

**Dans le benchmark :** mesurer sur un vrai téléphone, avec la France connexe et
`largeHeap`.

## Méthode

- **Données :** les sources retenues du catalogue
  ([`catalog/gtfs_france.csv`](catalog/gtfs_france.csv)), téléchargées les 18 et
  19 novembre 2026. Chaque version utilisée est dans
  [`results/feeds_used.csv`](results/feeds_used.csv).
- **Jour :** le mardi 24 novembre 2026, le mardi scolaire où circulent le plus de sources
  (220 sur 225). La fusion garde sa semaine ; le pipeline convertit le jour.
- **Fusion** (`gtfs_bench/`) :
  - chaque identifiant préfixé par sa source ;
  - courses présentes en double supprimées ;
  - homonymes éloignés renommés ;
  - correspondances à pied générées (300 m, et 500 m autour des gares).
- **Réseaux :**
  - 22 métropoles ⊂ 13 régions ⊂ la France (la courbe de taille, couche régionale) ;
  - trois versions de la France pour l'étape 8 : régionale seule, toutes les courses,
    connexe.
- **Pipeline :** `main`, sans modification, JDK 21.
- **Moteur :** `eu.dotshell:raptor-kmp-jvm` 2.2.0 depuis Maven Central, une JVM neuve
  par exécution, 4 correspondances permises (le réglage par défaut des applis).
- **Recherches :**
  - 1 000 paires d'arrêts aléatoires à travers le réseau, en départ et en « arriver
    avant » ;
  - 300 trajets dans Lyon et 300 dans Paris, rejoués sur chaque réseau qui contient la
    ville ;
  - dix trajets nommés ;
  - Paris → chaque préfecture.
- **Contre-vérification :** sur Lyon, une recherche aléatoire prend 0,46 ms en moyenne.
  Le benchmark de raptor-kmp donne 0,35 ms, sur un export TCL plus ancien.
- **Machine :** Intel Core Ultra 5 135H, 15 Go, Windows 11.

## Annexe : le détail

Chaque chiffre ci-dessus vient d'un fichier de [`results/`](results/). Les tableaux
ci-dessous sont ceux qui valent la lecture ; les fichiers CSV contiennent tout.

### A. Les arrêts de même nom

La même France, fusionnée avec les noms d'arrêts des producteurs, convertie et mesurée
de la même façon ([`engine_same_name_links.csv`](results/engine_same_name_links.csv)).

| France régionale | Renommés (benchmark) | Noms des producteurs |
|---|---:|---:|
| Liens de même nom créés par le moteur | 318 110 | 15 787 962 |
| Plus grand groupe d'arrêts portant un même nom | 23 | 2 669 |
| Mémoire occupée | 229 Mo | 282 Mo |
| Trajets dans Lyon, médiane / p95 | 4,2 / 6,3 ms | 37,1 / 70,7 ms |
| Trajets dans Paris en « arriver avant », p95 / p99 | 23,3 / 91,4 ms | 561,7 / 678,6 ms |
| Paires aléatoires « reliées » | 51 / 1 000 | 518 / 1 000 |
| Trajet typique dans Paris | 36 min | 20 min |

Les deux dernières lignes sont les itinéraires faux. Dix fois plus de paires sont
« reliées », et les trajets parisiens raccourcissent de 16 minutes, en sautant d'une
ville à l'autre par un nom d'arrêt partagé.

### B. Les trois réseaux France

([`connected_france.csv`](results/connected_france.csv),
[`connected_scenarios.csv`](results/connected_scenarios.csv),
[`connectivity_islands.csv`](results/connectivity_islands.csv),
[`reachability_prefectures.csv`](results/reachability_prefectures.csv))

| | Régional seul | Toutes les courses | France connexe |
|---|---:|---:|---:|
| Sources | 225 | 225 | 235 |
| Courses gardées par le pipeline | 397 477 (83 %) | 480 669 (99,9 %) | 481 983 (99,9 %) |
| Routes chargées | 35 453 | 72 641 | 73 493 |
| Arrêts dans le plus grand bloc connexe | 99,71 % | 99,71 % | 99,93 % |
| Chargement | 436 ms | 563 ms | 571 ms |
| Mémoire occupée | 229 Mo | 254 Mo | 257 Mo |
| Paires aléatoires reliées (sur 1 000) | 51 | 78 | 183 |
| Recherche aléatoire, médiane / p95 / p99 | 4,0 / 11,5 / 14,6 ms | 5,8 / 20,7 / 27,4 ms | 10,7 / 40,4 / 54,7 ms |
| « Arriver avant », médiane / p95 / p99 | 6,2 / 15,0 / 18,4 ms | 8,8 / 26,1 / 34,4 ms | 15,2 / 45,6 / 63,8 ms |
| Trajets dans Lyon, médiane / p95 | 4,2 / 6,3 ms | 4,7 / 7,8 ms | 5,0 / 11,6 ms |
| Trajets dans Paris, médiane / p95 | 6,5 / 9,9 ms | 8,2 / 14,6 ms | 7,9 / 15,6 ms |
| Recherche aléatoire avec 7 correspondances, p95 | 27,9 ms | 56,1 ms | 94,3 ms |

La couche longue distance représente 1 324 courses le 24 novembre :

- 862 SNCF : 538 TGV INOUI, 120 cars à réservation, 71 OUIGO, 72 Intercités, 34 Lyria,
  26 ICE ;
- 323 FlixBus ;
- 100 BlaBlaCar Bus ;
- 26 Trenitalia ;
- 8 Renfe ;
- 5 traversées Corsica Linea.

La France connexe a été mesurée quatre fois. D'une exécution à l'autre, le chargement a
varié de 0,08 s et le p95 aléatoire de 2,5 ms
([`engine/variants/runs/`](results/engine/variants/runs/)).

**La correction de la branche Toulon, vérifiée.** La France connexe a été fusionnée sans
le découpage du benchmark, puis convertie par `main` + `273aac0` :

- mêmes 481 983 courses et 73 493 routes ;
- mêmes durées vers les 95 préfectures, mêmes longs trajets ;
- 6 Mo de mémoire en moins.

Avec `main` seul, 17 % des courses disparaissent et la Corse devient inaccessible.

### C. Chaque réseau de la courbe de taille

Les 36 réseaux de la couche régionale, avant la correction n° 2.

| Réseau | Arrêts | Chargement | Mémoire | Recherche aléatoire, médiane / p95 |
|---|---:|---:|---:|---:|
| Métropole du Grand Paris | 35 364 | 128 ms | 37 Mo | 4,23 / 7,71 ms |
| Métropole de Lyon | 9 625 | 56 ms | 9 Mo | 0,48 / 1,04 ms |
| Aix-Marseille-Provence | 9 848 | 60 ms | 9 Mo | 0,59 / 1,36 ms |
| Métropole européenne de Lille | 3 314 | 36 ms | 3 Mo | 0,24 / 0,39 ms |
| Bordeaux Métropole | 3 911 | 36 ms | 4 Mo | 0,26 / 0,41 ms |
| Toulouse Métropole | 3 811 | 37 ms | 4 Mo | 0,28 / 0,44 ms |
| Nantes Métropole | 2 479 | 26 ms | 2 Mo | 0,15 / 0,28 ms |
| Métropole Nice Côte d'Azur | 2 821 | 31 ms | 3 Mo | 0,17 / 0,34 ms |
| Eurométropole de Strasbourg | 1 335 | 26 ms | 1 Mo | 0,08 / 0,22 ms |
| Montpellier Méditerranée Métropole | 1 453 | 23 ms | 1 Mo | 0,07 / 0,14 ms |
| Rennes Métropole | 1 774 | 23 ms | 2 Mo | 0,14 / 0,25 ms |
| Grenoble-Alpes Métropole | 2 173 | 25 ms | 2 Mo | 0,10 / 0,21 ms |
| Métropole Rouen Normandie | 2 481 | 27 ms | 2 Mo | 0,13 / 0,26 ms |
| Toulon Provence Méditerranée | 2 013 | 26 ms | 2 Mo | 0,17 / 0,31 ms |
| Saint-Étienne Métropole | 2 279 | 23 ms | 2 Mo | 0,11 / 0,24 ms |
| Tours Métropole Val de Loire | 1 496 | 24 ms | 2 Mo | 0,10 / 0,21 ms |
| Orléans Métropole | 1 346 | 18 ms | 1 Mo | 0,07 / 0,16 ms |
| Dijon Métropole | 1 095 | 19 ms | 1 Mo | 0,08 / 0,16 ms |
| Metz Métropole | 1 086 | 22 ms | 1 Mo | 0,08 / 0,19 ms |
| Métropole du Grand Nancy | 962 | 22 ms | 1 Mo | 0,08 / 0,23 ms |
| Clermont Auvergne Métropole | 1 360 | 22 ms | 1 Mo | 0,07 / 0,20 ms |
| Brest Métropole | 1 052 | 21 ms | 1 Mo | 0,11 / 0,25 ms |
| Île-de-France | 35 401 | 136 ms | 37 Mo | 3,14 / 6,18 ms |
| Centre-Val de Loire | 11 372 | 57 ms | 8 Mo | 0,13 / 0,69 ms |
| Bourgogne-Franche-Comté | 10 496 | 55 ms | 7 Mo | 0,15 / 0,58 ms |
| Normandie | 12 518 | 60 ms | 9 Mo | 0,22 / 0,77 ms |
| Hauts-de-France | 31 392 | 110 ms | 23 Mo | 0,38 / 2,13 ms |
| Grand Est | 26 374 | 93 ms | 20 Mo | 0,25 / 1,33 ms |
| Pays de la Loire | 13 820 | 62 ms | 11 Mo | 0,29 / 0,84 ms |
| Bretagne | 17 217 | 65 ms | 12 Mo | 0,24 / 1,08 ms |
| Nouvelle-Aquitaine | 28 914 | 110 ms | 20 Mo | 0,26 / 1,69 ms |
| Occitanie | 24 051 | 80 ms | 17 Mo | 0,41 / 1,51 ms |
| Auvergne-Rhône-Alpes | 54 223 | 118 ms | 38 Mo | 0,39 / 3,69 ms |
| Provence-Alpes-Côte d'Azur | 26 942 | 108 ms | 24 Mo | 0,92 / 2,54 ms |
| Corse | 731 | 15 ms | 1 Mo | 0,02 / 0,05 ms |
| France métropolitaine | 293 369 | 436 ms | 229 Mo | 4,03 / 11,53 ms |

## Reproduire

Depuis `benchmark/`, avec l'environnement décrit dans le [README](README.md) :

```bash
JAVA_HOME=~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2 ../gradlew -p .. :cli:installDist :benchmark-engine:installDist
```

```bash
cd notebooks && ../.venv/Scripts/python -m jupyter nbconvert --to notebook --execute gtfs_france.ipynb --output out.ipynb
```

```bash
.venv/Scripts/python -m gtfs_bench.variants   # arrêts de même nom, facultatif
.venv/Scripts/python -m gtfs_bench.connected  # les trois réseaux France (étape 8), ~20 min
```

Les sources changent tous les jours. Une nouvelle exécution choisit un autre jour de
référence et d'autres versions, et `results/feeds_used.csv` garde la trace des versions
utilisées.
