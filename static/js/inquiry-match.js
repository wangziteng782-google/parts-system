// 产品关联：三栏联动，规格弹窗复用 variants.js 的 openSpecManager

const imState = {
    records: [],
    recordPage: 1,
    recordPageSize: 30,
    recordPages: 1,
    status: 'all',
    keyword: '',
    selectedMissionId: null,
    batchMode: false,
    batchIds: new Set(),
    batchItems: [],
    products: [],
    productPage: 1,
    productPageSize: 30,
    productPages: 1,
    productTotal: 0,
    selectedPartId: null,
    specs: [],
    combinations: [],
    selectedSpecs: {},
    selectedGroupId: '',
    specWatcher: null,
};

// variants.js 会调用这两个函数，必须留在全局作用域
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
}

function showToast(message, type) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.classList.toggle('is-error', type === 'error');
    el.classList.add('show');
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.remove('show'), 2000);
}

function imFetch(url, options) {
    return fetch(url, Object.assign({ credentials: 'same-origin' }, options || {}))
        .then(async res => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || '请求失败');
            return data;
        });
}

// ========== 询价记录 ==========
async function loadRecords() {
    const list = document.getElementById('recordList');
    list.innerHTML = '<div class="im-empty">加载中…</div>';
    const params = new URLSearchParams({
        keyword: imState.keyword,
        status: imState.status,
        page: imState.recordPage,
        page_size: imState.recordPageSize,
    });
    try {
        const data = await imFetch('/api/inquiry-match/records?' + params);
        imState.records = data.items;
        imState.recordPages = data.pages;
        imState.recordPage = data.page;
        document.getElementById('statAll').textContent = data.stats.all;
        document.getElementById('statPending').textContent = data.stats.pending;
        document.getElementById('statMatched').textContent = data.stats.matched;
        document.getElementById('recordCount').textContent = data.stats.all + ' 条';
        document.getElementById('recordPageInfo').textContent =
            `第 ${data.page} / ${data.pages} 页，共 ${data.total} 条`;
        renderRecords();
        renderPager();
        if (imState.batchMode) loadBatchPreview();
    } catch (error) {
        list.innerHTML = `<div class="im-empty">${escapeHtml(error.message)}</div>`;
    }
}

// 页码只渲染首尾和当前页附近，237 页也不会拉出一长条
function renderPager() {
    const wrap = document.getElementById('recordPager');
    const pages = imState.recordPages;
    const current = imState.recordPage;
    if (!pages || pages <= 1) {
        wrap.innerHTML = '';
        return;
    }
    const numbers = Array.from(new Set([1, pages, current - 1, current, current + 1]))
        .filter(num => num >= 1 && num <= pages)
        .sort((a, b) => a - b);
    const cells = [];
    numbers.forEach((num, index) => {
        if (index && num - numbers[index - 1] > 1) {
            cells.push('<span class="im-pager-gap">…</span>');
        }
        cells.push(`<button type="button" class="im-pager-num ${num === current ? 'active' : ''}"
                           data-page="${num}">${num}</button>`);
    });
    wrap.innerHTML = `
        <button type="button" class="im-pager-arrow" data-page="${current - 1}"
                ${current <= 1 ? 'disabled' : ''}>&#8249;</button>
        ${cells.join('')}
        <button type="button" class="im-pager-arrow" data-page="${current + 1}"
                ${current >= pages ? 'disabled' : ''}>&#8250;</button>`;
    wrap.querySelectorAll('[data-page]').forEach(button => {
        button.onclick = () => {
            const page = Number(button.dataset.page);
            if (!page || page === imState.recordPage) return;
            imState.recordPage = page;
            loadRecords();
        };
    });
}

