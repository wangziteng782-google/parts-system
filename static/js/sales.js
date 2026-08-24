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
    renderSalesPagination();
}

function renderSalesCard(item, index) {
    const image = escapeSalesHtml(safeSalesImage(item.image));
    const isSubstitute = item.record_source_label === '替代品';
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    const badges = `<span class="source-badge ${source}">${sourceLabel}</span>${isSubstitute ? '<span class="source-badge substitute">替代品</span>' : ''}`;
    return `
        <article class="goods-card">
            <div class="goods-picture">
                <img src="${image}" alt="${escapeSalesHtml(salesText(item.product_name, '商品图片'))}"
                     loading="lazy" onerror="this.src='/static/img/site-logo.png';this.onerror=null">
            </div>
            <div class="goods-body">
                ${item.modification_completed ? '<span class="sales-completed-badge">已完成</span>' : ''}
                ${formatSalesPrice(item.display_price_min ?? item.display_price, false, item.display_price_max)}
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
    const isSubstitute = item.record_source_label === '替代品';
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    const badges = `<span class="source-badge ${source}">${sourceLabel}</span>${isSubstitute ? '<span class="source-badge substitute">替代品</span>' : ''}`;
    return `<tr>
        <td><div class="list-product"><button class="list-image-button" type="button" data-sales-preview-image="${image}" title="点击查看大图"><img src="${image}" alt="商品图片" loading="lazy" onerror="this.src='/static/img/site-logo.png';this.onerror=null"></button><div><strong>${escapeSalesHtml(salesText(item.product_name))}</strong>${badges}</div></div></td>
        <td>${escapeSalesHtml(salesText(item.product_brand))}</td>
        <td>${escapeSalesHtml(salesText(item.model))}</td>
        <td class="list-specification" title="${escapeSalesHtml(salesText(item.specification))}">${escapeSalesHtml(salesText(item.specification))}</td>
        <td>${formatSalesPrice(item.display_price_min ?? item.display_price, true, item.display_price_max)}</td>
        <td><div class="sales-list-extra">${renderPartsInvoiceInfo(item)}</div></td>
        <td><div class="sales-list-extra">${renderInquiryQuoteInfo(item)}</div></td>
        <td>${escapeSalesHtml(formatSalesDate(item.quote_updated_at))}</td>
        <td>${item.modification_completed ? '<span class="sales-completed-badge">已完成</span>' : ''}</td>
        <td><button class="sales-detail-button" type="button" data-sales-detail-index="${index}">详情</button></td>
    </tr>`;
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

function renderSalesVariantPrices(items) {
    const showActions = items.length > 1;
    const rows = items.map((item, index) => `<tr data-variant-index="${index}">
        <td>${escapeSalesHtml(detailValue(item.specification))}</td>
        <td class="sales-detail-variant-price">${escapeSalesHtml(detailAmountText(item.no_tax_price) || '—')}</td>
        <td class="sales-detail-variant-price">${escapeSalesHtml(detailAmountText(item.special_invoice_price) || '—')}</td>
        <td class="sales-detail-variant-price">${escapeSalesHtml(detailAmountText(item.general_invoice_price) || '—')}</td>
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
    const specialInvoice = detailAmountText(summary.purchase_special_invoice) || '—';
    const generalInvoice = detailAmountText(summary.purchase_general_invoice) || '—';
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
    const isSubstitute = item.record_source_label === '替代品';
    const source = item.record_source === 'inquiry' ? 'inquiry' : 'parts';
    const sourceLabel = source === 'inquiry' ? '来自询价记录' : '来自配件库';
    activeSalesDetailItem = item;
    const detailModal = document.getElementById('salesDetailModal');
    detailModal.classList.toggle('inquiry-detail', source === 'inquiry');
    detailModal.classList.toggle('parts-detail', source === 'parts');
    const sourceBadgeWrap = document.getElementById('salesDetailSource');
    sourceBadgeWrap.innerHTML = `<span class="source-badge ${source}">${sourceLabel}</span>${isSubstitute ? '<span class="source-badge substitute">替代品</span>' : ''}`;
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
        if (salesEls.imageOverlay.classList.contains('show')) closeSalesImagePreview();
        else if (salesEls.detailOverlay.classList.contains('show')) closeSalesProductDetail();
    });
}

bindSalesEvents();
setSalesView(salesState.view);
loadSalesProducts();
