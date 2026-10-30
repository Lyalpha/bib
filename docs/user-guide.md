# User guide

The in-app [tutorial](/tutorial) covers the astronomy background; this page is
the operator's view of the two explorers.

## SSP Explorer (`/ssp`)

1. **Select a population** — release, single/binary, IMF, metallicity, and (for
   v2.3 populations) the alpha-enhancement mix. Selectors cascade: only
   combinations that exist in the database are offered.
2. **Age** — the slider, playback, and property plots stop at
   log(age/yr) = 10.13, about the age of the Universe. Fetch data and the API
   still return the published grid from 6.0 to 11.0 in 0.1 dex steps. The
   **play** button animates through the displayed range; the speed slider sets
   decades of log-age per second; intermediate SED frames are interpolated in
   log-flux for smoothness and labelled as display-only. Every visible plot
   (SED, star counts, ionizing photons, SN rates, surviving mass, yields)
   follows the same clock.
3. **Visible plots** — tick boxes to show or hide panels. Photometry sits in a
   collapsible card under the SED.
4. **Mass** — rescales from the native normalisation of \(10^6\,M_\odot\)
   formed, over \(10^5\)–\(10^{10}\,M_\odot\). Spectra and census-style
   quantities scale linearly; extinction does not affect the timeseries panels.
5. **Dust extinction** — curve + E(B−V) (+ R_V where the curve allows). The SED
   is multiplied by \(10^{-0.4 A_\lambda}\): a foreground screen, not a mixed
   star–dust attenuation, and the removed light is not re-emitted. Each curve is
   applied only inside its published wavelength window; the regions outside it,
   where nothing is applied, are shaded on the SED and photometry through such
   passbands is flagged.
6. **Redshift** — stretches \(\lambda\) by \((1+z)\) and dims the plotted flux by
   \((10\,\mathrm{pc}/D_L)^2/(1+z)\) (flat ΛCDM). Photometry switches from
   absolute \(M_\mathrm{AB}\) at \(D_L=10\,\mathrm{pc}\) to apparent \(m_\mathrm{AB}\).
   Timeseries panels stay in the rest frame. **IGM attenuation** (on by default,
   Inoue et al. 2014 or Madau 1995) multiplies the observer-frame spectrum by
   the mean intergalactic transmission bluewards of Lyα(1+z). The live SED is
   marked with at most three vertical lines (dust-law window edges, dashed
   Lyα(1+z)) and a faint "ghost" of itself without the IGM factor; a pinned
   SSP keeps its own ghost whatever the live toggles say. The live SED's
   regions are also lightly shaded. The photometry table's *Correction
   applied* column shows pills — **Dust**, **IGM**, or **None** — with amber
   pills (*No dust (outside window)*, *Dust (partial)*, *No IGM*) where a
   requested correction could not be (fully) applied in that passband.
7. **Pin SSP on plots** — overlays this population on every visible plot (frozen SED
   slice plus that SSP's full history on the timeseries). A management chip
   lets you remove it. Pinned SSPs survive selector changes. With one or more
   pins, **sum visible spectra** adds the live SSP and every pin. **Sync
   visible spectra ages** moves every pin and the sum to the playhead age.
   Each pin keeps the mass, dust and redshift it had when pinned. Photometry
   stays on the live SSP.
8. **Filters** — overlay bundled transmission curves; the photometry table
   lists absolute AB magnitudes (D_L = 10 pc) for the live SED and every
   pinned SED. **Upload custom filter** accepts two-column ASCII
   (wavelength [Å], transmission).
9. **Export** — PNG of the SED plot; CSV/JSON of the spectrum at full native
   resolution (display plots use a rebinned copy, downloads never do). For
   tables with units and a query header, use [Fetch data](/request)
   (`GET /api/v1/export`). Add a product in `bib.export.catalog` when the
   explorer grows — the page reads that list.

## Synthetic demo banner

While any synthetic population or model is present, every page carries a
warning banner. The demo data exercise every feature of the interface but are
**toy shapes, not science**. Ingest real BPASS products and remove the demo
rows to clear the banner.
