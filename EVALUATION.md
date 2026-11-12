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
