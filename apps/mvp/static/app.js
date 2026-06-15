'use strict';
const $ = (id) => document.getElementById(id);
let files = [], jobId = null, poll = null, urls = { master: null, reel: null };

// ── upload picker ─────────────────────────────────────────────────────────
const drop = $('drop'), fileInput = $('file');
drop.onclick = () => fileInput.click();
['dragover', 'dragenter'].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', (ev) => setFiles([...ev.dataTransfer.files]));
fileInput.onchange = () => setFiles([...fileInput.files]);

function setFiles(list) {
  files = list.filter((f) => f.type.startsWith('image/'));
  const t = $('thumbs'); t.innerHTML = '';
  files.forEach((f) => { const img = document.createElement('img'); img.src = URL.createObjectURL(f); t.appendChild(img); });
  $('plan-btn').disabled = files.length < 3;
  $('drop').querySelector('.big').textContent = files.length ? `${files.length} photos ready` : 'Drop listing photos here';
}

// ── plan ──────────────────────────────────────────────────────────────────
$('plan-btn').onclick = async () => {
  $('plan-btn').disabled = true; $('plan-btn').textContent = 'Uploading…';
  const fd = new FormData();
  fd.append('address', $('address').value || 'Untitled listing');
  fd.append('rooms_per_shot', $('rps').value);
  files.forEach((f) => fd.append('files', f));
  const r = await fetch('/api/jobs', { method: 'POST', body: fd });
  if (!r.ok) { $('plan-btn').textContent = 'Plan Tour →'; $('plan-btn').disabled = false; alert('upload failed'); return; }
  jobId = (await r.json()).id;
  $('job-card').classList.remove('hidden');
  $('job-card').scrollIntoView({ behavior: 'smooth' });
  startPolling();
};

function startPolling() { clearInterval(poll); render(); poll = setInterval(render, 2500); }

// ── render job state ────────────────────────────────────────────────────────
async function render() {
  let j; try { j = await (await fetch('/api/jobs/' + jobId)).json(); } catch { return; }
  $('job-title').textContent = j.address || 'Tour';
  const pill = $('job-pill');
  pill.textContent = j.status;
  pill.className = 'pill ' + ({ ready: 'ready', done: 'done', error: 'error' }[j.status] || 'work');
  $('job-stage').textContent = j.stage || '';

  // stats
  const gen = j.generated || 0, n = j.n_shots || 0;
  $('job-stats').innerHTML = [
    stat('Photos', j.n_photos ?? '—'),
    stat('Segment shots', n || '—'),
    stat('Est. spend', j.est_spend_usd != null ? '$' + j.est_spend_usd : '—'),
    stat('Generated', n ? `${gen} / ${n}` : '—'),
  ].join('');

  // shot list
  if (j.worklist) {
    $('shotlist').innerHTML = j.worklist.map((s, i) => {
      const done = gen > i || (s.__done);
      return `<div class="shot">
        <div class="h"><span class="rooms">${(s.room_types || []).join(' → ')}</span>
          <span class="st ${done ? '' : 'pill ready'}" style="${done ? 'color:var(--pos)' : ''}">${done ? '✓ generated' : 'shot ' + (i + 1)}</span></div>
        <div class="prompt">${esc((s.prompt || '').slice(0, 180))}…</div></div>`;
    }).join('');
  }

  // agent handoff + finish gating
  const cta = $('agent-cta');
  if (j.status === 'ready' && gen < n) {
    cta.classList.remove('hidden');
    cta.innerHTML = `<b>Ready to generate.</b> ${n} segment shot${n > 1 ? 's' : ''} planned (~$${j.est_spend_usd}). ` +
      `Generation runs through the Higgsfield agent — ask Claude to “generate tour ${jobId}”, and progress will fill in here automatically.`;
  } else { cta.classList.add('hidden'); }

  $('finish-row').classList.toggle('hidden', !(n > 0 && gen >= n && j.status !== 'done' && j.status !== 'stitching'));

  // result
  if (j.status === 'done' && j.master_url) {
    urls = { master: j.master_url, reel: j.reel_url };
    $('result').classList.remove('hidden');
    setVideo('master');
    $('dl-master').href = j.master_url; $('dl-reel').href = j.reel_url || '#';
    clearInterval(poll);
  }
}

$('finish-btn').onclick = async () => {
  $('finish-btn').disabled = true; $('finish-btn').textContent = 'Stitching…';
  await fetch('/api/jobs/' + jobId + '/finish', { method: 'POST' });
};

document.querySelectorAll('.tab').forEach((t) => t.onclick = () => {
  document.querySelectorAll('.tab').forEach((x) => x.classList.remove('on'));
  t.classList.add('on'); setVideo(t.dataset.v);
});
function setVideo(which) { const u = urls[which]; if (u) $('player').src = u; }

const stat = (k, v) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
