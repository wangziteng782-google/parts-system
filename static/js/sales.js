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
    pagination: document.getElementById('salesPagination'),
    gridButton: document.getElementById('salesGridButton'),
    listButton: document.getElementById('salesListButton'),
    imageOverlay: document.getElementById('salesImageOverlay'),
    previewImage: document.getElementById('salesPreviewImage'),
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

    salesEls.empty.hidden = salesState.items.length > 0;
    if (!salesState.items.length) return;
    salesEls.grid.innerHTML = salesState.items.map(renderSalesCard).join('');
    salesEls.list.innerHTML = salesState.items.map(renderSalesListRow).join('');
    salesEls.list.querySelectorAll('[data-sales-preview-image]').forEach(button => {
        button.addEventListener('click', () => openSalesImagePreview(button.dataset.salesPreviewImage));
    });
    document.querySelectorAll('[data-sales-detail-index]').forEach(button => {
        button.addEventListener('click', () => openSalesProductDetail(Number(button.dataset.salesDetailIndex)));
    });
    document.querySelectorAll('[data-sales-ai-index]').forEach(button => {
        button.addEventListener('click', () => toggleSalesAiExplain(Number(button.dataset.salesAiIndex)));
    });
    document.querySelectorAll('[data-sales-compare-index]').forEach(button => {
        button.addEventListener('click', () => toggleSalesCompare(Number(button.dataset.salesCompareIndex)));
    });
    document.querySelectorAll('[data-sales-substitute-index]').forEach(button => {
        button.addEventListener('click', () => openSalesAiSubstitute(Number(button.dataset.salesSubstituteIndex)));
    });
    refreshSalesCompareUI();
    renderSalesPagination();
}

