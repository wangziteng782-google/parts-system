/**
 * sales 页“新建询价记录”：前端直连 OA 接口。
 * 身份来自 OA 跳转时携带的 token：后端验签后把它放进 URL fragment（#t=...），
 * 这里读出来存进 sessionStorage 并清掉地址栏，之后每个 OA 请求都用它。
 * 这样 OA 侧认的就是当前登录员工，客户列表自然只有他自己名下的客户。
 */
const OA_API_BASE = 'https://oa.yixiuti.com';
const OA_TOKEN_STORAGE = 'oa_admin_token';
// OA 现有能力：创建询价商品 + 客户沟通记录（无创建订单接口）
const OA_GOODS_CREATE = '/admin/QueryOrderGoods/createOrEdit';
const OA_CHAT_CREATE = '/admin/CommunicationRecords/createOrEdit';
const OA_CONFIG = '/admin/QueryOrder/config';
const OA_UPLOAD = '/admin/Attachment/upload';

// 取值对照来自 OA 前端 bundle（oc/uf/jse/Uf 这几张表）
const GOODS_TYPES = [{value: 1, label: '全品'}, {value: 2, label: '爆品'}, {value: 3, label: '改造'}];
const INVOICE_TYPES = [{value: 0, label: '普票'}, {value: 1, label: '专票'}, {value: 2, label: '不要票'}];
const INVOICE_COMPANIES = [
    {value: 1, label: '昭道'}, {value: 2, label: '吾爱'}, {value: 3, label: '丰泰'}, {value: 4, label: '沧州梯润'},
    {value: 5, label: '溧阳个体户'}, {value: 6, label: '易梯供应链'}, {value: 7, label: '圆保'}, {value: 8, label: '佑梯'},
];
const ELE_SCENES = ['新梯验收', '新梯加装', '旧梯更换 - 无线换无线', '旧梯更换 - 有线换无线'];
const GOODS_SOURCES = ['采购', '销售', '工具箱'];
const CHAT_TYPES = ['主', '电', '改'];
const CLIENT_CATEGORIES = ['A类', 'B类', 'C类', 'D类'];

const CLIENT_PAGE_SIZE = 20;

const inquiryState = {
    client: null,
    clients: [],
    clientPage: 1,
    clientTotal: 0,
    goods: [],
    submitting: false,
    chatType: '主',
    config: null,
    activeIndex: 0,
};

const inquiryEls = {
    entry: document.getElementById('salesInquiryEntry'),
    overlay: document.getElementById('salesInquiryOverlay'),
    picker: document.getElementById('salesInquiryClientOverlay'),
    pickerClose: document.getElementById('salesInquiryPickerClose'),
    close: document.getElementById('salesInquiryClose'),
    cancel: document.getElementById('salesInquiryCancel'),
    clientKeyword: document.getElementById('salesInquiryClientKeyword'),
    clientSearch: document.getElementById('salesInquiryClientSearch'),
    clientBody: document.getElementById('salesInquiryClientList'),
    clientCount: document.getElementById('salesInquiryClientCount'),
    clientPage: document.getElementById('salesInquiryClientPage'),
    clientPrev: document.getElementById('salesInquiryClientPrev'),
    clientNext: document.getElementById('salesInquiryClientNext'),
    clientSelected: document.getElementById('salesInquiryClientSelected'),
    goodsRows: document.getElementById('salesInquiryGoodsRows'),
    addGoods: document.getElementById('salesInquiryAddGoods'),
    content: document.getElementById('salesInquiryContent'),
    chatTypes: document.getElementById('salesInquiryChatTypes'),
    talkTime: document.getElementById('salesInquiryTalkTime'),
    gaizao: document.getElementById('salesInquiryGaizao'),
    category: document.getElementById('salesInquiryCategory'),
    quoteSource: document.getElementById('salesInquiryQuoteSource'),
    zhiTi: document.getElementById('salesInquiryZhiTi'),
    fuTi: document.getElementById('salesInquiryFuTi'),
    error: document.getElementById('salesInquiryError'),
    submit: document.getElementById('salesInquirySubmit'),
};

function oaToken() {
    const saved = sessionStorage.getItem(OA_TOKEN_STORAGE);
    if (saved) return saved;
    // ponytail: 正式环境从非 httponly cookie 读取 OA token
    const match = document.cookie.match(/(?:^|;\s*)oa_token=([^;]+)/);
    if (match) {
        const token = decodeURIComponent(match[1]);
        sessionStorage.setItem(OA_TOKEN_STORAGE, token);
        return token;
    }
    // ponytail: 本地调试用，F12 控制台执行 localStorage.oa_admin_token = '你的OA token' 即可
    const local = localStorage.getItem(OA_TOKEN_STORAGE);
    if (local) {
        sessionStorage.setItem(OA_TOKEN_STORAGE, local);
        return local;
    }
    return '';
}

async function oaRequest(path, options = {}) {
    const token = oaToken();
    if (!token) throw new Error('OA 登录凭证缺失，请从 OA 重新进入本页');
    const url = OA_API_BASE + path;
    let response;
    try {
        // ponytail: 直连 OA，不带 credentials，也不送 Referer（对方允许任意来源，Referer 反而可能被防火墙拦）
        response = await fetch(url, {
            ...options,
            credentials: 'omit',
            referrerPolicy: 'no-referrer',
            headers: {
                'Admin-Token': token,
                ...(options.headers || {}),
            },
        });
    } catch (error) {
        // 浏览器拿不到响应时只会给 TypeError: Failed to fetch，看不出断网、证书还是被拦
        console.error('[OA] 请求失败', url, error);
        throw new Error('连接 OA 失败，请确认当前网络能直接打开 oa.yixiuti.com');
    }
    let payload = null;
    try {
        payload = await response.json();
    } catch (_) {
        throw new Error(`OA 接口返回异常（HTTP ${response.status}）`);
    }
    if (!response.ok) throw new Error(payload?.msg || `OA 接口请求失败（HTTP ${response.status}）`);
    if (payload && payload.code !== undefined && Number(payload.code) !== 200) {
        throw new Error(payload.msg || 'OA 接口返回失败');
    }
    return payload?.data ?? payload;
}

/* ---------------- 入口与弹窗 ---------------- */

