// ── JobHunter-AI Frontend ──────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // ── NAV TAB SWITCHING ──────────────────────
  const TAB_TITLES = {
    dashboard:'Dashboard', hunter:'Hunter', sender:'Sender',
    leads:'Leads', bounces:'Bounce Handler', settings:'Settings'
  };

  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      el.classList.add('active');
      const tab = el.dataset.tab;
      document.getElementById('pane-' + tab).classList.add('active');
      document.getElementById('topbar-title').textContent = TAB_TITLES[tab] || tab;
      if (tab === 'leads') refreshLeads();
    });
  });

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
  let lastLogCount = 0;

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

      // Progress bar
      const pct = d.total ? Math.round((d.sent || 0) / d.total * 100) : 0;
      document.getElementById('progress-bar').style.width = pct + '%';
      document.getElementById('progress-pct').textContent = pct + '%';

      // Append new log entries
      if (d.log && d.log.length > lastLogCount) {
        const newEntries = d.log.slice(lastLogCount);
        newEntries.forEach(function(l) {
          appendLog('log-box', l.msg, l.level || '');
          // Also mirror to specific tab logs
          if (l.msg && l.msg.toLowerCase().includes('hunt')) {
            appendLog('hunter-log', l.msg, l.level || '');
          } else if (l.msg && (l.msg.toLowerCase().includes('send') || l.msg.toLowerCase().includes('email'))) {
            appendLog('sender-log', l.msg, l.level || '');
          } else if (l.msg && l.msg.toLowerCase().includes('bounce')) {
            appendLog('bounce-log', l.msg, l.level || '');
          }
        });
        lastLogCount = d.log.length;
      }
    } catch(_) {}
  }

  setInterval(fetchStatus, 1500);

  // ── QUICK ACTIONS ──────────────────────────
  document.getElementById('qa-hunt').addEventListener('click', startHunter);
  document.getElementById('qa-send').addEventListener('click', startSender);
  document.getElementById('qa-bounce').addEventListener('click', startBounce);
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
    toast('Hunter started...', 'info');
    appendLog('hunter-log', 'Hunting: ' + roles + ' | Exp: ' + experience + ' | Size: ' + companySize, 'info');
    const res = await apiPost('/api/run/hunt', {
      roles: roles,
      locations: locations,
      experience: experience,
      company_size: companySize,
      max: parseInt(document.getElementById('h-max').value) || 20,
      delay: parseInt(document.getElementById('h-delay').value) || 5,
    });
    if (res.error) {
      toast('Hunter error: ' + res.error, 'err');
    }
  }

  // ── SENDER ─────────────────────────────────
  document.getElementById('start-send-btn').addEventListener('click', startSender);

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

  // Search filter
  document.getElementById('leads-search').addEventListener('input', function() {
    renderLeads(this.value.toLowerCase());
  });

  async function refreshLeads() {
    const d = await apiGet('/api/leads');
    if (d.error) { toast('Failed to load leads', 'err'); return; }
    allLeads = d.leads || [];
    renderLeads('');
    document.getElementById('leads-search').value = '';
  }

  function renderLeads(filter) {
    const tbody = document.getElementById('leads-body');
    let leads = allLeads;

    if (filter) {
      leads = leads.filter(function(l) {
        return (l.company || '').toLowerCase().includes(filter)
            || (l.email || '').toLowerCase().includes(filter)
            || (l.role || '').toLowerCase().includes(filter);
      });
    }

    if (!leads.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:28px">' +
        (filter ? 'No leads match your search.' : 'No leads found. Run the Hunter to discover companies.') + '</td></tr>';
      return;
    }

    tbody.innerHTML = leads.map(function(l, i) {
      return '<tr>' +
        '<td style="color:var(--muted)">' + (i+1) + '</td>' +
        '<td>' + escapeHtml(l.company || '\u2014') + '</td>' +
        '<td style="color:var(--accent2)">' + escapeHtml(l.email || '\u2014') + '</td>' +
        '<td style="color:var(--text-dim)">' + escapeHtml(l.role || '\u2014') + '</td>' +
        '<td><span class="badge ' + (l.status||'pending') + '">' + (l.status||'pending') + '</span></td>' +
        '<td style="color:var(--muted);font-size:10px">' + escapeHtml(l.found || '\u2014') + '</td>' +
        '<td><button class="delete-btn" data-email="' + escapeHtml(l.email || '') + '" title="Delete lead">&times;</button></td>' +
        '</tr>';
    }).join('');

    // Bind delete buttons
    tbody.querySelectorAll('.delete-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        deleteLead(this.dataset.email);
      });
    });
  }

  async function deleteLead(email) {
    if (!confirm('Remove ' + email + ' from leads?')) return;
    const res = await apiDelete('/api/leads/' + encodeURIComponent(email));
    if (res.ok) {
      toast('Lead removed', 'ok');
      refreshLeads();
    } else {
      toast('Delete failed', 'err');
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
      '<td colspan="2"><input class="field-input" id="add-hr" placeholder="HR Name" value="HR Team" /></td>' +
      '<td><button class="btn sm primary" id="add-lead-save-btn">Add</button></td>';
    tbody.insertBefore(tr, tbody.firstChild);

    document.getElementById('add-lead-save-btn').addEventListener('click', saveNewLead);
  }

  async function saveNewLead() {
    const company = document.getElementById('add-company').value.trim();
    const email = document.getElementById('add-email').value.trim();
    const role = document.getElementById('add-role').value.trim();
    const hr = document.getElementById('add-hr').value.trim();

    if (!company || !email) {
      toast('Company and email are required', 'err');
      return;
    }

    const res = await apiPost('/api/leads', {company: company, email: email, role: role, hr: hr});
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
      YOUR_PORTFOLIO:document.getElementById('cfg-portfolio').value,
      YOUR_LINKEDIN: document.getElementById('cfg-linkedin').value,
      EMAIL:         document.getElementById('cfg-gmail').value,
      APP_PASSWORD:  document.getElementById('cfg-pass').value,
      ROLES:         document.getElementById('cfg-roles').value,
      LOCATIONS:     document.getElementById('cfg-locations').value,
      SEND_DELAY:    document.getElementById('cfg-senddelay').value,
      MAX_DAY:       document.getElementById('cfg-maxday').value,
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
    document.getElementById('cfg-portfolio').value = d.YOUR_PORTFOLIO || '';
    document.getElementById('cfg-linkedin').value  = d.YOUR_LINKEDIN || '';
    document.getElementById('cfg-gmail').value     = d.EMAIL || '';
    document.getElementById('cfg-roles').value     = d.ROLES || '';
    document.getElementById('cfg-locations').value = d.LOCATIONS || '';
    document.getElementById('cfg-senddelay').value = d.SEND_DELAY || '10';
    document.getElementById('cfg-maxday').value    = d.MAX_DAY || '50';

    // Also populate hunter defaults
    if (d.ROLES) document.getElementById('h-roles').value = d.ROLES;
    if (d.LOCATIONS) document.getElementById('h-locations').value = d.LOCATIONS;

    toast('Settings loaded from .env', 'ok');
  }

  // ── INIT ───────────────────────────────────
  loadSettings();
  fetchStatus();
});
