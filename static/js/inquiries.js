(() => {
    const state = {page: 1, pageSize: 20, pages: 1, status: 'pending', loading: false};
    const el = {
        form: document.getElementById('inquiryFilterForm'),
        keyword: document.getElementById('inquiryKeyword'),
        body: document.getElementById('inquiryTableBody'),
        tableState: document.getElementById('inquiryTableState'),
        total: document.getElementById('inquiryTotal'),
        pageSize: document.getElementById('inquiryPageSize'),
        pageInfo: document.getElementById('inquiryPageInfo'),
        prev: document.getElementById('inquiryPrev'),
        next: document.getElementById('inquiryNext'),
        toast: document.getElementById('inquiryToast'),
    };

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    function text(value, fallback = '') {
        const result = String(value ?? '').trim();
        return result || fallback;
    }

    function money(value) {
        if (!text(value)) return '';
        const amount = Number(value);
        return Number.isFinite(amount)
            ? `¥${amount.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
            : text(value);
    }

    function time(value) {
        return text(value) ? text(value).replace('T', ' ').slice(0, 16) : '';
    }

    function quoteType(value) {
        const raw = text(value);
        if (raw === '0') return '无税报价';
        if (raw === '1') return '含税报价';
        return raw;
    }

    function image(value) {
        const url = text(value) || '/static/img/site-logo.png';
        return `<div class="product-thumb"><img src="${escapeHtml(url)}" alt="" onerror="this.parentElement.innerHTML='▧'"></div>`;
    }

    function showToast(message) {
        el.toast.textContent = message;
        el.toast.classList.add('show');
        window.setTimeout(() => el.toast.classList.remove('show'), 2200);
    }

    function setState(message, icon = '⌛') {
        el.tableState.innerHTML = `<div class="state-icon">${escapeHtml(icon)}</div><div>${escapeHtml(message)}</div>`;
        el.tableState.classList.remove('hidden');
    }

    function hideState() {
        el.tableState.classList.add('hidden');
    }

    function queryParams() {
        const params = new URLSearchParams({
            status: state.status,
            page: state.page,
            page_size: state.pageSize,
        });
        if (el.keyword.value.trim()) params.set('keyword', el.keyword.value.trim());
        return params;
    }

    function feedbackHtml(item) {
        const feedback = item.feedback;
        if (!feedback) return '<div class="inquiry-feedback-desc">暂无销售反馈</div>';
        const labels = feedback.issue_type_labels?.join('、') || '反馈';
        return `
            <div class="inquiry-feedback-title">[${escapeHtml(labels)}] ${escapeHtml(feedback.feedback_user_name || '')}</div>
            <div class="inquiry-feedback-desc" title="${escapeHtml(feedback.description)}">${escapeHtml(feedback.description)}</div>
            <div>反馈时间：${escapeHtml(time(feedback.created_at))}</div>
            <div>状态：${escapeHtml(feedback.status || '')}</div>
        `;
    }

    function rowActions(item) {
        const feedbackId = item.feedback?.id || '';
        const statusButton = Number(item.listing_status) === 0
            ? `<button class="inquiry-show" data-action="show" data-id="${item.inquiry_mission_id}" data-goods-id="${item.inquiry_goods_id || ''}" data-feedback-id="${feedbackId}">恢复上架</button>`
            : `<button class="inquiry-hide" data-action="hide" data-id="${item.inquiry_mission_id}" data-goods-id="${item.inquiry_goods_id || ''}" data-feedback-id="${feedbackId}">下架</button>`;
        const feedbackButtons = feedbackId && item.feedback?.status === 'pending' ? `
            <button class="inquiry-complete" data-action="complete" data-feedback-id="${feedbackId}">反馈完成</button>
            <button class="inquiry-ignore" data-action="ignore" data-feedback-id="${feedbackId}">忽略反馈</button>
        ` : '';
        return `<div class="inquiry-actions">${statusButton}${feedbackButtons}</div>`;
    }

    function renderRows(items) {
        if (!items.length) {
            el.body.innerHTML = '';
            setState('没有找到符合条件的询价记录', '◎');
            return;
        }
        hideState();
        el.body.innerHTML = items.map((item, index) => `
            <tr>
                <td class="seq-cell">${(state.page - 1) * state.pageSize + index + 1}</td>
                <td>${image(item.image)}</td>
                <td>
                    <div class="inquiry-product">
                        <strong>${escapeHtml(text(item.product_name, '未命名商品'))}</strong>
                        <span>型号：${escapeHtml(text(item.model))}</span>
                        <span>规格：${escapeHtml(text(item.specification))}</span>
                        <span>品牌：${escapeHtml(text(item.product_brand))}</span>
                    </div>
                </td>
                <td>
                    <div class="inquiry-quote">
                        <div>报价类型：${escapeHtml(quoteType(item.quotation_type))}</div>
                        <div>采购报价：<b>${escapeHtml(money(item.purchase_price))}</b></div>
                        <div>无税运费：${escapeHtml(money(item.post_fee_purchase))}</div>
                        <div>含税运费：${escapeHtml(money(item.post_fee_has_tax_purchase))}</div>
                    </div>
                </td>
                <td><div class="inquiry-feedback">${feedbackHtml(item)}</div></td>
                <td><span class="inquiry-status ${Number(item.listing_status) === 0 ? 'hidden' : 'listed'}">${Number(item.listing_status) === 0 ? '已下架' : '上架中'}</span></td>
                <td>${escapeHtml(time(item.listing_updated_at || item.quote_updated_at))}</td>
                <td>${rowActions(item)}</td>
            </tr>
        `).join('');
    }

    function renderStats(stats) {
        document.getElementById('statPending').textContent = stats.pending || 0;
        document.getElementById('statListed').textContent = stats.listed || 0;
        document.getElementById('statHidden').textContent = stats.hidden || 0;
        document.getElementById('statAll').textContent = stats.all || 0;
    }

    async function requestJson(url, options = {}) {
        const response = await fetch(url, {
            credentials: 'same-origin',
            ...options,
            headers: {'Content-Type': 'application/json', ...(options.headers || {})},
        });
        if (!response.ok) throw new Error((await response.json()).detail || '请求失败');
        return response.json();
    }

    async function loadInquiries() {
        if (state.loading) return;
        state.loading = true;
        setState('正在加载询价记录...');
        try {
            const data = await requestJson(`/api/inquiries?${queryParams()}`);
            state.page = data.page;
            state.pages = data.pages;
            renderRows(data.items || []);
            renderStats(data.stats || {});
            el.total.textContent = data.total || 0;
            el.pageInfo.textContent = `第 ${data.page} / ${data.pages} 页`;
            el.prev.disabled = data.page <= 1;
            el.next.disabled = data.page >= data.pages;
        } catch (error) {
            el.body.innerHTML = '';
            setState(error.message || '询价记录加载失败', '!');
            showToast(error.message || '询价记录加载失败');
        } finally {
            state.loading = false;
        }
    }

    async function updateListing(button, listingStatus) {
        const reason = listingStatus === 0 ? window.prompt('请输入下架原因', '') : window.prompt('请输入恢复原因，可为空', '');
        if (reason === null) return;
        button.disabled = true;
        try {
            const data = await requestJson(`/api/inquiries/${button.dataset.id}/listing-status`, {
                method: 'PATCH',
                body: JSON.stringify({
                    listing_status: listingStatus,
                    inquiry_goods_id: Number(button.dataset.goodsId) || null,
                    feedback_id: Number(button.dataset.feedbackId) || null,
                    reason,
                }),
            });
            showToast(data.message || '操作成功');
            loadInquiries();
        } catch (error) {
            showToast(error.message || '操作失败');
            button.disabled = false;
        }
    }

    async function updateFeedback(button, status) {
        button.disabled = true;
        try {
            await requestJson(`/api/feedback/${button.dataset.feedbackId}/status`, {
                method: 'PATCH',
                body: JSON.stringify({status}),
            });
            showToast('反馈状态已更新');
            loadInquiries();
        } catch (error) {
            showToast(error.message || '操作失败');
            button.disabled = false;
        }
    }

    document.getElementById('inquiryTabs').addEventListener('click', event => {
        const button = event.target.closest('.operation-tab');
        if (!button) return;
        document.querySelectorAll('.operation-tab').forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        state.status = button.dataset.status;
        state.page = 1;
        loadInquiries();
    });

    el.form.addEventListener('submit', event => {
        event.preventDefault();
        state.page = 1;
        loadInquiries();
    });
    document.getElementById('inquiryReset').addEventListener('click', () => {
        el.keyword.value = '';
        state.page = 1;
        loadInquiries();
    });
    document.getElementById('inquiryRefresh').addEventListener('click', loadInquiries);
    el.pageSize.addEventListener('change', () => {
        state.pageSize = Number(el.pageSize.value) || 20;
        state.page = 1;
        loadInquiries();
    });
    el.prev.addEventListener('click', () => {
        if (state.page > 1) {
            state.page -= 1;
            loadInquiries();
        }
    });
    el.next.addEventListener('click', () => {
        if (state.page < state.pages) {
            state.page += 1;
            loadInquiries();
        }
    });
    el.body.addEventListener('click', event => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        if (button.dataset.action === 'hide') updateListing(button, 0);
        if (button.dataset.action === 'show') updateListing(button, 1);
        if (button.dataset.action === 'complete') updateFeedback(button, 'completed');
        if (button.dataset.action === 'ignore') updateFeedback(button, 'ignored');
    });

    loadInquiries();
})();
