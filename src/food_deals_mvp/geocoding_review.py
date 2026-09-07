"""A local, network-free pin review page with downloadable JSON decisions."""

import html
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from .extraction_models import Candidate
from .geocoding_models import Decisions, Resolutions


def write_review(
    path: Path, artifact: Resolutions, rows: list[Candidate], decisions: Decisions
) -> None:
    lookup = {r.row_id: r for r in rows}
    cards = []
    payload = []
    esc = html.escape
    for index, result in enumerate(artifact.rows):
        row = lookup[result.row_id]
        location = row.location
        assert location is not None
        options = ['<option value="">Leave pending</option>']
        details = []
        # Repeated provider objects across queries remain tied to their exact response.
        for i, place in enumerate(result.candidates):
            label = f"{place.name or place.address} ({place.precision})"
            chosen = (
                result.review == "approved"
                and result.coordinates is not None
                and result.coordinates.latitude == place.latitude
                and result.coordinates.longitude == place.longitude
            )
            options.append(
                f'<option value="{i}" {"selected" if chosen else ""}>{esc(label)}</option>'
            )
            link = (
                "https://www.openstreetmap.org/?"
                + urlencode({"mlat": place.latitude, "mlon": place.longitude})
                + f"#map=18/{place.latitude}/{place.longitude}"
            )
            details.append(
                f'<li>{esc(place.address)} · {esc(place.category)}/{esc(place.kind)} · {place.latitude}, {place.longitude} · {esc(place.precision)} · <a href="{esc(link, quote=True)}" target="_blank" rel="noopener noreferrer">Inspect pin on OpenStreetMap</a></li>'
            )
        options.append(
            f'<option value="reject" {"selected" if result.review == "rejected" else ""}>Reject / omit this location</option>'
        )
        cards.append(f'''<article><h2>{esc(row.title)}</h2>
<p>{esc(location.label)} · {esc(location.venue or "")} · {esc(location.address or "")} · {esc(location.unit or "")}</p>
<blockquote>{esc(" | ".join(location.evidence))}</blockquote>
<p>Queries: {esc(" | ".join(result.query_texts.values()) or "Not attempted")}</p>
<p>{esc(result.outcome)} / {esc(result.review)}: {esc(result.reason)}</p>
<ul>{"".join(details)}</ul><label>Pin decision <select data-index="{index}">{"".join(options)}</select></label>
<p><small>{esc(row.row_id)}</small></p></article>''')
        payload.append(
            {
                "row_id": row.row_id,
                "fingerprint": result.location_fingerprint,
                "candidates": [p.model_dump(mode="json") for p in result.candidates],
            }
        )
    # Escape '<' so source strings cannot terminate a script element.
    embedded = json.dumps(
        {"rows": payload, "decisions": decisions.model_dump(mode="json")["decisions"]},
        ensure_ascii=True,
    ).replace("<", "\\u003c")
    page = (
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Geocoding pin review</title>
<style>body{font:16px system-ui;max-width:1050px;margin:2rem auto;padding:0 1rem;background:#f5f5f2}article{background:white;padding:1rem;margin:1rem 0;border:1px solid #ddd}h2{font-size:1.15rem}select{max-width:100%}small{overflow-wrap:anywhere}button,input{padding:.5rem}blockquote{border-left:3px solid #aaa;padding-left:1rem}</style>
<h1>Review demo map locations</h1><p>Inspect the pin, building identity, and its association with this offer before approving. A building pin is approximate; units remain card details. Pending and rejected rows stay out of publication.</p>
<p>The page makes no geocoding requests. Map links open OpenStreetMap for visual inspection. Data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL).</p>
<label>Reviewer <input id="reviewer" placeholder="Your name" required></label> <button id="download">Download geocoding.json</button>
<p>Save the download as data/overrides/geocoding.json, then rerun geocode --offline before publishing. Existing aliases and unchanged decisions are preserved. Manual coordinate corrections can be entered in that JSON file.</p>
"""
        + "".join(cards)
        + """<script>
const data = """
        + embedded
        + """;
document.querySelector('#download').addEventListener('click', () => {
 const reviewer = document.querySelector('#reviewer').value.trim();
 if (!reviewer) { alert('Enter a reviewer name.'); return; }
 let decisions = data.decisions.slice();
 document.querySelectorAll('select[data-index]').forEach(select => {
  const row = data.rows[Number(select.dataset.index)];
  if (!select.value) return;
  // Remove only this row from an existing group decision; retain its siblings.
  decisions = decisions.flatMap(d => {
   if (d.action === 'alias' || !d.row_ids.includes(row.row_id)) return [d];
   const row_ids = d.row_ids.filter(id => id !== row.row_id);
   const location_fingerprints = Object.fromEntries(row_ids.map(id => [id, d.location_fingerprints[id]]));
   return row_ids.length ? [{...d, row_ids, location_fingerprints}] : [];
  });
  const d = {decision_id: 'pin-' + crypto.randomUUID(), row_ids:[row.row_id], location_fingerprints:{[row.row_id]:row.fingerprint}, reviewed_at:new Date().toISOString(), reviewer, reason:'Visually reviewed venue and offer association', source:'Local pin review with cached Nominatim evidence', action:select.value === 'reject' ? 'reject' : 'approve'};
  if (d.action === 'approve') {
   const p = row.candidates[Number(select.value)];
   d.candidate_id = p.candidate_id; d.response_fingerprint = p.response_fingerprint;
   d.source = 'https://www.openstreetmap.org/?mlat=' + p.latitude + '&mlon=' + p.longitude;
  }
  decisions.push(d);
 });
 const url = URL.createObjectURL(new Blob([JSON.stringify({schema_version:1, decisions},null,2)],{type:'application/json'}));
 const a = document.createElement('a'); a.href=url; a.download='geocoding.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
});
</script></html>"""
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(page)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