function today() {
    const now = new Date();
    const pad = value => String(value).padStart(2, '0');
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// 品牌 / 明目这些下拉的选项来自 OA 配置接口，一次取回后缓存
async function ensureOaConfig() {
    if (inquiryState.config) return;
    try {
        const data = await oaRequest(OA_CONFIG);
        inquiryState.config = {
            factory: data?.factory || [],
            ele_brand: data?.ele_brand || [],
            names: data?.names || [],
        };
    } catch (error) {
        inquiryState.config = {factory: [], ele_brand: [], names: []};
        showSalesToast(`读取 OA 选项失败：${error.message}`, 'error');
    }
}

function openPicker() {
    inquiryEls.picker.classList.add('show');
    inquiryEls.picker.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    inquiryEls.clientKeyword.focus();
    searchClients(1);
}

function closePicker() {
    inquiryEls.picker.classList.remove('show');
    inquiryEls.picker.setAttribute('aria-hidden', 'true');
    if (!inquiryEls.overlay.classList.contains('show')) document.body.style.overflow = '';
}

async function openInquiry() {
    inquiryState.client = null;
    inquiryState.goods = [];
    inquiryState.chatType = '主';
    inquiryState.activeIndex = 0;
    inquiryEls.clientKeyword.value = '';
    inquiryEls.clientBody.innerHTML = '';
    inquiryEls.clientCount.textContent = '共 0 条';
    inquiryEls.clientPage.textContent = '1/1';
    inquiryState.clients = [];
    inquiryState.clientPage = 1;
    inquiryState.clientTotal = 0;
    inquiryEls.clientSelected.hidden = true;
    inquiryEls.clientSelected.innerHTML = '';
    inquiryEls.content.value = '';
    inquiryEls.talkTime.value = '';
    inquiryEls.gaizao.checked = false;
    inquiryEls.category.value = '';
    inquiryEls.quoteSource.value = '';
    inquiryEls.zhiTi.value = '';
    inquiryEls.fuTi.value = '';
    inquiryEls.error.textContent = '';
    renderChatTypes();
    openPicker();
    await ensureOaConfig();
}

// 关掉询价表单时回到「选择客户」这一步，别把整个流程关掉
function backToClientPicker() {
    if (inquiryState.submitting) return;
    inquiryEls.overlay.classList.remove('show');
    inquiryEls.overlay.setAttribute('aria-hidden', 'true');
    openPicker();
}

// 整段流程都关掉，回到商品列表（提交成功用）
function closeInquiry(force = false) {
    if (inquiryState.submitting && !force) return;
    inquiryEls.overlay.classList.remove('show');
    inquiryEls.overlay.setAttribute('aria-hidden', 'true');
    closePicker();
    document.body.style.overflow = '';
}

/* ---------------- 客户 ---------------- */

async function searchClients(page = 1) {
    const keyword = inquiryEls.clientKeyword.value.trim();
    inquiryEls.clientSearch.disabled = true;
    inquiryEls.clientSearch.textContent = '加载中…';
    inquiryEls.clientBody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:#8a96aa;"><span class="loading-spinner" style="display:inline-block;width:18px;height:18px;vertical-align:middle;margin-right:8px;"></span>加载中...</td></tr>';
    try {
        // 只取当前员工名下客户，公海客户不参与询价
        const params = new URLSearchParams({
            page: String(page),
            limit: String(CLIENT_PAGE_SIZE),
            only_my_customer: '1',
            is_public_sea_customer: '0',
        });
        if (keyword) {
            if (/^\d{5,}$/.test(keyword)) params.set('phone', keyword);
            else params.set('name', keyword);
        }
        const data = await oaRequest(`/admin/Client/list?${params}`);
        const items = data?.list || [];
        inquiryState.clients = items;
        inquiryState.clientPage = page;
        inquiryState.clientTotal = Number(data?.count || 0);
        renderClients(items);
    } catch (error) {
        inquiryEls.clientBody.innerHTML = `<tr class="inquiry-client-empty-row"><td colspan="7">${escapeSalesHtml(error.message)}</td></tr>`;
        showSalesToast(error.message, 'error');
    } finally {
        inquiryEls.clientSearch.disabled = false;
        inquiryEls.clientSearch.textContent = '搜索';
    }
}

function renderClients(items) {
    const total = inquiryState.clientTotal;
    const pages = Math.max(1, Math.ceil(total / CLIENT_PAGE_SIZE));
    inquiryEls.clientCount.textContent = `共 ${total} 条`;
    inquiryEls.clientPage.textContent = `${inquiryState.clientPage}/${pages}`;
    inquiryEls.clientPrev.disabled = inquiryState.clientPage <= 1;
    inquiryEls.clientNext.disabled = inquiryState.clientPage >= pages;
    if (!items.length) {
        inquiryEls.clientBody.innerHTML = '<tr class="inquiry-client-empty-row"><td colspan="7">没找到客户，换个姓名或手机号试试</td></tr>';
        return;
    }
    inquiryEls.clientBody.innerHTML = items.map(item => `
        <tr data-client-id="${escapeSalesHtml(item.id)}">
            <td><strong>${escapeSalesHtml(item.name || '未命名客户')}</strong></td>
            <td>${escapeSalesHtml(item.phone || '-')}</td>
            <td title="${escapeSalesHtml(item.company_name || '')}">${escapeSalesHtml(item.company_name || '-')}</td>
            <td>${escapeSalesHtml(item.category || '-')}</td>
            <td>${escapeSalesHtml(item.zhi_ti_num || '-')}</td>
            <td>${escapeSalesHtml(item.fu_ti_num || '-')}</td>
            <td>${escapeSalesHtml(item.admin_id_name || '-')}</td>
        </tr>`).join('');
}

function selectClient(client) {
    if (!client) return;
    inquiryState.client = client;
    inquiryEls.clientSelected.hidden = false;
    inquiryEls.clientSelected.innerHTML = `
        <strong>${escapeSalesHtml(client.name || '未命名客户')}</strong>
        <span>${escapeSalesHtml(client.phone || '')}</span>
        <em>${escapeSalesHtml(client.company_name || '')}</em>
        <button type="button" class="inquiry-client-change" id="salesInquiryClientChange">更换客户</button>`;
    // OA 的沟通记录默认带出客户现有资料
    inquiryEls.category.value = client.category || '';
    inquiryEls.zhiTi.value = client.zhi_ti_num || '';
    inquiryEls.fuTi.value = client.fu_ti_num || '';
    inquiryEls.gaizao.checked = String(client.is_gai_zao_ke_hu || '0') === '1';
    document.getElementById('salesInquiryClientChange').addEventListener('click', openPicker);
    closePicker();
    inquiryEls.overlay.classList.add('show');
    inquiryEls.overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const keyword = document.getElementById('salesSearchInput')?.value?.trim() || salesState.keyword || '';
    if (!inquiryState.goods.length) addGoodsRow({goods_spec: keyword});
}

/* ---------------- 产品 ---------------- */

function addGoodsRow(prefill = {}) {
    inquiryState.goods.push({
        goods_name: prefill.goods_name || '',
        ele_type: '',
        goods_spec: prefill.goods_spec || '',
        goods_type: 1,
        source: '采购',
        inquiry_time: today(),
        factory: '',
        ele_brand: '',
        names: '',
        ele_scene: '',
        goods_num: 1,
        goods_unit: '',
        goods_price: '',
        goods_price_tax: '',
        tax_rate: '',
        invoice: 0,
        invoice_company: '',
        post_fee: '',
        post_fee_tax_rate: '',
        post_fee_has_tax: '',
        total_amount_sign: '',
        is_free: 0,
        is_goods_price_fee: 0,
        goods_weight: '',
        warehouse: '',
        goods_describe: '',
        address: '',
        post_fee_describe: '',
        total_amount_sign_remark: '',
        send_address: '',
        files: [],
    });
    renderGoodsRows();
    const cards = inquiryEls.goodsRows.querySelectorAll('[data-goods-index]');
    const last = cards[cards.length - 1];
    const nameInput = last?.querySelector('[data-field="goods_name"]');
    if (nameInput) {
        nameInput.focus();
        // 带上搜索词时把光标放到末尾，接着打字就行
        nameInput.setSelectionRange(nameInput.value.length, nameInput.value.length);
    }
}

function fieldBox(label, control, span = 1) {
    // 必填星号、? 提示都放到文字前面，和 OA 表单一致
    const marks = label.match(/<i[^>]*>[^<]*<\/i>/g) || [];
    const text = label.replace(/<i[^>]*>[^<]*<\/i>/g, '').trim();
    const prefix = marks.length ? `${marks.join('')} ` : '';
    return `<label class="inquiry-field${span > 1 ? ` span-${span}` : ''}"><span class="inquiry-field-label">${prefix}${text}</span>${control}</label>`;
}

// 售价和含税售价二选一，填了其中一个，另一个的必填星号就隐藏（元素常驻，方便来回切换）
function requiredStar(name, show) {
    return ` <i data-star="${name}"${show ? '' : ' hidden'}>*</i>`;
}

function textInput(field, value, placeholder, type = 'text') {
    return `<input type="${type}" data-field="${field}" value="${escapeSalesHtml(value)}" placeholder="${placeholder}">`;
}

function suffixInput(field, value, placeholder, suffix, type = 'text') {
    return `${textInput(field, value, placeholder, type)}<span class="inquiry-field-suffix">${suffix}</span>`;
}

// OA 自己算的字段，前端只占位展示，不提交
function readonlyInput(placeholder = '') {
    return `<input type="text" class="is-readonly" value="" placeholder="${placeholder}" readonly tabindex="-1">`;
}

function radioGroup(field, items, value, groupName) {
    return `<span class="inquiry-radios">${items.map(item => `
        <label class="inquiry-radio">
            <input type="radio" name="${groupName}-${field}" value="${item.value}" data-field="${field}"${String(item.value) === String(value) ? ' checked' : ''}>
            <span>${item.label}</span>
        </label>`).join('')}</span>`;
}

// OA 表单里这些字段都是 el-select，统一做成可输入筛选的下拉
function optionSelect(field, items, value, placeholder = '请选择', allowCreate = false) {
    const list = items.map(item => ({value: String(item.value), label: String(item.label)}));
    const selected = list.find(item => item.value === String(value));
    const label = selected ? selected.label : '';
    const options = list.map(item => `<li data-value="${escapeSalesHtml(item.value)}">${escapeSalesHtml(item.label)}</li>`).join('');
    return `<span class="inquiry-select" data-select${allowCreate ? ' data-create' : ''}>
        <input type="text" class="inquiry-select-input" value="${escapeSalesHtml(label)}" data-label="${escapeSalesHtml(label)}" placeholder="${placeholder}" autocomplete="off">
        <input type="hidden" data-field="${field}" value="${selected ? escapeSalesHtml(selected.value) : ''}">
        <ul class="inquiry-select-options" hidden>${options}</ul>
    </span>`;
}

function configSelect(field, value) {
    const items = (inquiryState.config?.[field] || []).map(item => ({value: item.id, label: item.name}));
    return optionSelect(field, items, value, items.length ? '其他请输入后选择' : '加载中…');
}

// 图标取自 OA 前端 bundle 里 YxfUpload 用的 Element Plus 图标
const ICON_ZOOM_IN = '<svg viewBox="0 0 1024 1024" width="16" height="16" fill="currentColor"><path d="m795.904 750.72 124.992 124.928a32 32 0 0 1-45.248 45.248L750.656 795.904a416 416 0 1 1 45.248-45.248zM480 832a352 352 0 1 0 0-704 352 352 0 0 0 0 704zm-32-384v-96a32 32 0 0 1 64 0v96h96a32 32 0 0 1 0 64h-96v96a32 32 0 0 1-64 0v-96h-96a32 32 0 0 1 0-64h96z"/></svg>';
const ICON_DELETE = '<svg viewBox="0 0 1024 1024" width="16" height="16" fill="currentColor"><path d="M160 256H96a32 32 0 0 1 0-64h256V95.936a32 32 0 0 1 32-32h256a32 32 0 0 1 32 32V192h256a32 32 0 1 1 0 64h-64v672a32 32 0 0 1-32 32H192a32 32 0 0 1-32-32V256zm448-64v-64H416v64h192zM224 896h576V256H224v640zm192-128a32 32 0 0 1-32-32V416a32 32 0 0 1 64 0v320a32 32 0 0 1-32 32zm192 0a32 32 0 0 1-32-32V416a32 32 0 0 1 64 0v320a32 32 0 0 1-32 32z"/></svg>';
const ICON_LOCATION = '<svg viewBox="0 0 1024 1024" width="14" height="14" fill="currentColor"><path d="M512 128c-176 0-320 144-320 320 0 240 320 448 320 448s320-208 320-448c0-176-144-320-320-320zm0 448a128 128 0 1 1 0-256 128 128 0 0 1 0 256z"/></svg>';

function renderGoodsRows() {
    inquiryEls.goodsRows.innerHTML = inquiryState.goods.map((good, index) => {
        const files = good.files || [];
        const thumbs = files.map((item, fileIndex) => `
            <div class="inquiry-upload-item" data-preview-image="${fileIndex}">
                <img src="${item.url}" alt="">
                <span class="inquiry-upload-actions">
                    <button type="button" data-preview-image="${fileIndex}" title="预览">${ICON_ZOOM_IN}</button>
                    <button type="button" data-remove-image="${fileIndex}" title="删除">${ICON_DELETE}</button>
                </span>
            </div>`).join('');
        return `
        <article class="inquiry-goods-card" data-goods-index="${index}">
            <header class="inquiry-goods-head">
                <strong>${index + 1}. ${escapeSalesHtml(good.goods_name || '未命名产品')}</strong>
                <span>×${escapeSalesHtml(good.goods_num)}</span>
                <button type="button" data-remove aria-label="删除该产品" ${inquiryState.goods.length === 1 ? 'disabled' : ''}>删除</button>
            </header>
            <div class="inquiry-fields">
                <div class="inquiry-field span-3 inquiry-field-images">
                    <span class="inquiry-field-label">商品图片</span>
                    <div class="inquiry-goods-media${files.length >= MAX_GOODS_IMAGES ? ' is-hide' : ''}">
                        ${thumbs}
                        <label class="inquiry-upload-plus" data-drop-zone title="点击上传，也可以拖拽图片进来">
                            <span>＋</span>
                            <input type="file" accept="image/*" multiple data-image-input hidden>
                        </label>
                    </div>
                </div>
                ${fieldBox('商品类型 <i>*</i>', radioGroup('goods_type', GOODS_TYPES, good.goods_type, `g${index}`))}
                ${fieldBox('报价来源 <i>*</i>', optionSelect('source', GOODS_SOURCES.map(x => ({value: x, label: x})), good.source))}
                ${fieldBox('客户询价日期 <i>*</i>', textInput('inquiry_time', good.inquiry_time, '', 'date'))}
                ${fieldBox('商品名称 <i>*</i>', textInput('goods_name', good.goods_name, '请输入商品名称'), 2)}
                ${fieldBox('电梯场景', optionSelect('ele_scene', ELE_SCENES.map(x => ({value: x, label: x})), good.ele_scene, '请选择', true))}
                ${fieldBox('规格型号 <i>*</i>', textInput('goods_spec', good.goods_spec, '请输入规格型号'))}
                ${fieldBox('商品品牌', configSelect('factory', good.factory))}
                ${fieldBox('电梯品牌 <i>*</i>', configSelect('ele_brand', good.ele_brand))}
                ${fieldBox('明目 <i>*</i>', configSelect('names', good.names))}
                ${fieldBox('发票类型 <i>*</i>', optionSelect('invoice', INVOICE_TYPES, good.invoice))}
                ${fieldBox('开票单位 <i>*</i>', optionSelect('invoice_company', INVOICE_COMPANIES, good.invoice_company))}
                ${fieldBox(`售价${requiredStar('goods_price', !good.goods_price_tax)}`, textInput('goods_price', good.goods_price, '请输入售价'))}
                ${fieldBox('商品税率', suffixInput('tax_rate', good.tax_rate, '请输入商品税率', '%'))}
                ${fieldBox('商品税费', readonlyInput())}
                ${fieldBox(`含税售价${requiredStar('goods_price_tax', !good.goods_price)}`, textInput('goods_price_tax', good.goods_price_tax, '请输入含税售价'))}
                ${fieldBox('数量 <i>*</i>', textInput('goods_num', good.goods_num, '1', 'number'))}
                ${fieldBox('单位', textInput('goods_unit', good.goods_unit, '请输入单位'))}
                ${fieldBox('运费', textInput('post_fee', good.post_fee, '请输入运费'))}
                ${fieldBox('运费税率', suffixInput('post_fee_tax_rate', good.post_fee_tax_rate, '请输入运费税率', '%'))}
                ${fieldBox('运费税费', readonlyInput())}
                ${fieldBox('含税运费', textInput('post_fee_has_tax', good.post_fee_has_tax, '请输入含税运费'))}
                ${fieldBox('应收总额', readonlyInput())}
                ${fieldBox('记录业绩', textInput('total_amount_sign', good.total_amount_sign, '请输入记录业绩'))}
                ${fieldBox('重量(kg)', suffixInput('goods_weight', good.goods_weight, '请输入重量(kg)', 'kg'))}
                ${fieldBox('重量合计', `${readonlyInput('请输入重量合计')}<span class="inquiry-field-suffix">kg</span>`)}
                ${fieldBox('发货仓库', textInput('warehouse', good.warehouse, '请输入发货仓库'))}
                ${fieldBox('是否赠送', radioGroup('is_free', [{value: 0, label: '非赠送'}, {value: 1, label: '赠送'}], good.is_free, `g${index}`))}
                ${fieldBox('是否包邮', radioGroup('is_goods_price_fee', [{value: 0, label: '不包邮'}, {value: 1, label: '包邮'}], good.is_goods_price_fee, `g${index}`))}
                <div class="inquiry-field"></div>
                ${fieldBox('询运费 <i class="inquiry-field-tip" title="填写询运费描述将发起询运费任务">?</i>', `<textarea rows="2" data-field="address" placeholder="填写询运费描述将发起询运费任务">${escapeSalesHtml(good.address)}</textarea>`)}
                ${fieldBox('询价描述 <i class="inquiry-field-tip" title="补充该商品的询价信息">?</i>', `<textarea rows="2" data-field="goods_describe" placeholder="请输入询价描述">${escapeSalesHtml(good.goods_describe)}</textarea>`)}
                ${fieldBox('实收备注', textInput('total_amount_sign_remark', good.total_amount_sign_remark, '请输入实收备注'))}
                ${fieldBox('商品备注', `<textarea rows="2" data-field="post_fee_describe" placeholder="快递公司、邮寄方式等">${escapeSalesHtml(good.post_fee_describe)}</textarea>`)}
                ${fieldBox(`<span class="inquiry-address-link" data-address-pick title="点击选择客户的收货地址">${ICON_LOCATION}收货地址</span>`, `<textarea rows="2" data-field="send_address" placeholder="请输入收货地址">${escapeSalesHtml(good.send_address)}</textarea>`, 2)}
            </div>
        </article>`;
    }).join('');
}

/* ---------------- 沟通记录 ---------------- */

function renderChatTypes() {
    inquiryEls.chatTypes.querySelectorAll('[data-chat-type]').forEach(button => {
        button.classList.toggle('active', button.dataset.chatType === inquiryState.chatType);
    });
}

/* ---------------- 图片 ---------------- */

const MAX_GOODS_IMAGES = 4;
const MAX_IMAGE_SIZE = 5 * 1024 * 1024;

function imagesFromTransfer(transfer) {
    if (!transfer) return [];
    const files = Array.from(transfer.files || []);
    if (files.length) return files.filter(file => file.type.startsWith('image/'));
    return Array.from(transfer.items || [])
        .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
        .map(item => item.getAsFile())
        .filter(Boolean);
}

function appendImageFiles(good, files) {
    if (!good) return;
    good.files = good.files || [];
    let added = 0;
    for (const file of files) {
        if (good.files.length >= MAX_GOODS_IMAGES) {
            showSalesToast(`超出限制，最多上传 ${MAX_GOODS_IMAGES} 个图片`, 'error');
            break;
        }
        if (!file.type.startsWith('image/')) {
            showSalesToast('只能上传图片文件', 'error');
            continue;
        }
        if (file.size > MAX_IMAGE_SIZE) {
            showSalesToast('单张图片不能超过 5MB', 'error');
            continue;
        }
        good.files.push({file, url: URL.createObjectURL(file)});
        added += 1;
    }
    if (added) renderGoodsRows();
}

/* ---------------- 图片预览 ---------------- */

// 照 el-image-viewer 的行为：遮罩关闭、左右切换、缩放、旋转
const viewerState = {urls: [], index: 0, scale: 1, rotate: 0};
let viewerEls = null;

function ensureViewer() {
    if (viewerEls) return viewerEls;
    const root = document.createElement('div');
    root.className = 'inquiry-viewer';
    root.innerHTML = `
        <span class="inquiry-viewer-close" data-viewer-close>✕</span>
        <span class="inquiry-viewer-arrow prev" data-viewer-step="-1">‹</span>
        <span class="inquiry-viewer-arrow next" data-viewer-step="1">›</span>
        <div class="inquiry-viewer-stage"><img alt=""></div>
        <div class="inquiry-viewer-bar">
            <button type="button" data-viewer-zoom="-1" title="缩小">－</button>
            <span data-viewer-scale>100%</span>
            <button type="button" data-viewer-zoom="1" title="放大">＋</button>
            <button type="button" data-viewer-rotate title="旋转">↻</button>
        </div>`;
    root.addEventListener('click', event => {
        const step = event.target.closest('[data-viewer-step]');
        if (step) return stepViewer(Number(step.dataset.viewerStep));
        const zoom = event.target.closest('[data-viewer-zoom]');
        if (zoom) return zoomViewer(Number(zoom.dataset.viewerZoom));
        if (event.target.closest('[data-viewer-rotate]')) {
            viewerState.rotate += 90;
            return applyViewerTransform();
        }
        if (event.target.closest('[data-viewer-close]') || event.target === root || event.target.classList.contains('inquiry-viewer-stage')) closeViewer();
    });
    root.addEventListener('wheel', event => {
        event.preventDefault();
        zoomViewer(event.deltaY < 0 ? 1 : -1);
    }, {passive: false});
    document.body.appendChild(root);
    viewerEls = {root, img: root.querySelector('img'), scale: root.querySelector('[data-viewer-scale]')};
    return viewerEls;
}

function applyViewerTransform() {
    viewerEls.img.style.transform = `scale(${viewerState.scale}) rotate(${viewerState.rotate}deg)`;
    viewerEls.scale.textContent = `${Math.round(viewerState.scale * 100)}%`;
}

function renderViewer() {
    const hasMany = viewerState.urls.length > 1;
    viewerEls.img.src = viewerState.urls[viewerState.index] || '';
    viewerEls.root.querySelector('[data-viewer-step="-1"]').hidden = !hasMany;
    viewerEls.root.querySelector('[data-viewer-step="1"]').hidden = !hasMany;
}

function resetViewer() {
    viewerState.scale = 1;
    viewerState.rotate = 0;
    applyViewerTransform();
}

function openViewer(urls, index) {
    if (!urls.length) return;
    ensureViewer();
    viewerState.urls = urls;
    viewerState.index = Math.min(index, urls.length - 1);
    resetViewer();
    renderViewer();
    viewerEls.root.classList.add('show');
}

function closeViewer() {
    viewerEls?.root.classList.remove('show');
}

function stepViewer(step) {
    const total = viewerState.urls.length;
    if (!total) return;
    viewerState.index = (viewerState.index + step + total) % total;
    resetViewer();
    renderViewer();
}

function zoomViewer(step) {
    if (!viewerEls) return;
    viewerState.scale = Math.min(5, Math.max(.3, Number((viewerState.scale + step * .25).toFixed(2))));
    applyViewerTransform();
}

/* ---------------- 右键粘贴（OA 上传位上的右键菜单） ---------------- */

// Ctrl+V 粘贴图片：直接监听 paste 事件，从剪贴板数据提取图片
inquiryEls.goodsRows?.addEventListener('paste', event => {
    const zone = event.target.closest('[data-drop-zone]');
    if (!zone) return;
    const files = imagesFromTransfer(event.clipboardData);
    if (!files.length) return;
    event.preventDefault();
    const card = zone.closest('[data-goods-index]');
    const good = inquiryState.goods[Number(card?.dataset.goodsIndex)];
    if (good) appendImageFiles(good, files);
});

// 右键菜单：粘贴图片。真正去读剪贴板，读不了再退回 Ctrl+V
let pasteMenuEl = null;
function closePasteMenu() {
    pasteMenuEl?.remove();
    pasteMenuEl = null;
}
inquiryEls.goodsRows?.addEventListener('contextmenu', event => {
    const zone = event.target.closest('[data-drop-zone]');
    if (!zone) return;
    event.preventDefault();
    closePasteMenu();
    const card = zone.closest('[data-goods-index]');
    pasteMenuEl = document.createElement('div');
    pasteMenuEl.className = 'inquiry-paste-menu';
    pasteMenuEl.textContent = '粘贴图片';
    pasteMenuEl.style.left = `${event.clientX}px`;
    pasteMenuEl.style.top = `${event.clientY}px`;
    pasteMenuEl.addEventListener('click', async () => {
        closePasteMenu();
        const good = inquiryState.goods[Number(card?.dataset.goodsIndex)];
        if (!good) return;
        // navigator.clipboard 只在 HTTPS 或 localhost 下存在，Firefox 也不支持读图片
        if (!navigator.clipboard?.read) {
            showSalesToast('当前环境读不了剪贴板，请点一下上传位后按 Ctrl + V');
            return;
        }
        try {
            const files = [];
            for (const item of await navigator.clipboard.read()) {
                for (const type of item.types.filter(type => type.startsWith('image/'))) {
                    const blob = await item.getType(type);
                    files.push(new File([blob], `paste_${Date.now()}.${type.split('/')[1]}`, {type}));
                }
            }
            if (!files.length) {
                showSalesToast('剪贴板里没有图片');
                return;
            }
            appendImageFiles(good, files);
        } catch {
            // 多数是没点「允许」或权限被拒
            showSalesToast('未获得剪贴板权限，请点一下上传位后按 Ctrl + V');
        }
    });
    document.body.appendChild(pasteMenuEl);
    document.addEventListener('click', closePasteMenu, {once: true});
});

/* ---------------- 收货地址：弹窗列出客户历史地址 ---------------- */

const OA_CLIENT_ADDRESS = '/admin/Client/client_address';
let addressDialogEl = null;
let addressTarget = null;
let addressPage = 1;
let addressPages = 1;
let addressLimit = 50;

function ensureAddressDialog() {
    if (addressDialogEl) return addressDialogEl;
    const overlay = document.createElement('div');
    overlay.className = 'sales-inquiry-overlay address';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML = `
        <section class="sales-inquiry-modal inquiry-address-modal" role="dialog" aria-label="客户历史收货地址">
            <header class="inquiry-address-head">
                <h3>客户历史收货地址</h3>
                <button type="button" class="inquiry-address-close" data-address-close aria-label="关闭">×</button>
            </header>
            <div class="inquiry-address-body">
                <table>
                    <thead><tr><th class="col-idx">序号</th><th>历史收货地址</th><th class="col-ops">操作</th></tr></thead>
                    <tbody data-address-body></tbody>
                </table>
            </div>
            <footer class="inquiry-address-foot">
                <div class="inquiry-address-pager">
                    <button type="button" data-address-page="first" title="首页">«</button>
                    <button type="button" data-address-page="prev" title="上一页">‹</button>
                    <span class="inquiry-address-page-box" data-address-page-now>1</span>
                    <span class="inquiry-address-page-total" data-address-page-total>/ 1</span>
                    <button type="button" data-address-page="next" title="下一页">›</button>
                    <button type="button" data-address-page="last" title="末页">»</button>
                    <select class="inquiry-address-limit" data-address-limit>
                        <option value="20">20条/页</option>
                        <option value="50" selected>50条/页</option>
                        <option value="100">100条/页</option>
                    </select>
                    <span data-address-count>共 0 条记录</span>
                </div>
            </footer>
            <div class="inquiry-address-actions">
                <button type="button" class="inquiry-address-closebtn" data-address-close>关闭</button>
            </div>
        </section>`;
    overlay.addEventListener('click', event => {
        if (event.target === overlay || event.target.closest('[data-address-close]')) {
            closeAddressDialog();
            return;
        }
        const pageBtn = event.target.closest('[data-address-page]');
        if (pageBtn) {
            turnAddressPage(pageBtn.dataset.addressPage);
            return;
        }
        const fill = event.target.closest('[data-address-fill]');
        if (fill) {
            fillAddress(fill.dataset.addressFill);
            return;
        }
        const copy = event.target.closest('[data-address-copy]');
        if (copy) copyAddress(copy.dataset.addressCopy);
    });
    overlay.addEventListener('change', event => {
        if (!event.target.closest('[data-address-limit]')) return;
        addressLimit = Number(event.target.value) || 50;
        loadAddressPage(1);
    });
    document.body.appendChild(overlay);
    addressDialogEl = overlay;
    return overlay;
}

function openAddressDialog(card) {
    const textarea = card?.querySelector('[data-field="send_address"]');
    if (!textarea) return;
    addressTarget = textarea;
    ensureAddressDialog();
    addressDialogEl.classList.add('show');
    addressDialogEl.setAttribute('aria-hidden', 'false');
    loadAddressPage(1);
}

function closeAddressDialog() {
    addressDialogEl?.classList.remove('show');
    addressDialogEl?.setAttribute('aria-hidden', 'true');
    addressTarget = null;
}

async function loadAddressPage(page) {
    const clientId = inquiryState.client?.id;
    const body = addressDialogEl.querySelector('[data-address-body]');
    if (!clientId) {
        body.innerHTML = '<tr><td colspan="3" class="inquiry-address-empty">请先选择客户</td></tr>';
        return;
    }
    body.innerHTML = '<tr><td colspan="3" class="inquiry-address-empty">加载中…</td></tr>';
    try {
        // 接口要的是客户 id，参数名是 id 不是 client_id
        const data = await oaRequest(`${OA_CLIENT_ADDRESS}?id=${clientId}&page=${page}&limit=${addressLimit}`);
        const list = data?.list || [];
        const count = Number(data?.count || 0);
        addressPage = page;
        addressPages = Math.max(1, Math.ceil(count / addressLimit));
        if (!list.length) {
            body.innerHTML = '<tr><td colspan="3" class="inquiry-address-empty">该客户还没有收货地址</td></tr>';
        } else {
            body.innerHTML = list.map((item, index) => {
                const text = item.send_address || '';
                return `
                <tr>
                    <td class="col-idx">${(page - 1) * addressLimit + index + 1}</td>
                    <td>${escapeSalesHtml(text)}</td>
                    <td class="col-ops">
                        <button type="button" data-address-fill="${escapeSalesHtml(text)}">一键填写</button>
                        <button type="button" data-address-copy="${escapeSalesHtml(text)}">复制</button>
                    </td>
                </tr>`;
            }).join('');
        }
        updateAddressPager(count);
    } catch (error) {
        body.innerHTML = `<tr><td colspan="3" class="inquiry-address-empty">${escapeSalesHtml(error.message)}</td></tr>`;
    }
}

function updateAddressPager(count) {
    addressDialogEl.querySelector('[data-address-page-now]').textContent = String(addressPage);
    addressDialogEl.querySelector('[data-address-page-total]').textContent = `/ ${addressPages}`;
    addressDialogEl.querySelector('[data-address-count]').textContent = `共 ${count} 条记录`;
    addressDialogEl.querySelectorAll('[data-address-page]').forEach(button => {
        const direction = button.dataset.addressPage;
        button.disabled = (direction === 'first' || direction === 'prev')
            ? addressPage <= 1
            : addressPage >= addressPages;
    });
}

function turnAddressPage(direction) {
    const target = {first: 1, prev: addressPage - 1, next: addressPage + 1, last: addressPages}[direction];
    if (!target || target < 1 || target > addressPages) return;
    loadAddressPage(target);
}

function fillAddress(text) {
    if (!addressTarget) return;
    addressTarget.value = text;
    addressTarget.dispatchEvent(new Event('input', {bubbles: true}));
    closeAddressDialog();
    showSalesToast('已填写收货地址', 'success');
}

async function copyAddress(text) {
    try {
        await navigator.clipboard.writeText(text);
        showSalesToast('已复制到剪贴板', 'success');
    } catch {
        // 兜底：用 execCommand 复制
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showSalesToast('已复制到剪贴板', 'success');
        } catch {
            showSalesToast('复制失败，请手动复制');
        }
    }
}

