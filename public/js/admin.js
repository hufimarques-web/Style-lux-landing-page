/* ==========================================================================
   Style Lux Auto Details - Admin Portal Application Logic
   ========================================================================== */

let adminToken = '';

document.addEventListener('DOMContentLoaded', () => {
  checkAuth();
});

async function checkAuth() {
  try {
    const res = await fetch('/api/admin/bookings');
    if (res.status === 200) {
      showDashboard();
    } else {
      showLogin();
    }
  } catch (e) {
    showLogin();
  }
}

function showLogin() {
  document.getElementById('loginView').style.display = 'block';
  document.getElementById('dashboardView').style.display = 'none';
}

function showDashboard() {
  document.getElementById('loginView').style.display = 'none';
  document.getElementById('dashboardView').style.display = 'block';
  loadBookings();
}

async function performLogin() {
  const user = document.getElementById('loginUser').value.trim();
  const pass = document.getElementById('loginPass').value.trim();
  const errEl = document.getElementById('loginError');

  errEl.style.display = 'none';
  errEl.textContent = '';

  if (!user || !pass) {
    errEl.textContent = 'Por favor preencha o utilizador e a palavra-passe.';
    errEl.style.display = 'block';
    return;
  }

  try {
    const res = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass })
    });

    const data = await res.json();

    if (res.ok && data.success) {
      adminToken = data.token;
      showDashboard();
    } else {
      errEl.textContent = data.error || 'Credenciais inválidas.';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Erro ao efetuar contacto com o servidor.';
    errEl.style.display = 'block';
  }
}

async function performLogout() {
  try {
    await fetch('/api/admin/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (e) {}
  adminToken = '';
  showLogin();
}

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');

  const activeBtn = event.target;
  if (activeBtn) activeBtn.classList.add('active');

  const tabContent = document.getElementById(`tab-${tabName}`);
  if (tabContent) tabContent.style.display = 'block';

  if (tabName === 'bookings') loadBookings();
  if (tabName === 'blocking') loadBlockedSlots();
  if (tabName === 'settings') loadSettings();
}

async function loadBookings() {
  const statusFilter = document.getElementById('filterStatus').value;
  const dateFilter = document.getElementById('filterDate').value;
  const tbody = document.getElementById('bookingsTableBody');

  tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">A carregar marcações...</td></tr>';

  let url = '/api/admin/bookings?';
  if (statusFilter) url += `status=${encodeURIComponent(statusFilter)}&`;
  if (dateFilter) url += `date=${encodeURIComponent(dateFilter)}&`;

  try {
    const res = await fetch(url);
    if (!res.ok) {
      showLogin();
      return;
    }
    const data = await res.json();
    renderBookingsTable(data.bookings || []);
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--status-red);">Erro ao carregar lista de marcações.</td></tr>';
  }
}

function renderBookingsTable(bookings) {
  const tbody = document.getElementById('bookingsTableBody');
  tbody.innerHTML = '';

  if (bookings.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:var(--text-muted);">Nenhuma marcação encontrada.</td></tr>';
    return;
  }

  bookings.forEach(b => {
    const tr = document.createElement('tr');

    const tdRef = document.createElement('td');
    tdRef.style.fontWeight = '700';
    tdRef.textContent = b.reference;
    tr.appendChild(tdRef);

    const tdDate = document.createElement('td');
    tdDate.textContent = `${b.booking_date} às ${b.time_slot}`;
    tr.appendChild(tdDate);

    const tdName = document.createElement('td');
    tdName.textContent = b.customer_name;
    tr.appendChild(tdName);

    const tdPhone = document.createElement('td');
    tdPhone.textContent = b.customer_phone;
    tr.appendChild(tdPhone);

    const tdCar = document.createElement('td');
    tdCar.textContent = b.car_model;
    tr.appendChild(tdCar);

    const tdService = document.createElement('td');
    tdService.textContent = b.service_key === 'completa' ? 'Premium Completa' : 'Premium';
    tr.appendChild(tdService);

    const tdPrice = document.createElement('td');
    tdPrice.textContent = `${b.price} €`;
    tr.appendChild(tdPrice);

    const tdUtm = document.createElement('td');
    tdUtm.style.fontSize = '0.75rem';
    tdUtm.style.color = 'var(--text-muted)';
    const utmParts = [];
    if (b.utm_source) utmParts.push(`src:${b.utm_source}`);
    if (b.utm_medium) utmParts.push(`med:${b.utm_medium}`);
    if (b.utm_campaign) utmParts.push(`cmp:${b.utm_campaign}`);
    tdUtm.textContent = utmParts.length ? utmParts.join(' | ') : 'direto';
    tr.appendChild(tdUtm);

    const tdStatus = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `badge-status badge-${b.status.toLowerCase()}`;
    badge.textContent = b.status;
    tdStatus.appendChild(badge);
    tr.appendChild(tdStatus);

    const tdAction = document.createElement('td');
    const select = document.createElement('select');
    select.className = 'form-control';
    select.style.padding = '0.3rem 0.5rem';
    select.style.fontSize = '0.8rem';
    select.style.width = 'auto';

    ['Pendente', 'Concluída', 'Cancelada'].forEach(st => {
      const opt = document.createElement('option');
      opt.value = st;
      opt.textContent = st;
      if (b.status === st) opt.selected = true;
      select.appendChild(opt);
    });

    select.onchange = () => changeStatus(b.id, select.value);
    tdAction.appendChild(select);
    tr.appendChild(tdAction);

    tbody.appendChild(tr);
  });
}