function renderSalesCard(item, index) {
    const image = escapeSalesHtml(safeSalesImage(item.image));
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    return `
        <article class="goods-card">
            <div class="goods-picture">
                <img src="${image}" alt="${escapeSalesHtml(salesText(item.product_name, '商品图片'))}"
                     loading="lazy" onerror="this.src='/static/img/site-logo.png';this.onerror=null">
            </div>
            <div class="goods-body">
                <span class="source-badge ${source}">${sourceLabel}</span>
                ${item.modification_completed ? '<span class="sales-completed-badge">已完成</span>' : ''}
                ${formatSalesPrice(item.display_price_min ?? item.display_price, false, item.display_price_max)}
                <div class="goods-name" title="${escapeSalesHtml(item.product_name)}">${escapeSalesHtml(salesText(item.product_name))}</div>
                <div class="goods-meta">
                    <div><label>品牌</label><span>${escapeSalesHtml(salesText(item.product_brand))}</span></div>
                    <div><label>型号</label><span title="${escapeSalesHtml(item.model)}">${escapeSalesHtml(salesText(item.model))}</span></div>
                    <div><label>更新</label><span>${escapeSalesHtml(formatSalesDate(item.quote_updated_at))}</span></div>
                </div>
                <div class="goods-actions">
                    <button class="sales-card-detail-button" type="button" data-sales-detail-index="${index}">查看详情</button>
                    <button class="sales-compare-button" type="button" data-sales-compare-index="${index}">对比</button>
                    <button class="sales-ai-button" type="button" data-sales-ai-index="${index}">
                        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2L2 7v10l10 5 10-5V7L12 2zm0 2.2L19.5 8 12 11.8 4.5 8 12 4.2zM4 9.8l7 3.5v7.4l-7-3.5V9.8zm9 10.9v-7.4l7-3.5v7.4l-7 3.5z"/></svg>
                        AI讲解
                    </button>
                    <button class="sales-ai-button" type="button" data-sales-substitute-index="${index}">AI替代</button>
                </div>
            </div>
            <div class="sales-ai-panel" id="salesAiPanel-${index}" hidden></div>
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
    const summary = item.invoice_quote_summary || {};
    const main = item.part_price_summary || {};
    const special = summary.has_variant_quotes
        ? salesPriceRangeText(summary.special_min, summary.special_max)
            || (summary.special_available ? '可开专票' : '')
        : (main.purchase_special_invoice_available
            ? '可开专票' : detailAmountText(main.purchase_special_invoice));
    const general = summary.has_variant_quotes
        ? salesPriceRangeText(summary.general_min, summary.general_max)
            || (summary.general_available ? '可开普票' : '')
        : (main.purchase_general_invoice_available
            ? '可开普票' : detailAmountText(main.purchase_general_invoice));
    return [['含专票', special], ['含普票', general]]
        .filter(([, value]) => detailValue(value))
        .map(([label, value]) => `<div><label>${label}</label><span>${escapeSalesHtml(value)}</span></div>`)
        .join('');
}

function renderInquiryQuoteInfo(item) {
    if (item.record_source !== 'inquiry') return '';
    return [
        ['报价类型', quotationTypeText(item.quotation_type)],
        ['无税运费报价', detailAmountText(item.post_fee_purchase)],
        ['含税运费报价', detailAmountText(item.post_fee_has_tax_purchase)],
    ].filter(([, value]) => detailValue(value))
        .map(([label, value]) => `<div><label>${label}</label><span>${escapeSalesHtml(value)}</span></div>`)
        .join('');
}

function renderSalesListRow(item, index) {
    const image = escapeSalesHtml(safeSalesImage(item.image));
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    return `<tr>
        <td><div class="list-product"><button class="list-image-button" type="button" data-sales-preview-image="${image}" title="点击查看大图"><img src="${image}" alt="商品图片" loading="lazy" onerror="this.src='/static/img/site-logo.png';this.onerror=null"></button><div><strong>${escapeSalesHtml(salesText(item.product_name))}</strong><span class="source-badge ${source}">${sourceLabel}</span></div></div></td>
        <td>${escapeSalesHtml(salesText(item.product_brand))}</td>
        <td>${escapeSalesHtml(salesText(item.model))}</td>
        <td class="list-specification" title="${escapeSalesHtml(salesText(item.specification))}">${escapeSalesHtml(salesText(item.specification))}</td>
        <td>${formatSalesPrice(item.display_price_min ?? item.display_price, true, item.display_price_max)}</td>
        <td><div class="sales-list-extra">${renderPartsInvoiceInfo(item)}</div></td>
        <td><div class="sales-list-extra">${renderInquiryQuoteInfo(item)}</div></td>
        <td>${escapeSalesHtml(formatSalesDate(item.quote_updated_at))}</td>
        <td>${item.modification_completed ? '<span class="sales-completed-badge">已完成</span>' : ''}</td>
        <td><div class="list-actions"><button class="sales-detail-button" type="button" data-sales-detail-index="${index}">详情</button><button class="sales-compare-button" type="button" data-sales-compare-index="${index}">对比</button><button class="sales-ai-button" type="button" data-sales-ai-index="${index}">AI讲解</button><button class="sales-ai-button" type="button" data-sales-substitute-index="${index}">AI替代</button></div></td>
    </tr>
    <tr class="sales-ai-list-row" id="salesAiListRow-${index}" hidden><td colspan="10"><div class="sales-ai-panel-content" id="salesAiListPanel-${index}"></div></td></tr>`;
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

function variantDetailValue(quote, field, fallback) {
    return quote && detailValue(quote[field]) ? quote[field] : fallback;
}

function renderSalesDetailInfo(item, source, sourceLabel, quote = null) {
    const fields = source === 'parts'
        ? [
            ['商品品牌：', item.product_brand],
            ['产品分类：', item.product_type],
            ['产品性质：', item.nature],
            ['质保期限：', variantDetailValue(quote, 'warranty_time', item.warranty)],
            ['适用电梯品牌：', item.applicable_elevator_brand],
            ['替代型号：', item.substitute_model],
            ['发货地：', variantDetailValue(quote, 'shipping_origin', item.shipping_origin)],
            ['发货时间：', variantDetailValue(quote, 'shipping_time', item.shipping_time)],
            ['报价有效期：', variantDetailValue(quote, 'expire_date', item.quote_validity)],
            ['每日截单时间：', variantDetailValue(quote, 'daily_order_time', item.daily_cutoff_time)],
            ['报价时间：', quote?.quote_time],
            ['采购运费：', quote ? detailAmountText(quote.purchase_shipping) : ''],
            ['更新人：', item.updater || item.filler],
            ['更新时间：', quote?.update_time ? formatSalesDate(quote.update_time) : (item.quote_updated_at ? formatSalesDate(item.quote_updated_at) : '')],
            ['运费备注：', quote?.freight_remark, 'wide'],
            ['规格报价备注：', quote?.quote_remark, 'wide'],
            ['注意事项：', item.precautions, 'full'],
            ['技术参数：', item.technical_params, 'full'],
            ['商品备注：', item.remark, 'wide'],
            ['补充备注：', item.remark_2, 'wide'],
            ['数据来源：', sourceLabel],
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
    salesEls.detailInfoTitle.textContent = source === 'parts' ? '配件库信息' : '询价信息';
    salesEls.detailInfoGrid.innerHTML = visibleFields.map(([label, value, width = '']) => `
        <div class="${width ? `sales-detail-${width}` : ''}">
            <label>${escapeSalesHtml(label)}</label>
            <span>${escapeSalesHtml(value)}</span>
        </div>`).join('');
}

function setSalesDetailText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value ?? '').trim();
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

async function loadSalesCommunications(orderGoodsId) {
    activeSalesDetailOrderGoodsId = orderGoodsId;
    salesEls.detailChatCount.textContent = '加载中';
    salesEls.detailChatBody.innerHTML = '<tr><td colspan="6" class="sales-detail-empty">正在加载沟通记录...</td></tr>';
    try {
        const data = await salesRequest(`/api/sales/inquiry-communications?order_goods_id=${encodeURIComponent(orderGoodsId)}`);
        if (activeSalesDetailOrderGoodsId !== orderGoodsId) return;
        const items = data.items || [];
        salesEls.detailChatCount.textContent = `${items.length} 条`;
        salesEls.detailChatBody.innerHTML = renderSalesCommunicationRows(items);
    } catch (error) {
        if (activeSalesDetailOrderGoodsId !== orderGoodsId) return;
        salesEls.detailChatCount.textContent = '加载失败';
        salesEls.detailChatBody.innerHTML = `<tr><td colspan="6" class="sales-detail-empty">${escapeSalesHtml(error.message)}</td></tr>`;
    }
}

function invoicePriceText(price, available, availableText) {
    if (detailValue(price)) return detailAmountText(price);
    return available ? availableText : '';
}

function renderSalesVariantPrices(items) {
    const showActions = items.length > 1;
    const rows = items.map((item, index) => `<tr data-variant-index="${index}">
        <td>${escapeSalesHtml(detailValue(item.specification))}</td>
        <td class="sales-detail-variant-price">${escapeSalesHtml(detailAmountText(item.no_tax_price))}</td>
        <td class="sales-detail-variant-price">${escapeSalesHtml(invoicePriceText(item.special_invoice_price, item.special_invoice_available, '可开专票'))}</td>
        <td class="sales-detail-variant-price">${escapeSalesHtml(invoicePriceText(item.general_invoice_price, item.general_invoice_available, '可开普票'))}</td>
        ${showActions ? `<td><button type="button" class="sales-variant-select" onclick="selectSalesVariantQuote(${index})">查看</button></td>` : ''}
    </tr>`).join('');
    return `<div class="sales-detail-variant-table-wrap"><table>
        <thead><tr><th>规格组合</th><th>不含票单价</th><th>含专票</th><th>含普票</th>${showActions ? '<th>操作</th>' : ''}</tr></thead>
        <tbody>${rows}</tbody>
    </table></div>`;
}

function selectSalesVariantQuote(index) {
    const quote = activeSalesVariantQuotes[index];
    if (!quote || !activeSalesDetailItem) return;
    document.querySelectorAll('.sales-detail-variant-table-wrap tbody tr').forEach((row, rowIndex) => {
        row.classList.toggle('selected', rowIndex === index);
        const button = row.querySelector('.sales-variant-select');
        if (button) button.textContent = rowIndex === index ? '已选择' : '查看';
    });
    const price = quote.no_tax_price || quote.special_invoice_price || quote.general_invoice_price;
    setSalesDetailText('salesDetailSpecification', detailValue(quote.specification));
    setSalesDetailText('salesDetailPrice', detailPriceText(price) || '价格待定');
    renderSalesDetailInfo(activeSalesDetailItem, 'parts', '来自配件库', quote);
}

function renderSalesPartsMainPrices(summary = {}) {
    const specialInvoice = summary.purchase_special_invoice_available
        ? '可开专票'
        : detailAmountText(summary.purchase_special_invoice);
    const generalInvoice = summary.purchase_general_invoice_available
        ? '可开普票'
        : detailAmountText(summary.purchase_general_invoice);
    const fields = [
        ['进项专票', specialInvoice],
        ['进项普票', generalInvoice],
        ['采购运费', detailAmountText(summary.purchase_shipping)],
    ];
    return `<div class="sales-detail-main-price-grid">${fields.map(([label, value]) => `
        <div><label>${label}</label><strong>${escapeSalesHtml(value)}</strong></div>
    `).join('')}</div>`;
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
        if (items.length) {
            salesEls.detailPartsPriceContent.innerHTML = renderSalesVariantPrices(items);
            selectSalesVariantQuote(0);
        } else {
            activeSalesVariantQuotes = [];
            salesEls.detailPartsPriceContent.innerHTML = renderSalesPartsMainPrices(item.part_price_summary);
        }
    } catch (error) {
        if (activeSalesDetailPartId !== partId) return;
        salesEls.detailPriceMultiplier.textContent = '加载失败';
        salesEls.detailPartsPriceContent.innerHTML = `<div class="sales-detail-price-loading">${escapeSalesHtml(error.message)}</div>`;
    }
}

function openSalesProductDetail(index) {
    const item = salesState.items[index];
    if (!item) return;
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    activeSalesDetailItem = item;
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    const detailModal = document.getElementById('salesDetailModal');
    detailModal.classList.toggle('inquiry-detail', source === 'inquiry');
    detailModal.classList.toggle('parts-detail', source === 'parts');
    const sourceBadge = document.getElementById('salesDetailSource');
    sourceBadge.textContent = sourceLabel;
    sourceBadge.className = `source-badge ${source}`;
    setSalesDetailText('salesDetailTitle', source === 'inquiry' ? '询价商品详情' : '配件商品详情');
    setSalesDetailText('salesDetailName', item.product_name);
    setSalesDetailText('salesDetailModel', salesText(item.model));
    setSalesDetailText('salesDetailSpecification', salesText(item.specification));
    setSalesDetailText('salesDetailPrice', detailPriceText(item.display_price) || '价格待完善');
    setSalesDetailText(
        'salesDetailQuotationType',
        source === 'inquiry' ? quotationTypeText(item.quotation_type) : '',
    );
    setSalesDetailText(
        'salesDetailPurchasePrice',
        source === 'inquiry' ? detailAmountText(item.purchase_price) : '',
    );
    setSalesDetailText(
        'salesDetailPostFeePurchase',
        source === 'inquiry' ? detailAmountText(item.post_fee_purchase) : '',
    );
    setSalesDetailText(
        'salesDetailPostFeeHasTaxPurchase',
        source === 'inquiry' ? detailAmountText(item.post_fee_has_tax_purchase) : '',
    );
    renderSalesDetailInfo(item, source, sourceLabel);
    document.getElementById('salesDetailImage').src = safeSalesImage(item.image);
    const orderGoodsId = Number(item.order_goods_id);
    const showCommunications = source === 'inquiry' && Number.isInteger(orderGoodsId) && orderGoodsId > 0;
    salesEls.detailChat.hidden = !showCommunications;
    activeSalesDetailOrderGoodsId = showCommunications ? orderGoodsId : null;
    if (showCommunications) loadSalesCommunications(orderGoodsId);
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
    salesEls.detailOverlay.classList.remove('show');
    salesEls.detailOverlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

// ===================== AI 讲解 =====================

const salesAiState = {};

function toggleSalesAiExplain(index) {
    const item = salesState.items[index];
    if (!item) return;
    const gridPanel = document.getElementById(`salesAiPanel-${index}`);
    const listRow = document.getElementById(`salesAiListRow-${index}`);
    const isGrid = gridPanel && !gridPanel.hidden;
    const isList = listRow && !listRow.hidden;
    if (isGrid) {
        gridPanel.hidden = true;
        return;
    }
    if (isList) {
        listRow.hidden = true;
        return;
    }
    const target = gridPanel || (listRow ? document.getElementById(`salesAiListPanel-${index}`) : null);
    if (!target) return;
    if (gridPanel) gridPanel.hidden = false;
    if (listRow) listRow.hidden = false;
    if (salesAiState[index]) {
        target.innerHTML = salesAiState[index];
        return;
    }
    fetchSalesAiExplain(index, item, target);
}

async function fetchSalesAiExplain(index, item, container) {
    const body = {
        product_name: item.product_name || '',
        model: item.model || null,
        product_brand: item.product_brand || null,
        specification: item.specification || null,
        product_type: item.product_type || null,
        nature: item.nature || null,
        display_price: item.display_price || null,
        warranty: item.warranty || null,
        shipping_origin: item.shipping_origin || null,
        shipping_time: item.shipping_time || null,
        precautions: item.precautions || null,
        technical_params: item.technical_params || null,
        remark: item.remark || null,
        substitute_model: item.substitute_model || null,
        applicable_elevator_brand: item.applicable_elevator_brand || null,
        record_source: item.record_source || null,
    };
    const labels = ['安装位置', '产品特点', '销售话术'];
    await streamAiRequest('/api/sales/ai-explain', body, container, labels, (content) => {
        salesAiState[index] = `<div class="sales-ai-content">${renderAiSections(content, labels)}</div>`;
    });
}

// ===================== AI 产品对比 =====================

const salesCompareState = { items: [] };

function compareItemKey(item) {
    return `${item.record_source || 'parts'}:${item.id ?? ''}`;
}

function isItemCompared(item) {
    return salesCompareState.items.some(c => c.key === compareItemKey(item));
}

function toggleSalesCompare(index) {
    const item = salesState.items[index];
    if (!item) return;
    const key = compareItemKey(item);
    const existing = salesCompareState.items.findIndex(c => c.key === key);
    if (existing >= 0) {
        salesCompareState.items.splice(existing, 1);
    } else {
        if (salesCompareState.items.length >= 2) {
            showSalesToast('最多选择两个商品进行对比', 'error');
            return;
        }
        salesCompareState.items.push({ key, item });
    }
    refreshSalesCompareUI();
}

function refreshSalesCompareUI() {
    document.querySelectorAll('[data-sales-compare-index]').forEach(button => {
        const item = salesState.items[Number(button.dataset.salesCompareIndex)];
        const active = item && isItemCompared(item);
        button.classList.toggle('active', active);
        button.textContent = active ? '已选对比' : '对比';
    });
    renderSalesCompareBar();
}

function renderSalesCompareBar() {
    const bar = document.getElementById('salesCompareBar');
    const names = document.getElementById('salesCompareNames');
    const countEl = document.getElementById('salesCompareCount');
    const go = document.getElementById('salesCompareGo');
    if (!bar || !names || !countEl || !go) return;
    const count = salesCompareState.items.length;
    if (count === 0) {
        bar.classList.remove('show');
        return;
    }
    bar.classList.add('show');
    countEl.textContent = count;
    names.innerHTML = salesCompareState.items
        .map(c => `<span class="compare-chip">${escapeSalesHtml(salesText(c.item.product_name, '未命名商品'))}</span>`)
        .join('<span class="compare-vs">vs</span>');
    go.disabled = count < 2;
}

function clearSalesCompare() {
    salesCompareState.items = [];
    refreshSalesCompareUI();
}

function comparePayload(item) {
    return {
        product_name: item.product_name || '',
        model: item.model || null,
        product_brand: item.product_brand || null,
        specification: item.specification || null,
        product_type: item.product_type || null,
        nature: item.nature || null,
        display_price: item.display_price || null,
        warranty: item.warranty || null,
        shipping_origin: item.shipping_origin || null,
        shipping_time: item.shipping_time || null,
        precautions: item.precautions || null,
        technical_params: item.technical_params || null,
        remark: item.remark || null,
        substitute_model: item.substitute_model || null,
        applicable_elevator_brand: item.applicable_elevator_brand || null,
        record_source: item.record_source || null,
    };
}

function openSalesCompare() {
    const overlay = document.getElementById('salesCompareOverlay');
    if (!overlay || salesCompareState.items.length < 2) {
        showSalesToast('请选择两个商品进行对比', 'error');
        return;
    }
    const [a, b] = salesCompareState.items;
    document.getElementById('salesCompareNameA').textContent = salesText(a.item.product_name, '产品A');
    document.getElementById('salesCompareNameB').textContent = salesText(b.item.product_name, '产品B');
    document.getElementById('salesCompareBody').innerHTML = '';
    overlay.classList.add('show');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    runSalesAiCompare();
}

function closeSalesCompare() {
    const overlay = document.getElementById('salesCompareOverlay');
    if (!overlay) return;
    overlay.classList.remove('show');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

async function runSalesAiCompare() {
    const [a, b] = salesCompareState.items;
    const body = document.getElementById('salesCompareBody');
    if (!body || !a || !b) return;
    await streamAiRequest(
        '/api/sales/ai-compare',
        { product_a: comparePayload(a.item), product_b: comparePayload(b.item) },
        body,
        ['差异对比', '各自优势', '推荐建议'],
    );
}

function renderAiSections(text, labels) {
    let html = escapeSalesHtml(text).replace(/\*\*/g, '');
    labels.forEach((label, i) => {
        const re = new RegExp(`^${label}[:：]?\\s*`, 'gm');
        html = html.replace(re, `${i === 0 ? '' : '</div>'}<div class="ai-section"><span class="ai-section-label">${label}：</span>`);
    });
    html += '</div>';
    return html.replace(/\n/g, '<br>');
}

function aiLoadingHtml(initialText) {
    return `
        <div class="sales-ai-loading">
            <div class="ai-loading-header">
                <span class="ai-loading-icon">AI</span>
                <span class="ai-loading-text ai-stage-text">${escapeSalesHtml(initialText)}</span>
            </div>
            <div class="ai-progress-bar"><div class="ai-progress-fill ai-stream-fill"></div></div>
        </div>`;
}

async function streamAiRequest(url, payload, container, labels, afterDone) {
    container.innerHTML = aiLoadingHtml('正在连接 AI...');
    const setStage = (pct, text) => {
        const fill = container.querySelector('.ai-stream-fill');
        const txt = container.querySelector('.ai-stage-text');
        if (fill) fill.style.width = pct + '%';
        if (txt) txt.textContent = text;
    };
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'same-origin',
        });
        if (!response.ok) {
            let message = '请求失败，请稍后重试';
            try { const err = await response.json(); message = err.detail || message; } catch (_) {}
            throw new Error(message);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finished = false;
        let resultContent = '';
        while (!finished) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let idx;
            while ((idx = buffer.indexOf('\n\n')) !== -1) {
                const chunk = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                let event = 'message';
                let data = '';
                for (const line of chunk.split('\n')) {
                    if (line.startsWith('event:')) event = line.slice(6).trim();
                    else if (line.startsWith('data:')) data += line.slice(5).trim();
                }
                if (!data) continue;
                let parsed;
                try { parsed = JSON.parse(data); } catch (_) { continue; }
                if (event === 'stage') {
                    if (parsed.stage === 'reasoning') setStage(55, 'AI 思考中...');
                    else if (parsed.stage === 'content') setStage(85, '正在生成回答...');
                } else if (event === 'done') {
                    finished = true;
                    resultContent = parsed.content || '';
                } else if (event === 'error') {
                    throw new Error(parsed.detail || 'AI生成失败，请稍后重试');
                }
            }
        }
        if (!finished) throw new Error('AI 响应中断，请重试');
        setStage(100, '完成');
        container.innerHTML = `<div class="sales-ai-content">${renderAiSections(resultContent, labels)}</div>`;
        if (afterDone) afterDone(resultContent);
    } catch (error) {
        container.innerHTML = `<div class="sales-ai-error">${escapeSalesHtml(error.message)}</div>`;
    }
}

// ===================== 通用 AI 工具弹窗 =====================

function showSalesAiTool(title) {
    const overlay = document.getElementById('salesAiToolOverlay');
    if (!overlay) return;
    document.getElementById('salesAiToolTitle').textContent = title;
    document.getElementById('salesAiToolBody').innerHTML = '';
    overlay.classList.add('show');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
}

function closeSalesAiTool() {
    const overlay = document.getElementById('salesAiToolOverlay');
    if (!overlay) return;
    overlay.classList.remove('show');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
}

async function runAiTool(body, url, payload, labels) {
    await streamAiRequest(url, payload, body, labels);
}

// ===================== AI 替代型号 =====================

function openSalesAiSubstitute(index) {
    const item = salesState.items[index];
    if (!item) return;
    showSalesAiTool(`AI 替代型号 · ${salesText(item.product_name, '商品')}`);
    const body = document.getElementById('salesAiToolBody');
    runAiTool(body, '/api/sales/ai-substitute', substitutePayload(item), ['替代型号', '替代理由']);
}

function substitutePayload(item) {
    return {
        product_name: item.product_name || '',
        model: item.model || null,
        product_brand: item.product_brand || null,
        specification: item.specification || null,
        product_type: item.product_type || null,
        applicable_elevator_brand: item.applicable_elevator_brand || null,
        technical_params: item.technical_params || null,
        substitute_model: item.substitute_model || null,
    };
}

// ===================== AI 询价匹配 =====================

function openSalesAiMatch() {
    showSalesAiTool('AI 需求识别');
    const body = document.getElementById('salesAiToolBody');
    body.innerHTML = `
        <div class="ai-match-input-wrap">
            <textarea id="salesAiMatchInput" class="ai-match-input" maxlength="500"
                placeholder="粘贴客户需求描述，例如：&#10;三菱门机变频器，要全新的，现货"></textarea>
            <div class="ai-match-hint"><span id="salesAiMatchCount">0</span>/500</div>
        </div>
        <div class="ai-match-actions">
            <button type="button" class="compare-go" id="salesAiMatchGo">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2L2 7v10l10 5 10-5V7L12 2z"/></svg>
                智能识别
            </button>
        </div>`;
    const input = document.getElementById('salesAiMatchInput');
    const countEl = document.getElementById('salesAiMatchCount');
    const go = document.getElementById('salesAiMatchGo');
    input.addEventListener('input', () => {
        countEl.textContent = String(input.value.length);
    });
    go.addEventListener('click', () => runSalesAiMatch());
    input.focus();
}

async function runSalesAiMatch() {
    const input = document.getElementById('salesAiMatchInput');
    const body = document.getElementById('salesAiToolBody');
    if (!input || !body) return;
    const text = input.value.trim();
    if (!text) {
        showSalesToast('请先粘贴需求描述', 'error');
        return;
    }
    const labels = ['搜索关键词', '品牌', '型号', '品类'];
    await streamAiRequest('/api/sales/ai-match', { text }, body, labels, (content) => {
        const keyword = extractMatchKeyword(content);
        if (!keyword) return;
        body.insertAdjacentHTML('beforeend', `
            <div class="ai-match-actions">
                <button type="button" class="compare-go" id="salesAiMatchSearch">用关键词搜索</button>
            </div>`);
        const searchBtn = document.getElementById('salesAiMatchSearch');
        if (searchBtn) {
            searchBtn.addEventListener('click', () => {
                closeSalesAiTool();
                salesEls.input.value = keyword;
                salesState.keyword = keyword;
                salesState.page = 1;
                loadSalesProducts();
            });
        }
    });
}

function extractMatchKeyword(content) {
    const m = content.match(/搜索关键词[:：]\s*([^\n]+)/);
    if (!m) return '';
    const kw = m[1].trim();
    return (kw && kw !== '无') ? kw : '';
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
        showSalesToast('反馈提交成功，感谢你的帮助');
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

function openSalesImagePreview(imageUrl) {
    salesEls.previewImage.src = safeSalesImage(imageUrl);
    salesEls.imageOverlay.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeSalesImagePreview() {
    salesEls.imageOverlay.classList.remove('show');
    salesEls.previewImage.src = '';
    document.body.style.overflow = '';
}

function bindSalesEvents() {
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
    const aiMatchButton = document.getElementById('salesAiMatchButton');
    if (aiMatchButton) aiMatchButton.addEventListener('click', openSalesAiMatch);
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
    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (salesEls.feedbackOverlay.classList.contains('show')) return;
        const compareOverlay = document.getElementById('salesCompareOverlay');
        const aiToolOverlay = document.getElementById('salesAiToolOverlay');
        if (salesEls.imageOverlay.classList.contains('show')) closeSalesImagePreview();
        else if (compareOverlay && compareOverlay.classList.contains('show')) closeSalesCompare();
        else if (aiToolOverlay && aiToolOverlay.classList.contains('show')) closeSalesAiTool();
        else if (salesEls.detailOverlay.classList.contains('show')) closeSalesProductDetail();
    });
}

bindSalesEvents();
setSalesView(salesState.view);
loadSalesProducts();
