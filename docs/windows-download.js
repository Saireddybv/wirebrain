// Offer a current, tested ZIP. The ordinary links still work if the public API is unavailable.
(async () => {
  const repo = 'Saireddybv/wirebrain';
  try {
    const response = await fetch('https://api.github.com/repos/' + repo +
      '/actions/artifacts?name=Wirebrain-Windows-x64&per_page=30', {credentials: 'omit'});
    if (!response.ok) return;
    const {artifacts} = await response.json();
    const available = artifacts.filter(({expired, name, workflow_run: run}) =>
      !expired && name === 'Wirebrain-Windows-x64' && run &&
      run.head_repository_id === run.repository_id && Number.isSafeInteger(run.id));
    const latest = available.find(a => a.workflow_run.head_branch === 'main') ||
      available.find(a => a.workflow_run.head_branch === 'codex/windows-download');
    if (!latest || !Number.isSafeInteger(latest.id)) return;
    const url = 'https://github.com/' + repo + '/actions/runs/' + latest.workflow_run.id + '/artifacts/' + latest.id;
    for (const button of document.querySelectorAll('[data-tester-download]')) {
      button.href = url;
      button.textContent = 'Download Windows tester';
    }
  } catch {
    // Keep the link to the setup instructions or the workflow if GitHub rate-limits this request.
  }
})();