async function changeStatus(bookingId, newStatus) {
  try {
    const res = await fetch('/api/admin/bookings/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: bookingId, status: newStatus })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      loadBookings();
    } else {
      alert(`Não foi possível alterar o estado: ${data.message || data.error}`);
      loadBookings();
    }
  } catch (err) {
    alert('Erro de rede ao atualizar o estado.');
    loadBookings();
  }
}

async function submitManualBooking() {
  const errEl = document.getElementById('manualError');
  const succEl = document.getElementById('manualSuccess');
  errEl.style.display = 'none';
  succEl.style.display = 'none';

  const payload = {
    service_key: document.getElementById('manService').value,
    booking_date: document.getElementById('manDate').value,
    time_slot: document.getElementById('manSlot').value.trim(),
    customer_name: document.getElementById('manName').value.trim(),
    customer_phone: document.getElementById('manPhone').value.trim(),
    car_model: document.getElementById('manCar').value.trim()
  };

  try {
    const res = await fetch('/api/admin/bookings/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok && data.success) {
      succEl.textContent = `Marcação criada com sucesso! Referência: ${data.booking.reference}`;
      succEl.style.display = 'block';
      // Reset inputs
      document.getElementById('manName').value = '';
      document.getElementById('manPhone').value = '';
      document.getElementById('manCar').value = '';
      document.getElementById('manSlot').value = '';
    } else {
      errEl.textContent = data.error || 'Erro ao criar marcação.';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Erro de comunicação ao criar marcação.';
    errEl.style.display = 'block';
  }
}

async function loadBlockedSlots() {
  const tbody = document.getElementById('blockedTableBody');
  tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">A carregar bloqueios...</td></tr>';

  try {
    const res = await fetch('/api/admin/blocked-slots');
    const data = await res.json();
    renderBlockedTable(data.blocked_slots || []);
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--status-red);">Erro ao carregar bloqueios.</td></tr>';
  }
}

function renderBlockedTable(items) {
  const tbody = document.getElementById('blockedTableBody');
  tbody.innerHTML = '';

  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Nenhum bloqueio ativo.</td></tr>';
    return;
  }

  items.forEach(item => {
    const tr = document.createElement('tr');

    const tdDate = document.createElement('td');
    tdDate.textContent = item.booking_date;
    tr.appendChild(tdDate);

    const tdSlot = document.createElement('td');
    tdSlot.textContent = item.time_slot === '*' ? 'Dia Inteiro (Todos os horários)' : item.time_slot;
    if (item.time_slot === '*') tdSlot.style.color = 'var(--brand-red)';
    tr.appendChild(tdSlot);

    const tdReason = document.createElement('td');
    tdReason.textContent = item.reason;
    tr.appendChild(tdReason);

    const tdAction = document.createElement('td');
    const btn = document.createElement('button');
    btn.className = 'btn-secondary';
    btn.style.padding = '0.3rem 0.75rem';
    btn.style.fontSize = '0.8rem';
    btn.textContent = 'Remover Bloqueio';
    btn.onclick = () => unblockSlot(item.booking_date, item.time_slot);
    tdAction.appendChild(btn);
    tr.appendChild(tdAction);

    tbody.appendChild(tr);
  });
}

async function submitBlockSlot() {
  const errEl = document.getElementById('blockError');
  errEl.style.display = 'none';

  const bDate = document.getElementById('blockDate').value;
  const tSlot = document.getElementById('blockSlot').value.trim();
  const reason = document.getElementById('blockReason').value.trim();

  if (!bDate || !tSlot) {
    errEl.textContent = 'Por favor introduza a data e o horário (ou "*").';
    errEl.style.display = 'block';
    return;
  }

  try {
    const res = await fetch('/api/admin/block-slot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ booking_date: bDate, time_slot: tSlot, reason })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      loadBlockedSlots();
      document.getElementById('blockSlot').value = '';
      document.getElementById('blockReason').value = '';
    } else {
      errEl.textContent = data.message || data.error || 'Erro ao guardar bloqueio.';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Erro de comunicação ao bloquear.';
    errEl.style.display = 'block';
  }
}

async function unblockSlot(dateStr, slotStr) {
  try {
    const res = await fetch('/api/admin/unblock-slot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ booking_date: dateStr, time_slot: slotStr })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      loadBlockedSlots();
    } else {
      alert(`Erro ao desbloquear: ${data.message || data.error}`);
    }
  } catch (e) {
    alert('Erro de comunicação ao desbloquear.');
  }
}

async function loadSettings() {
  try {
    const res = await fetch('/api/admin/settings');
    const data = await res.json();
    if (data.settings) {
      document.getElementById('setDailyLimit').value = data.settings.daily_limit;
      document.getElementById('setSlots').value = (data.settings.available_slots || []).join(', ');
    }
  } catch (e) {}
}

async function saveSettings() {
  const errEl = document.getElementById('settingsError');
  const succEl = document.getElementById('settingsSuccess');
  errEl.style.display = 'none';
  succEl.style.display = 'none';

  const limitVal = parseInt(document.getElementById('setDailyLimit').value, 10);
  const slotsStr = document.getElementById('setSlots').value;
  const slotsArr = slotsStr.split(',').map(s => s.trim()).filter(s => s.length > 0);

  try {
    const res = await fetch('/api/admin/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_limit: limitVal, available_slots: slotsArr })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      succEl.textContent = 'Configurações de capacidade e horários atualizadas!';
      succEl.style.display = 'block';
      loadSettings();
    } else {
      errEl.textContent = data.message || data.error || 'Erro ao guardar configurações.';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Erro de comunicação ao guardar configurações.';
    errEl.style.display = 'block';
  }
}
