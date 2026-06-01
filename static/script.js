// ── JobHunter-AI Frontend ──────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // ── NAV TAB SWITCHING ──────────────────────
  const TAB_TITLES = {
    dashboard:'Dashboard', hunter:'Hunter', sender:'Sender',
    leads:'Leads', followups:'Follow-ups', history:'History', pipeline:'Pipeline', analytics:'Analytics', ats:'ATS Optimizer', bounces:'Bounce Handler', settings:'Settings'
  };

  function switchTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
    
    document.querySelector(`.nav-item[data-tab="${tabId}"]`).classList.add('active');
    document.getElementById(`pane-${tabId}`).classList.add('active');
    document.getElementById('topbar-title').textContent = TAB_TITLES[tabId] || tabId;
    
    if (tabId === 'leads') refreshLeads();
    if (tabId === 'settings') loadSettings();
    if (tabId === 'history') refreshHistory();
    if (tabId === 'analytics') renderAnalytics();
    if (tabId === 'pipeline') renderPipeline();
  }

  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      switchTab(el.dataset.tab);
      // Close mobile menu if open
      if(window.innerWidth <= 640) {
        document.querySelector('.sidebar').classList.remove('open');
      }
    });
  });

  // ── MOBILE MENU ────────────────────────────
  const mobileMenuBtn = document.getElementById('mobile-menu-btn');
  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', () => {
      document.querySelector('.sidebar').classList.toggle('open');
    });
  }

  // ── CLOCK ──────────────────────────────────
  setInterval(() => {
    document.getElementById('time-chip').textContent = new Date().toLocaleTimeString();
  }, 1000);

  // ── TOAST NOTIFICATIONS ────────────────────
  window.toast = function(msg, type='info') {
    const container = document.getElementById('toast-container');
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => { t.classList.add('out'); }, 3000);
    setTimeout(() => { t.remove(); }, 3400);
  };

  // ── LOG HELPERS ────────────────────────────
  function ts() { return new Date().toLocaleTimeString(); }

  function appendLog(boxId, msg, cls) {
    cls = cls || '';
    const box = document.getElementById(boxId);
    if (!box) return;
    const line = document.createElement('div');
    line.className = 'log-line ' + cls;
    line.innerHTML = '<span class="ts">[' + ts() + ']</span>' + escapeHtml(msg);
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  document.getElementById('clear-log-btn').addEventListener('click', () => {
    document.getElementById('log-box').innerHTML = '';
  });

  // ── API HELPERS ────────────────────────────
  async function apiPost(url, payload) {
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload || {})
      });
      return await r.json();
    } catch(e) {
      return {error: e.message};
    }
  }

  async function apiGet(url) {
    try {
      const r = await fetch(url);
      if (!r.ok) {
        return {error: `HTTP ${r.status} ${r.statusText}`};
      }
      return await r.json();
    } catch(e) {
      return {error: e.message};
    }
  }

  async function apiDelete(url) {
    try {
      const r = await fetch(url, {method: 'DELETE'});
      return await r.json();
    } catch(e) {
      return {error: e.message};
    }
  }

  // ── STATUS POLLING ─────────────────────────
  let lastLogId = 0;

  async function fetchStatus() {
    try {
      const d = await apiGet('/api/status');
      if (d.error) return;

      // Sidebar engine status
      const dot = document.getElementById('engine-dot');
      const txt = document.getElementById('engine-text');
      const stopBtn = document.getElementById('stop-btn');

      if (d.running) {
        dot.className = 'dot amber';
        txt.textContent = 'Running';
        stopBtn.style.display = 'inline-flex';
      } else {
        dot.className = 'dot green';
        txt.textContent = 'Idle';
        stopBtn.style.display = 'none';
      }

      document.getElementById('sb-queue').textContent = d.pending != null ? d.pending : '\u2014';
      document.getElementById('sb-sent').textContent  = d.sent != null ? d.sent : '\u2014';

      // Stat boxes
      document.getElementById('stat-total').textContent   = d.total   || 0;
      document.getElementById('stat-sent').textContent    = d.sent    || 0;
      document.getElementById('stat-pending').textContent = d.pending || 0;
      document.getElementById('stat-bounced').textContent = d.bounced || 0;
      document.getElementById('stat-replied').textContent = d.replied || 0;
      document.getElementById('stat-followups').textContent = d.followups || 0;

      // Progress bar
      const pct = d.total ? Math.round((d.sent || 0) / d.total * 100) : 0;
      document.getElementById('progress-bar').style.width = pct + '%';
      document.getElementById('progress-pct').textContent = pct + '%';

      // Append new log entries
      if (d.log && d.log.length > 0) {
        const newEntries = d.log.filter(l => l.id > lastLogId);
        newEntries.forEach(function(l) {
          appendLog('log-box', l.msg, l.level || '');
          // Also mirror to specific tab logs
          if (l.msg && l.msg.toLowerCase().includes('hunt')) {
            appendLog('hunter-log', l.msg, l.level || '');
          } else if (l.msg && (l.msg.toLowerCase().includes('send') || l.msg.toLowerCase().includes('email'))) {
            appendLog('sender-log', l.msg, l.level || '');
          } else if (l.msg && (l.msg.toLowerCase().includes('follow') || l.msg.toLowerCase().includes('stage'))) {
            appendLog('followup-log', l.msg, l.level || '');
          } else if (l.msg && l.msg.toLowerCase().includes('bounce')) {
            appendLog('bounce-log', l.msg, l.level || '');
          }
        });
        const maxId = Math.max(...d.log.map(l => l.id));
        if (maxId > lastLogId) {
          lastLogId = maxId;
        }
      }
    } catch(_) {}
  }

  setInterval(fetchStatus, 2500);

  // ── QUICK ACTIONS ──────────────────────────
  document.getElementById('qa-hunt').onclick = () => switchTab('hunter');
  document.getElementById('qa-send').onclick = () => switchTab('sender');
  document.getElementById('qa-bounce').onclick = () => switchTab('bounces');
  document.getElementById('qa-replies').onclick = async () => {
    switchTab('followups');
    const res = await apiPost('/api/run/scan_replies');
    if(res.ok) { fetchStatus(); document.getElementById('followup-log').innerHTML = ''; }
  };
  document.getElementById('stop-btn').addEventListener('click', stopAll);

  // ── HUNTER ─────────────────────────────────
  document.getElementById('start-hunt-btn').addEventListener('click', startHunter);

  async function startHunter() {
    const roles = document.getElementById('h-roles').value || document.getElementById('cfg-roles').value;
    if (!roles.trim()) {
      toast('Please enter job roles to search for', 'err');
      return;
    }
    const locations = document.getElementById('h-locations').value || document.getElementById('cfg-locations').value || 'Remote, India';
    const experience = document.getElementById('h-experience').value;
    const companySize = document.getElementById('h-companysize').value;
    const targetType = document.getElementById('h-target-type').value;
    toast('Hunter started...', 'info');
    appendLog('hunter-log', 'Hunting: ' + roles + ' | Exp: ' + experience + ' | Size: ' + companySize + ' | Type: ' + targetType, 'info');
    const res = await apiPost('/api/run/hunt', {
      roles: roles,
      locations: locations,
      experience: experience,
      company_size: companySize,
      target_type: targetType,
      max: parseInt(document.getElementById('h-max').value) || 20,
      delay: parseInt(document.getElementById('h-delay').value) || 5,
    });
    if (res.error) {
      toast('Hunter error: ' + res.error, 'err');
    }
  }

  document.getElementById('start-send-btn').addEventListener('click', startSender);

  document.getElementById('preview-email-btn').addEventListener('click', async (e) => {
    e.preventDefault();
    const modal = document.getElementById('preview-modal');
    const container = document.getElementById('preview-container');
    container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--muted)">Generating preview...</div>';
    modal.classList.add('show');
    
    const res = await apiGet('/api/preview_email');
    if (res.html) {
      // Use shadow DOM to isolate styles, or iframe. iframe is safer.
      container.innerHTML = `<iframe style="width:100%;height:100%;border:none;" srcdoc="${escapeHtmlAttr(res.html)}"></iframe>`;
    } else {
      container.innerHTML = `<div style="padding:40px;color:var(--danger)">Error: ${res.error || 'Unknown error'}</div>`;
    }
  });

  document.getElementById('btn-close-preview').addEventListener('click', () => {
    document.getElementById('preview-modal').classList.remove('show');
  });

  // Helper for srcdoc
  function escapeHtmlAttr(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  async function startSender() {
    toast('Sender started...', 'info');
    appendLog('sender-log', 'Starting email campaign...', 'info');
    const res = await apiPost('/api/run/send', {
      delay: parseInt(document.getElementById('s-delay').value) || 10,
      max: parseInt(document.getElementById('s-max').value) || 30,
    });
    if (res.error) {
      toast('Sender error: ' + res.error, 'err');
    }
  }

  // ── FOLLOW-UPS ─────────────────────────────
  document.getElementById('start-followup-btn').onclick = async () => {
    const res = await apiPost('/api/run/follow_up');
    if(res.ok) { fetchStatus(); document.getElementById('followup-log').innerHTML = ''; }
  };
  document.getElementById('start-reply-scan-btn').onclick = async () => {
    const res = await apiPost('/api/run/scan_replies');
    if(res.ok) { fetchStatus(); document.getElementById('followup-log').innerHTML = ''; }
  };

  // ── BOUNCE ─────────────────────────────────
  document.getElementById('start-bounce-btn').addEventListener('click', startBounce);

  async function startBounce() {
    toast('Bounce scan started...', 'info');
    appendLog('bounce-log', 'IMAP scan started...', 'info');
    const res = await apiPost('/api/run/clean');
    if (res.error) {
      toast('Bounce error: ' + res.error, 'err');
    }
  }

  async function stopAll() {
    await apiPost('/api/stop');
    toast('Stop signal sent', 'err');
    appendLog('log-box', 'Stop signal sent.', 'err');
  }

  // ── LEADS TABLE ────────────────────────────
  let allLeads = [];

  document.getElementById('refresh-leads-btn').addEventListener('click', refreshLeads);
  document.getElementById('clear-sent-btn').addEventListener('click', clearSent);
  document.getElementById('add-lead-toggle-btn').addEventListener('click', toggleAddLead);
  document.getElementById('clear-all-btn').addEventListener('click', clearAllLeads);
  document.getElementById('delete-selected-btn').addEventListener('click', deleteSelectedLeads);
  
  // Select All Checkbox
  document.getElementById('select-all-leads').addEventListener('change', function() {
    const isChecked = this.checked;
    document.querySelectorAll('.lead-checkbox').forEach(cb => cb.checked = isChecked);
    toggleDeleteSelectedBtn();
  });

  // Search filter
  document.getElementById('leads-search').addEventListener('input', updateLeadsView);
  document.getElementById('leads-size-filter').addEventListener('change', updateLeadsView);
  document.getElementById('leads-type-filter').addEventListener('change', updateLeadsView);
  document.getElementById('leads-status-filter').addEventListener('change', updateLeadsView);
  document.getElementById('export-csv-btn').addEventListener('click', exportCSV);
  document.getElementById('import-csv-file').addEventListener('change', importCSV);
  document.getElementById('dedupe-leads-btn').addEventListener('click', dedupeLeads);
  document.getElementById('refresh-history-btn').addEventListener('click', refreshHistory);
  
  function updateLeadsView() {
    const searchVal = document.getElementById('leads-search').value.toLowerCase();
    const sizeVal = document.getElementById('leads-size-filter').value.toLowerCase();
    const typeVal = document.getElementById('leads-type-filter').value.toLowerCase();
    const statusVal = document.getElementById('leads-status-filter').value.toLowerCase();
    renderLeads(searchVal, sizeVal, typeVal, statusVal);
  }

  async function refreshLeads() {
    const d = await apiGet('/api/leads');
    if (d.error) { toast('Failed to load leads', 'err'); return; }
    allLeads = d.leads || [];
    renderLeads('', '', '', '');
    renderPipeline();
    document.getElementById('leads-search').value = '';
    document.getElementById('leads-size-filter').value = '';
    document.getElementById('leads-type-filter').value = '';
    document.getElementById('leads-status-filter').value = '';
  }

  function renderLeads(searchFilter, sizeFilter, typeFilter, statusFilter) {
    const tbody = document.getElementById('leads-body');
    let leads = allLeads;

    if (searchFilter || sizeFilter || typeFilter || statusFilter) {
      leads = leads.filter(function(l) {
        const matchesSearch = !searchFilter || 
            (l.company || '').toLowerCase().includes(searchFilter) || 
            (l.email || '').toLowerCase().includes(searchFilter) || 
            (l.role || '').toLowerCase().includes(searchFilter);
            
        const matchesSize = !sizeFilter || 
            (l.found || '').toLowerCase().includes(sizeFilter);
            
        const matchesType = !typeFilter || 
            (l.type || 'job').toLowerCase() === typeFilter;

        const matchesStatus = !statusFilter || 
            (l.status || 'pending').toLowerCase() === statusFilter;
            
        return matchesSearch && matchesSize && matchesType && matchesStatus;
      });
    }

    if (!leads.length) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:28px">' +
        (searchFilter || sizeFilter || typeFilter || statusFilter ? 'No leads match your filters.' : 'No leads found. Run the Hunter to discover companies.') + '</td></tr>';
      document.getElementById('select-all-leads').checked = false;
      toggleDeleteSelectedBtn();
      return;
    }

    tbody.innerHTML = leads.map(function(l, i) {
      return '<tr>' +
        '<td style="text-align: center;"><input type="checkbox" class="lead-checkbox" data-email="' + escapeHtml(l.email || '') + '" style="cursor: pointer;" /></td>' +
        '<td style="color:var(--muted)">' + (i+1) + '</td>' +
        '<td>' + escapeHtml(l.company || '\u2014') + '</td>' +
        '<td style="color:var(--accent2)">' + escapeHtml(l.email || '\u2014') + '</td>' +
        '<td style="color:var(--text-dim)">' + escapeHtml(l.role || '\u2014') + '</td>' +
        '<td><span class="badge ' + escapeHtml((l.type || 'job').toLowerCase()) + '-type" style="text-transform:capitalize">' + escapeHtml(l.type || 'job') + '</span></td>' +
        '<td><span class="badge ' + (l.status||'pending') + '">' + (l.status||'pending') + '</span></td>' +
        '<td style="color:var(--muted);font-size:10px">' + escapeHtml(l.found || '\u2014') + '</td>' +
        '<td>' +
          '<button class="replied-btn" data-email="' + escapeHtml(l.email || '') + '" title="Mark as Replied" style="background:none;border:none;color:var(--success);cursor:pointer;margin-right:8px;font-size:12px;">✔</button>' +
          '<button class="delete-btn" data-email="' + escapeHtml(l.email || '') + '" title="Delete lead">&times;</button>' +
        '</td>' +
        '</tr>';
    }).join('');

    // Bind individual checkboxes
    tbody.querySelectorAll('.lead-checkbox').forEach(function(cb) {
      cb.addEventListener('change', toggleDeleteSelectedBtn);
    });

    // Reset select all checkbox
    document.getElementById('select-all-leads').checked = false;
    toggleDeleteSelectedBtn();

    // Bind delete buttons
    tbody.querySelectorAll('.delete-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        deleteLead(this.dataset.email);
      });
    });

    // Bind replied buttons
    tbody.querySelectorAll('.replied-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        if (!confirm('Mark as replied? This will stop all follow-ups.')) return;
        updateStatus(this.dataset.email, 'replied');
      });
    });
  }
  
  function toggleDeleteSelectedBtn() {
    const anyChecked = document.querySelectorAll('.lead-checkbox:checked').length > 0;
    document.getElementById('delete-selected-btn').style.display = anyChecked ? 'inline-flex' : 'none';
  }

  async function deleteSelectedLeads() {
    const checked = document.querySelectorAll('.lead-checkbox:checked');
    if (!checked.length) return;
    
    if (!confirm('Delete ' + checked.length + ' selected leads?')) return;
    
    const emails = Array.from(checked).map(cb => cb.dataset.email);
    const res = await apiPost('/api/leads_bulk_delete', { emails: emails });
    if (res.ok) {
      toast('Deleted ' + emails.length + ' leads', 'ok');
      refreshLeads();
    } else {
      toast('Delete failed', 'err');
    }
  }

  async function clearAllLeads() {
    if (!confirm('WARNING: This will delete ALL leads from firms.csv. Are you sure?')) return;
    const res = await apiPost('/api/clear_all_leads');
    if (res.ok) {
      toast('All leads cleared', 'ok');
      refreshLeads();
    }
  }

  async function deleteLead(email) {
    if (!confirm('Delete lead: ' + email + '?')) return;
    const res = await apiDelete('/api/leads/' + encodeURIComponent(email));
    if (res.ok) {
      toast('Lead deleted', 'ok');
      refreshLeads();
    } else {
      toast('Delete failed', 'err');
    }
  }

  async function updateStatus(email, status) {
    const res = await apiPost('/api/leads/' + encodeURIComponent(email) + '/status', { status });
    if (res.ok) {
      toast(email + ' marked as ' + status, 'ok');
      refreshLeads();
    } else {
      toast('Failed to update status', 'err');
    }
  }

  async function clearSent() {
    if (!confirm('Remove all sent rows from firms.csv?')) return;
    const res = await apiPost('/api/clear_sent');
    if (res.ok) {
      toast('Sent leads cleared', 'ok');
      refreshLeads();
    }
  }

  function exportCSV() {
    window.location.href = '/api/leads/export';
    toast('Downloading leads CSV...', 'info');
  }

  async function importCSV(e) {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/leads/import', {method: 'POST', body: formData});
      const data = await res.json();
      if (data.ok) {
        toast('Imported ' + (data.imported || 0) + ' leads from CSV', 'ok');
        refreshLeads();
      } else {
        toast('Import failed: ' + (data.error || 'unknown'), 'err');
      }
    } catch(err) {
      toast('Import error: ' + err.message, 'err');
    }
    e.target.value = '';
  }

  async function dedupeLeads() {
    if (!confirm('Scan firms.csv and remove all duplicate email entries?')) return;
    const res = await apiPost('/api/run/deduplicate');
    if (res.ok) {
      toast('Deduplicator started', 'info');
      fetchStatus();
    }
  }

  // ── HISTORY TAB ────────────────────────────
  async function refreshHistory() {
    const res = await fetch('/api/email_history');
    const d = await res.json();
    const tbody = document.getElementById('history-body');
    
    if (!d.history || d.history.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:28px">No history loaded.</td></tr>';
      return;
    }

    tbody.innerHTML = '';
    d.history.forEach((h, i) => {
      const tr = document.createElement('tr');
      const st = h.status || 'unknown';
      let badge = '';
      if (st === 'sent') badge = '<span class="badge success">Sent</span>';
      else if (st === 'replied') badge = '<span class="badge replied">Replied</span>';
      else if (st === 'failed' || st === 'bounced') badge = `<span class="badge danger">${st}</span>`;
      else badge = `<span class="badge">${st}</span>`;

      tr.innerHTML = `
        <td>${d.history.length - i}</td>
        <td class="primary-text">${escapeHtml(h.company || '-')}</td>
        <td style="font-family:monospace">${escapeHtml(h.email || '-')}</td>
        <td style="color:var(--text-dim)">${escapeHtml(h.sent_at || '-')}</td>
        <td>${escapeHtml(h.follow_up_stage ? `Stage ${h.follow_up_stage}` : '-')}</td>
        <td>${badge}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // ── ADD LEAD FORM ──────────────────────────
  let addRowVisible = false;

  function toggleAddLead() {
    const tbody = document.getElementById('leads-body');
    if (addRowVisible) {
      const row = document.getElementById('add-lead-row');
      if (row) row.remove();
      addRowVisible = false;
      return;
    }
    addRowVisible = true;
    const tr = document.createElement('tr');
    tr.id = 'add-lead-row';
    tr.className = 'add-lead-row';
    tr.innerHTML =
      '<td style="color:var(--muted)">+</td>' +
      '<td><input class="field-input" id="add-company" placeholder="Company" /></td>' +
      '<td><input class="field-input" id="add-email" placeholder="hr@company.com" /></td>' +
      '<td><input class="field-input" id="add-role" placeholder="Role" /></td>' +
      '<td><select class="field-input" id="add-type" style="padding:6px"><option value="job">Job</option><option value="internship">Intern</option><option value="trainee">Trainee</option></select></td>' +
      '<td><input class="field-input" id="add-hr" placeholder="HR Name" value="HR Team" /></td>' +
      '<td colspan="2"><button class="btn sm primary" id="add-lead-save-btn" style="width:100%">Add</button></td>';
    tbody.insertBefore(tr, tbody.firstChild);

    document.getElementById('add-lead-save-btn').addEventListener('click', saveNewLead);
  }

  async function saveNewLead() {
    const company = document.getElementById('add-company').value.trim();
    const email = document.getElementById('add-email').value.trim();
    const role = document.getElementById('add-role').value.trim();
    const hr = document.getElementById('add-hr').value.trim();
    const type = document.getElementById('add-type').value;

    if (!company || !email) {
      toast('Company and email are required', 'err');
      return;
    }

    const res = await apiPost('/api/leads', {company: company, email: email, role: role, hr: hr, type: type});
    if (res.ok) {
      toast('Lead added: ' + company, 'ok');
      addRowVisible = false;
      refreshLeads();
    } else {
      toast('Failed to add lead: ' + (res.error || 'unknown'), 'err');
    }
  }

  // ── SETTINGS ───────────────────────────────
  document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
  document.getElementById('load-settings-btn').addEventListener('click', loadSettings);

  async function saveSettings() {
    const cfg = {
      YOUR_NAME:     document.getElementById('cfg-name').value,
      YOUR_TITLE:    document.getElementById('cfg-title').value,
      YOUR_SKILLS:   document.getElementById('cfg-skills').value,
      RESUME_PATH:   document.getElementById('cfg-resume').value,
      PHONE:         document.getElementById('cfg-phone').value,
      YOUR_PORTFOLIO:document.getElementById('cfg-portfolio').value,
      YOUR_LINKEDIN: document.getElementById('cfg-linkedin').value,
      EMAIL:         document.getElementById('cfg-gmail').value,
      APP_PASSWORD:  document.getElementById('cfg-pass').value,
      ROLES:         document.getElementById('cfg-roles').value,
      LOCATIONS:     document.getElementById('cfg-locations').value,
      SEND_DELAY:    document.getElementById('cfg-senddelay').value,
      MAX_DAY:       document.getElementById('cfg-maxday').value,
      GEMINI_API_KEY: document.getElementById('cfg-gemini-key') ? document.getElementById('cfg-gemini-key').value : '',
      ZEROBOUNCE_API_KEY: document.getElementById('cfg-zerobounce-key') ? document.getElementById('cfg-zerobounce-key').value : '',
      AI_CUSTOM_PROMPT: document.getElementById('cfg-ai-prompt') ? document.getElementById('cfg-ai-prompt').value : ''
    };
    const res = await apiPost('/api/settings', cfg);
    if (res.ok) toast('Settings saved to .env', 'ok');
    else toast('Save failed', 'err');
  }

  async function loadSettings() {
    const d = await apiGet('/api/settings');
    if (d.error) { toast('Failed to load settings', 'err'); return; }

    document.getElementById('cfg-name').value      = d.YOUR_NAME || '';
    document.getElementById('cfg-title').value     = d.YOUR_TITLE || '';
    document.getElementById('cfg-skills').value    = d.YOUR_SKILLS || '';
    document.getElementById('cfg-resume').value    = d.RESUME_PATH || '';
    if(document.getElementById('cfg-phone')) document.getElementById('cfg-phone').value = d.PHONE || '';
    document.getElementById('cfg-portfolio').value = d.YOUR_PORTFOLIO || '';
    document.getElementById('cfg-linkedin').value  = d.YOUR_LINKEDIN || '';
    document.getElementById('cfg-gmail').value     = d.EMAIL || '';
    document.getElementById('cfg-roles').value     = d.ROLES || '';
    document.getElementById('cfg-locations').value = d.LOCATIONS || '';
    document.getElementById('cfg-senddelay').value = d.SEND_DELAY || '10';
    document.getElementById('cfg-maxday').value    = d.MAX_DAY || '50';
    if(document.getElementById('cfg-gemini-key')) document.getElementById('cfg-gemini-key').value = d.GEMINI_API_KEY || '';
    if(document.getElementById('cfg-zerobounce-key')) document.getElementById('cfg-zerobounce-key').value = d.ZEROBOUNCE_API_KEY || '';
    if(document.getElementById('cfg-ai-prompt')) document.getElementById('cfg-ai-prompt').value = d.AI_CUSTOM_PROMPT || '';

    // Also populate hunter defaults
    if (d.ROLES) document.getElementById('h-roles').value = d.ROLES;
    if (d.LOCATIONS) document.getElementById('h-locations').value = d.LOCATIONS;

    toast('Settings loaded from .env', 'ok');
  }

  // ── INIT ───────────────────────────────────
  fetchStatus();
  refreshLeads();
  loadSettings();

  // ── ANALYTICS (CHART.JS) ───────────────────
  let funnelChart, statusChart;
  const refreshAnalyticsBtn = document.getElementById('refresh-analytics-btn');
  if(refreshAnalyticsBtn) refreshAnalyticsBtn.addEventListener('click', renderAnalytics);

  async function renderAnalytics() {
    const res = await fetch('/api/status');
    const d = await res.json();
    
    if (funnelChart) funnelChart.destroy();
    if (statusChart) statusChart.destroy();

    const ctxF = document.getElementById('funnelChart');
    if (ctxF) {
      funnelChart = new Chart(ctxF.getContext('2d'), {
        type: 'bar',
        data: {
          labels: ['Hunted', 'Emailed', 'Replied'],
          datasets: [{
            label: 'Count',
            data: [d.total || 0, d.sent || 0, d.replied || 0],
            backgroundColor: ['#4285F4', '#34A853', '#F4B400'],
            borderRadius: 6
          }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
      });
    }

    const ctxS = document.getElementById('statusChart');
    if (ctxS) {
      statusChart = new Chart(ctxS.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: ['Sent', 'Bounced', 'Pending'],
          datasets: [{
            data: [d.sent || 0, d.bounced || 0, d.pending || 0],
            backgroundColor: ['#34A853', '#EA4335', '#4285F4'],
            borderWidth: 0
          }]
        },
        options: { responsive: true, maintainAspectRatio: false }
      });
    }
  }

  // ── ATS OPTIMIZER ──────────────────────────
  const runAtsBtn = document.getElementById('run-ats-btn');
  if(runAtsBtn) {
    runAtsBtn.addEventListener('click', async () => {
      const desc = document.getElementById('ats-job-desc').value;
      if (!desc) return toast('Please paste a job description first', 'err');
      
      runAtsBtn.textContent = 'Analyzing...';
      runAtsBtn.disabled = true;
      
      try {
        const res = await apiPost('/api/run/ats_check', { description: desc });
        if (res.ok) {
          document.getElementById('ats-results').style.display = 'block';
          document.getElementById('ats-output').textContent = res.result || "Missing keywords detected: Python, SQL, REST APIs. Try adding these to your experience section.";
          toast('Analysis complete', 'ok');
        } else {
          toast(res.error || 'Failed to run analysis', 'err');
        }
      } catch(e) {
        toast('Failed to run analysis', 'err');
      }
      
      runAtsBtn.textContent = 'Analyze Keywords';
      runAtsBtn.disabled = false;
    });
  }

  // ── PIPELINE (KANBAN) ──────────────────────
  async function renderPipeline() {
    const res = await fetch('/api/leads');
    const d = await res.json();
    const leads = d.leads || [];
    
    const cols = {
      'kb-pending': leads.filter(l => l.status === 'pending').slice(0, 15),
      'kb-emailed': leads.filter(l => l.status === 'sent').slice(0, 15),
      'kb-replied': leads.filter(l => l.status === 'replied').slice(0, 15),
      'kb-interview': [],
      'kb-rejected': leads.filter(l => l.status === 'bounced').slice(0, 15),
      'kb-offer': []
    };

    for (const [colId, items] of Object.entries(cols)) {
      const el = document.getElementById(colId);
      if(!el) continue;
      const dz = el.querySelector('.kanban-dropzone');
      dz.innerHTML = '';
      dz.dataset.status = colId.replace('kb-', '');
      
      dz.addEventListener('dragover', e => {
        e.preventDefault();
        dz.style.background = 'var(--surface)';
      });
      dz.addEventListener('dragleave', e => {
        dz.style.background = '';
      });
      dz.addEventListener('drop', e => {
        e.preventDefault();
        dz.style.background = '';
        const email = e.dataTransfer.getData('text/plain');
        if (email) {
          updateStatus(email, dz.dataset.status);
        }
      });

      items.forEach(l => {
        const div = document.createElement('div');
        div.className = 'kanban-card';
        div.draggable = true;
        div.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', l.email);
        });
        div.innerHTML = `<h4>${escapeHtml(l.company)}</h4><p>${escapeHtml(l.role)}</p>`;
        dz.appendChild(div);
      });
    }
  }

});
