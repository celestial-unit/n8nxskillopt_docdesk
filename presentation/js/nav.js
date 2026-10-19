/**
 * nav.js — Document Desk Presentation Navigation
 * Keyboard shortcuts, prev/next, progress bar, slide counter.
 */

const TOTAL_SLIDES = 12;

const SLIDE_FILES = [
  '01-title.html',
  '02-problem.html',
  '03-why.html',
  '04-usecases.html',
  '05-coreidea.html',
  '06-architecture.html',
  '07-skillopt.html',
  '08-bizobj.html',
  '09-dsobj.html',
  '10-experiments.html',
  '11-potential.html',
  '12-closing.html',
];

function getCurrentSlideNumber() {
  const filename = window.location.pathname.split('/').pop();
  const idx = SLIDE_FILES.indexOf(filename);
  return idx >= 0 ? idx + 1 : 1;
}

function goToSlide(n) {
  if (n < 1 || n > TOTAL_SLIDES) return;
  window.location.href = SLIDE_FILES[n - 1];
}

function goNext() { goToSlide(getCurrentSlideNumber() + 1); }
function goPrev() { goToSlide(getCurrentSlideNumber() - 1); }

function initNav() {
  const n = getCurrentSlideNumber();

  const counterEl = document.querySelector('.slide-counter');
  if (counterEl) counterEl.textContent = `Slide ${n} of ${TOTAL_SLIDES}`;

  const fillEl = document.querySelector('.progress-bar-fill');
  if (fillEl) fillEl.style.width = `${(n / TOTAL_SLIDES) * 100}%`;

  const prevBtn = document.querySelector('.nav-btn-prev');
  const nextBtn = document.querySelector('.nav-btn-next');
  if (prevBtn && n === 1)            prevBtn.classList.add('disabled');
  if (nextBtn && n === TOTAL_SLIDES) nextBtn.classList.add('disabled');

  document.title = `Document Desk — Slide ${n} of ${TOTAL_SLIDES}`;
}

document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  switch (e.key) {
    case 'ArrowRight': case 'ArrowDown': case ' ': case 'PageDown':
      e.preventDefault(); goNext(); break;
    case 'ArrowLeft': case 'ArrowUp': case 'PageUp':
      e.preventDefault(); goPrev(); break;
    case 'Home':   e.preventDefault(); goToSlide(1);            break;
    case 'End':    e.preventDefault(); goToSlide(TOTAL_SLIDES); break;
    case 'Escape': window.location.href = '../index.html';       break;
  }
});

document.addEventListener('DOMContentLoaded', initNav);
