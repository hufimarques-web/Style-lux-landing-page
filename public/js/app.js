/* ==========================================================================
   Style Lux Auto Details - Client Application & Booking Engine
   ========================================================================== */

let state = {
  selectedService: 'premium',
  selectedDate: '',
  selectedSlot: '',
  utmSource: '',
  utmMedium: '',
  utmCampaign: ''
};

let availabilityReqSeq = 0;

const SERVICES_DATA = {
  'exterior': { name: 'Lavagem Exterior + proteção básica', price: '30 €', amount: 30 },
  'premium': { name: 'Lavagem Premium', price: '80 €', amount: 80.0 },
  'completa': { name: 'Lavagem Premium Completa', price: '130 €', amount: 130.0 }
};

document.addEventListener('DOMContentLoaded', () => {
  const compact = window.matchMedia('(max-width: 600px)');
  const setPackageDetails = () => document.querySelectorAll('.package-details').forEach(detail => { detail.open = !compact.matches; });
  setPackageDetails();
  compact.addEventListener('change', setPackageDetails);
  parseUrlParams();
  setupDatePicker();
  selectService(state.selectedService);
});

function parseUrlParams() {
  const urlParams = new URLSearchParams(window.location.search);
  
  const sParam = urlParams.get('servico');
  if (Object.hasOwn(SERVICES_DATA, sParam)) {
    state.selectedService = sParam;
    setTimeout(() => {
      openBookingModal(sParam);
    }, 400);
  }

  state.utmSource = urlParams.get('utm_source') || '';
  state.utmMedium = urlParams.get('utm_medium') || '';
  state.utmCampaign = urlParams.get('utm_campaign') || '';
}

function setupDatePicker() {
  const dateInput = document.getElementById('bookingDate');
  if (!dateInput) return;

  // Set min date to today in Europe/Lisbon timezone
  const todayLisbon = getTodayLisbonStr();
  dateInput.min = todayLisbon;
  dateInput.value = todayLisbon;
  state.selectedDate = todayLisbon;

  fetchAvailability();
}

function getTodayLisbonStr() {
  try {
    const formatter = new Intl.DateTimeFormat('en-CA', { 
      timeZone: 'Europe/Lisbon', 
      year: 'numeric', 
      month: '2-digit', 
      day: '2-digit' 
    });
    return formatter.format(new Date()); // Formats as YYYY-MM-DD
  } catch (e) {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }
}

function selectService(serviceKey) {
  if (!SERVICES_DATA[serviceKey]) return;
  const wasWax = state.selectedService === 'exterior';
  state.selectedService = serviceKey;
  const wax = serviceKey === 'exterior';
  if (wax) availabilityReqSeq++;
  document.getElementById('waxFields').hidden = !wax;
  document.getElementById('bookingSchedule').hidden = wax;
  ['sumDate','sumTime'].forEach(id => document.getElementById(id).closest('.summary-row').hidden = wax);
  setElemText('bookingTitle', wax ? 'Pedir lavagem exterior' : 'Agendar Entrega da Viatura');
  setElemText('btnSubmitBooking', wax ? 'Enviar pedido de contacto' : 'Confirmar Marcação');
  if (wasWax && !wax) fetchAvailability();

  document.querySelectorAll('.service-option').forEach(opt => { opt.classList.remove('selected'); opt.setAttribute('aria-pressed', 'false'); });
  const optEl = document.getElementById(`opt-${serviceKey}`);
  if (optEl) { optEl.classList.add('selected'); optEl.setAttribute('aria-pressed', 'true'); }

  updateSummary();
}

function openBookingModal(serviceKey) {
  if (serviceKey && SERVICES_DATA[serviceKey]) {
    selectService(serviceKey);
  }
  
  const modal = document.getElementById('bookingModal');
  if (modal) modal.classList.add('active');
  document.body.style.overflow = 'hidden';

  // Reset steps
  document.getElementById('bookingFormStep').style.display = 'block';
  document.getElementById('bookingConfirmationStep').style.display = 'none';
  hideError();

  if (!state.selectedDate) {
    setupDatePicker();
  } else {
    fetchAvailability();
  }
}