inquiryEls.goodsRows?.addEventListener('click', event => {
    const pick = event.target.closest('[data-address-pick]');
    if (!pick) return;
    event.preventDefault();
    openAddressDialog(pick.closest('[data-goods-index]'));
});

/* ---------------- 提交 ---------------- */

// ponytail: 图片随提交一起上传，失败时该商品还没创建，不会留下半条数据
async function uploadOaImage(file) {
    const form = new FormData();
    form.append('file', file);
    const data = await oaRequest(OA_UPLOAD, {method: 'POST', body: form});
    if (!data?.url) throw new Error('图片上传失败');
    return data.url;
}

async function createOaGoods(good, orderId) {
    return oaRequest(OA_GOODS_CREATE, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            goods_name: good.goods_name,
            goods_spec: good.goods_spec,
            ele_type: good.ele_type,
            goods_type: Number(good.goods_type) || 1,
            source: good.source || '',
            inquiry_time: good.inquiry_time || '',
            factory: good.factory ? Number(good.factory) : '',
            ele_brand: good.ele_brand ? Number(good.ele_brand) : '',
            names: good.names ? Number(good.names) : '',
            ele_scene: good.ele_scene || '',
            goods_num: Number(good.goods_num) || 0,
            goods_unit: good.goods_unit || '',
            goods_price: good.goods_price || '',
            goods_price_tax: good.goods_price_tax || '',
            tax_rate: good.tax_rate || '',
            invoice: String(good.invoice ?? ''),
            invoice_company: good.invoice_company ? Number(good.invoice_company) : '',
            post_fee: good.post_fee || '',
            post_fee_tax_rate: good.post_fee_tax_rate || '',
            post_fee_has_tax: good.post_fee_has_tax || '',
            total_amount_sign: good.total_amount_sign || '',
            is_free: Number(good.is_free) || 0,
            is_goods_price_fee: Number(good.is_goods_price_fee) || 0,
            goods_weight: good.goods_weight || '',
            warehouse: good.warehouse || '',
            goods_describe: good.goods_describe || '',
            address: good.address || '',
            total_amount_sign_remark: good.total_amount_sign_remark || '',
            post_fee_describe: good.post_fee_describe || '',
            images: good.images || '',
            package_id: '',
            send_address: good.send_address || '',
            query_order_id: orderId || 0,
        }),
    });
}