function renderRecords() {
    const list = document.getElementById('recordList');
    if (!imState.records.length) {
        list.innerHTML = '<div class="im-empty">没有符合条件的询价记录</div>';
        return;
    }
    list.innerHTML = imState.records.map((item, index) => {
        const matched = !!item.part_id;
        const rawPrice = Number(item.purchase_price);
        const priceLabel = item.price_label || '';
        const price = rawPrice > 0
            ? '￥' + (Number.isInteger(rawPrice) ? rawPrice : rawPrice.toFixed(2))
            : '暂无报价';
        const thumb = item.image
            ? `<img class="im-record-thumb" src="${escapeHtml(item.image)}" alt="商品图片"
                    loading="lazy" data-image="${escapeHtml(item.image)}" data-index="${index}">`
            : '<div class="im-record-thumb"></div>';
        const checked = imState.batchIds.has(item.inquiry_mission_id);
        return `<div class="im-record ${item.inquiry_mission_id === imState.selectedMissionId ? 'active' : ''} ${checked ? 'checked' : ''}"
                     data-id="${item.inquiry_mission_id}">
            ${imState.batchMode ? '<span class="im-check"></span>' : ''}
            <div class="n">${index + 1}</div>
            <div class="rmain">
                <div class="rname">
                    ${escapeHtml(item.product_name || '未命名')}
                    <span class="im-pill ${matched ? 'ok' : ''}">${matched ? '已匹配' : '待匹配'}</span>
                </div>
                <div class="model">${escapeHtml(item.specification || '（无规格型号）')}</div>
                <div class="rmeta">
                    <div class="rmeta-row rmeta-row--plain">
                        <span>创建人：${escapeHtml(item.create_user || '—')}</span>
                        <i class="rmeta-sep"></i>
                        <span>创建时间：${imDate(item.create_time) || '—'}</span>
                    </div>
                    <div class="rmeta-row rmeta-row--price">
                        ${priceLabel
                            ? `<span class="price-label ${priceLabel === '含税采购价' ? 'is-tax' : ''}">${escapeHtml(priceLabel)}</span>`
                            : ''}
                        <span class="price ${rawPrice > 0 ? '' : 'missing'}">${price}</span>
                    </div>
                </div>
            </div>
            <div class="rside">
                ${thumb}
                <button type="button" class="im-record-detail" data-detail="${item.inquiry_mission_id}">详情</button>
            </div>
        </div>`;
    }).join('');
    list.querySelectorAll('.im-record').forEach(el => {
        el.onclick = () => {
            const missionId = Number(el.dataset.id);
            if (imState.batchMode) toggleBatch(missionId);
            else selectRecord(missionId);
        };
    });
    list.querySelectorAll('[data-detail]').forEach(btn => {
        btn.onclick = event => {
            event.stopPropagation();
            openDetail(Number(btn.dataset.detail));
        };
    });
    list.querySelectorAll('img[data-image]').forEach(img => {
        img.onclick = event => {
            event.stopPropagation();
            const item = imState.records[Number(img.dataset.index)] || {};
            openImagePreview(img.dataset.image, item.images);
        };
    });
}

// ========== 批量关联 ==========
function enterBatch() {
    imState.batchMode = true;
    imState.batchIds = new Set();
    imState.batchItems = [];
    document.getElementById('batchToggle').textContent = '退出批量';
    document.getElementById('batchTools').hidden = false;
    document.getElementById('batchFooter').hidden = false;
    document.getElementById('recordList').classList.add('batch-mode');
    // 批量要重新选目标，别沿用上一条单条记录留下的产品和 SKU
    imState.selectedPartId = null;
    imState.selectedGroupId = '';
    imState.selectedSpecs = {};
    renderProducts();
    resetSkuPanel();
    renderRecords();
    updateBatchUi();
    loadBatchPreview();
}

function exitBatch() {
    imState.batchMode = false;
    imState.batchIds = new Set();
    imState.batchItems = [];
    document.getElementById('batchToggle').textContent = '批量关联';
    document.getElementById('batchTools').hidden = true;
    document.getElementById('batchFooter').hidden = true;
    document.getElementById('batchSpecs').innerHTML = '';
    document.getElementById('recordList').classList.remove('batch-mode');
    renderRecords();
    updateSummary();
}

function toggleBatch(missionId) {
    if (imState.batchIds.has(missionId)) {
        imState.batchIds.delete(missionId);
    } else {
        // 无规格的记录可能是完全不同的小件，套同一个 SKU 会批量写错
        const record = imState.records.find(item => item.inquiry_mission_id === missionId);
        if (record && !String(record.specification || '').trim()) {
            showToast('无规格型号的记录不支持批量关联，请单独关联', 'error');
            return;
        }
        imState.batchIds.add(missionId);
    }
    renderRecords();
    updateBatchUi();
}

// 同型号按钮点一次选中整组，再点一次取消整组
function toggleBatchSpec(spec) {
    const ids = imState.batchItems
        .filter(item => item.spec === spec)
        .map(item => item.id);
    const allSelected = ids.length > 0 && ids.every(id => imState.batchIds.has(id));
    ids.forEach(id => {
        if (allSelected) imState.batchIds.delete(id);
        else imState.batchIds.add(id);
    });
    renderRecords();
    updateBatchUi();
}

// 全选本页：无规格的记录跳过，这类记录套同一个 SKU 风险太大
function toggleBatchPage(select) {
    let skipped = 0;
    imState.records.forEach(item => {
        const missionId = item.inquiry_mission_id;
        if (!select) {
            imState.batchIds.delete(missionId);
            return;
        }
        if (!String(item.specification || '').trim()) {
            skipped += 1;
            return;
        }
        imState.batchIds.add(missionId);
    });
    renderRecords();
    updateBatchUi();
    if (skipped) showToast(`已跳过 ${skipped} 条无规格记录`);
}

function updateBatchUi() {
    const count = imState.batchIds.size;
    document.getElementById('batchCount').textContent = `已选 ${count} 条`;
    document.getElementById('batchFooterCount').textContent = `已选择 ${count} 条询价记录`;
    const selectable = imState.records.filter(
        item => String(item.specification || '').trim()
    );
    document.getElementById('batchSelectAll').checked = selectable.length > 0
        && selectable.every(item => imState.batchIds.has(item.inquiry_mission_id));
    syncBatchSpecState();
    updateSummary();
}

