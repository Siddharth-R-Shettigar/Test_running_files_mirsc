const form = document.querySelector('#upload-form');
const input = document.querySelector('#image-input');
const dropzone = document.querySelector('.dropzone');
const fileName = document.querySelector('#file-name');
const button = document.querySelector('#analyze-button');
const loading = document.querySelector('#loading');
const errorBox = document.querySelector('#error');
const report = document.querySelector('#report');
const sampleButton = document.querySelector('#sample-button');
const resetButton = document.querySelector('#reset-button');
const exportButton = document.querySelector('#export-button');
let latestReport = null;

function selectFile(file) {
  if (!file) return;
  input.files = (() => {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    return transfer.files;
  })();
  fileName.textContent = file.name;
  button.disabled = false;
}

input.addEventListener('change', () => selectFile(input.files[0]));
['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => {
  event.preventDefault();
  dropzone.classList.add('dragging');
}));
['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => {
  event.preventDefault();
  dropzone.classList.remove('dragging');
}));
dropzone.addEventListener('drop', event => selectFile(event.dataTransfer.files[0]));

function inferSummaryText(data) {
  return data.human_summary || data.summary || data.reasoning || data.risk_reason || 'No assessment available.';
}

function inferSummaryColor(data) {
  if (data.summary_color) return data.summary_color;

  const verdict = (data.verdict || '').toLowerCase();
  if (verdict.includes('fake')) return 'red';
  if (verdict.includes('real')) return 'green';
  if (data.risk_level === 'HIGH RISK') return 'red';
  if (data.risk_level === 'PASS') return 'green';
  return 'amber';
}

function inferSummaryLabel(data) {
  if (data.summary_label) return data.summary_label;
  if (data.risk_level) return data.risk_level;
  if (data.verdict === 'likely_fake') return 'HIGH RISK';
  if (data.verdict === 'likely_real') return 'PASS';
  return 'REVIEW';
}

function showReport(data) {
  latestReport = data;
  const signals = data.detector_signals || [];
  const badge = document.querySelector('#risk-badge');
  const summaryText = inferSummaryText(data);
  const summaryColor = inferSummaryColor(data);
  const summaryLabel = inferSummaryLabel(data);
  const normalizedScore = Number(data.forensic_risk_score ?? ((Number(data.final_score ?? 0) / 100) || 0)).toFixed(2);

  document.querySelector('#filename').textContent = data.file_analyzed || 'Document report';
  badge.textContent = summaryLabel;
  badge.className = `risk-badge ${summaryColor}`;
  document.querySelector('#risk-score').textContent = normalizedScore;
  document.querySelector('#risk-reason').textContent = summaryText;
  document.querySelector('#detector-count').textContent = `${signals.length} checks evaluated`;
  document.querySelector('#signals').innerHTML = signals.map(signal => `
    <article class="signal ${signal.status || ''}">
      <div class="signal-top"><span>${signal.detector_name || 'Unnamed detector'}</span><span class="signal-score">${Math.round(Number(signal.score || 0) * 100)}%</span></div>
      <p>${signal.explanation || 'No explanation provided.'}</p>
    </article>`).join('');
  report.classList.remove('hidden');
  report.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function resetView() {
  latestReport = null;
  form.reset();
  fileName.textContent = '';
  button.disabled = true;
  report.classList.add('hidden');
  errorBox.classList.add('hidden');
}

sampleButton.addEventListener('click', async () => {
  const response = await fetch('/sample');
  const blob = await response.blob();
  selectFile(new File([blob], 'U.S._passport_card.jpg', { type: blob.type }));
});
resetButton.addEventListener('click', resetView);
exportButton.addEventListener('click', () => {
  if (!latestReport) return;
  const blob = new Blob([JSON.stringify(latestReport, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${latestReport.file_analyzed || 'kavach-report'}-report.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

document.querySelectorAll('.filter-button').forEach(filterButton => {
  filterButton.addEventListener('click', () => {
    document.querySelectorAll('.filter-button').forEach(item => item.classList.remove('active'));
    filterButton.classList.add('active');
    const filter = filterButton.dataset.filter;
    document.querySelectorAll('.signal').forEach(signal => {
      signal.classList.toggle('filtered-out', filter !== 'all' && !signal.classList.contains(filter));
    });
  });
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!input.files[0]) return;
  loading.classList.remove('hidden');
  errorBox.classList.add('hidden');
  report.classList.add('hidden');
  button.disabled = true;
  try {
    const response = await fetch('/analyze', { method: 'POST', body: new FormData(form) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Analysis failed.');
    showReport(data);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
    button.disabled = false;
  }
});