async function createOaChat(chat) {
    return oaRequest(OA_CHAT_CREATE, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            id: 0,
            client_id: inquiryState.client.id,
            // 1 = 让 OA 顺手建一张询价单，返回值里的 query_order_id 就是新单号
            create_query_order: 1,
            query_order_id: 0,
            content: chat.content,
            type: chat.type,
            talk_time: chat.talk_time,
            is_gai_zao_ke_hu: chat.is_gai_zao_ke_hu,
            category: chat.category,
            zhi_ti_num: chat.zhi_ti_num,
            fu_ti_num: chat.fu_ti_num,
        }),
    });
}

function collectGoods() {
    return inquiryState.goods
        .map(good => ({
            ...good,
            goods_name: String(good.goods_name || '').trim(),
            goods_spec: String(good.goods_spec || '').trim(),
            goods_num: Number(good.goods_num) || 0,
        }))
        .filter(good => good.goods_name);
}

function collectChat() {
    return {
        content: inquiryEls.content.value.trim(),
        type: inquiryState.chatType,
        talk_time: inquiryEls.talkTime.value.trim(),
        is_gai_zao_ke_hu: inquiryEls.gaizao.checked ? '1' : '0',
        category: inquiryEls.category.value,
        quote_source: inquiryEls.quoteSource.value,
        zhi_ti_num: inquiryEls.zhiTi.value.trim(),
        fu_ti_num: inquiryEls.fuTi.value.trim(),
    };
}

