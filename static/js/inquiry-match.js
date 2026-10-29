// 产品关联：四栏联动，规格弹窗复用 variants.js 的 openSpecManager

const imState = {
    records: [],
    recordPage: 1,
    recordPageSize: 30,
    recordPages: 1,
    status: 'all',
    keyword: '',
    selectedMissionId: null,
    leaves: [],
    selectedCategory: '',
    products: [],
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
    } catch (error) {
        list.innerHTML = `<div class="im-empty">${escapeHtml(error.message)}</div>`;
    }
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
        const price = rawPrice > 0
            ? '￥' + (Number.isInteger(rawPrice) ? rawPrice : rawPrice.toFixed(2))
            : '询价中';
        const thumb = item.image
            ? `<img class="im-record-thumb" src="${escapeHtml(item.image)}" alt="商品图片"
                    loading="lazy" data-image="${escapeHtml(item.image)}">`
            : '<div class="im-record-thumb"></div>';
        return `<div class="im-record ${item.inquiry_mission_id === imState.selectedMissionId ? 'active' : ''}"
                     data-id="${item.inquiry_mission_id}">
            <div class="n">${index + 1}</div>
            <div class="rmain">
                <div class="rname">
                    ${escapeHtml(item.product_name || '未命名')}
                    <span class="im-pill ${matched ? 'ok' : ''}">${matched ? '已匹配' : '待匹配'}</span>
                </div>
                <div class="model">${escapeHtml(item.specification || '（无规格型号）')}</div>
                <div class="rmeta">
                    <div class="rmeta-row">
                        <span>创建人：${escapeHtml(item.create_user || '—')}</span>
                    </div>
                    <div class="rmeta-row">
                        <span>创建时间：${imDate(item.create_time) || '—'}</span>
                    </div>
                    <div class="rmeta-row">
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
        el.onclick = () => selectRecord(Number(el.dataset.id));
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
            openImagePreview(img.dataset.image);
        };
    });
}

function selectRecord(missionId) {
    imState.selectedMissionId = missionId;
    renderRecords();
    const record = imState.records.find(item => item.inquiry_mission_id === missionId);
    updateSummary();

    if (record && record.part_id) {
        // 已匹配过：按库里记录的产品分类和型号直接定位，不靠询价名称猜
        const guessed = suggestCategory(record.product_name);
        document.getElementById('productSearch').value = '';
        imState.selectedCategory = record.matched_part_type || (guessed ? guessed.name : '');
        imState.selectedPartId = record.part_id;
        imState.selectedGroupId = record.variant_group_id || '';
        resetSkuPanel();
        renderTree();
        loadProducts().then(() => ensureProductSelected(record));
        return;
    }

    // 未匹配：清空分类，按询价里的型号/名称跨分类筛产品
    imState.selectedCategory = '';
    imState.selectedPartId = null;
    imState.selectedGroupId = '';
    resetSkuPanel();
    renderTree();
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
        await loadProducts();
        return;
    }

    for (const attempt of tries) {
        input.value = attempt.value;
        await loadProducts();
        if (imState.products.length) {
            document.getElementById('productCount').textContent =
                `${imState.products.length} 个型号（按${attempt.label}自动筛选）`;
            return;
        }
    }

    document.getElementById('productList').innerHTML =
        '<div class="im-empty">型号和名称都没筛到产品，可改关键词、换个分类，或去新增产品</div>';
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

function suggestCategory(name) {
    if (!name) return null;
    const exact = imState.leaves.find(leaf => leaf.name === name);
    if (exact) return exact;
    const hits = imState.leaves.filter(leaf => name.includes(leaf.name));
    hits.sort((a, b) => b.name.length - a.name.length);
    return hits[0] || null;
}

// ========== 分类树 ==========
async function loadCategories() {
    try {
        const data = await imFetch('/api/inquiry-match/categories');
        imState.leaves = [];
        data.tree.forEach(first => (first.children || []).forEach(second => {
            (second.children || []).forEach(leaf => {
                imState.leaves.push({ name: leaf.name, count: leaf.count });
            });
        }));
        imState.tree = data.tree;
        document.getElementById('categoryCount').textContent = imState.leaves.length + ' 个分类';
        renderTree();
    } catch (error) {
        document.getElementById('categoryTree').innerHTML =
            `<div class="im-empty">${escapeHtml(error.message)}</div>`;
    }
}

function renderTree() {
    const wrap = document.getElementById('categoryTree');
    const html = (imState.tree || []).map(first => {
        const seconds = (first.children || []).map(second => {
            const leaves = (second.children || []).map(leaf => `
                <div class="im-tree-leaf ${leaf.name === imState.selectedCategory ? 'active' : ''} ${leaf.count ? '' : 'is-zero'}"
                     data-name="${escapeHtml(leaf.name)}">
                    <span>${escapeHtml(leaf.name)}</span>
                    <span class="im-tree-count">${leaf.count}</span>
                </div>`).join('') || '<div class="im-tree-empty">暂无三级分类</div>';
            return `<details class="im-tree-second" open>
                <summary>${escapeHtml(second.name)}</summary>
                ${leaves}
            </details>`;
        }).join('') || '<div class="im-tree-empty">暂无二级分类</div>';
        return `<details class="im-tree-first" open>
            <summary>${escapeHtml(first.name)}</summary>
            ${seconds}
        </details>`;
    }).join('');
    wrap.innerHTML = html || '<div class="im-empty">暂无分类</div>';

    wrap.querySelectorAll('.im-tree-leaf').forEach(el => {
        el.onclick = () => {
            imState.selectedCategory = el.dataset.name;
            imState.selectedPartId = null;
            imState.selectedGroupId = '';
            // 只切换高亮，不重画整棵树，避免折叠状态被重置
            wrap.querySelectorAll('.im-tree-leaf').forEach(node => {
                node.classList.toggle('active', node === el);
            });
            resetSkuPanel();
            loadProducts();
        };
    });

    const active = wrap.querySelector('.im-tree-leaf.active');
    if (active) active.scrollIntoView({ block: 'nearest' });
}

// ========== 产品列表 ==========
function loadProducts() {
    const list = document.getElementById('productList');
    const keyword = document.getElementById('productSearch').value.trim();
    if (!imState.selectedCategory && !keyword) {
        list.innerHTML = '<div class="im-empty">请先在第二列选择产品分类，或直接输入关键词搜索</div>';
        document.getElementById('productCount').textContent = '请先选分类';
        return Promise.resolve();
    }
    const params = new URLSearchParams({ category: imState.selectedCategory, keyword, limit: 2000 });
    return imFetch('/api/inquiry-match/products?' + params).then(data => {
        imState.products = data.items;
        const shown = data.items.length;
        const total = data.total || shown;
        document.getElementById('productCount').textContent =
            total > shown ? `已显示 ${shown} / 共 ${total} 个型号` : `${shown} 个型号`;
        renderProducts();
    }).catch(error => {
        list.innerHTML = `<div class="im-empty">${escapeHtml(error.message)}</div>`;
    });
}

function renderProducts() {
    const list = document.getElementById('productList');
    if (!imState.products.length) {
        list.innerHTML = '<div class="im-empty">该分类下没有产品</div>';
        return;
    }
    list.innerHTML = imState.products.map((item, index) => `
        <div class="im-product ${item.id === imState.selectedPartId ? 'active' : ''}" data-part="${item.id}">
            <div class="p-seq">${index + 1}</div>
            <div class="p-info">
                <div class="p-name">${escapeHtml(item.product_name || '未命名产品')}</div>
                <div class="p-model">${escapeHtml(item.model || '无型号')}</div>
                <span class="p-type">${escapeHtml(item.product_type || '待重新分类')}</span>
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
            imState.selectedSpecs[el.dataset.spec] = el.dataset.value;
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
    if (record) parts.push(record.product_name || '询价');
    if (product) parts.push(product.model || product.product_name || '产品');
    if (groupId) parts.push('SKU 已选');
    else if (imState.selectedPartId) parts.push('未选 SKU');

    document.getElementById('matchSummary').textContent =
        parts.length ? parts.join(' · ') : '尚未完成选择';
    const canSave = !!(imState.selectedMissionId && imState.selectedPartId);
    document.getElementById('saveMatch').disabled = !canSave;
    document.getElementById('clearMatch').disabled = !record || !record.part_id;
}