function closeBookingModal() {
  const modal = document.getElementById('bookingModal');
  if (modal) modal.classList.remove('active');
  document.body.style.overflow = '';
}

async function fetchAvailability(preserveSelection = false) {
  if (state.selectedService === 'exterior') return;
  const dateInput = document.getElementById('bookingDate');
  const slotsGrid = document.getElementById('slotsGrid');
  const noticeEl = document.getElementById('availabilityNotice');

  if (!dateInput || !slotsGrid) return;
  
  const targetDate = dateInput.value;
  let previousSlot = preserveSelection && state.selectedDate === targetDate ? state.selectedSlot : '';
  state.selectedDate = targetDate;
  if (!preserveSelection) state.selectedSlot = '';
  updateSummary();

  const reqId = ++availabilityReqSeq;

  if (!targetDate) {
    slotsGrid.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem;">Selecione uma data para ver horários.</div>';
    noticeEl.textContent = '';
    return;
  }

  if (!preserveSelection) slotsGrid.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem;">A carregar horários disponíveis...</div>';
  noticeEl.textContent = '';

  try {
    const res = await fetch(`/api/availability?date=${encodeURIComponent(targetDate)}`);
    const data = await res.json();

    // Prevent race conditions: drop stale responses if user picked another date
    if (reqId !== availabilityReqSeq || state.selectedDate !== targetDate) {
      return;
    }

    if (!data.is_valid_date) {
      state.selectedSlot = '';
      updateSummary();
      slotsGrid.innerHTML = `<div style="color:var(--status-red); font-size:0.9rem; grid-column: 1 / -1;">${escapeText(data.reason)}</div>`;
      noticeEl.textContent = '';
      return;
    }

    if (!data.slots || data.slots.length === 0) {
      state.selectedSlot = '';
      updateSummary();
      slotsGrid.innerHTML = '<div style="color:var(--text-muted); font-size:0.9rem; grid-column: 1 / -1;">Sem horários configurados.</div>';
      noticeEl.textContent = '';
      return;
    }

    if (preserveSelection) previousSlot = state.selectedSlot;
    state.selectedSlot = '';
    slotsGrid.innerHTML = '';
    let availableCount = 0;

    data.slots.forEach(s => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'slot-btn';
      btn.textContent = s.time;

      if (s.available) {
        availableCount++;
        btn.onclick = () => selectSlot(s.time, btn);
      } else {
        btn.disabled = true;
        btn.title = s.reason;
      }

      slotsGrid.appendChild(btn);
      if (s.available && previousSlot === s.time) selectSlot(s.time, btn);
    });

    updateSummary();
    if (data.day_blocked) {
      noticeEl.textContent = 'Dia encerrado ou totalmente bloqueado pelo administrador.';
      noticeEl.style.color = 'var(--status-red)';
    } else if (data.remaining_capacity <= 0) {
      noticeEl.textContent = 'Limite diário de lavagens atingido para este dia.';
      noticeEl.style.color = 'var(--status-red)';
    } else {
      noticeEl.textContent = `${availableCount} horário(s) disponível(is) para esta data (${data.remaining_capacity} vagas restantes no dia).`;
      noticeEl.style.color = 'var(--text-muted)';
    }

  } catch (err) {
    if (reqId === availabilityReqSeq) {
      slotsGrid.innerHTML = '<div style="color:var(--status-red); font-size:0.9rem;">Erro ao ligar ao servidor de disponibilidade.</div>';
    }
  }
}

function selectSlot(timeSlot, btnElement) {
  state.selectedSlot = timeSlot;

  document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
  if (btnElement) btnElement.classList.add('selected');

  updateSummary();
}

function updateSummary() {
  const serviceInfo = SERVICES_DATA[state.selectedService] || SERVICES_DATA['premium'];
  
  setElemText('sumService', serviceInfo.name);
  setElemText('sumPrice', serviceInfo.price);
  setElemText('sumDate', state.selectedDate ? formatDatePT(state.selectedDate) : '-');
  setElemText('sumTime', state.selectedSlot ? state.selectedSlot : 'Selecione um horário');
}