async function submitInquiry() {
    if (inquiryState.submitting) return;
    inquiryEls.error.textContent = '';
    if (!inquiryState.client) {
        inquiryEls.error.textContent = '请先选择客户';
        return;
    }
    const goods = collectGoods();
    if (!goods.length) {
        inquiryEls.error.textContent = '请至少填写一个商品名称';
        return;
    }
    if (goods.some(good => good.goods_num <= 0)) {
        inquiryEls.error.textContent = '商品数量必须大于 0';
        return;
    }

    const chat = collectChat();
    if (!chat.content) {
        inquiryEls.error.textContent = '请填写沟通内容，OA 用它生成询价单';
        return;
    }
    inquiryState.submitting = true;
    inquiryEls.submit.disabled = true;
    inquiryEls.submit.querySelector('span').textContent = '提交中…';
    const createdIds = [];
    try {
        // 图片先传完，附件失败时还没有写任何 OA 数据
        for (const good of goods) {
            const images = [];
            for (const item of good.files) images.push(await uploadOaImage(item.file));
            good.images = images.join(',');
        }
        // OA 只能靠沟通记录建询价单，先建单拿到单号，再把商品挂进去
        const chatRes = await createOaChat(chat);
        const orderId = Number(chatRes?.query_order_id || 0);
        if (!orderId) throw new Error('生成询价单失败');
        for (const good of goods) {
            const created = await createOaGoods(good, orderId);
            const goodsId = Number(created?.id || 0);
            if (!goodsId) throw new Error('创建询价商品失败');
            createdIds.push(goodsId);
        }
        showSalesToast(`询价单已生成，含 ${goods.length} 个商品`, 'success');
        closeInquiry(true);
        loadSalesProducts();
    } catch (error) {
        // ponytail: 无事务，失败时就报告已完成数量，不回滚
        const done = createdIds.length;
        const message = done
            ? `询价单已生成，${done}/${goods.length} 个商品成功，失败：${error.message}`
            : error.message;
        inquiryEls.error.textContent = message;
        showSalesToast(message, 'error');
    } finally {
        inquiryState.submitting = false;
        inquiryEls.submit.disabled = false;
        inquiryEls.submit.querySelector('span').textContent = '提交询价';
    }
}

