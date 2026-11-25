const salesState = {
    keyword: '',
    sort: 'default',
    page: 1,
    pageSize: 20,
    total: 0,
    items: [],
    view: localStorage.getItem('sales_view') === 'list' ? 'list' : 'grid',
};

const salesEls = {
    form: document.getElementById('salesSearchForm'),
    input: document.getElementById('salesSearchInput'),
    totalTop: document.getElementById('salesTotalTop'),
    resultTitle: document.getElementById('salesResultTitle'),
    resultDescription: document.getElementById('salesResultDescription'),
    resultRange: document.getElementById('salesResultRange'),
    loading: document.getElementById('salesLoading'),
    empty: document.getElementById('salesEmpty'),
    grid: document.getElementById('salesGoodsGrid'),
    list: document.getElementById('salesGoodsList'),
    listWrap: document.getElementById('salesGoodsListWrap'),
    pagination: document.getElementById('salesPagination'),
    gridButton: document.getElementById('salesGridButton'),
    listButton: document.getElementById('salesListButton'),
    imageOverlay: document.getElementById('salesImageOverlay'),
    previewImage: document.getElementById('salesPreviewImage'),
    galleryPrev: document.getElementById('salesGalleryPrev'),
    galleryNext: document.getElementById('salesGalleryNext'),
    imageCounter: document.getElementById('salesImageCounter'),
    detailOverlay: document.getElementById('salesDetailOverlay'),
    detailChat: document.getElementById('salesDetailChat'),
    detailChatCount: document.getElementById('salesDetailChatCount'),
    detailChatBody: document.getElementById('salesDetailChatBody'),
    detailInfoGrid: document.getElementById('salesDetailInfoGrid'),
    detailInfoTitle: document.getElementById('salesDetailInfoTitle'),
    detailPartsPrices: document.getElementById('salesDetailPartsPrices'),
    detailPriceMultiplier: document.getElementById('salesDetailPriceMultiplier'),
    detailPartsPriceContent: document.getElementById('salesDetailPartsPriceContent'),
    feedbackOverlay: document.getElementById('salesFeedbackOverlay'),
    feedbackForm: document.getElementById('salesFeedbackForm'),
    feedbackProductName: document.getElementById('salesFeedbackProductName'),
    feedbackProductModel: document.getElementById('salesFeedbackProductModel'),
    feedbackSource: document.getElementById('salesFeedbackSource'),
    feedbackDescription: document.getElementById('salesFeedbackDescription'),
    feedbackDescriptionCount: document.getElementById('salesFeedbackDescriptionCount'),
    feedbackTypeError: document.getElementById('salesFeedbackTypeError'),
    feedbackDescriptionError: document.getElementById('salesFeedbackDescriptionError'),
    feedbackSubmit: document.getElementById('salesFeedbackSubmitButton'),
    toast: document.getElementById('salesToast'),
};

let activeSalesDetailOrderGoodsId = null;
let activeSalesDetailPartId = null;
let activeSalesDetailItem = null;
let activeSalesVariantQuotes = [];
// 全量规格组合（含库里没报价的），用来判断「选了但没这个组合」
let activeSalesVariantPool = [];
// 当前选中的规格组合，一键询价时用它把询价和 SKU 绑上
let activeSalesVariantGroupId = '';
// 规格组合是否已加载完：加载完才知道「有没有规格」，加载中一律不放询价按钮
let activeSalesVariantLoaded = false;
// 规格选择状态：incomplete 未选满 / matched 命中且有报价 / missing 选满但拿不到报价
let activeSalesSpecState = 'incomplete';

function escapeSalesHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function salesText(value, fallback = '—') {
    const text = String(value ?? '').trim();
    return text || fallback;
}

function safeSalesImage(url) {
    const value = String(url ?? '').trim();
    if (!value) return '/static/img/site-logo.png';
    try {
        const parsed = new URL(value, window.location.origin);
        if (!['http:', 'https:'].includes(parsed.protocol)) return '/static/img/site-logo.png';
        return parsed.href;
    } catch (_) {
        return '/static/img/site-logo.png';
    }
}

function formatSalesPrice(value, compact = false, maxValue = null) {
    if (value === null || value === undefined || value === '') {
        return compact
            ? '<span class="list-price pending">价格待完善</span>'
            : '<div class="goods-price pending">价格待完善</div>';
    }
    const formatAmount = amount => {
        const numeric = Number(amount);
        return Number.isFinite(numeric)
            ? numeric.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : escapeSalesHtml(amount);
    };
    const formatted = formatAmount(value);
    const hasRange = maxValue !== null && maxValue !== undefined && maxValue !== ''
        && Number(maxValue) !== Number(value);
    const priceText = hasRange ? `¥${formatted}～¥${formatAmount(maxValue)}` : `¥${formatted}`;
    return compact
        ? `<span class="list-price">${priceText}</span>`
        : `<div class="goods-price">${priceText}<small>${hasRange ? '销售参考价区间' : '销售参考价'}</small></div>`;
}

function formatSalesDate(value) {
    if (!value) return '暂无报价时间';
    return String(value).replace('T', ' ').slice(0, 16);
}

function formatExpiryDeadline(expireDate, updateTime) {
    if (!expireDate) return '';
    const daysMatch = String(expireDate).match(/^(\d+)\s*天$/);
    if (daysMatch && updateTime) {
        const d = new Date(updateTime);
        if (!isNaN(d)) {
            d.setDate(d.getDate() + parseInt(daysMatch[1], 10));
            return `<div class="list-expiry-deadline">有效期至 ${d.toISOString().slice(0, 10)}</div>`;
        }
    }
    return `<div class="list-expiry-deadline">${escapeSalesHtml(expireDate)}</div>`;
}

async function salesRequest(url, options = {}) {
    const response = await fetch(url, {
        credentials: 'same-origin',
        ...options,
        headers: {
            ...(options.headers || {}),
        },
    });
    if (!response.ok) {
        let message = '请求失败，请稍后重试';
        try {
            const error = await response.json();
            message = error.detail || message;
        } catch (_) {}
        throw new Error(message);
    }
    return response.json();
}

function showSalesToast(message, type = '') {
    salesEls.toast.textContent = message;
    salesEls.toast.className = `sales-toast show ${type}`.trim();
    clearTimeout(showSalesToast.timer);
    showSalesToast.timer = setTimeout(() => {
        salesEls.toast.className = 'sales-toast';
    }, 2600);
}

async function loadSalesProducts() {
    salesEls.loading.style.display = 'flex';
    salesEls.empty.hidden = true;
    salesEls.grid.innerHTML = '';
    salesEls.list.innerHTML = '';
    salesEls.pagination.innerHTML = '';

    const params = new URLSearchParams({
        keyword: salesState.keyword,
        sort: salesState.sort,
        page: String(salesState.page),
        page_size: String(salesState.pageSize),
    });
    try {
        const data = await salesRequest(`/api/sales/products?${params}`);
        salesState.items = data.items || [];
        salesState.total = Number(data.total || 0);
        salesState.page = Number(data.page || 1);
        renderSalesProducts();
        if (data.oa_available === false) {
            showSalesToast('OA询价记录暂时无法读取，当前仅展示配件库数据', 'error');
        }
    } catch (error) {
        salesState.items = [];
        salesState.total = 0;
        salesEls.empty.hidden = false;
        salesEls.empty.querySelector('strong').textContent = '商品查询失败';
        salesEls.empty.querySelector('span').textContent = error.message;
        showSalesToast(error.message, 'error');
    } finally {
        salesEls.loading.style.display = 'none';
    }
}