async function submitBooking() {
  hideError();

  const customerName = (document.getElementById('customerName')?.value || '').trim();
  const customerPhone = (document.getElementById('customerPhone')?.value || '').trim();
  const carModel = (document.getElementById('carModel')?.value || '').trim();

  if (!state.selectedService) {
    showError('Por favor selecione um serviço.');
    return;
  }
  if (state.selectedService !== 'exterior' && !state.selectedDate) {
    showError('Por favor selecione uma data válida.');
    return;
  }
  if (state.selectedService !== 'exterior' && !state.selectedSlot) {
    showError('Por favor escolha um horário de entrega disponível.');
    return;
  }
  if (!customerName || customerName.length < 2) {
    showError('Por favor introduza o seu nome completo.');
    return;
  }
  if (!customerPhone || customerPhone.length < 9) {
    showError('Por favor introduza um telemóvel válido (mínimo 9 dígitos).');
    return;
  }
  if (!carModel || carModel.length < 2) {
    showError('Por favor introduza a marca e modelo da viatura.');
    return;
  }

  const btnSubmit = document.getElementById('btnSubmitBooking');
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.textContent = state.selectedService === 'exterior' ? 'A enviar pedido...' : 'A processar reserva...';
  }

  const wax = state.selectedService === 'exterior';
  const payload = {
    service_key: state.selectedService,
    preference: document.getElementById('waxPreference').value.trim(),
    booking_date: state.selectedDate,
    time_slot: state.selectedSlot,
    customer_name: customerName,
    customer_phone: customerPhone,
    car_model: carModel,
    utm_source: state.utmSource,
    utm_medium: state.utmMedium,
    utm_campaign: state.utmCampaign
  };

  try {
    const res = await fetch(wax ? '/api/wax-requests' : '/api/bookings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.textContent = wax ? 'Enviar pedido de contacto' : 'Confirmar Marcação';
    }

    if (res.ok && data.success) {
      showConfirmation(wax ? data.request : data.booking, wax);
    } else {
      showError(data.error || 'Não foi possível concluir a reserva.');
      fetchAvailability();
    }
  } catch (err) {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.textContent = wax ? 'Enviar pedido de contacto' : 'Confirmar Marcação';
    }
    showError('Ocorreu um erro de comunicação com o servidor. Por favor tente novamente.');
  }
}

function showConfirmation(booking, wax = false) {
  setElemText('confirmationTitle', wax ? 'Pedido recebido!' : 'Marcação Confirmada com Sucesso!');
  setElemText('confirmationMessage', wax ? 'Vamos contactá-lo para combinar uma vaga. Ainda não existe data ou horário confirmado. Guarde a referência do seu pedido:' : 'Guarde a sua referência de agendamento:');
  ['resDate','resTime'].forEach(id => document.getElementById(id).closest('.summary-row').hidden = wax);
  document.getElementById('bookingFormStep').style.display = 'none';
  document.getElementById('bookingConfirmationStep').style.display = 'block';

  setElemText('resRefCode', booking.reference);
  setElemText('resService', booking.service_name);
  setElemText('resDate', formatDatePT(booking.booking_date));
  setElemText('resTime', booking.time_slot);
  setElemText('resCar', booking.car_model);
  setElemText('resPrice', `${booking.price} €`);
}

function showError(msg) {
  const errEl = document.getElementById('formError');
  if (errEl) {
    errEl.textContent = msg;
    errEl.style.display = 'block';
    errEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function hideError() {
  const errEl = document.getElementById('formError');
  if (errEl) {
    errEl.textContent = '';
    errEl.style.display = 'none';
  }
}

function setElemText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function escapeText(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatDatePT(dateStr) {
  if (!dateStr || dateStr.length !== 10) return dateStr;
  const parts = dateStr.split('-');
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

// Refresh the shared availability without clearing a still-valid selection.
setInterval(() => {
  const form = document.getElementById('bookingFormStep');
  const submit = document.getElementById('btnSubmitBooking');
  if (!document.hidden && form && form.getClientRects().length && state.selectedDate && !(submit && submit.disabled)) fetchAvailability(true);
}, 15000);