/* ---------------- 事件 ---------------- */

inquiryEls.entry?.addEventListener('click', openInquiry);
// 关掉询价表单回到选择客户，只有选择客户上的叉才整段退出
inquiryEls.close?.addEventListener('click', backToClientPicker);
inquiryEls.cancel?.addEventListener('click', backToClientPicker);
inquiryEls.pickerClose?.addEventListener('click', closePicker);
inquiryEls.clientSearch?.addEventListener('click', () => searchClients(1));
inquiryEls.clientKeyword?.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
        event.preventDefault();
        searchClients(1);
    }
});
inquiryEls.clientPrev?.addEventListener('click', () => {
    if (inquiryState.clientPage > 1) searchClients(inquiryState.clientPage - 1);
});
inquiryEls.clientNext?.addEventListener('click', () => searchClients(inquiryState.clientPage + 1));
inquiryEls.clientBody?.addEventListener('click', event => {
    const row = event.target.closest('[data-client-id]');
    if (!row) return;
    selectClient(inquiryState.clients.find(item => String(item.id) === row.dataset.clientId));
});
inquiryEls.addGoods?.addEventListener('click', () => addGoodsRow());
inquiryEls.submit?.addEventListener('click', submitInquiry);

inquiryEls.chatTypes?.addEventListener('click', event => {
    const button = event.target.closest('[data-chat-type]');
    if (!button) return;
    inquiryState.chatType = button.dataset.chatType;
    renderChatTypes();
});

