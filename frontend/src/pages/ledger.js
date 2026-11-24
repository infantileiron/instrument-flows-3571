import { badge, lead, section, table } from '../components/common/ui.js';
import { receiptNames } from '../constants/domain.js';
import { bindForm } from '../hooks/form.js';
import { request, session } from '../stores/session.js';
import { workspace } from '../stores/workspace.js';
import { escape as e, option } from '../utils/html.js';

const canSign = () => session.user.role === 'analyst';
const remaining = row => row.quantity - (row.reversed_quantity || 0);

function receiptRows(receipts) {
  const catalog = workspace.catalog;
  const halls = Object.fromEntries(catalog.halls.map(hall => [hall.code, hall.name]));
  const instruments = Object.fromEntries(catalog.instruments.map(item => [item.code, item]));
  return receipts.map(row => {
    const reversal = row.kind === 'reversal';
    const lines = reversal ? row.lines || [] : [];
    const routes = [...new Set(lines.map(line => `${line.source}>${line.destination}`))];
    const families = [...new Set(lines.map(line => line.instrument))];
    const route = !reversal ? `${e(halls[row.source])}<span class="arrow">→</span>${e(halls[row.destination])}`
      : routes.length === 1 ? `${e(halls[lines[0].source])}<span class="arrow">→</span>${e(halls[lines[0].destination])}`
        : '<small>按行归集 · 多方向</small>';
    const family = !reversal ? e(instruments[row.instrument].name)
      : families.length === 1 ? e(instruments[families[0]].name) : '多种器材';
    const unit = !reversal ? instruments[row.instrument].unit
      : families.length === 1 ? instruments[families[0]].unit : '件';
    const quantity = `${reversal ? '−' : ''}${reversal ? row.line_total : row.quantity} ${e(unit)}`;
    const relation = reversal
      ? lines.map(line => `${e(line.original_reference)} ×${line.quantity}`).join('　')
      : [row.reversed_by ? e(row.reversed_by) : '',
        row.reversed_quantity ? `<small>已冲 ${row.reversed_quantity}/${row.quantity}</small>` : ''].filter(Boolean).join('');
    return `<tr><th scope="row"><span class="code">${e(row.reference)}</span>
      <small title="${e(row.note)}">${e(row.note)}</small></th><td>${e(row.effective_on)}</td>
      <td>${route}</td><td>${family}<small>${e(row.signer_name)}</small></td>
      <td class="number ${reversal ? 'negative' : ''}">${quantity}</td>
      <td>${badge(receiptNames[row.kind], reversal ? 'red' : '')}
      ${badge(row.signature_valid ? '验签通过' : '签名失效', row.signature_valid ? 'green' : 'red')}</td>
      <td class="code">${relation || '—'}</td></tr>`;
  }).join('');
}

const commonFields = (reference) => `<label>凭据编号<input name="reference" placeholder="${reference}" required minlength="3" maxlength="32" pattern="[A-Z0-9][A-Z0-9\\-]{2,31}"></label>
  <label>生效日期<input name="effective_on" type="date" required></label>`;
const note = '<label class="wide">交接事由<input name="note" minlength="2" maxlength="200" required></label>';

const lineRow = (choices) => `<div class="line-row">
  <select name="line_original" required>${choices}</select>
  <input name="line_quantity" type="number" min="1" max="500" placeholder="扣减件数" required>
  <button type="button" class="outline" data-remove aria-label="删除此行">×</button></div>`;

