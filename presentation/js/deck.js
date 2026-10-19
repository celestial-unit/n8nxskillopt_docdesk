(() => {
  const slides = [...document.querySelectorAll('.slide')];
  let index = 0;
  const counter = document.querySelector('#counter');
  const progress = document.querySelector('#progress');
  const overview = document.querySelector('#overview');
  const render = (next) => {
    index = Math.max(0, Math.min(slides.length - 1, next));
    slides.forEach((slide, i) => slide.classList.toggle('active', i === index));
    counter.textContent = `${String(index + 1).padStart(2, '0')} / ${String(slides.length).padStart(2, '0')}`;
    progress.style.width = `${((index + 1) / slides.length) * 100}%`;
    document.title = `DocDesk · ${String(index + 1).padStart(2, '0')} — ${slides[index].querySelector('h1,h2')?.textContent.trim() || 'Presentation'}`;
    history.replaceState(null, '', `#s${index + 1}`);
  };
  const navigate = (event) => {
    const id = event.target.closest('.thumb')?.dataset.slide;
    if (id) { overview.classList.add('hidden'); render(Number(id) - 1); }
  };
  document.querySelector('#prev').addEventListener('click', () => render(index - 1));
  document.querySelector('#next').addEventListener('click', () => render(index + 1));
  document.querySelector('#overviewBtn').addEventListener('click', () => overview.classList.remove('hidden'));
  document.querySelector('#closeOverview').addEventListener('click', () => overview.classList.add('hidden'));
  overview.querySelector('.thumbs').innerHTML = slides.map((s, i) => `<button class="thumb" data-slide="${i + 1}"><b>${String(i + 1).padStart(2, '0')}</b>${s.querySelector('h1,h2')?.textContent.replace(/\s+/g, ' ').trim() || 'Slide'}</button>`).join('');
  overview.addEventListener('click', navigate);
  document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
    if (overview && !overview.classList.contains('hidden')) {
      if (e.key === 'Escape' || e.key.toLowerCase() === 'o') overview.classList.add('hidden');
      return;
    }
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' '].includes(e.key)) { e.preventDefault(); render(index + 1); }
    if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.key)) { e.preventDefault(); render(index - 1); }
    if (e.key === 'Home') render(0);
    if (e.key === 'End') render(slides.length - 1);
    if (e.key.toLowerCase() === 'o') overview.classList.remove('hidden');
    if (e.key.toLowerCase() === 'f') document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.();
  });
  render(Math.max(0, Number(location.hash.slice(2)) - 1));

  const setTest = (weak, best, status) => {
    const weakNode = document.querySelector('#testWeak');
    const bestNode = document.querySelector('#testBest');
    if (weakNode && weak != null) weakNode.textContent = `${Math.round(Number(weak) * 100)}%`;
    if (bestNode && best != null) bestNode.textContent = `${Math.round(Number(best) * 100)}%`;
    const note = document.querySelector('#testStatus');
    if (note && status) note.textContent = status;
  };
  const loadMetrics = async () => {
    try {
      const response = await fetch('http://localhost:8000/skillopt/showcase', { cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      if (data.selection) {
        const a = document.querySelector('#s8 .score-compare article:first-child strong');
        const b = document.querySelector('#s8 .score-after strong');
        if (data.selection.weak_baseline != null) a.textContent = `${Math.round(data.selection.weak_baseline * 100)}%`;
        if (data.selection.optimized != null) b.textContent = `${Math.round(data.selection.optimized * 100)}%`;
      }
      if (data.test) {
        const score = document.querySelector('#testSoft');
        if (score && data.test.weak_baseline_soft_nem != null && data.test.optimized_soft_nem != null) {
          score.textContent = Number(data.test.weak_baseline_soft_nem).toFixed(2) + ' → ' + Number(data.test.optimized_soft_nem).toFixed(2);
        }
        const hard = document.querySelectorAll('#s9 .test-metrics b');
        if (hard.length === 2) {
          hard[0].textContent = String(data.test.weak_baseline_exact) + '/' + data.test.total;
          hard[1].textContent = String(data.test.optimized_exact) + '/' + data.test.total;
        }
        setTest(null, null, 'Held-out TEST · soft NEM improves; strict exact match stays 0/10.');
      } else if (data.status === 'running') {
        setTest(null, null, 'TEST is running; selection is shown above.');
      } else if (data.status === 'complete') {
        setTest(null, null, 'Run complete; TEST details are in the project report.');
      }
    } catch (_) {
      setTest(null, null, 'Open the deck with the API running to load current TEST metrics.');
    }
  };
  loadMetrics();

  fallbackDiagrams();

  function fallbackDiagrams() {
    const models = [
      [['New document', 'Route by type', 'Extract fields', 'Code + RAG', 'Validate'], ['Accepted', 'Human review', 'Retry / failed']],
      [['TRAIN rollouts', 'Reflect', 'Bounded edits', 'SELECTION gate'], ['Keep candidate', 'Keep current', 'TEST once']]
    ];
    document.querySelectorAll('.mermaid').forEach((root, i) => {
      const rows = models[i] || models[0];
      const labels = rows[0];
      const w = 1050, h = 230, x0 = 22, gap = 14, boxW = (w - 44 - gap * (labels.length - 1)) / labels.length, boxH = 54, y = 78;
      const esc = (s) => s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
      let svg = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Flow diagram">`;
      labels.forEach((label, k) => {
        const x = x0 + k * (boxW + gap);
        if (k) svg += `<path d="M${x - gap + 1} ${y + boxH / 2}h${gap - 4}" stroke="#b0a897" stroke-width="2" marker-end="url(#arrow)"/>`;
        svg += `<rect x="${x}" y="${y}" width="${boxW}" height="${boxH}" rx="11" fill="#182a35" stroke="${k === 3 ? '#e0a03e' : '#60a5fa'}"/>`;
        svg += `<text x="${x + boxW / 2}" y="${y + 32}" fill="#f0ebe2" text-anchor="middle" class="label">${esc(label)}</text>`;
      });
      svg += `<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#b0a897"/></marker></defs>`;
      const bottom = rows[1];
      bottom.forEach((label, k) => {
        const bw = 150, x = 90 + k * 210, yy = 166;
        svg += `<rect x="${x}" y="${yy}" width="${bw}" height="38" rx="9" fill="#173129" stroke="#2dd4a0"/><text x="${x + bw/2}" y="${yy + 24}" fill="#2dd4a0" text-anchor="middle" class="label">${esc(label)}</text>`;
      });
      svg += '</svg>';
      root.innerHTML = svg;
    });
  }
})();