function syncGoodsField(event) {
    const card = event.target.closest('[data-goods-index]');
    const field = event.target.dataset.field;
    if (!card || !field) return;
    const good = inquiryState.goods[Number(card.dataset.goodsIndex)];
    if (good) good[field] = event.target.value;
}

// 售价、含税售价互为替代，实时切换必填星号
function syncPriceStars(card) {
    if (!card) return;
    const price = card.querySelector('[data-field="goods_price"]')?.value.trim();
    const tax = card.querySelector('[data-field="goods_price_tax"]')?.value.trim();
    const priceStar = card.querySelector('[data-star="goods_price"]');
    const taxStar = card.querySelector('[data-star="goods_price_tax"]');
    if (priceStar) priceStar.hidden = Boolean(tax);
    if (taxStar) taxStar.hidden = Boolean(price);
}

inquiryEls.goodsRows?.addEventListener('input', event => {
    syncGoodsField(event);
    syncPriceStars(event.target.closest('[data-goods-index]'));
});
inquiryEls.goodsRows?.addEventListener('change', event => {
    const input = event.target.closest('[data-image-input]');
    if (!input) {
        syncGoodsField(event);
        return;
    }
    const card = input.closest('[data-goods-index]');
    appendImageFiles(inquiryState.goods[Number(card?.dataset.goodsIndex)], Array.from(input.files));
    // 清空才能重复选择同一张图
    input.value = '';
});

/* ---------------- 可输入筛选的下拉 ---------------- */

function closeSelect(box) {
    if (!box) return;
    const input = box.querySelector('.inquiry-select-input');
    // 没选就走人，输入框恢复成上一个已选的值
    input.value = input.dataset.label || '';
    input.dataset.hint = '0';
    input.classList.remove('is-hint');
    box.classList.remove('is-open');
    box.querySelector('.inquiry-select-options').hidden = true;
}

function ensureSelectItem(panel, className, defaultText = '') {
    let item = panel.querySelector(`li.${className}`);
    if (!item) {
        item = document.createElement('li');
        item.className = className;
        item.textContent = defaultText;
        panel.appendChild(item);
    }
    return item;
}

function filterSelect(box, keyword) {
    const panel = box.querySelector('.inquiry-select-options');
    const items = Array.from(panel.querySelectorAll('li:not(.is-empty):not(.is-create)'));
    const word = keyword.trim().toLowerCase();
    const current = box.querySelector('[data-field]')?.value || '';
    let visible = 0;
    items.forEach(item => {
        const hit = !word || item.textContent.toLowerCase().includes(word);
        item.hidden = !hit;
        item.classList.remove('is-active');
        // 当前选中的那条高亮，跟 OA 的下拉一致
        item.classList.toggle('is-selected', Boolean(current) && item.dataset.value === current);
        if (hit) visible += 1;
    });
    const create = ensureSelectItem(panel, 'is-create');
    const empty = ensureSelectItem(panel, 'is-empty', '没有匹配的选项');
    create.hidden = true;
    empty.hidden = true;
    if (visible) return;
    // 允许自定义值的字段，把输入的内容当成一个可选项
    if (box.hasAttribute('data-create') && keyword.trim()) {
        const text = keyword.trim();
        create.hidden = false;
        create.dataset.value = text;
        create.dataset.label = text;
        create.textContent = `使用“${text}”`;
    } else {
        empty.hidden = false;
    }
}

function openSelect(box) {
    inquiryEls.goodsRows.querySelectorAll('[data-select].is-open').forEach(other => {
        if (other !== box) closeSelect(other);
    });
    const input = box.querySelector('.inquiry-select-input');
    const label = input.dataset.label || '';
    box.classList.add('is-open');
    box.querySelector('.inquiry-select-options').hidden = false;
    // 已选文案变成灰字提示，光标停在末尾，不整段选中
    input.value = label;
    input.dataset.hint = label ? '1' : '0';
    input.classList.toggle('is-hint', Boolean(label));
    filterSelect(box, '');
    input.setSelectionRange(input.value.length, input.value.length);
}