export function ledgerPage(reversals = false) {
  const { receipts, catalog } = workspace;
  const selected = reversals ? receipts.filter(row => row.kind === 'reversal') : receipts;
  const eligible = receipts.filter(row => row.kind === 'loan' && row.signature_valid && remaining(row) > 0);
  const halls = catalog.halls.map(hall => option(hall.code, hall.name)).join('');
  const instruments = Object.fromEntries(catalog.instruments.map(item => [item.code, item]));
  const instrumentOptions = catalog.instruments.map(item => option(item.code, `${item.name} · ${item.unit}`)).join('');
  const choices = option('', '选择原签领凭据', '') + eligible.map(row =>
    `<option value="${e(row.reference)}" data-remaining="${remaining(row)}">${e(row.reference)} · 剩 ${remaining(row)} ${e(instruments[row.instrument].unit)} · ${e(row.note)}</option>`).join('');
  const form = reversals ? `<form id="sign" class="entry-form">${commonFields('CX-1115-02')}
    <div class="wide lines-box" id="lines">${lineRow(choices)}</div>
    <div class="wide line-actions"><button type="button" class="outline" id="add-line">＋ 添加扣减行</button>
    <span class="hint">一张冲销单可扣回多张签领，每张只扣错录的件数。</span></div>
    <template id="line-template" data-max="${eligible.length}">${lineRow(choices)}</template>
    ${note}<div class="form-end wide"><button type="submit" class="primary">签名并冲销</button><span class="error" role="alert"></span></div></form>` :
    `<form id="sign" class="entry-form">${commonFields('CT-1115-03')}
    <label>出借馆<select name="source" required>${halls}</select></label>
    <label>入借馆<select name="destination" required>${option('', '选择入借馆', '')}${halls}</select></label>
    <label>器材族<select name="instrument">${instrumentOptions}</select></label>
    <label>数量<input name="quantity" type="number" min="1" max="500" required></label>
    ${note}<div class="form-end wide"><button type="submit" class="primary">签名并入账</button><span class="error" role="alert"></span></div></form>`;
  return lead(reversals ? '冲销核对' : '凭据台账', reversals ? '以原签领编号追溯误录凭据与冲销生效日。' : '查看馆际调借、签名状态与原始凭据的关联。') +
    `<div class="work-grid">${section(reversals ? '冲销凭据' : '电子签领记录', `最近 ${selected.length} 笔 · 按生效日倒序`,
      table(['凭据 / 事由', '生效日', '出借 → 入借', '器材 / 签领人', '数量', '签名状态', '关联凭据'], receiptRows(selected),
        reversals ? '当前没有冲销凭据。误录签领可在登记时引用原凭据编号。' : '台账为空。请先登记一笔跨馆签领。'))}
      ${canSign() ? section(reversals ? '登记冲销' : '登记签领', reversals ? '每行引用一张原签领并扣部分或全部件数；任一原单可冲余量不足时整单退回。' : '确认器材和方向后，以当前席位签名。', form) : ''}</div>`;
}

export function bindLedger(reversals, refresh) {
  if (!reversals) {
    bindForm('#sign', async body => {
      body.quantity = Number(body.quantity);
      const result = await request('/receipts/loans', { body });
      await refresh(`凭据 ${result.reference} 已签名入账。`);
    });
    return;
  }
  const form = document.querySelector('#sign');
  if (!form) return;
  const box = form.querySelector('#lines');
  const template = form.querySelector('#line-template');
  const addButton = form.querySelector('#add-line');
  const syncAdd = () => { addButton.disabled = box.children.length >= Number(template.dataset.max || 1); };
  addButton.addEventListener('click', () => {
    box.appendChild(template.content.firstElementChild.cloneNode(true));
    syncAdd();
  });
  box.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove]');
    if (remove && box.children.length > 1) {
      remove.closest('.line-row').remove();
      syncAdd();
    }
  });
  box.addEventListener('change', event => {
    if (event.target.name !== 'line_original') return;
    const input = event.target.closest('.line-row').querySelector('[name=line_quantity]');
    input.max = event.target.selectedOptions[0]?.dataset.remaining || 500;
  });
  syncAdd();
  bindForm('#sign', async body => {
    const lines = [...box.querySelectorAll('.line-row')].map(row => ({
      original_reference: row.querySelector('[name=line_original]').value,
      quantity: Number(row.querySelector('[name=line_quantity]').value),
    }));
    const result = await request('/receipts/reversals', {
      body: { reference: body.reference, effective_on: body.effective_on, note: body.note, lines },
    });
    await refresh(`凭据 ${result.reference} 已冲销。`);
  });
}