function salesResultName() {
    if (salesState.keyword) return `“${salesState.keyword}” 搜索结果`;
    return '全部产品';
}

function renderSalesProducts() {
    const resultName = salesResultName();
    salesEls.totalTop.textContent = salesState.total.toLocaleString('zh-CN');
    salesEls.resultTitle.textContent = resultName;
    salesEls.resultDescription.textContent = salesState.keyword
        ? `正在查询与“${salesState.keyword}”相关的配件库和历史询价记录`
        : '同时查询配件库和历史询价记录中的销售参考价格';
    const start = salesState.total ? (salesState.page - 1) * salesState.pageSize + 1 : 0;
    const end = Math.min(salesState.page * salesState.pageSize, salesState.total);
    salesEls.resultRange.textContent = `显示 ${start}-${end} / 共 ${salesState.total.toLocaleString('zh-CN')} 条`;

    const isEmpty = !salesState.items.length;
    // 空状态里的询价入口也要跟着草稿状态变文案
    window.syncInquiryEntryLabel?.();
    salesEls.empty.hidden = !isEmpty;
    salesEls.grid.hidden = isEmpty;
    salesEls.listWrap.hidden = isEmpty;
    if (isEmpty) return;
    salesEls.grid.innerHTML = salesState.items.map(renderSalesCard).join('');
    salesEls.list.innerHTML = salesState.items.map(renderSalesListRow).join('');
    salesEls.list.querySelectorAll('[data-sales-preview-index]').forEach(button => {
        button.addEventListener('click', () => {
            const idx = Number(button.dataset.salesPreviewIndex);
            const item = salesState.items[idx];
            const images = (item && item.images && item.images.length) ? item.images : [item?.image || '/static/img/site-logo.png'];
            openSalesImagePreview(images);
        });
    });
    document.querySelectorAll('[data-sales-detail-index]').forEach(button => {
        button.addEventListener('click', () => openSalesProductDetail(Number(button.dataset.salesDetailIndex)));
    });
    renderSalesPagination();
}

function isSalesItemDiscontinued(item) {
    return item.has_any_price && !item.has_nonzero_price;
}

function isEmptyPrice(v) {
    return v === null || v === undefined || v === '' || Number(v) === 0;
}

function isPricePending(item) {
    // 无任何报价记录时返回 false，交给 formatSalesPrice 展示「价格待完善」
    if (!item.has_any_price) return false;
    if (!item.has_nonzero_price) return false;
    if (item.display_type === 'multi_variant') {
        return isEmptyPrice(item.display_price_min) && isEmptyPrice(item.display_price_max);
    }
    return isEmptyPrice(item.display_price);
}

function renderSalesCard(item, index) {
    const image = escapeSalesHtml(safeSalesImage(item.image));
    const isSubstitute = item.record_source_label === '替代品';
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    const badges = `<span class="source-badge ${source}">${sourceLabel}</span>${isSubstitute ? '<span class="source-badge substitute">替代品</span>' : ''}`;
    const isDiscontinued = isSalesItemDiscontinued(item);
    const isPending = isPricePending(item);
    const priceHtml = isDiscontinued
        ? '<div class="goods-price discontinued">已停产</div>'
        : isPending
            ? '<div class="goods-price pending">价格待定</div>'
            : formatSalesPrice(item.display_price_min ?? item.display_price, false, item.display_price_max);
    return `
        <article class="goods-card">
            <div class="goods-picture">
                <img src="${image}" alt="${escapeSalesHtml(salesText(item.product_name, '商品图片'))}"
                     loading="lazy" onerror="this.src='/static/img/site-logo.png';this.onerror=null">
            </div>
            <div class="goods-body">
                ${item.modification_completed ? '<span class="sales-completed-badge">已完成</span>' : ''}
                ${priceHtml}
                <div class="goods-name" title="${escapeSalesHtml(item.product_name)}">${escapeSalesHtml(salesText(item.product_name))}${badges}</div>
                <div class="goods-meta">
                    <div><label>品牌</label><span>${escapeSalesHtml(salesText(item.product_brand))}</span></div>
                    <div><label>型号</label><span title="${escapeSalesHtml(item.model)}">${escapeSalesHtml(salesText(item.model))}</span></div>
                    <div><label>更新</label><span>${escapeSalesHtml(formatSalesDate(item.quote_updated_at))}</span></div>
                </div>
                <button class="sales-card-detail-button" type="button" data-sales-detail-index="${index}">查看详情</button>
            </div>
        </article>`;
}

function salesPriceRangeText(minValue, maxValue) {
    if (!detailValue(minValue)) return '';
    const minText = detailAmountText(minValue);
    return detailValue(maxValue) && Number(maxValue) !== Number(minValue)
        ? `${minText}～${detailAmountText(maxValue)}`
        : minText;
}

function renderPartsInvoiceInfo(item) {
    if (item.record_source !== 'parts') return '';
    const special = item.special_price;
    const general = item.general_price;
    return [['含专票', special], ['含普票', general]]
        .filter(([, value]) => detailValue(value))
        .map(([label, value]) => `<div><label>${label}</label><span>${escapeSalesHtml(value)}</span></div>`)
        .join('');
}

function renderSalesListRow(item, index) {
    const image = escapeSalesHtml(safeSalesImage(item.image));
    const isSubstitute = item.record_source_label === '替代品';
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    const badges = `<span class="source-badge ${source}">${sourceLabel}</span>${isSubstitute ? '<span class="source-badge substitute">替代品</span>' : ''}`;
    const isDiscontinued = isSalesItemDiscontinued(item);
    const isPending = isPricePending(item);
    const priceHtml = isDiscontinued
        ? '<span class="list-price discontinued">已停产</span>'
        : isPending
            ? '<span class="list-price pending">价格待定</span>'
            : formatSalesPrice(item.display_price_min ?? item.display_price, true, item.display_price_max);
    return `<tr>
        <td><div class="list-product"><button class="list-image-button" type="button" data-sales-preview-index="${index}" title="点击查看大图"><img src="${image}" alt="商品图片" loading="lazy" onerror="this.src='/static/img/site-logo.png';this.onerror=null"></button><div><strong>${escapeSalesHtml(salesText(item.product_name))}</strong>${badges}</div></div></td>
        <td>${escapeSalesHtml(salesText(item.product_brand))}</td>
        <td>${escapeSalesHtml(salesText(item.model))}</td>
        <td class="list-specification">${source === 'inquiry' ? escapeSalesHtml(salesText(item.specification)) : renderVariantCombinations(item.variant_combinations)}</td>
        <td>${priceHtml}${formatExpiryDeadline(item.expire_date, item.quote_updated_at)}</td>
        <td><div class="sales-list-extra">${renderPartsInvoiceInfo(item)}</div></td>
        <td>${escapeSalesHtml(formatSalesDate(item.quote_updated_at))}</td>
        <td>${item.modification_completed ? '<span class="sales-completed-badge">已完成</span>' : ''}</td>
        <td><button class="sales-detail-button" type="button" data-sales-detail-index="${index}">详情</button></td>
    </tr>`;
}

