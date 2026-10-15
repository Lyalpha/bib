import { apiGet } from "/static/js/api.js";

const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const demoBadge = '<span class="badge warn">demo</span>';

function popLabel(p) {
  const type = p.pop_type === "bin" ? "binary" : "single";
  const bits = [p.release, p.imf, p.z_label, type];
  if (p.alpha_label) bits.push(p.alpha_label);
  return bits.join(" · ");
}

function pickExample(pops) {
  const pool = pops.filter((p) => !p.is_synthetic);
  const src = pool.length ? pool : pops;
  return (
    src.find((p) => p.z_label === "z020" && p.pop_type === "bin" && !p.alpha_label) ||
    src.find((p) => p.z_label === "z020" && p.pop_type === "bin") ||
    src[0] ||
    null
  );
}

function renderExamples(pops) {
  const host = document.getElementById("api-examples");
  if (!host) return;
  const origin = window.location.origin;
  const example = pickExample(pops);
  if (!example) {
    host.textContent =
      "# No populations are loaded on this instance yet.\n" +
      `# curl -s ${origin}/api/v1/meta`;
    return;
  }
  const id = example.id;
  const label = popLabel(example);
  const logAge = "9.0";
  host.textContent = [
    `# Catalogue of every population loaded here. Each object includes id`,
    `# (use as population_id), release, imf, z_label, pop_type, alpha_label, products.`,
    `curl -s ${origin}/api/v1/populations`,
    ``,
    `# Population id=${id} is ${label}.`,
    `# Returns provenance (source filename + SHA-256) and the 51-age log_lbol grid.`,
    `curl -s ${origin}/api/v1/populations/${id}`,
    ``,
    `# Native-resolution rest-frame SED for that population at log10(age/yr)=${logAge} (1 Gyr).`,
    `# JSON: wavelength [Å], flux [L☉/Å] normalised to 10^6 M☉ formed, log_lbol, mass, dust.`,
    `curl -s "${origin}/api/v1/populations/${id}/sed?log_age=${logAge}"`,
    ``,
    `# Same SED as CSV on the native 1 Å grid (full precision; two columns).`,
    `curl -s "${origin}/api/v1/populations/${id}/sed?log_age=${logAge}&format=csv" -o sed.csv`,
    ``,
    `# Absolute AB magnitudes through SDSS g and r for the same SED (source at 10 pc).`,
    `curl -s "${origin}/api/v1/photometry?population_id=${id}&log_age=${logAge}&filters=sdss.g,sdss.r"`,
  ].join("\n");
}

(async () => {
  const summary = document.getElementById("loaded-summary");
  const popBody = document.querySelector("#pop-table tbody");
  try {
    const [meta, pops] = await Promise.all([
      apiGet("/meta"),
      apiGet("/populations"),
    ]);

    summary.innerHTML =
      meta.releases
        .map((r) => `<span class="badge ok">${esc(r.version)} · ${r.n_populations} populations</span>`)
        .join(" ") +
      (meta.has_synthetic ? ` <span class="badge warn">includes synthetic demo data</span>` : "");

    popBody.innerHTML = pops.length
      ? pops
          .map(
            (p) => `<tr>
          <td class="mono" title="${esc(popLabel(p))}">${p.id}</td>
          <td>${esc(p.release)}</td>
          <td class="wrap" title="${esc(p.imf)}">${esc(p.imf_info?.form_label || p.imf)}</td>
          <td title="${esc(p.imf)}">${esc(p.imf_info?.params_label || "—")}</td>
          <td title="Z = ${p.z_value}">${esc(p.z_label)}</td>
          <td>${p.pop_type === "bin" ? "binary" : "single"}</td>
          <td>${p.alpha_label ? esc(p.alpha_label) : "—"}</td>
          <td class="wrap small muted">${(p.products || []).map(esc).join(", ") || "—"}</td>
          <td>${p.is_synthetic ? demoBadge : ""}</td>
        </tr>`,
          )
          .join("")
      : '<tr><td colspan="9" class="muted">Nothing loaded on this instance.</td></tr>';

    renderExamples(pops);
  } catch {
    summary.innerHTML = '<span class="badge warn">database unavailable</span>';
    popBody.innerHTML =
      '<tr><td colspan="9" class="muted">Could not reach the API.</td></tr>';
    const host = document.getElementById("api-examples");
    if (host) host.textContent = "# Could not reach the API to build examples.";
  }
})();