function pickSelect(item) {
    const box = item.closest('[data-select]');
    const input = box.querySelector('.inquiry-select-input');
    const hidden = box.querySelector('[data-field]');
    const text = item.dataset.label || item.textContent;
    input.value = text;
    input.dataset.label = text;
    input.dataset.hint = '0';
    input.classList.remove('is-hint');
    hidden.value = item.dataset.value || text;
    box.classList.remove('is-open');
    box.querySelector('.inquiry-select-options').hidden = true;
    hidden.dispatchEvent(new Event('change', {bubbles: true}));
}

inquiryEls.goodsRows?.addEventListener('focusin', event => {
    const box = event.target.closest?.('[data-select]');
    if (box && event.target.classList.contains('inquiry-select-input')) openSelect(box);
});

inquiryEls.goodsRows?.addEventListener('input', event => {
    const box = event.target.closest('[data-select]');
    if (!box || !event.target.classList.contains('inquiry-select-input')) return;
    const input = event.target;
    // 灰字状态下开始打字，用输入的内容整段替换掉已选文案
    if (input.dataset.hint === '1') {
        const label = input.dataset.label || '';
        if (label && input.value.startsWith(label)) input.value = input.value.slice(label.length);
        input.dataset.hint = '0';
        input.classList.remove('is-hint');
    }
    box.querySelector('.inquiry-select-options').hidden = false;
    filterSelect(box, input.value);
});

inquiryEls.goodsRows?.addEventListener('mousedown', event => {
    // 点面板时别让输入框失焦，否则面板会先被关掉
    if (event.target.closest('.inquiry-select-options')) event.preventDefault();
});

inquiryEls.goodsRows?.addEventListener('focusout', event => {
    const box = event.target.closest?.('[data-select]');
    if (box && !box.contains(event.relatedTarget)) closeSelect(box);
});

inquiryEls.goodsRows?.addEventListener('click', event => {
    const input = event.target.closest('.inquiry-select-input');
    if (input) openSelect(input.closest('[data-select]'));
    const item = event.target.closest('.inquiry-select-options li');
    if (item && !item.classList.contains('is-empty')) pickSelect(item);
});

inquiryEls.goodsRows?.addEventListener('keydown', event => {
    const box = event.target.closest?.('[data-select]');
    if (!box) return;
    const items = Array.from(box.querySelectorAll('.inquiry-select-options li'))
        .filter(item => !item.hidden && !item.classList.contains('is-empty'));
    if (event.key === 'Escape') {
        event.stopPropagation();
        closeSelect(box);
        return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (box.querySelector('.inquiry-select-options').hidden) {
            openSelect(box);
            return;
        }
        const active = box.querySelector('li.is-active');
        const index = active ? items.indexOf(active) : -1;
        const next = event.key === 'ArrowDown'
            ? Math.min(items.length - 1, index + 1)
            : Math.max(0, index - 1);
        items.forEach(item => item.classList.remove('is-active'));
        items[next]?.classList.add('is-active');
        return;
    }
    if (event.key === 'Enter') {
        event.preventDefault();
        const active = box.querySelector('li.is-active') || items[0];
        if (active) pickSelect(active);
    }
});

document.addEventListener('mousedown', event => {
    if (!event.target.closest?.('[data-select]')) {
        inquiryEls.goodsRows?.querySelectorAll('[data-select].is-open').forEach(closeSelect);
    }
});

inquiryEls.goodsRows?.addEventListener('dragover', event => {
    const zone = event.target.closest('[data-drop-zone]');
    if (!zone) return;
    event.preventDefault();
    zone.classList.add('is-drag');
});
inquiryEls.goodsRows?.addEventListener('dragleave', event => {
    const zone = event.target.closest('[data-drop-zone]');
    // 移到子元素时不算离开
    if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-drag');
});
inquiryEls.goodsRows?.addEventListener('drop', event => {
    const zone = event.target.closest('[data-drop-zone]');
    if (!zone) return;
    event.preventDefault();
    zone.classList.remove('is-drag');
    const card = zone.closest('[data-goods-index]');
    if (card) inquiryState.activeIndex = Number(card.dataset.goodsIndex);
    appendImageFiles(
        inquiryState.goods[Number(card?.dataset.goodsIndex)],
        imagesFromTransfer(event.dataTransfer),
    );
});
// 图片拖到弹窗空白处时别让浏览器直接打开图片
['dragover', 'drop'].forEach(type => {
    inquiryEls.overlay?.addEventListener(type, event => {
        if (!event.target.closest('[data-drop-zone]')) event.preventDefault();
    });
});

document.addEventListener('paste', event => {
    if (!inquiryEls.overlay?.classList.contains('show')) return;
    const files = imagesFromTransfer(event.clipboardData);
    if (!files.length) return;
    event.preventDefault();
    const good = inquiryState.goods[inquiryState.activeIndex] || inquiryState.goods[0];
    appendImageFiles(good, files);
});

inquiryEls.goodsRows?.addEventListener('focusin', event => {
    const card = event.target.closest('[data-goods-index]');
    if (card) inquiryState.activeIndex = Number(card.dataset.goodsIndex);
});

inquiryEls.goodsRows?.addEventListener('click', event => {
    const cardEl = event.target.closest('[data-goods-index]');
    if (cardEl) inquiryState.activeIndex = Number(cardEl.dataset.goodsIndex);
    const removeImage = event.target.closest('[data-remove-image]');
    if (removeImage) {
        const card = removeImage.closest('[data-goods-index]');
        const good = inquiryState.goods[Number(card?.dataset.goodsIndex)];
        const index = Number(removeImage.dataset.removeImage);
        const item = good?.files[index];
        if (!item) return;
        URL.revokeObjectURL(item.url);
        good.files.splice(index, 1);
        renderGoodsRows();
        return;
    }
    const preview = event.target.closest('[data-preview-image]');
    if (preview) {
        const card = preview.closest('[data-goods-index]');
        const good = inquiryState.goods[Number(card?.dataset.goodsIndex)];
        if (good?.files?.length) openViewer(good.files.map(item => item.url), Number(preview.dataset.previewImage));
        return;
    }
    const button = event.target.closest('[data-remove]');
    if (!button) return;
    const card = button.closest('[data-goods-index]');
    if (!card || inquiryState.goods.length === 1) return;
    inquiryState.goods.splice(Number(card.dataset.goodsIndex), 1);
    renderGoodsRows();
});

document.addEventListener('keydown', event => {
    if (viewerEls?.root.classList.contains('show')) {
        if (event.key === 'Escape') closeViewer();
        if (event.key === 'ArrowLeft') stepViewer(-1);
        if (event.key === 'ArrowRight') stepViewer(1);
        return;
    }
    if (event.key !== 'Escape') return;
    if (addressDialogEl?.classList.contains('show')) {
        closeAddressDialog();
        return;
    }
    if (inquiryEls.picker?.classList.contains('show')) {
        closePicker();
        return;
    }
    if (inquiryEls.overlay?.classList.contains('show')) backToClientPicker();
});