// 整组都被选中时按钮显示选中态，取消任意一条就退回普通态
function syncBatchSpecState() {
    const wrap = document.getElementById('batchSpecs');
    if (!wrap) return;
    wrap.querySelectorAll('[data-spec]').forEach(chip => {
        const ids = imState.batchItems
            .filter(item => item.spec === chip.dataset.spec)
            .map(item => item.id);
        chip.classList.toggle(
            'is-active',
            ids.length > 0 && ids.every(id => imState.batchIds.has(id))
        );
    });
}

// 分组只用规格型号：同一个型号会有一堆不同叫法，名称不能当键
async function loadBatchPreview() {
    if (!imState.keyword) {
        imState.batchItems = [];
        renderBatchSpecs();
        return;
    }
    try {
        const params = new URLSearchParams({
            keyword: imState.keyword,
            status: imState.status,
        });
        const data = await imFetch('/api/inquiry-match/batch/preview?' + params);
        imState.batchItems = data.items || [];
        // 选择跟着筛选走，预览里已经没有的 id 直接丢掉，避免选中看不见的记录
        const alive = new Set(imState.batchItems.map(item => item.id));
        Array.from(imState.batchIds).forEach(id => {
            if (!alive.has(id)) imState.batchIds.delete(id);
        });
        renderBatchSpecs();
        renderRecords();
        updateBatchUi();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 同型号按钮：只按规格型号分组，同一个型号会有一堆不同叫法，名称不能当键
function renderBatchSpecs() {
    const wrap = document.getElementById('batchSpecs');
    if (!imState.batchMode || !imState.keyword) {
        wrap.innerHTML = '';
        return;
    }
    const groups = new Map();
    imState.batchItems.forEach(item => {
        if (!item.spec) return;
        if (!groups.has(item.spec)) {
            groups.set(item.spec, { spec: item.spec, ids: [], names: new Set(), matched: 0 });
        }
        const group = groups.get(item.spec);
        group.ids.push(item.id);
        if (item.name) group.names.add(item.name);
        if (item.matched_part_id) group.matched += 1;
    });
    wrap.innerHTML = Array.from(groups.values()).map(group => {
        const hint = [
            `${group.ids.length} 条`,
            group.names.size > 1 ? `${group.names.size} 种叫法` : '',
            group.matched ? `已关联 ${group.matched}` : '',
        ].filter(Boolean).join(' · ');
        return `<button type="button" class="im-spec-chip" data-spec="${escapeHtml(group.spec)}"
                        title="${escapeHtml(hint)}">选择同型号（${escapeHtml(group.spec)}）</button>`;
    }).join('');
    wrap.querySelectorAll('[data-spec]').forEach(btn => {
        btn.onclick = () => toggleBatchSpec(btn.dataset.spec);
    });
    syncBatchSpecState();
}

function selectRecord(missionId) {
    imState.selectedMissionId = missionId;
    renderRecords();
    const record = imState.records.find(item => item.inquiry_mission_id === missionId);
    updateSummary();

    if (record && record.part_id) {
        // 已匹配过：按询价型号筛产品，再把库里那条记录补进列表并选中
        imState.selectedPartId = record.part_id;
        imState.selectedGroupId = record.variant_group_id || '';
        resetSkuPanel();
        imState.productPage = 1;
        autoFilterByRecord(record).then(() => ensureProductSelected(record));
        return;
    }

    // 未匹配：按询价里的型号/名称筛产品
    imState.selectedPartId = null;
    imState.selectedGroupId = '';
    resetSkuPanel();
    autoFilterByRecord(record);
}

// 点开询价记录后自动筛产品：先按型号，没命中再按名称，都跨分类搜
async function autoFilterByRecord(record) {
    if (!record) return;
    const input = document.getElementById('productSearch');
    const tries = [
        { value: String(record.specification || '').trim(), label: '型号' },
        { value: String(record.product_name || '').trim(), label: '名称' },
    ].filter(item => item.value);

    if (!tries.length) {
        input.value = '';
        imState.productPage = 1;
        await loadProducts();
        return;
    }

    for (const attempt of tries) {
        input.value = attempt.value;
        imState.productPage = 1;
        await loadProducts();
        if (imState.productTotal) {
            document.getElementById('productCount').textContent =
                `共 ${imState.productTotal} 个型号（按${attempt.label}自动筛选）`;
            return;
        }
    }

    document.getElementById('productList').innerHTML =
        '<div class="im-empty">型号和名称都没筛到产品，可改关键词或去新增产品</div>';
    document.getElementById('productCount').textContent = '未找到匹配产品';
}

function ensureProductSelected(record) {
    const partId = Number(record.part_id);
    // 产品可能不在当前分页里，补到列表首位，否则用户看不到选中的是哪条
    if (!imState.products.some(item => item.id === partId)) {
        imState.products.unshift({
            id: partId,
            product_name: record.matched_part_name,
            model: record.matched_part_model,
            product_brand: record.matched_part_brand,
            product_type: record.matched_part_type,
            update_time: null,
            sku_count: Number(record.matched_part_sku_count) || 0,
            matched_count: 1,
        });
        document.getElementById('productCount').textContent = imState.products.length + ' 个型号';
    }
    imState.selectedPartId = partId;
    selectProduct(partId, record.variant_group_id);
}

// ========== 产品列表 ==========
function loadProducts() {
    const list = document.getElementById('productList');
    const keyword = document.getElementById('productSearch').value.trim();
    const params = new URLSearchParams({
        keyword,
        page: imState.productPage,
        page_size: imState.productPageSize,
    });
    return imFetch('/api/inquiry-match/products?' + params).then(data => {
        imState.products = data.items;
        imState.productPage = data.page;
        imState.productPages = data.pages || 1;
        imState.productTotal = data.total || 0;
        document.getElementById('productCount').textContent = `共 ${imState.productTotal} 个型号`;
        document.getElementById('productPageInfo').textContent =
            `第 ${imState.productPage} / ${imState.productPages} 页`;
        renderProducts();
    }).catch(error => {
        list.innerHTML = `<div class="im-empty">${escapeHtml(error.message)}</div>`;
    });
}

function renderProducts() {
    const list = document.getElementById('productList');
    if (!imState.products.length) {
        list.innerHTML = '<div class="im-empty">没有找到产品，可换关键词试试</div>';
        return;
    }
    list.innerHTML = imState.products.map((item, index) => `
        <div class="im-product ${item.id === imState.selectedPartId ? 'active' : ''}" data-part="${item.id}">
            <div class="p-seq">${index + 1}</div>
            <div class="p-info">
                <div class="p-name">${escapeHtml(item.product_name || '未命名产品')}</div>
                <div class="p-model">${escapeHtml(item.model || '无型号')}</div>
                <span class="p-type">${escapeHtml(item.product_type || '未分类')}</span>
                ${item.product_brand ? `<span class="p-brand">${escapeHtml(item.product_brand)}</span>` : ''}
                <div class="p-updated">
                    <span>最后修改：${imDate(item.update_time) || '—'}</span>
                    <span class="p-meta">SKU ${item.sku_count} · 已关联 ${item.matched_count}</span>
                </div>
            </div>
        </div>`).join('');
    list.querySelectorAll('.im-product').forEach(el => {
        el.onclick = () => selectProduct(Number(el.dataset.part));
    });
}

async function selectProduct(partId, presetGroupId) {
    imState.selectedPartId = partId;
    imState.selectedGroupId = presetGroupId || '';
    imState.selectedSpecs = {};
    renderProducts();
    updateSummary();
    document.getElementById('openSpecBtn').disabled = false;
    await loadCombinations();
}

// ========== SKU 规格 ==========
async function loadCombinations() {
    const body = document.getElementById('skuBody');
    if (!imState.selectedPartId) {
        resetSkuPanel();
        return;
    }
    body.innerHTML = '<div class="im-empty">加载中…</div>';
    try {
        const [specs, combos] = await Promise.all([
            imFetch(`/api/products/${imState.selectedPartId}/variant-specs`),
            imFetch(`/api/products/${imState.selectedPartId}/variant-combinations`),
        ]);
        imState.specs = (specs || []).filter(item => (item.values || []).length);
        imState.combinations = combos || [];
        // 已关联过 SKU 的，把规格值预先点上
        if (imState.selectedGroupId) {
            const combo = imState.combinations.find(
                item => item.variant_group_id === imState.selectedGroupId
            );
            if (combo) {
                imState.selectedSpecs = {};
                (combo.specs || []).forEach(spec => {
                    imState.selectedSpecs[spec.name] = spec.value;
                });
            } else {
                imState.selectedGroupId = '';
            }
        }
        renderSkuPanel();
    } catch (error) {
        body.innerHTML = `<div class="im-empty">${escapeHtml(error.message)}</div>`;
    }
}

function resetSkuPanel() {
    document.getElementById('skuBody').innerHTML = '<div class="im-empty">请先在左侧选择产品型号</div>';
    document.getElementById('openSpecBtn').disabled = !imState.selectedPartId;
    updateSummary();
}

function renderSkuPanel() {
    const body = document.getElementById('skuBody');
    const product = imState.products.find(item => item.id === imState.selectedPartId) || {};

    if (!imState.specs.length) {
        body.innerHTML = `<div class="im-empty">
            该产品还没有规格，请点右上角「新增规格」添加规格名和规格值。
        </div>`;
        updateSummary();
        return;
    }

    const rows = imState.specs.map(spec => {
        const current = imState.selectedSpecs[spec.spec_name];
        const values = (spec.values || [])
            .filter(value => value.is_active !== false)
            .map(value => `<span class="im-sku-value ${current === value.value ? 'selected' : ''}"
                    data-spec="${escapeHtml(spec.spec_name)}" data-value="${escapeHtml(value.value)}">
                    ${escapeHtml(value.value)}</span>`).join('');
        return `<div class="im-sku-row">
            <div class="im-sku-row-label">${escapeHtml(spec.spec_name)}</div>
            <div class="im-sku-row-values">${values || '<span class="im-muted">待填写规格值</span>'}</div>
        </div>`;
    }).join('');

    body.innerHTML = `
        <div class="im-spec-area">
            <div class="im-spec-head">
                <strong>SKU / 规格选择</strong>
                <span class="im-muted">${escapeHtml(product.product_name || '')} · ${escapeHtml(product.model || '')}</span>
            </div>
            <div class="im-spec-body">${rows}</div>
        </div>`;

    body.querySelectorAll('.im-sku-value').forEach(el => {
        el.onclick = () => {
            const { spec, value } = el.dataset;
            // 再点一次同一个值就是取消选择
            if (imState.selectedSpecs[spec] === value) delete imState.selectedSpecs[spec];
            else imState.selectedSpecs[spec] = value;
            imState.selectedGroupId = '';
            renderSkuPanel();
            updateSummary();
        };
    });
}

function findSelectedGroup() {
    if (imState.selectedGroupId) return imState.selectedGroupId;
    if (!imState.specs.length) return '';
    const picked = imState.specs.every(spec => imState.selectedSpecs[spec.spec_name]);
    if (!picked) return '';
    const combo = imState.combinations.find(item => {
        const map = {};
        (item.specs || []).forEach(spec => { map[spec.name] = spec.value; });
        return imState.specs.every(spec => map[spec.spec_name] === imState.selectedSpecs[spec.spec_name]);
    });
    return combo ? combo.variant_group_id : '';
}

// ========== 保存 ==========
function updateSummary() {
    const record = imState.records.find(item => item.inquiry_mission_id === imState.selectedMissionId);
    const product = imState.products.find(item => item.id === imState.selectedPartId);
    const groupId = findSelectedGroup();
    const parts = [];
    if (imState.batchMode) parts.push(`已选 ${imState.batchIds.size} 条`);
    else if (record) parts.push(record.product_name || '询价');
    if (product) parts.push(product.model || product.product_name || '产品');
    if (groupId) parts.push('SKU 已选');
    else if (imState.selectedPartId) parts.push('未选 SKU');

    document.getElementById('matchSummary').textContent =
        parts.length ? parts.join(' · ') : '尚未完成选择';
    const saveBtn = document.getElementById('saveMatch');
    if (imState.batchMode) {
        const count = imState.batchIds.size;
        saveBtn.textContent = count ? `保存关联（${count} 条）` : '保存关联';
        saveBtn.disabled = !(count && imState.selectedPartId);
    } else {
        saveBtn.textContent = '保存关联';
        saveBtn.disabled = !(imState.selectedMissionId && imState.selectedPartId);
    }
    // 批量模式下取消关联还是走单条，先去掉避免两边语义混在一起
    document.getElementById('clearMatch').disabled =
        imState.batchMode || !record || !record.part_id;
}

async function saveMatch() {
    const partId = imState.selectedPartId;
    const groupId = findSelectedGroup();
    if (!partId) return;
    if (imState.specs.length && !groupId) {
        showToast('请先选择完整的规格组合', 'error');
        return;
    }
    if (imState.batchMode) {
        await saveBatchMatch(partId, groupId);
        return;
    }
    const missionId = imState.selectedMissionId;
    if (!missionId) return;
    try {
        await imFetch('/api/inquiry-match/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                inquiry_mission_id: missionId,
                part_id: partId,
                variant_group_id: groupId || null,
            }),
        });
        showToast('已保存');
        await loadRecords();
        const saved = imState.records.find(item => item.inquiry_mission_id === missionId);
        if (saved) {
            imState.selectedMissionId = missionId;
            renderRecords();
        }
        updateSummary();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function saveBatchMatch(partId, groupId) {
    const ids = Array.from(imState.batchIds);
    if (!ids.length) {
        showToast('请先勾选询价记录', 'error');
        return;
    }
    const idSet = new Set(ids);
    const specs = new Set(ids.map(id => {
        const item = imState.batchItems.find(row => row.id === id);
        return item ? item.spec : '';
    }));
    if (specs.size > 1) {
        showToast(`选中包含 ${specs.size} 种规格型号，请按规格分组关联`, 'error');
        return;
    }
    const product = imState.products.find(item => item.id === partId) || {};
    const overwritten = imState.batchItems.filter(item =>
        idSet.has(item.id) && item.matched_part_id
        && Number(item.matched_part_id) !== partId
    ).length;
    const lines = [
        `将把 ${ids.length} 条询价关联到：${product.product_name || '产品'} ${product.model || ''}`.trim(),
    ];
    // 没搜索词就没有分组数据，规格由后端校验，这里不瞎写
    if (imState.batchItems.length) lines.push(`规格型号：${[...specs][0] || '无规格'}`);
    lines.push(`目标 SKU：${groupId || '未选择规格组合'}`);
    if (overwritten) lines.push(`其中 ${overwritten} 条原已关联其他产品，将被覆盖`);
    if (!window.confirm(lines.join('\n') + '\n\n确认继续？')) return;
    try {
        const result = await imFetch('/api/inquiry-match/batch/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                inquiry_mission_ids: ids,
                part_id: partId,
                variant_group_id: groupId || null,
            }),
        });
        showToast(`已关联 ${result.saved} 条`
            + (result.overwritten ? `，覆盖 ${result.overwritten} 条` : ''));
        exitBatch();
        await loadRecords();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function clearMatch() {
    const missionId = imState.selectedMissionId;
    if (!missionId) return;
    try {
        await imFetch('/api/inquiry-match/' + missionId, { method: 'DELETE' });
        showToast('已取消匹配');
        await loadRecords();
        updateSummary();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ========== 规格弹窗（复用 variants.js） ==========
async function openSpecEditor() {
    if (!imState.selectedPartId) return;
    currentProductId = imState.selectedPartId;
    await openSpecManager();
    if (imState.specWatcher) clearInterval(imState.specWatcher);
    // 弹窗关闭后重新拉组合，新规格生成的组合才能出现在列表里
    imState.specWatcher = setInterval(() => {
        const modal = document.getElementById('variantSpecManagerModal');
        if (modal && modal.classList.contains('open')) return;
        clearInterval(imState.specWatcher);
        imState.specWatcher = null;
        loadCombinations();
    }, 400);
}

// ========== 图片预览 ==========
let imImageGallery = { images: [], index: 0 };

function openImagePreview(url, images) {
    if (!url) return;
    const list = Array.isArray(images) && images.length ? images : [url];
    imImageGallery = { images: list, index: Math.max(0, list.indexOf(url)) };
    renderImagePreview();
    document.getElementById('imageOverlay').hidden = false;
}

function renderImagePreview() {
    const { images, index } = imImageGallery;
    document.getElementById('imagePreview').src = images[index] || '';
    const multiple = images.length > 1;
    document.getElementById('imagePrev').hidden = !multiple;
    document.getElementById('imageNext').hidden = !multiple;
}

function stepImagePreview(offset) {
    const { images, index } = imImageGallery;
    if (images.length < 2) return;
    imImageGallery.index = (index + offset + images.length) % images.length;
    renderImagePreview();
}

function closeImagePreview() {
    document.getElementById('imageOverlay').hidden = true;
    imImageGallery = { images: [], index: 0 };
}

// ========== 询价详情弹窗 ==========
function imText(value) {
    const text = value === null || value === undefined ? '' : String(value).trim();
    return text ? escapeHtml(text) : '';
}

function imMoney(value) {
    if (value === null || value === undefined || value === '') return '';
    const num = Number(value);
    if (!Number.isFinite(num)) return escapeHtml(String(value));
    return '¥' + num.toFixed(2);
}

function imNumber(value) {
    if (value === null || value === undefined || value === '') return '';
    const num = Number(value);
    if (!Number.isFinite(num)) return escapeHtml(String(value));
    return escapeHtml(String(Number(num.toFixed(4))));
}

function imDate(value) {
    if (!value) return '';
    return escapeHtml(String(value).replace('T', ' ').slice(0, 16));
}

async function openDetail(missionId) {
    const overlay = document.getElementById('detailOverlay');
    overlay.classList.add('show');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    document.getElementById('detailQuotes').innerHTML =
        '<div class="im-detail-empty">加载中…</div>';
    document.getElementById('detailChatBody').innerHTML = '';
    document.getElementById('detailSelected').textContent = '';
    try {
        const data = await imFetch('/api/inquiry-match/detail/' + missionId);
        renderDetail(data);
    } catch (error) {
        showToast(error.message, 'error');
        closeDetail();
    }
}

function invoiceText(value) {
    const num = Number(value);
    if (num === 2) return '专票';
    if (num === 1) return '普票';
    return '';
}

function renderDetail(data) {
    const images = Array.isArray(data.images) && data.images.length
        ? data.images
        : (data.image ? [data.image] : []);
    const detailImage = document.getElementById('detailImage');
    const thumbs = document.getElementById('detailThumbs');
    const showImage = url => {
        detailImage.src = url || '/static/img/site-logo.png';
        // 有真实图片才允许点击放大，占位图点了没意义
        detailImage.style.cursor = url ? 'zoom-in' : 'default';
        detailImage.onclick = url ? () => openImagePreview(url, images) : null;
        thumbs.querySelectorAll('img').forEach(el => {
            el.classList.toggle('is-active', el.dataset.url === url);
        });
    };
    // 只有一张时不显示缩略图条，省得占地方
    thumbs.hidden = images.length < 2;
    thumbs.innerHTML = images.map(url =>
        `<img src="${escapeHtml(url)}" alt="商品图片" data-url="${escapeHtml(url)}">`).join('');
    thumbs.querySelectorAll('img').forEach(el => {
        el.onclick = () => showImage(el.dataset.url);
    });
    showImage(images[0] || '');

    document.getElementById('detailMissionSn').textContent = data.mission_sn || '—';
    document.getElementById('detailMissionType').textContent =
        Number(data.mission_type) === 3 ? '询价/运费' : '询价';
    document.getElementById('detailCreator').textContent =
        data.creator ? '创建人：' + data.creator : '';
    document.getElementById('detailStatusText').textContent = data.mission_status_text || '';
    const missionTime = document.getElementById('detailMissionTime');
    missionTime.textContent = data.mission_time_text ? '报价用时 ' + data.mission_time_text : '';
    missionTime.hidden = !data.mission_time_text;

    document.getElementById('detailGoodsName').textContent = data.product_name || '未命名';
    document.getElementById('detailGoodsSpec').textContent = data.specification || '';
    document.getElementById('detailGoodsMeta').innerHTML = [
        ['数量', imNumber(data.goods_num)],
        ['发票', invoiceText(data.invoice)],
        ['创建时间', imDate(data.create_time)],
        ['询价日期', imDate(data.inquiry_time)],
    ].filter(([, value]) => value)
        .map(([label, value]) => `<span>${label}：${value}</span>`)
        .join('');

    const descRows = [
        ['询价描述', data.goods_describe],
        ['询运描述', data.post_fee_describe],
    ].filter(([, value]) => imText(value));
    document.getElementById('detailGoodsDesc').innerHTML = descRows.length
        ? descRows.map(([label, value]) =>
            `<div><label>${label}：</label><span>${imText(value)}</span></div>`).join('')
        : '<div class="im-muted">暂无描述</div>';

    renderQuotes(data.quotes || []);
    loadDetailChat(data.order_goods_id);
}

function renderQuotes(quotes) {
    const wrap = document.getElementById('detailQuotes');
    const selected = document.getElementById('detailSelected');
    if (!quotes.length) {
        wrap.innerHTML = '<div class="im-detail-empty">这条询价没有供应商报价记录</div>';
        selected.textContent = '当前选中：无供应商报价';
        return;
    }
    wrap.innerHTML = quotes.map(quote => {
        const withTax = String(quote.purchase_quotation_type || '').trim() === '1';
        const quotePrice = withTax ? quote.jh_goods_price_has_tax : quote.jh_goods_price;
        const priceLabel = withTax ? '含税采购价' : '无税采购价';
        const unit = imMoney(quotePrice);
        const offer = imMoney(quote.purchase_price);
        const profit = imText(quote.profit_rate);
        const calc = unit
            ? [unit, profit ? `× 利润 ${profit}%` : '', offer ? `= 报价 ${offer}` : '']
                .filter(Boolean).join(' ')
            : '';
        const field = (label, value, opts) => {
            const options = opts || {};
            const classes = ['im-quote-field'];
            if (options.full) classes.push('is-full');
            const labelClasses = [];
            if (options.price) labelClasses.push('is-price');
            if (options.tax) labelClasses.push('is-tax');
            if (options.required) labelClasses.push('is-required');
            return `<div class="${classes.join(' ')}">
                <label class="${labelClasses.join(' ')}">${label}</label>
                <span class="im-quote-value">${value}</span>
            </div>`;
        };
        const postFee = imMoney(quote.jh_post_fee);
        return `<article class="im-quote-card ${Number(quote.is_selected) === 1 ? 'is-selected' : ''}">
            <header class="im-quote-head">
                <span class="im-quote-radio" aria-hidden="true"></span>
                <span class="im-quote-supplier">${imText(quote.supplier_name) || '未命名供应商'}</span>
                <span class="im-quote-no">报价 #${quote.index}</span>
            </header>
            <div class="im-quote-grid">
                ${field('供应商', imText(quote.supplier_name), { required: true })}
                ${field('报价来源', imText(quote.purchase_source), { required: true })}
                ${field('商品品牌', imText(quote.factory_name), { required: true })}
                ${field('电梯品牌', imText(quote.ele_brand_name))}
                ${field('规格型号', imText(quote.goods_spec), { full: true })}
                ${field('发货仓库', imText(quote.warehouse))}
                ${field('销售提点', imText(quote.reminder))}
                ${field(priceLabel, imMoney(quotePrice), { price: true, tax: withTax })}
                ${field('利润系数', profit ? profit + '%' : '', { required: true })}
                ${postFee ? field('运费', postFee, { full: true }) : ''}
            </div>
            <footer class="im-quote-total">
                <span>${calc}</span>
                <strong>${offer || '—'}</strong>
            </footer>
        </article>`;
    }).join('');

    const picked = quotes.find(item => Number(item.is_selected) === 1) || quotes[0];
    const pickedWithTax = String(picked.purchase_quotation_type || '').trim() === '1';
    selected.textContent = `当前选中：${picked.supplier_name || '未选择供应商'}`
        + `  ${pickedWithTax ? '含税' : '不含税'} ${imMoney(picked.purchase_price) || ''}`;
}

function imAttachmentUrl(url) {
    const value = String(url ?? '').trim();
    if (!value) return '';
    try {
        const parsed = new URL(value, window.location.origin);
        return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
    } catch (error) {
        return '';
    }
}

async function loadDetailChat(orderGoodsId) {
    const body = document.getElementById('detailChatBody');
    const count = document.getElementById('detailChatCount');
    if (!orderGoodsId) {
        count.textContent = '';
        body.innerHTML = '<div class="im-detail-empty">暂无沟通记录</div>';
        return;
    }
    count.textContent = '加载中';
    body.innerHTML = '<div class="im-detail-empty">正在加载沟通记录…</div>';
    try {
        const data = await imFetch(
            '/api/sales/inquiry-communications?order_goods_id=' + encodeURIComponent(orderGoodsId)
        );
        const items = data.items || [];
        count.textContent = items.length + ' 条';
        body.innerHTML = items.length ? items.map(item => {
            const links = (item.attachments || [])
                .map(imAttachmentUrl)
                .filter(Boolean)
                .map((url, i) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">附件${i + 1}</a>`)
                .join('');
            return `<article class="im-chat-item">
                <header>
                    <span>${escapeHtml(item.creator || '')}</span>
                    <time>${imDate(item.create_time)}</time>
                </header>
                <p>${escapeHtml(item.content || '')}</p>
                ${links ? `<div class="im-chat-links">${links}</div>` : ''}
            </article>`;
        }).join('') : '<div class="im-detail-empty">暂无沟通记录</div>';
    } catch (error) {
        count.textContent = '加载失败';
        body.innerHTML = `<div class="im-detail-empty">${escapeHtml(error.message)}</div>`;
    }
}

function closeDetail() {
    const overlay = document.getElementById('detailOverlay');
    overlay.classList.remove('show');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

// ========== 初始化 ==========
function bindEvents() {
    document.getElementById('recordTabs').addEventListener('click', event => {
        const tab = event.target.closest('.im-tab');
        if (!tab) return;
        imState.status = tab.dataset.status;
        imState.recordPage = 1;
        document.querySelectorAll('#recordTabs .im-tab').forEach(el => {
            el.classList.toggle('active', el === tab);
        });
        // 换筛选条件就退出批量，免得选中的记录已经不在结果里
        if (imState.batchMode) exitBatch();
        loadRecords();
    });

    document.getElementById('batchToggle').onclick = () => {
        if (imState.batchMode) exitBatch();
        else enterBatch();
    };
    document.getElementById('batchClear').onclick = () => {
        imState.batchIds = new Set();
        renderRecords();
        updateBatchUi();
    };
    document.getElementById('batchSelectAll').onchange = event => {
        toggleBatchPage(event.target.checked);
    };

    const searchRecords = () => {
        imState.keyword = document.getElementById('recordSearch').value.trim();
        imState.recordPage = 1;
        // 换筛选条件就退出批量，免得选中的记录已经不在结果里
        if (imState.batchMode) exitBatch();
        loadRecords();
    };
    // 输入即搜（300ms 防抖），和产品型号搜索一致，不用按回车
    let recordSearchTimer;
    document.getElementById('recordSearchBtn').onclick = searchRecords;
    document.getElementById('recordSearch').addEventListener('input', () => {
        clearTimeout(recordSearchTimer);
        recordSearchTimer = setTimeout(searchRecords, 300);
    });
    document.getElementById('recordSearch').addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        clearTimeout(recordSearchTimer);
        searchRecords();
    });

    document.getElementById('productSearchBtn').onclick = () => {
        imState.productPage = 1;
        loadProducts();
    };
    // 输入即搜（300ms 防抖），清空自动恢复完整列表，参考 goods 页产品列表
    let productSearchTimer;
    document.getElementById('productSearch').addEventListener('input', () => {
        clearTimeout(productSearchTimer);
        productSearchTimer = setTimeout(() => {
            imState.productPage = 1;
            loadProducts();
        }, 300);
    });
    document.getElementById('productPrev').onclick = () => {
        if (imState.productPage > 1) {
            imState.productPage -= 1;
            loadProducts();
        }
    };
    document.getElementById('productNext').onclick = () => {
        if (imState.productPage < imState.productPages) {
            imState.productPage += 1;
            loadProducts();
        }
    };
    document.getElementById('createProductBtn').onclick = () => {
        const missionId = imState.selectedMissionId;
        const url = missionId
            ? `/goods?create=1&from_inquiry=${encodeURIComponent(missionId)}`
            : '/goods?create=1';
        window.open(url, '_blank');
    };

    // 从新增产品窗口切回本页时刷新产品列表，新加的产品才会出现
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        loadProducts();
    });
    document.getElementById('productSearch').addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            clearTimeout(productSearchTimer);
            imState.productPage = 1;
            loadProducts();
        }
    });

    document.getElementById('openSpecBtn').onclick = openSpecEditor;
    document.getElementById('saveMatch').onclick = saveMatch;
    document.getElementById('clearMatch').onclick = clearMatch;

    document.getElementById('detailClose').onclick = closeDetail;
    document.getElementById('detailFooterClose').onclick = closeDetail;
    // 两个弹窗都只认关闭按钮和 Esc，点遮罩不关，避免误触
    document.getElementById('imageClose').onclick = closeImagePreview;
    document.getElementById('imagePrev').onclick = event => {
        event.stopPropagation();
        stepImagePreview(-1);
    };
    document.getElementById('imageNext').onclick = event => {
        event.stopPropagation();
        stepImagePreview(1);
    };
    document.addEventListener('keydown', event => {
        const imageOverlay = document.getElementById('imageOverlay');
        if (!imageOverlay.hidden) {
            if (event.key === 'Escape') closeImagePreview();
            else if (event.key === 'ArrowLeft') stepImagePreview(-1);
            else if (event.key === 'ArrowRight') stepImagePreview(1);
            return;
        }
        if (event.key !== 'Escape') return;
        const overlay = document.getElementById('detailOverlay');
        if (overlay.classList.contains('show')) closeDetail();
    });
}

async function initInquiryMatch() {
    bindEvents();
    await loadRecords();
    loadProducts();
    updateSummary();
}

initInquiryMatch();