async function saveMatch() {
    const missionId = imState.selectedMissionId;
    const partId = imState.selectedPartId;
    if (!missionId || !partId) return;
    const groupId = findSelectedGroup();
    if (imState.specs.length && !groupId) {
        showToast('请先选择完整的规格组合', 'error');
        return;
    }
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
function openImagePreview(url) {
    if (!url) return;
    document.getElementById('imagePreview').src = url;
    document.getElementById('imageOverlay').hidden = false;
}

function closeImagePreview() {
    document.getElementById('imageOverlay').hidden = true;
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
    document.getElementById('detailSummary').innerHTML =
        '<span class="im-muted">加载中…</span>';
    document.getElementById('detailStrip').innerHTML = '';
    document.getElementById('detailGrid').innerHTML = '';
    try {
        const data = await imFetch('/api/inquiry-match/detail/' + missionId);
        renderDetail(data);
    } catch (error) {
        showToast(error.message, 'error');
        closeDetail();
    }
}

function renderDetail(data) {
    const detailImage = document.getElementById('detailImage');
    detailImage.src = data.image || '/static/img/site-logo.png';
    // 有真实图片才允许点击放大，占位图点了没意义
    detailImage.style.cursor = data.image ? 'zoom-in' : 'default';
    detailImage.onclick = data.image ? () => openImagePreview(data.image) : null;

    document.getElementById('detailSummary').innerHTML = [
        ['商品名称：', imText(data.product_name) || '—'],
        ['规格型号：', imText(data.specification) || '—'],
        ['产品规格：', imText(data.ele_type) || '—'],
        ['商品单价：', imMoney(data.goods_price)
            ? `<b class="im-detail-price">${imMoney(data.goods_price)}</b>` : '—'],
    ].map(([label, value]) => `<label>${label}</label><span>${value}</span>`).join('');

    document.getElementById('detailStrip').innerHTML = [
        ['报价类型', imText(data.quotation_type) || '—'],
        ['采购报价', imMoney(data.purchase_price) || '—'],
        ['无税运费报价', imMoney(data.post_fee_purchase) || '—'],
        ['含税运费报价', imMoney(data.post_fee_has_tax_purchase) || '—'],
    ].map(([label, value]) => `<div><label>${label}</label><strong>${value}</strong></div>`).join('');

    const fields = [
        ['商品品牌/厂家', imText(data.product_brand)],
        ['商品税率', imText(data.tax_rate)],
        ['商品税费', imMoney(data.tax_fee)],
        ['含税售价', imMoney(data.goods_price_tax)],
        ['运费', imMoney(data.post_fee)],
        ['运费税率', imText(data.post_fee_tax_rate)],
        ['运费税费', imMoney(data.post_fee_tax_fee)],
        ['含税运费', imMoney(data.post_fee_has_tax)],
        ['数量', imNumber(data.goods_num)],
        ['单位', imText(data.goods_unit)],
        ['应收总额', imMoney(data.total_amount)],
        ['电梯场景', imText(data.ele_scene)],
        ['询价日期', imDate(data.inquiry_time)],
        ['创建时间', imDate(data.create_time)],
        ['询价描述', imText(data.goods_describe), true],
        ['询运描述', imText(data.post_fee_describe), true],
        ['商品备注', imText(data.remark), true],
        ['收货地址', imText(data.address), true],
    ].filter(([, value]) => value);

    document.getElementById('detailGrid').innerHTML = fields.map(([label, value, full]) => `
        <div class="${full ? 'im-detail-full' : ''}">
            <label>${label}</label><span>${value}</span>
        </div>`).join('')
        || '<div class="im-detail-full"><span class="im-muted">暂无更多信息</span></div>';

    loadDetailChat(data.order_goods_id);
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
    const wrap = document.getElementById('detailChat');
    const body = document.getElementById('detailChatBody');
    const count = document.getElementById('detailChatCount');
    if (!orderGoodsId) {
        wrap.hidden = true;
        return;
    }
    wrap.hidden = false;
    count.textContent = '加载中';
    body.innerHTML = '<tr><td colspan="5" class="im-detail-empty">正在加载沟通记录…</td></tr>';
    try {
        const data = await imFetch(
            '/api/sales/inquiry-communications?order_goods_id=' + encodeURIComponent(orderGoodsId)
        );
        const items = data.items || [];
        count.textContent = items.length + ' 条';
        body.innerHTML = items.length ? items.map((item, index) => {
            const links = (item.attachments || [])
                .map(imAttachmentUrl)
                .filter(Boolean)
                .map((url, i) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">附件${i + 1}</a>`)
                .join('');
            return `<tr>
                <td>${index + 1}</td>
                <td class="im-detail-content">${escapeHtml(item.content || '')}</td>
                <td>${links}</td>
                <td>${escapeHtml(item.creator || '')}</td>
                <td>${imDate(item.create_time)}</td>
            </tr>`;
        }).join('') : '<tr><td colspan="5" class="im-detail-empty">暂无沟通记录</td></tr>';
    } catch (error) {
        count.textContent = '加载失败';
        body.innerHTML = `<tr><td colspan="5" class="im-detail-empty">${escapeHtml(error.message)}</td></tr>`;
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
        loadRecords();
    });

    const searchRecords = () => {
        imState.keyword = document.getElementById('recordSearch').value.trim();
        imState.recordPage = 1;
        loadRecords();
    };
    document.getElementById('recordSearchBtn').onclick = searchRecords;
    document.getElementById('recordSearch').addEventListener('keydown', event => {
        if (event.key === 'Enter') searchRecords();
    });

    document.getElementById('recordPrev').onclick = () => {
        if (imState.recordPage > 1) {
            imState.recordPage -= 1;
            loadRecords();
        }
    };
    document.getElementById('recordNext').onclick = () => {
        if (imState.recordPage < imState.recordPages) {
            imState.recordPage += 1;
            loadRecords();
        }
    };

    document.getElementById('productSearchBtn').onclick = () => loadProducts();
    document.getElementById('createProductBtn').onclick = () => {
        window.open('/goods?create=1', '_blank');
    };

    // 从新增产品窗口切回本页时刷新产品列表，新加的产品才会出现
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        if (!imState.selectedCategory && !document.getElementById('productSearch').value.trim()) return;
        loadProducts();
    });
    document.getElementById('productSearch').addEventListener('keydown', event => {
        if (event.key === 'Enter') loadProducts();
    });

    document.getElementById('openSpecBtn').onclick = openSpecEditor;
    document.getElementById('saveMatch').onclick = saveMatch;
    document.getElementById('clearMatch').onclick = clearMatch;

    document.getElementById('detailClose').onclick = closeDetail;
    document.getElementById('detailOverlay').addEventListener('click', event => {
        if (event.target.id === 'detailOverlay') closeDetail();
    });
    document.getElementById('imageOverlay').onclick = closeImagePreview;
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        const imageOverlay = document.getElementById('imageOverlay');
        if (!imageOverlay.hidden) {
            closeImagePreview();
            return;
        }
        const overlay = document.getElementById('detailOverlay');
        if (overlay.classList.contains('show')) closeDetail();
    });
}

async function initInquiryMatch() {
    bindEvents();
    await loadCategories();
    await loadRecords();
    updateSummary();
}

initInquiryMatch();