function renderVariantCombinations(combinations) {
    if (!combinations || !combinations.length) {
        return '<span class="list-spec-empty">—</span>';
    }
    // 列表只展示详情默认选中的那一条：每个规格维度取第一个值
    const picked = [];
    collectSpecDimensions(combinations).forEach((values, key) => {
        picked.push(`${key}：${values[0]}`);
    });
    // 解析不出维度时退回第一条原文
    const text = picked.length ? picked.join('；') : (combinations[0].specification || '未命名组合');
    return `<div class="variant-combo-row">${escapeSalesHtml(text)}</div>`;
}

function detailPriceText(value) {
    if (value === null || value === undefined || value === '') return '';
    const amount = Number(value);
    return Number.isFinite(amount)
        ? `¥${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : salesText(value);
}

function detailValue(value) {
    return String(value ?? '').trim();
}

function detailAmountText(value) {
    return detailValue(value) ? detailPriceText(value) : '';
}

function quotationTypeText(value) {
    const type = detailValue(value);
    if (type === '0') return '无税报价';
    if (type === '1') return '含税报价';
    return type;
}

function renderSalesDetailInfo(item, source, sourceLabel, quote = null) {
    const fields = source === 'parts'
        ? [
            ['商品品牌', item.product_brand],
            ['产品分类', item.product_type],
            // 质保、发货、有效期这些一律以选中 SKU 的报价行为准，不再回落商品主表
            ['质保期限', quote?.warranty_time],
            ['适用电梯品牌', item.applicable_elevator_brand],
            ['替代型号', item.substitute_model],
            ['发货地', quote?.shipping_origin],
            ['发货时间', quote?.shipping_time],
            ['报价有效期', quote?.expire_date],
            ['每日截单时间', quote?.daily_order_time],
            ['报价时间', quote?.quote_time],
            ['采购运费', quote ? detailAmountText(quote.purchase_shipping) : ''],
            ['更新人', item.updater || item.filler],
            ['更新时间', quote?.update_time ? formatSalesDate(quote.update_time) : (item.quote_updated_at ? formatSalesDate(item.quote_updated_at) : '')],
            ['运费备注', quote?.freight_remark],
            ['商品备注', item.remark, 'full'],
            ['补充备注', item.remark_2, 'full'],
            ['注意事项', item.precautions, 'full'],
            ['技术参数', item.technical_params, 'full'],
        ]
        : [
            ['售价：', detailAmountText(item.display_price)],
            ['商品品牌/厂家：', item.product_brand],
            ['商品税率：', item.tax_rate],
            ['商品税费：', detailAmountText(item.tax_fee)],
            ['含税售价：', detailAmountText(item.goods_price_tax)],
            ['运费：', detailAmountText(item.post_fee)],
            ['运费税率：', item.post_fee_tax_rate],
            ['运费税费：', detailAmountText(item.post_fee_tax_fee)],
            ['含税运费：', detailAmountText(item.post_fee_has_tax)],
            ['数量：', item.goods_num],
            ['单位：', item.goods_unit],
            ['应收总额：', detailAmountText(item.total_amount)],
            ['电梯场景：', item.ele_scene],
            ['询价日期：', item.inquiry_time ? formatSalesDate(item.inquiry_time) : ''],
            ['创建时间：', item.create_time ? formatSalesDate(item.create_time) : ''],
            ['询价描述：', item.goods_describe, 'wide'],
            ['询运描述：', item.post_fee_describe, 'wide'],
            ['商品备注：', item.remark, 'wide'],
            ['收货地址：', item.address, 'full'],
            ['数据来源：', sourceLabel],
        ];
    // 配件库详情使用固定字段模板，空值也保留对应位置，避免有无标准规格时布局不一致。
    // 询价记录沿用原有行为，只展示实际存在的业务字段。
    const visibleFields = source === 'parts'
        ? fields
        : fields.filter(([, value]) => detailValue(value));
    if (salesEls.detailInfoTitle) {
        salesEls.detailInfoTitle.textContent = source === 'parts' ? '配件库信息' : '询价信息';
    }
    const infoTabButton = document.querySelector('[data-sales-tab="info"]');
    if (infoTabButton) infoTabButton.textContent = source === 'parts' ? '配件库信息' : '询价信息';
    salesEls.detailInfoGrid.innerHTML = visibleFields.map(([label, value, width = '']) => {
        const text = detailValue(value);
        return `
        <div class="${width ? `sales-detail-${width}` : ''}">
            <label>${escapeSalesHtml(label)}</label>
            <span class="${text ? '' : 'sales-detail-info-empty'}">${escapeSalesHtml(text || '—')}</span>
        </div>`;
    }).join('');
}

function setSalesDetailText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value ?? '').trim();
}

// 顶部信息项：没有值就整块隐藏
function setSalesDetailMeta(itemId, valueId, value) {
    const wrap = document.getElementById(itemId);
    const target = document.getElementById(valueId);
    const text = detailValue(value);
    if (target) target.textContent = text;
    if (wrap) wrap.hidden = !text;
}

function safeSalesAttachmentUrl(url) {
    const value = String(url ?? '').trim();
    if (!value) return '';
    try {
        const parsed = new URL(value, window.location.origin);
        return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
    } catch (_) {
        return '';
    }
}

function renderSalesCommunicationRows(items) {
    if (!items.length) {
        return '<tr><td colspan="6" class="sales-detail-empty">暂无沟通记录</td></tr>';
    }
    return items.map((item, index) => {
        const attachments = (item.attachments || [])
            .map(safeSalesAttachmentUrl)
            .filter(Boolean)
            .map((url, attachmentIndex) => `<a href="${escapeSalesHtml(url)}" target="_blank" rel="noopener noreferrer">附件${attachmentIndex + 1}</a>`)
            .join('、');
        return `<tr>
            <td>${index + 1}</td>
            <td class="sales-detail-content">${escapeSalesHtml(salesText(item.content, ''))}</td>
            <td>${attachments || ''}</td>
            <td>${escapeSalesHtml(salesText(item.creator, ''))}</td>
            <td>${escapeSalesHtml(formatSalesDate(item.create_time))}</td>
            <td></td>
        </tr>`;
    }).join('');
}

// 沟通记录要同时写新版和新版之外的旧版表格
function setSalesChatContent(countText, rowsHtml) {
    if (salesEls.detailChatCount) salesEls.detailChatCount.textContent = countText;
    if (salesEls.detailChatBody) salesEls.detailChatBody.innerHTML = rowsHtml;
    const legacyCount = document.getElementById('salesDetailChatCountLegacy');
    if (legacyCount) legacyCount.textContent = countText;
    const legacyBody = document.getElementById('salesDetailChatBodyLegacy');
    if (legacyBody) legacyBody.innerHTML = rowsHtml;
}

async function loadSalesCommunications(orderGoodsId) {
    activeSalesDetailOrderGoodsId = orderGoodsId;
    setSalesChatContent('加载中', '<tr><td colspan="6" class="sales-detail-empty">正在加载沟通记录...</td></tr>');
    try {
        const data = await salesRequest(`/api/sales/inquiry-communications?order_goods_id=${encodeURIComponent(orderGoodsId)}`);
        if (activeSalesDetailOrderGoodsId !== orderGoodsId) return;
        const items = data.items || [];
        setSalesChatContent(`${items.length} 条`, renderSalesCommunicationRows(items));
    } catch (error) {
        if (activeSalesDetailOrderGoodsId !== orderGoodsId) return;
        setSalesChatContent('加载失败', `<tr><td colspan="6" class="sales-detail-empty">${escapeSalesHtml(error.message)}</td></tr>`);
    }
}

// 「性质：原厂；颜色：黑屏」→ [{ key: '性质', value: '原厂' }, ...]
function parseSalesSpecs(label) {
    return String(label || '')
        .split(/[;；]/)
        .map(part => {
            const index = part.search(/[:：]/);
            if (index < 0) return null;
            const key = part.slice(0, index).trim();
            const value = part.slice(index + 1).trim();
            return key && value ? { key, value } : null;
        })
        .filter(Boolean);
}

let activeSalesSpecMap = {};

function specsToMap(specs) {
    return Object.fromEntries(specs.map(spec => [spec.key, spec.value]));
}

// 所有规格组合按属性维度归并，收集每个维度出现过的值
function collectSpecDimensions(items) {
    const dimensions = new Map();
    items.forEach(item => {
        parseSalesSpecs(item.specification).forEach(({ key, value }) => {
            if (!dimensions.has(key)) dimensions.set(key, []);
            const values = dimensions.get(key);
            if (!values.includes(value)) values.push(value);
        });
    });
    return dimensions;
}

// 全量组合（variant_combinations）打底，有报价的组合（variant-quotes）挂上 quote
function buildSalesVariantPool(item, quotes) {
    const quoteByGroup = new Map();
    for (const quote of quotes) {
        const key = String(quote.variant_group_id || '');
        if (key) quoteByGroup.set(key, quote);
    }
    const pool = [];
    const seen = new Set();
    for (const combo of (item?.variant_combinations || [])) {
        const key = String(combo.variant_group_id || '');
        if (!key || seen.has(key)) continue;
        seen.add(key);
        pool.push({
            variant_group_id: key,
            specification: combo.specification || '',
            is_discontinued: Boolean(combo.is_discontinued),
            quote: quoteByGroup.get(key) || null,
        });
    }
    // 列表接口没带全量组合时，退回只渲染有报价的组合
    for (const quote of quotes) {
        const key = String(quote.variant_group_id || '');
        if (!key || seen.has(key)) continue;
        seen.add(key);
        pool.push({
            variant_group_id: key,
            specification: quote.specification || '',
            is_discontinued: false,
            quote,
        });
    }
    return pool;
}

// 规格按属性维度归并，每个维度一行值按钮，全部可点（不置灰）
function renderSalesVariantPrices(pool) {
    if (!pool.length) {
        return '<div class="sales-detail-price-empty">该产品暂无规格</div>';
    }
    const dimensions = collectSpecDimensions(pool);
    if (!dimensions.size) {
        // 规格串解析不出属性时，退化成一条一行
        return pool.map((entry, index) => `
            <div class="sales-detail-spec-group">
                <span class="sales-detail-spec-group-label">规格${index + 1}</span>
                <div class="sales-detail-spec-values">
                    <button type="button" class="sales-detail-spec-option${activeSalesVariantGroupId === entry.variant_group_id ? ' active' : ''}"
                            onclick="selectSalesVariantQuote(${index})">${escapeSalesHtml(detailValue(entry.specification))}</button>
                </div>
            </div>`).join('');
    }
    return [...dimensions.entries()].map(([key, values]) => `
        <div class="sales-detail-spec-group">
            <span class="sales-detail-spec-group-label">${escapeSalesHtml(key)}</span>
            <div class="sales-detail-spec-values">
                ${values.map(value => {
                    const selected = activeSalesSpecMap[key] === value;
                    // 凑不出组合的值置灰不可点，和产品关联页的 SKU 选择保持一致
                    const disabled = !selected && !salesValueAvailable(key, value);
                    return `<button type="button" class="sales-detail-spec-option${selected ? ' active' : ''}${disabled ? ' is-disabled' : ''}"
                                data-spec-key="${escapeSalesHtml(key)}" data-spec-value="${escapeSalesHtml(value)}"
                                ${disabled ? 'disabled aria-disabled="true"' : ''}
                                onclick="selectSalesSpecValue(this)">${escapeSalesHtml(value)}</button>`;
                }).join('')}
            </div>
        </div>`).join('');
}

// 当前已选条件下还能凑出真实组合的规格值才可点
function salesValueAvailable(key, value) {
    const pool = activeSalesVariantPool;
    if (!pool.length) return true;
    const specsOf = entry => parseSalesSpecs(entry.specification);
    // 该规格名没进任何组合（刚加还没配组合）时不做限制
    if (!pool.some(entry => specsOf(entry).some(spec => spec.key === key))) return true;
    return pool.some(entry => {
        const map = specsToMap(specsOf(entry));
        if (map[key] !== value) return false;
        return Object.entries(activeSalesSpecMap).every(([k, v]) =>
            !detailValue(v) || k === key || map[k] === v);
    });
}

// 点规格值只切换这一维：再点一次取消选中，不联动、不预选其它维度
function selectSalesSpecValue(button) {
    const key = button.dataset.specKey;
    const value = button.dataset.specValue;
    if (!key || !value) return;
    const next = {...activeSalesSpecMap};
    if (next[key] === value) delete next[key];
    else next[key] = value;
    activeSalesSpecMap = next;
    applySalesSpecSelection();
    // 没选满就没有组合价，清掉上一个组合留下的数字
    if (activeSalesSpecState === 'incomplete') {
        setSalesDetailPrices('', '', '', true);
    }
}

// 当前已选的值，按维度顺序返回
function selectedSpecValues() {
    const dimensions = collectSpecDimensions(activeSalesVariantPool);
    const keys = dimensions.size ? [...dimensions.keys()] : Object.keys(activeSalesSpecMap);
    return keys.map(key => detailValue(activeSalesSpecMap[key])).filter(Boolean);
}

// 按当前选择找组合，找不到说明库里没有这个组合
function findSalesSpecEntry() {
    const picks = Object.entries(activeSalesSpecMap).filter(([, value]) => detailValue(value));
    if (!picks.length) return null;
    return activeSalesVariantPool.find(entry => {
        const specs = parseSalesSpecs(entry.specification);
        return picks.every(([key, value]) => specs.some(spec => spec.key === key && spec.value === value));
    }) || null;
}

// 有价格记录但三项价格全空时销售看不到价，同样要转采购
function hasUsableVariantPrice(quote) {
    if (!quote) return false;
    return !isEmptyPrice(quote.no_tax_price)
        || !isEmptyPrice(quote.special_invoice_price)
        || !isEmptyPrice(quote.general_invoice_price);
}

// 规格选中后的统一判定：命中且有报价 → 可询价；选满但拿不到报价 → 引导创建询价单
function applySalesSpecSelection(forcedEntry = null) {
    const dimensions = collectSpecDimensions(activeSalesVariantPool);
    const picked = Object.entries(activeSalesSpecMap).filter(([, value]) => detailValue(value));
    const complete = Boolean(forcedEntry)
        || (dimensions.size ? picked.length >= dimensions.size : false);
    const entry = forcedEntry || (complete ? findSalesSpecEntry() : null);
    const quote = entry?.quote || null;
    const usable = hasUsableVariantPrice(quote);

    activeSalesVariantGroupId = usable ? String(entry.variant_group_id) : '';
    activeSalesSpecState = !complete ? 'incomplete' : (usable ? 'matched' : 'missing');

    salesEls.detailPartsPriceContent.innerHTML = renderSalesVariantPrices(activeSalesVariantPool);
    if (usable) {
        setSalesDetailPrices(quote.no_tax_price, quote.special_invoice_price, quote.general_invoice_price, true);
        renderSalesDetailInfo(activeSalesDetailItem, 'parts', '来自配件库', quote);
    } else if (complete) {
        // 没报价就把价格清空，别留着上一个组合的数字
        setSalesDetailPrices('', '', '', true);
        renderSalesDetailInfo(activeSalesDetailItem, 'parts', '来自配件库');
    }
    syncSalesDetailInquiryButton();
}

function selectSalesVariantQuote(index) {
    const entry = activeSalesVariantPool[index];
    if (!entry || !activeSalesDetailItem) return;
    activeSalesSpecMap = specsToMap(parseSalesSpecs(entry.specification));
    applySalesSpecSelection(entry);
}

// 一键询价按钮 + 询价单提示条：按钮看规格状态，提示条只要有规格就常驻
function syncSalesDetailInquiryButton() {
    const button = document.getElementById('salesDetailInquiryButton');
    const notice = document.getElementById('salesDetailSpecNotice');
    if (!button) return;
    const isParts = activeSalesDetailItem?.record_source !== 'inquiry';
    const hasSpec = activeSalesVariantPool.length > 0;
    // 没有规格等于不用选，直接可询价；有规格必须命中一条有报价的组合
    const ready = activeSalesVariantLoaded && (!hasSpec || activeSalesSpecState === 'matched');
    // 询价来源不显示；配件库来源常驻，规格没选好就置灰
    button.hidden = !isParts;
    button.disabled = !ready;
    // 已有询价草稿时按钮改成「加入询价单」，点一下是追加而不是新建
    window.syncInquiryEntryLabel?.();
    if (!notice) return;
    // 提示条是表单的一部分，不跟着选规格才出现，销售扫一眼就能直接建单
    const showNotice = isParts && activeSalesVariantLoaded && hasSpec;
    notice.hidden = !showNotice;
}

let activeSalesDetailImages = [];
let activeSalesDetailImageIndex = 0;

// 价格盒：不含票价用大字，含专票、含普票跟在后面
// showAll（配件库来源）：固定展示三种价格，缺的留「—」，不再用含票价兜底主价
function setSalesDetailPrices(noTax, special, general, showAll = false) {
    const label = document.getElementById('salesDetailPriceLabel');
    const priceEl = document.getElementById('salesDetailPrice');
    const noTaxText = detailPriceText(noTax);
    const specialText = detailAmountText(special);
    const generalText = detailAmountText(general);
    if (showAll) {
        setSalesDetailText('salesDetailPrice', noTaxText || '—');
        if (priceEl) priceEl.classList.toggle('is-empty', !noTaxText);
        if (label) label.textContent = '不含票价';
        setSalesPriceExtra('salesDetailSpecialWrap', 'salesDetailSpecialPrice', specialText, '');
        setSalesPriceExtra('salesDetailGeneralWrap', 'salesDetailGeneralPrice', generalText, '');
        return;
    }
    if (priceEl) priceEl.classList.remove('is-empty');
    // 询价来源：有的组合只录了含票价，这时用含票兜底并改标签，否则「价格待定」和旁边的 ¥230 自相矛盾
    const fallback = specialText || generalText;
    setSalesDetailText('salesDetailPrice', noTaxText || fallback || '价格待定');
    if (label) {
        label.textContent = noTaxText ? '不含票价'
            : specialText ? '含专票价'
            : generalText ? '含普票价' : '不含票价';
    }
    // 主价已经拿含票价兜底时，右侧不再重复同一个数字
    const duplicated = noTaxText ? '' : fallback;
    setSalesPriceExtra('salesDetailSpecialWrap', 'salesDetailSpecialPrice', specialText, duplicated);
    setSalesPriceExtra('salesDetailGeneralWrap', 'salesDetailGeneralPrice', generalText, duplicated);
}

function setSalesPriceExtra(wrapId, valueId, text, duplicated) {
    const wrap = document.getElementById(wrapId);
    const target = document.getElementById(valueId);
    if (!wrap || !target) return;
    if (text && text === duplicated) {
        wrap.hidden = true;
        target.textContent = '';
        return;
    }
    wrap.hidden = false;
    wrap.classList.toggle('is-empty', !text);
    target.textContent = text || '—';
}

function switchSalesDetailTab(name) {
    document.querySelectorAll('.sales-detail-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.salesTab === name);
    });
    document.querySelectorAll('.sales-detail-panel').forEach(panel => {
        panel.hidden = panel.dataset.salesPanel !== name;
    });
}

// 询价来源沿用改版前的排版，配件库才用新结构
function switchSalesDetailBody(mode, item) {
    const partsBody = document.querySelector('[data-sales-body="parts"]');
    const inquiryBody = document.querySelector('[data-sales-body="inquiry"]');
    if (!partsBody || !inquiryBody) return;
    const isInquiry = mode === 'inquiry';
    partsBody.hidden = isInquiry;
    inquiryBody.hidden = !isInquiry;
    // 配件没有关联询价记录，那个标签页永远是空的，藏掉
    const chatTab = document.querySelector('[data-sales-tab="chat"]');
    if (chatTab) chatTab.hidden = !isInquiry;
    if (!isInquiry) switchSalesDetailTab('info');
    if (!isInquiry || !item) return;

    const setText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text || '';
    };
    setText('salesDetailNameLegacy', item.product_name);
    setText('salesDetailModelLegacy', salesText(item.model));
    setText('salesDetailSpecificationLegacy', salesText(item.specification));
    setText('salesDetailPriceLegacy', detailPriceText(item.display_price) || '价格待完善');
    setText('salesDetailQuotationTypeLegacy', quotationTypeText(item.quotation_type));
    setText('salesDetailPostFeePurchaseLegacy', detailAmountText(item.post_fee_purchase));
    setText('salesDetailPostFeeHasTaxPurchaseLegacy', detailAmountText(item.post_fee_has_tax_purchase));

    const legacyImage = document.getElementById('salesDetailImageLegacy');
    if (legacyImage) legacyImage.src = safeSalesImage(item.image);

    // 字段渲染不复制一份，直接搬新版那棵子树
    const legacyGrid = document.getElementById('salesDetailInfoGridLegacy');
    if (legacyGrid) legacyGrid.innerHTML = salesEls.detailInfoGrid.innerHTML;
}

function renderSalesDetailThumbs(images) {
    activeSalesDetailImages = images;
    activeSalesDetailImageIndex = 0;
    const multiple = images.length > 1;
    const prev = document.getElementById('salesDetailImagePrev');
    const next = document.getElementById('salesDetailImageNext');
    if (prev) prev.hidden = !multiple;
    if (next) next.hidden = !multiple;
    const wrap = document.getElementById('salesDetailThumbs');
    if (!wrap) return;
    // 单图不占位置，和原型一致
    if (!multiple) {
        wrap.innerHTML = '';
        return;
    }
    wrap.innerHTML = images.map((url, index) => `
        <button type="button" class="sales-detail-thumb${index === 0 ? ' active' : ''}"
                onclick="selectSalesDetailImage(${index})" aria-label="第 ${index + 1} 张图片">
            <img src="${escapeSalesHtml(safeSalesImage(url))}" alt="商品图片 ${index + 1}" loading="lazy"
                 onerror="this.src='/static/img/site-logo.png';this.onerror=null">
        </button>`).join('');
}

function selectSalesDetailImage(index) {
    const url = activeSalesDetailImages[index];
    if (!url) return;
    activeSalesDetailImageIndex = index;
    const image = document.getElementById('salesDetailImage');
    if (image) image.src = safeSalesImage(url);
    document.querySelectorAll('.sales-detail-thumb').forEach((thumb, i) => {
        thumb.classList.toggle('active', i === index);
    });
}

// 主图左右切换，缩略图列跟着滚动到可见位置
function stepSalesDetailImage(delta) {
    const count = activeSalesDetailImages.length;
    if (count < 2) return;
    selectSalesDetailImage((activeSalesDetailImageIndex + delta + count) % count);
    const active = document.querySelector('.sales-detail-thumb.active');
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
}

async function loadSalesPartVariantQuotes(partId, item) {
    activeSalesDetailPartId = partId;
    salesEls.detailPartsPrices.hidden = false;
    salesEls.detailPartsPriceContent.innerHTML = '<div class="sales-detail-price-loading">正在加载价格信息...</div>';
    try {
        const data = await salesRequest(`/api/sales/parts/${encodeURIComponent(partId)}/variant-quotes`);
        if (activeSalesDetailPartId !== partId) return;
        const items = data.items || [];
        activeSalesVariantQuotes = items;
        activeSalesVariantPool = buildSalesVariantPool(item, items);
        activeSalesVariantLoaded = true;
        if (!activeSalesVariantPool.length) {
            activeSalesSpecMap = {};
            activeSalesVariantGroupId = '';
            activeSalesSpecState = 'incomplete';
            syncSalesDetailInquiryButton();
            salesEls.detailPartsPriceContent.innerHTML =
                '<div class="sales-detail-price-empty">该产品暂无规格</div>';
            return;
        }
        // 打开详情默认选中一条组合：优先有报价的那条，保证一进来就能看到价格
        const defaultIndex = activeSalesVariantPool.findIndex(
            entry => hasUsableVariantPrice(entry.quote)
        );
        selectSalesVariantQuote(defaultIndex >= 0 ? defaultIndex : 0);
    } catch (error) {
        if (activeSalesDetailPartId !== partId) return;
        // 拉不到规格就清空选中，别把上一个商品的 SKU 带进询价
        activeSalesVariantQuotes = [];
        activeSalesVariantPool = [];
        activeSalesSpecMap = {};
        activeSalesVariantGroupId = '';
        activeSalesSpecState = 'incomplete';
        activeSalesVariantLoaded = false;
        syncSalesDetailInquiryButton();
        salesEls.detailPriceMultiplier.textContent = '加载失败';
        salesEls.detailPartsPriceContent.innerHTML = `<div class="sales-detail-price-loading">${escapeSalesHtml(error.message)}</div>`;
    }
}

function openSalesProductDetail(index) {
    const item = salesState.items[index];
    if (!item) return;
    const isSubstitute = item.record_source_label === '替代品';
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    activeSalesDetailItem = item;
    const detailModal = document.getElementById('salesDetailModal');
    detailModal.classList.toggle('inquiry-detail', source === 'inquiry');
    detailModal.classList.toggle('parts-detail', source === 'parts');
    const sourceBadgeWrap = document.getElementById('salesDetailSource');
    sourceBadgeWrap.innerHTML = `<span class="source-badge ${source}">${sourceLabel}</span>${isSubstitute ? '<span class="source-badge substitute">替代品</span>' : ''}`;
    // 一键询价只对配件库来源有意义，且要等规格加载完、命中组合才放出来
    activeSalesVariantQuotes = [];
    activeSalesVariantPool = [];
    activeSalesSpecMap = {};
    activeSalesVariantGroupId = '';
    activeSalesSpecState = 'incomplete';
    activeSalesVariantLoaded = false;
    syncSalesDetailInquiryButton();
    setSalesDetailText('salesDetailTitle', source === 'inquiry' ? '询价商品详情' : '配件商品详情');
    setSalesDetailText('salesDetailName', item.product_name);
    setSalesDetailText('salesDetailCrumbName', salesText(item.product_name));
    const isInquiry = source === 'inquiry';
    // 基础信息：值为空就隐藏整项，不要摆一排「—」
    setSalesDetailMeta('salesDetailModelItem', 'salesDetailModel', item.model);
    setSalesDetailMeta('salesDetailBrandItem', 'salesDetailBrand', item.product_brand);
    setSalesDetailMeta('salesDetailCategoryItem', 'salesDetailCategory', item.product_type);
    setSalesDetailMeta('salesDetailWarrantyItem', 'salesDetailWarranty', item.warranty);
    setSalesDetailText('salesDetailSubstitute', detailValue(item.substitute_model));
    // 配件库三种价格各取各的原始值：不含票用 no_tax_price，避免拿含票价兜底后标签对不上
    const noTaxForDetail = isInquiry ? item.display_price
        : (Object.prototype.hasOwnProperty.call(item, 'no_tax_price') ? item.no_tax_price : item.display_price);
    setSalesDetailPrices(noTaxForDetail, item.special_price, item.general_price, !isInquiry);
    setSalesDetailText('salesDetailQuotationType', isInquiry ? quotationTypeText(item.quotation_type) : '');
    setSalesDetailText('salesDetailPostFeePurchase', isInquiry ? detailAmountText(item.post_fee_purchase) : '');
    setSalesDetailText(
        'salesDetailPostFeeHasTaxPurchase',
        isInquiry ? detailAmountText(item.post_fee_has_tax_purchase) : '',
    );
    // 配件库的价格标签由 setSalesDetailPrices 按实际兜底情况决定，这里只处理询价来源
    if (isInquiry) setSalesDetailText('salesDetailPriceLabel', '销售参考价');
    // 配件库的质保、发货地统一放在上面的「服务」行，这里不再重复
    const warrantyItem = document.getElementById('salesDetailWarrantyItem');
    if (warrantyItem && !isInquiry) warrantyItem.hidden = true;
    const substituteWrap = document.getElementById('salesDetailSubstituteWrap');
    if (substituteWrap) {
        const text = detailValue(document.getElementById('salesDetailSubstitute')?.textContent);
        substituteWrap.hidden = isInquiry || !text;
    }
    document.getElementById('salesDetailQuotationWrap').hidden = !isInquiry;
    document.getElementById('salesDetailPostFeeWrap').hidden = !isInquiry;
    document.getElementById('salesDetailPostFeeTaxWrap').hidden = !isInquiry;
    renderSalesDetailInfo(item, source, sourceLabel);
    switchSalesDetailTab('info');
    switchSalesDetailBody(source, item);
    const detailImage = document.getElementById('salesDetailImage');
    detailImage.src = safeSalesImage(item.image);
    const images = (item.images && item.images.length) ? item.images : [item.image || '/static/img/site-logo.png'];
    renderSalesDetailThumbs(images);
    detailImage.onclick = () => openSalesImagePreview(images);
    detailImage.style.cursor = 'zoom-in';
    const legacyImage = document.getElementById('salesDetailImageLegacy');
    if (legacyImage) {
        legacyImage.onclick = () => openSalesImagePreview(images);
        legacyImage.style.cursor = 'zoom-in';
    }
    const orderGoodsId = Number(item.order_goods_id);
    const showCommunications = source === 'inquiry' && Number.isInteger(orderGoodsId) && orderGoodsId > 0;
    activeSalesDetailOrderGoodsId = showCommunications ? orderGoodsId : null;
    if (showCommunications) {
        loadSalesCommunications(orderGoodsId);
    } else {
        setSalesChatContent('0 条', '<tr><td colspan="6" class="sales-detail-empty">这笔询价没有沟通记录</td></tr>');
    }
    const partId = Number(item.id);
    const loadVariantQuotes = source === 'parts' && Number.isInteger(partId) && partId > 0;
    activeSalesDetailPartId = loadVariantQuotes ? partId : null;
    salesEls.detailPartsPrices.hidden = !loadVariantQuotes;
    if (loadVariantQuotes) loadSalesPartVariantQuotes(partId, item);
    salesEls.detailOverlay.classList.add('show');
    salesEls.detailOverlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
}

function closeSalesProductDetail() {
    closeSalesFeedback();
    activeSalesDetailOrderGoodsId = null;
    activeSalesDetailPartId = null;
    activeSalesDetailItem = null;
    activeSalesVariantQuotes = [];
    activeSalesVariantPool = [];
    activeSalesSpecMap = {};
    activeSalesVariantGroupId = '';
    activeSalesSpecState = 'incomplete';
    activeSalesVariantLoaded = false;
    document.getElementById('salesDetailImage').onclick = null;
    salesEls.detailOverlay.classList.remove('show');
    salesEls.detailOverlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

function clearSalesFeedbackErrors() {
    salesEls.feedbackTypeError.textContent = '';
    salesEls.feedbackDescriptionError.textContent = '';
    salesEls.feedbackDescription.classList.remove('invalid');
}

function openSalesFeedback() {
    const item = activeSalesDetailItem;
    if (!item) {
        showSalesToast('请先选择需要反馈的商品', 'error');
        return;
    }
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    salesEls.feedbackForm.reset();
    clearSalesFeedbackErrors();
    salesEls.feedbackDescriptionCount.textContent = '0';
    salesEls.feedbackProductName.textContent = salesText(item.product_name, '未命名商品');
    salesEls.feedbackProductModel.textContent = `型号：${salesText(item.model, '暂无型号')}`;
    salesEls.feedbackSource.textContent = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    salesEls.feedbackSource.className = `source-badge ${source}`;
    salesEls.feedbackOverlay.classList.add('show');
    salesEls.feedbackOverlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
}

function closeSalesFeedback() {
    if (!salesEls.feedbackOverlay.classList.contains('show')) return;
    salesEls.feedbackOverlay.classList.remove('show');
    salesEls.feedbackOverlay.setAttribute('aria-hidden', 'true');
    salesEls.feedbackSubmit.disabled = false;
    salesEls.feedbackSubmit.querySelector('span').textContent = '提交反馈';
    if (!salesEls.detailOverlay.classList.contains('show')) {
        document.body.style.overflow = '';
    }
}

async function submitSalesFeedback(event) {
    event.preventDefault();
    const item = activeSalesDetailItem;
    if (!item) return;
    clearSalesFeedbackErrors();
    const problemTypes = [...salesEls.feedbackForm.querySelectorAll('input[name="salesFeedbackProblem"]:checked')]
        .map(input => input.value);
    const description = salesEls.feedbackDescription.value.trim();
    let valid = true;
    if (!problemTypes.length) {
        salesEls.feedbackTypeError.textContent = '请至少选择一项问题类型';
        valid = false;
    }
    if (!description) {
        salesEls.feedbackDescriptionError.textContent = '请输入具体错误描述';
        salesEls.feedbackDescription.classList.add('invalid');
        valid = false;
    }
    if (!valid) return;

    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    salesEls.feedbackSubmit.disabled = true;
    salesEls.feedbackSubmit.querySelector('span').textContent = '正在提交…';
    try {
        await salesRequest('/api/sales/feedback', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                record_source: source,
                parts_id: source === 'parts' ? (Number(item.id) || null) : null,
                inquiry_mission_id: source === 'inquiry' ? (Number(item.inquiry_mission_id || item.id) || null) : null,
                inquiry_goods_id: source === 'inquiry' ? (Number(item.order_goods_id) || null) : null,
                problem_types: problemTypes,
                description,
            }),
        });
        showSalesToast('反馈提交成功，感谢你的帮助', 'success');
        closeSalesFeedback();
    } catch (error) {
        showSalesToast(error.message || '反馈提交失败，请稍后重试', 'error');
        salesEls.feedbackSubmit.disabled = false;
        salesEls.feedbackSubmit.querySelector('span').textContent = '提交反馈';
    }
}

function renderSalesPagination() {
    const pages = Math.ceil(salesState.total / salesState.pageSize);
    if (pages <= 1) return;
    const pageNumbers = new Set([1, pages, salesState.page - 1, salesState.page, salesState.page + 1]);
    const validPages = [...pageNumbers].filter(page => page >= 1 && page <= pages).sort((a, b) => a - b);
    let buttons = `<span>第 ${salesState.page} / ${pages} 页</span>`;
    buttons += `<button type="button" ${salesState.page === 1 ? 'disabled' : ''} onclick="goSalesPage(${salesState.page - 1})">上一页</button>`;
    let previous = 0;
    validPages.forEach(page => {
        if (previous && page - previous > 1) buttons += '<i>…</i>';
        buttons += `<button type="button" class="${page === salesState.page ? 'active' : ''}" onclick="goSalesPage(${page})">${page}</button>`;
        previous = page;
    });
    buttons += `<button type="button" ${salesState.page === pages ? 'disabled' : ''} onclick="goSalesPage(${salesState.page + 1})">下一页</button>`;
    salesEls.pagination.innerHTML = buttons;
}

function goSalesPage(page) {
    const pages = Math.ceil(salesState.total / salesState.pageSize);
    if (page < 1 || page > pages || page === salesState.page) return;
    salesState.page = page;
    loadSalesProducts();
    document.querySelector('.sales-result-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function setSalesView(view) {
    salesState.view = view === 'list' ? 'list' : 'grid';
    document.body.classList.toggle('sales-list-view', salesState.view === 'list');
    salesEls.gridButton.classList.toggle('active', salesState.view === 'grid');
    salesEls.listButton.classList.toggle('active', salesState.view === 'list');
    localStorage.setItem('sales_view', salesState.view);
}

let salesImageGallery = { images: [], index: 0 };
// 大图预览缩放状态：scale=1 时不拖拽，位移只在放大后生效
let salesImageZoom = { scale: 1, x: 0, y: 0 };
let salesImageDrag = null;
const SALES_IMAGE_MAX_SCALE = 4;

function _applySalesImageZoom() {
    const img = salesEls.previewImage;
    if (!img) return;
    const { scale, x, y } = salesImageZoom;
    img.style.transform = scale === 1 ? '' : `translate(${x}px, ${y}px) scale(${scale})`;
    img.classList.toggle('is-zoomed', scale > 1);
    const value = document.getElementById('salesImageZoomValue');
    if (value) value.textContent = `${Math.round(scale * 100)}%`;
}

function resetSalesImageZoom() {
    salesImageZoom = { scale: 1, x: 0, y: 0 };
    salesImageDrag = null;
    _applySalesImageZoom();
}

function _setSalesImageScale(next) {
    const scale = Math.min(SALES_IMAGE_MAX_SCALE, Math.max(1, next));
    // 缩回原始比例时位移一并归零，避免图片停在偏移位置
    salesImageZoom = scale === 1
        ? { scale: 1, x: 0, y: 0 }
        : { scale, x: salesImageZoom.x, y: salesImageZoom.y };
    _applySalesImageZoom();
}

function zoomSalesImage(direction) {
    _setSalesImageScale(salesImageZoom.scale * (direction > 0 ? 1.25 : 0.8));
}

function toggleSalesImageZoom() {
    if (salesImageZoom.scale > 1) resetSalesImageZoom();
    else _setSalesImageScale(2);
}

function openSalesImagePreview(imageUrl) {
    const images = Array.isArray(imageUrl) ? imageUrl : [imageUrl];
    salesImageGallery = { images, index: 0 };
    _renderSalesImageGallery();
    salesEls.imageOverlay.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function _renderSalesImageGallery() {
    const { images, index } = salesImageGallery;
    salesEls.previewImage.src = safeSalesImage(images[index]);
    // 切图后回到原始比例，不要带着上一张的缩放
    resetSalesImageZoom();
    const counter = salesEls.imageCounter;
    if (counter) counter.textContent = images.length > 1 ? `${index + 1} / ${images.length}` : '';
    const prevBtn = salesEls.galleryPrev;
    const nextBtn = salesEls.galleryNext;
    if (prevBtn) prevBtn.style.visibility = images.length > 1 && index > 0 ? 'visible' : 'hidden';
    if (nextBtn) nextBtn.style.visibility = images.length > 1 && index < images.length - 1 ? 'visible' : 'hidden';
}

function salesImageGalleryPrev() {
    if (salesImageGallery.index > 0) {
        salesImageGallery.index--;
        _renderSalesImageGallery();
    }
}

function salesImageGalleryNext() {
    if (salesImageGallery.index < salesImageGallery.images.length - 1) {
        salesImageGallery.index++;
        _renderSalesImageGallery();
    }
}

function closeSalesImagePreview() {
    salesEls.imageOverlay.classList.remove('show');
    salesEls.previewImage.src = '';
    salesImageGallery = { images: [], index: 0 };
    resetSalesImageZoom();
    document.body.style.overflow = '';
}

function bindSalesEvents() {
    // 大图预览：滚轮/双击缩放，放大后可按住拖拽移动
    const previewImg = salesEls.previewImage;
    if (previewImg) {
        previewImg.addEventListener('dblclick', event => {
            event.preventDefault();
            toggleSalesImageZoom();
        });
        previewImg.addEventListener('wheel', event => {
            event.preventDefault();
            _setSalesImageScale(salesImageZoom.scale * (event.deltaY < 0 ? 1.15 : 0.87));
        }, { passive: false });
        previewImg.addEventListener('mousedown', event => {
            if (salesImageZoom.scale <= 1) return;
            event.preventDefault();
            salesImageDrag = {
                startX: event.clientX,
                startY: event.clientY,
                originX: salesImageZoom.x,
                originY: salesImageZoom.y,
            };
            previewImg.classList.add('is-dragging');
        });
        window.addEventListener('mousemove', event => {
            if (!salesImageDrag) return;
            salesImageZoom.x = salesImageDrag.originX + (event.clientX - salesImageDrag.startX);
            salesImageZoom.y = salesImageDrag.originY + (event.clientY - salesImageDrag.startY);
            _applySalesImageZoom();
        });
        window.addEventListener('mouseup', () => {
            if (!salesImageDrag) return;
            salesImageDrag = null;
            previewImg.classList.remove('is-dragging');
        });
    }

    salesEls.form.addEventListener('submit', event => {
        event.preventDefault();
        salesState.keyword = salesEls.input.value.trim();
        salesState.page = 1;
        loadSalesProducts();
    });
    document.querySelectorAll('.sort-button').forEach(button => {
        button.addEventListener('click', () => {
            if (salesState.sort === button.dataset.sort) return;
            salesState.sort = button.dataset.sort;
            salesState.page = 1;
            document.querySelectorAll('.sort-button').forEach(item => item.classList.toggle('active', item === button));
            loadSalesProducts();
        });
    });
    salesEls.gridButton.addEventListener('click', () => setSalesView('grid'));
    salesEls.listButton.addEventListener('click', () => setSalesView('list'));
    document.getElementById('salesFeedbackOpenButton').addEventListener('click', openSalesFeedback);
    document.getElementById('salesFeedbackCloseButton').addEventListener('click', closeSalesFeedback);
    salesEls.feedbackDescription.addEventListener('input', () => {
        salesEls.feedbackDescriptionCount.textContent = String(salesEls.feedbackDescription.value.length);
        if (salesEls.feedbackDescription.value.trim()) {
            salesEls.feedbackDescriptionError.textContent = '';
            salesEls.feedbackDescription.classList.remove('invalid');
        }
    });
    salesEls.feedbackForm.querySelectorAll('input[name="salesFeedbackProblem"]').forEach(input => {
        input.addEventListener('change', () => {
            if (salesEls.feedbackForm.querySelector('input[name="salesFeedbackProblem"]:checked')) {
                salesEls.feedbackTypeError.textContent = '';
            }
        });
    });
    salesEls.feedbackForm.addEventListener('submit', submitSalesFeedback);
    // 缺规格时走询价单：来源采购，规格组合当型号传过去，配件库图片一起带
    document.getElementById('salesDetailSpecCreate')?.addEventListener('click', () => {
        if (!activeSalesDetailItem) return;
        openInquiry(activeSalesDetailItem, {
            specText: selectedSpecValues().join('/'),
            goodsSource: '采购',
            missSpec: true,
        });
    });
    // 询价流程的弹窗叠在详情页上层，ESC 一次只关最上面那层，不能连详情页一起关
    const inquiryOverlaySelector = [
        '#salesInquiryClientOverlay.show',
        '#salesInquiryOverlay.show',
        '.sales-inquiry-overlay.address.show',
        '.inquiry-viewer.show',
    ].join(',');
    document.addEventListener('keydown', event => {
        if (salesEls.feedbackOverlay.classList.contains('show')) return;
        if (salesEls.imageOverlay.classList.contains('show')) {
            if (event.key === 'Escape') closeSalesImagePreview();
            else if (event.key === 'ArrowLeft') salesImageGalleryPrev();
            else if (event.key === 'ArrowRight') salesImageGalleryNext();
            return;
        }
        if (event.key !== 'Escape') return;
        if (document.querySelector(inquiryOverlaySelector)) return;
        if (salesEls.detailOverlay.classList.contains('show')) {
            closeSalesProductDetail();
        }
    });
}

bindSalesEvents();
setSalesView(salesState.view);
loadSalesProducts();
