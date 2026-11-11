# Research metrics

These figures sit beside the existing stop optimizer. They do not change which candidate the optimizer picks. They describe a proposed set of stops after that choice is made.

The comparison is the walking network only. Existing stops are the current network. Existing stops plus new stops are the proposal. School and music-school weights are used for placement and are left out of resident counts.

## 1. Public-transport journey chains

Source: Fabian Kühnel (2025), *Entwicklung von Kriterien zur kleinräumigen Bewertung des ÖPNV-Angebots*, RWTH Aachen, model V3, Table 6-1 and Table A-7. DOI: [10.18154/RWTH-2025-08909](https://doi.org/10.18154/RWTH-2025-08909).

For distances beyond 100 m, the log-odds coefficient on walking distance is −0.004 per 10 m. Frequency is assumed unchanged, so the frequency coefficients from model V3 are not applied.

For resident group i:

- `f(d) = max(d − 100, 0) / 10`
- `Δlogit = −0.004 × [f(d_new) − f(d_old)]`
- `OR = exp(Δlogit)`
- `p_new = (p_old × OR) / (1 − p_old + p_old × OR)`
- `E = N × q × p` journey chains per day

`p_old` defaults to 0.10 and `q` to 2. Both are scenario inputs. They are not a measured Gilching modal split. One probability is applied to every residential point because no zone file is loaded.

A walk that has no finite path is dropped. It is not treated as a very long distance. Walks over 1,500 m are flagged. That 1,500 m mark is a caution in this app, not a range from Table 6-1.

Check: 1,000 residents, walk cut from 600 m to 200 m, `p_old` 0.10, two journeys a day. The odds ratio is about 1.1735, the new probability about 11.53%, and the gain about 30.7 journey chains per day.

The coefficient is observational. Using it as the effect of building a stop is a counterfactual extrapolation.

## 2. CO₂e

Source: Umweltbundesamt passenger-car average for 2024, 164 g CO₂e per passenger-kilometre, including the energy chain. [Emissions data](https://www.umweltbundesamt.de/themen/verkehr/emissionsdaten).

Additional bus passengers are assumed to board buses that already run. Marginal bus emissions are therefore zero. The average bus factor per passenger-kilometre is not subtracted. This holds only while vehicle-kilometres stay the same.

`Avoided passenger-km = max(ΔE, 0) × car_shift_share × L`

`kg CO₂e per day = avoided passenger-km × 164 / 1000`

`tonnes per year = kg per day × operating days / 1000`

Default car-shift share is 0.5, not 1, because a new bus journey may replace a walk, a bike ride, or no trip. Default replaced distance is 8 km and default operating days are 250. Both are scenario inputs, not measured Gilching trip lengths. Car vehicle trips are omitted unless an occupancy is supplied.

Check: 30.7 extra journey chains, all replacing an 8 km car journey, give about 40.28 kg CO₂e per day and about 10.07 tonnes over 250 days.

Each resident is assigned to one nearest stop in the combined network, so overlapping catchments are not added twice. A new stop's figure is the sum for residents whose nearest stop is that one.

## 3. Electoral associations

Source: Johannes Kiess and Marius Dilling (2025), *Das Kreuz mit den Öffentlichen*, Else-Frenkel-Brunswik-Institut, commissioned by Greenpeace. [PDF](https://www.greenpeace.de/publikationen/20250507_Das_Kreuz_mit_den_Oeffentlichen_V05_FINAL.pdf). Table 5 (AfD) and Table 8 (Die Linke).

This is a municipal comparison. It does not show that a new stop changes a person's vote. The app labels every figure from this module as a model-based association, not a forecast of voting changes.

The paper's quality index runs from 1 (very good) to 7 (very poor) and also uses service frequency. That published score is not loaded. When a comparison runs, the two index fields are filled from the walking network: the first from the existing stops, the second from the existing stops plus the new ones. Each resident is placed in a class at 300, 500, 750, 1000, 1500 and 2000 metres, and the classes are averaged by population. A missing path scores 7. That average is a scenario score, so a shorter walk moves it by a fraction of a step rather than by a whole class for the municipality.

AfD, Table 5: east reference slope +1.51, southern interaction −0.31. Gilching is in Bavaria, so the slope used here is 1.20. An index move from 5.0 to 4.5 is `1.20 × (4.5 − 5.0) = −0.60` percentage points of second-vote share. The southern slope is not used for other regions.

Die Linke, Table 8: coefficient −0.15, not statistically significant in the multivariate model. No number is produced. BSW has no significant accessibility association in the study, and no coefficient is applied.

2025 Bundestag second votes for Gilching are the municipality sum of the Bundeswahlleiterin polling-district file, including postal districts (AGS 09188121), as compiled at [wahlergebnisse.io](https://wahlergebnisse.io/gemeinde/09188121-gilching).
