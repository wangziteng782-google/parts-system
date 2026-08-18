// ========== 层级规格渲染（动态支持任意层级） ==========
        function renderVariantHierarchy() {
            if (!currentVariantSpecs.length) return '';
            const pendingRequiredSpecs = currentVariantSpecs.filter(
                spec => spec.is_required && (!spec.values || !spec.values.length)
            );
            const pendingHint = pendingRequiredSpecs.length
                ? `<div class="required-spec-pending">固定规格“${pendingRequiredSpecs.map(
                    spec => escapeHtml(spec.spec_name)
                ).join('、')}”暂未填写，不影响使用其他已配置规格查询和维护供应商价格。</div>`
                : '';
            const selectableSpecs = currentVariantSpecs.filter(
                spec => spec.values && spec.values.length
            );
            if (!selectableSpecs.length) {
                return pendingHint || '<div class="vs-no-data">暂无可选择的规格值。</div>';
            }

            // 递归渲染层级
            function renderLevel(level, currentSpecs) {
                if (level >= selectableSpecs.length) return '';

                const spec = selectableSpecs[level];
                const isLastLevel = level === selectableSpecs.length - 1;
                let html = '';

                spec.values.forEach(v => {
                    const specs = [...currentSpecs, { name: spec.spec_name, value: v.value }];
                    const hasPersistedBranch = currentVariantCombinations.some(combo => combo.is_active &&
                        specs.every(selected => combo.specs?.some(
                            item => item.name === selected.name && item.value === selected.value
                        ))
                    );
                    if (!hasPersistedBranch) return;

                    if (isLastLevel) {
                        // 最后一层：显示可点击的规格项
                        const combination = currentVariantCombinations.find(combo => combo.is_active &&
                            matchSpecs(combo.specs, specs)
                        );
                        if (!combination) return;
                        const prices = combination.prices || [];
                        html += renderSpecItem(spec.spec_name, v.value, specs, prices);
                    } else {
                        // 中间层：显示分组标题，递归下一层
                        html += `<div class="vs-level vs-level-${level + 1}">`;
                        html += `<div class="vs-level-header vs-level-${level + 1}-header">`;
                        html += `<span class="vs-level-label vs-level-${level + 1}-label"><span class="key">${escapeHtml(spec.spec_name)}：</span><span class="val">${escapeHtml(v.value)}</span></span>`;
                        html += `</div>`;
                        html += `<div class="vs-level-content">`;
                        html += renderLevel(level + 1, specs);
                        html += `</div>`;
                        html += `</div>`;
                    }
                });

                // 如果是最后一层，包裹在 grid 容器中
                if (isLastLevel) {
                    html = `<div class="vs-grid">${html}</div>`;
                }

                return html;
            }

            return pendingHint + renderLevel(0, []);
        }

        function matchSpecs(priceSpecs, targetSpecs) {
            if (!priceSpecs || priceSpecs.length !== targetSpecs.length) return false;
            return targetSpecs.every(ts => priceSpecs.some(ps => ps.name === ts.name && ps.value === ts.value));
        }

        function hasConfiguredSupplierPrice(value) {
            return value !== null && value !== undefined && String(value).trim() !== '';
        }

        function supplierInvoicePriceText(value, invoiceName) {
            if (!hasConfiguredSupplierPrice(value)) return null;
            if (Number(value) === 0) return `可开${invoiceName}（价格待定）`;
            return `¥${String(value)}`;
        }

        function formatSpecSupplierPrice(value, invoiceName = '') {
            if (value === null || value === undefined || String(value).trim() === '') {
                return '<span class="vs-price-empty">未配置</span>';
            }
            if (invoiceName && Number(value) === 0) {
                return `<span class="vs-price-available">${escapeHtml(`可开${invoiceName}（价格待定）`)}</span>`;
            }
            return `<span class="vs-price-amount">¥${escapeHtml(String(value))}</span>`;
        }

        function renderSpecItem(specName, specValue, specs, prices) {
            const hasSupplier = prices.length > 0;
            let supplierPricesHtml = '';
            if (hasSupplier) {
                supplierPricesHtml = prices.map(p => {
                    const name = escapeHtml(p.supplier || '未命名');
                    const cap = p.oa_supplier_id ? _oaSupplierCapability[p.oa_supplier_id] : null;
                    return `<div class="vs-supplier-price-card">
                        <div class="vs-supplier-price-name">${name}</div>
                        <div class="vs-supplier-price-list">
                            <div class="vs-supplier-price-row">
                                <span class="vs-price-label">不含票单价</span>
                                ${(!cap || cap.is_no_tax) ? formatSpecSupplierPrice(p.no_tax_price) : '<span class="vs-price-empty">不支持</span>'}
                            </div>
                            <div class="vs-supplier-price-row">
                                <span class="vs-price-label">含专票</span>
                                ${(!cap || cap.is_special) ? formatSpecSupplierPrice(p.purchase_special_invoice, '专票') : '<span class="vs-price-empty">不支持</span>'}
                            </div>
                            <div class="vs-supplier-price-row">
                                <span class="vs-price-label">含普票</span>
                                ${(!cap || cap.is_normal) ? formatSpecSupplierPrice(p.purchase_general_invoice, '普票') : '<span class="vs-price-empty">不支持</span>'}
                            </div>
                        </div>
                    </div>`;
                }).join('');
            } else {
                supplierPricesHtml = '<span class="no-supplier-text">未配置供应商</span>';
            }
            const specsJson = JSON.stringify(specs).replace(/"/g, '&quot;');
            const classes = ['vs-spec-item'];
            if (!hasSupplier) classes.push('no-supplier');
            return `<div class="${classes.join(' ')}" onclick="openSupplierPanel('${specsJson}')">
                <div class="vs-spec-title"><span class="vs-spec-key">${escapeHtml(specName)}：</span><span class="vs-spec-value">${escapeHtml(specValue)}</span></div>
                <div class="vs-supplier-prices">${supplierPricesHtml}</div>
            </div>`;
        }

        function selectVariantSpecs(el, specsJson) {
            const specs = JSON.parse(specsJson.replace(/&quot;/g, '"'));
            // 更新选中状态
            selectedVariantValues = specs;
            // 更新 UI
            document.querySelectorAll('.vs-spec-item').forEach(item => item.classList.remove('selected'));
            el.classList.add('selected');
            // 触发供应商选择
            updateSupplierSelector();
        }

        // ========== 供应商面板（向左滑出） ==========
        let currentPanelSpecs = null;
        let currentPanelPriceId = null;
        let isNewSupplierMode = false; // 标记是否处于新增模式

        async function openSupplierPanel(specsJson) {
            currentPanelSpecs = JSON.parse(specsJson.replace(/&quot;/g, '"'));
            currentPanelPriceId = null;
            isNewSupplierMode = false;

            let panel = document.getElementById('supplierPanel');
            if (!panel) {
                panel = document.createElement('div');
                panel.id = 'supplierPanel';
                panel.className = 'supplier-panel-overlay';
                panel.addEventListener('click', e => { if (e.target === panel) closeSupplierPanel(); });
                document.body.appendChild(panel);
            }
            // 创建面板容器结构（只创建一次）
            const specTitle = currentPanelSpecs.map(s => `${s.name}: ${s.value}`).join(' / ');
            panel.innerHTML = `<div class="sp-container">
                <div class="sp-header">
                    <div class="sp-header-left">
                        <span class="sp-header-title">供应商管理</span>
                        <span class="sp-header-spec">${escapeHtml(specTitle)}</span>
                    </div>
                    <div class="sp-header-right">
                        <button class="sp-close-btn" onclick="closeSupplierPanel()">×</button>
                    </div>
                </div>
                <div class="sp-body">
                    <div class="sp-left">
                        <div class="sp-list-title">
                            <span>供应商列表 (<span id="spSupplierCount">0</span>)</span>
                            <button class="sp-add-btn-small" onclick="addPanelSupplier()">+ 新增</button>
                        </div>
                        <div class="sp-list" id="spSupplierList"></div>
                    </div>
                    <div class="sp-right" id="spDetailArea"></div>
                </div>
            </div>`;
            panel.classList.add('open');
            // 渲染内容
            renderPanelContent();
        }

        // 只更新内容区域（左侧列表 + 右侧详情），不重新创建容器
        async function renderPanelContent() {
            if (!currentPanelSpecs) return;

            const matchingPrices = currentVariantPrices.filter(p => matchSpecs(p.specs, currentPanelSpecs));

            // 预加载所有供应商的开票能力，用于判断是否显示价格
            const oaIds = [...new Set(matchingPrices.map(p => p.oa_supplier_id).filter(Boolean))];
            await Promise.all(oaIds.map(id => _loadOaSupplierCapability(id)));

            // 更新供应商数量
            const countEl = document.getElementById('spSupplierCount');
            if (countEl) countEl.textContent = matchingPrices.length;

            // 左侧供应商列表
            const listEl = document.getElementById('spSupplierList');
            if (listEl) {
                if (matchingPrices.length > 0) {
                    listEl.innerHTML = matchingPrices.map(p => {
                        const isActive = currentPanelPriceId === p.id;
                        const extFields = (p.external_price_fields || '').split(',').filter(Boolean);
                        const cap = p.oa_supplier_id ? _oaSupplierCapability[p.oa_supplier_id] : null;
                        const priceMap = {
                            no_tax: (!cap || cap.is_no_tax) && hasConfiguredSupplierPrice(p.no_tax_price) ? `¥${escapeHtml(String(p.no_tax_price))}` : null,
                            special: (!cap || cap.is_special) && supplierInvoicePriceText(p.purchase_special_invoice, '专票'),
                            general: (!cap || cap.is_normal) && supplierInvoicePriceText(p.purchase_general_invoice, '普票'),
                        };
                        const labelMap = { no_tax: '不含票', special: '含专票', general: '含普票' };
                        // 展示全部 3 个价格，对外展示的加标记
                        const allRows = Object.keys(labelMap).map(f => {
                            const val = priceMap[f] || '-';
                            const badge = extFields.includes(f) ? '<span class="sp-ext-badge">外</span>' : '';
                            return `<div class="sp-info-row"><span class="sp-label">${labelMap[f]}</span><span class="sp-val">${escapeHtml(val)}${badge}</span></div>`;
                        }).join('');
                        return `<div class="sp-supplier-card ${isActive ? 'active' : ''}" data-price-id="${p.id}" onclick="selectPanelSupplier(${p.id})">
                            <div class="sp-card-header">
                                <span class="sp-card-name">${escapeHtml(p.supplier || '未命名')}</span>
                                <button class="sp-card-del" onclick="event.stopPropagation();deletePanelSupplier(${p.id})" title="删除">×</button>
                            </div>
                            ${allRows ? `<div class="sp-card-info">${allRows}</div>` : ''}
                        </div>`;
                    }).join('');
                } else {
                    listEl.innerHTML = '<div class="sp-empty">暂无供应商，点击上方按钮添加</div>';
                }
            }

            // 右侧详情表单
            const detailEl = document.getElementById('spDetailArea');
            if (detailEl) {
                // 缓存同规格组合的所有供应商价格 + 当前编辑的 priceId，供 _limitExtFields 统计用
                detailEl.dataset.matchingPrices = JSON.stringify(matchingPrices);
                detailEl.dataset.currentPriceId = currentPanelPriceId || '';
                if (isNewSupplierMode) {
                    detailEl.innerHTML = renderSupplierDetailForm({ isNew: true });
                    loadSupplierDropdown(''); // 加载供应商列表（旧，兼容）
                    _initSupplierSelect(null, ''); // 初始化 OA 供应商下拉
                    _limitExtFields(); // 应用对外展示数量限制
                } else if (currentPanelPriceId) {
                    const p = matchingPrices.find(x => x.id === currentPanelPriceId);
                    if (p) {
                        detailEl.innerHTML = renderSupplierDetailForm(p);
                        loadSupplierDropdown(p.supplier); // 加载并选中当前供应商（旧，兼容）
                        _initSupplierSelect(p.oa_supplier_id, p.supplier); // 初始化 OA 供应商下拉
                        _limitExtFields(); // 应用对外展示数量限制
                    }
                } else {
                    detailEl.innerHTML = '<div class="sp-detail-empty">请选择左侧供应商查看详情，或点击上方按钮新增供应商</div>';
                }
            }
        }

        function toggleSupplierFreight() {
            const shipType = document.querySelector('input[name="spShipType"]:checked')?.value || '';
            document.getElementById('spShipIncludeBox')?.classList.toggle('hide', shipType !== 'include');
            document.getElementById('spShipExcludeBox')?.classList.toggle('hide', shipType !== 'exclude');
        }

        function showSupplierRequiredError(element, message) {
            if (element) {
                element.classList.add('sp-input-error');
                element.scrollIntoView({behavior:'smooth', block:'center'});
                element.focus();
                element.addEventListener('input', () => element.classList.remove('sp-input-error'), {once:true});
            }
            showToast(message, 'error');
            return false;
        }

        function requiredSupplierPrice(inputId, label) {
            const input = document.getElementById(inputId);
            const raw = input?.value.trim() || '';
            if (raw === '' || !Number.isFinite(Number(raw)) || Number(raw) < 0) {
                showSupplierRequiredError(input, `请填写正确的${label}`);
                return null;
            }
            return Number(raw);
        }

        // 加载供应商名称候选项；输入框既可搜索选择，也可直接填写新名称
        async function loadSupplierDropdown(selectedValue) {
            const inputEl = document.getElementById('spSupplierName');
            const listEl = document.getElementById('spSupplierNameList');
            if (!inputEl || !listEl) return;
            inputEl.value = selectedValue || '';
            
            try {
                const res = await fetch('/api/suppliers');
                if (!res.ok) return;
                const suppliers = await res.json();

                // 兜底：若当前供应商不在列表中（如来自价格表的供应商未收录进 parts 表），强制加入并选中
                const supplierList = Array.isArray(suppliers) ? suppliers.slice() : [];
                if (selectedValue && !supplierList.includes(selectedValue)) {
                    supplierList.unshift(selectedValue);
                }

                listEl.innerHTML = supplierList.map(s => `<option value="${escapeHtml(s)}"></option>`).join('');
            } catch (e) {
                console.error('加载供应商列表失败:', e);
            }
        }

        function closeSupplierPanel() {
            const panel = document.getElementById('supplierPanel');
            if (panel) panel.classList.remove('open');
            refreshSpecItemData();
        }

        async function refreshSpecItemData() {
            if (!currentProductId) return;
            const [sRes, pRes, cRes] = await Promise.all([
                fetch(`/api/products/${currentProductId}/variant-specs`),
                fetch(`/api/products/${currentProductId}/variant-prices`),
                fetch(`/api/products/${currentProductId}/variant-combinations`)
            ]);
            currentVariantSpecs = sRes.ok ? await sRes.json() : [];
            currentVariantPrices = pRes.ok ? await pRes.json() : [];
            currentVariantCombinations = cRes.ok ? await cRes.json() : [];
            if (currentData) renderDetail(currentData);
            if (document.getElementById('variantSpecManagerModal')?.classList.contains('open')) {
                await loadVariantManager();
            }
        }

        // OA 供应商缓存（避免重复请求）
        let _oaSupplierCache = null;
        let _oaSupplierCapability = {}; // { oa_supplier_id: { is_special_invoice, is_normal_invoice, is_no_invoice, tax_points } }

        async function _loadOaSuppliers() {
            if (_oaSupplierCache) return _oaSupplierCache;
            try {
                const res = await fetch('/api/suppliers');
                if (res.ok) _oaSupplierCache = await res.json();
            } catch (e) { /* 忽略，使用手动输入兜底 */ }
            return _oaSupplierCache || [];
        }

        async function _loadOaSupplierCapability(oaId) {
            if (!oaId || _oaSupplierCapability[oaId]) return _oaSupplierCapability[oaId];
            try {
                const res = await fetch(`/api/oa/suppliers/${oaId}`);
                if (res.ok) {
                    const data = await res.json();
                    const parseTaxPoint = (v) => { const n = parseFloat(String(v).replace('%', '')); return isNaN(n) ? 0 : n; };
                    _oaSupplierCapability[oaId] = {
                        is_special: !!data.is_special_invoice,
                        is_normal: !!data.is_normal_invoice,
                        is_no_tax: !!data.is_no_invoice,
                        special_tax: parseTaxPoint(data.special_tax_point),
                        normal_tax: parseTaxPoint(data.normal_tax_point),
                        no_tax_point: parseTaxPoint(data.no_tax_point),
                    };
                }
            } catch (e) { /* 忽略 */ }
            return _oaSupplierCapability[oaId] || null;
        }

        // 根据供应商选择更新开票能力 → 禁用不支持的票种输入框和对外展示开关
        async function _onSupplierChanged() {
            const oaSel = document.getElementById('spOaSupplierSelect');
            const oaId = oaSel ? Number(oaSel.value) : null;
            const cap = oaId ? await _loadOaSupplierCapability(oaId) : null;
            const fields = [
                { key: 'noTax', input: 'spInputNoTax', extSwitch: 'spExtNoTax', supported: cap ? cap.is_no_tax : true },
                { key: 'special', input: 'spSpecialVal', extSwitch: 'spExtSpecial', supported: cap ? cap.is_special : true },
                { key: 'normal', input: 'spNormalVal', extSwitch: 'spExtNormal', supported: cap ? cap.is_normal : true },
            ];
            for (const f of fields) {
                const inp = document.getElementById(f.input);
                const sw = document.getElementById(f.extSwitch);
                if (!f.supported) {
                    if (inp) { inp.value = ''; inp.disabled = true; inp.classList.add('sp-input-disabled'); }
                    if (sw) { sw.checked = false; sw.disabled = true; sw.dataset.oaDisabled = '1'; }
                } else {
                    if (inp) { inp.disabled = false; inp.classList.remove('sp-input-disabled'); }
                    if (sw) { sw.disabled = false; sw.dataset.oaDisabled = ''; }
                }
            }
            // 重新校验3选限制（供应商变更后可能所有开关都启用）
            _limitExtFields();
            // 缓存税点供价格自动计算使用 + 显示税率
            const taxRow = document.getElementById('spTaxRateRow');
            const taxSpecialEl = document.getElementById('spTaxSpecial');
            const taxNormalEl = document.getElementById('spTaxNormal');
            if (cap) {
                document.getElementById('spDetailArea').dataset.taxSpecial = cap.special_tax;
                document.getElementById('spDetailArea').dataset.taxNormal = cap.normal_tax;
                if (taxSpecialEl) taxSpecialEl.textContent = cap.special_tax || '—';
                if (taxNormalEl) taxNormalEl.textContent = cap.normal_tax || '—';
                if (taxRow) taxRow.classList.remove('hide');
            } else {
                document.getElementById('spDetailArea').dataset.taxSpecial = 0;
                document.getElementById('spDetailArea').dataset.taxNormal = 0;
                if (taxRow) taxRow.classList.add('hide');
            }
        }

        // 价格自动计算：填写一个价格 → 根据税点算另外两个
        function _autoCalcPrices(sourceKey) {
            const taxSpecial = Number(document.getElementById('spDetailArea')?.dataset.taxSpecial) || 0;
            const taxNormal = Number(document.getElementById('spDetailArea')?.dataset.taxNormal) || 0;
            const noTaxEl = document.getElementById('spInputNoTax');
            const specialEl = document.getElementById('spSpecialVal');
            const normalEl = document.getElementById('spNormalVal');
            if (!noTaxEl || !specialEl || !normalEl) return;

            const noTaxVal = noTaxEl.value.trim();
            const specialVal = specialEl.value.trim();
            const normalVal = normalEl.value.trim();

            if (sourceKey === 'noTax' && noTaxVal !== '' && !isNaN(Number(noTaxVal))) {
                const base = Number(noTaxVal);
                if (taxSpecial) specialEl.value = (base * (1 + taxSpecial / 100)).toFixed(2);
                if (taxNormal) normalEl.value = (base * (1 + taxNormal / 100)).toFixed(2);
            } else if (sourceKey === 'special' && specialVal !== '' && !isNaN(Number(specialVal)) && taxSpecial) {
                const base = Number(specialVal) / (1 + taxSpecial / 100);
                noTaxEl.value = base.toFixed(2);
                if (taxNormal) normalEl.value = (base * (1 + taxNormal / 100)).toFixed(2);
            } else if (sourceKey === 'normal' && normalVal !== '' && !isNaN(Number(normalVal)) && taxNormal) {
                const base = Number(normalVal) / (1 + taxNormal / 100);
                noTaxEl.value = base.toFixed(2);
                if (taxSpecial) specialEl.value = (base * (1 + taxSpecial / 100)).toFixed(2);
            }
        }

        function renderSupplierDetailForm(p) {
            const isNew = p.isNew || false;
            const hasNoTax = !isNew && p.no_tax_price !== null && p.no_tax_price !== undefined && p.no_tax_price !== '';
            const hasSpecial = !isNew && p.purchase_special_invoice !== null && p.purchase_special_invoice !== undefined && p.purchase_special_invoice !== '';
            const hasNormal = !isNew && p.purchase_general_invoice !== null && p.purchase_general_invoice !== undefined && p.purchase_general_invoice !== '';
            const freightChoice = p.freight_remark === '不含运费' ? 'exclude' : (p.freight_remark ? 'include' : '');
            // external_price_fields → 三个 SET 开关
            const extFields = (p.external_price_fields || '').split(',').filter(Boolean);
            const extNoTax = extFields.includes('no_tax');
            const extSpecial = extFields.includes('special');
            const extNormal = extFields.includes('general');
            return `<div class="sp-detail-form">
                <!-- 基础信息 -->
                <div class="sp-card">
                    <h3>基础信息</h3>
                    <div class="sp-row-main" style="margin-top:12px;">
                        <div class="sp-col-item" style="flex:2">
                            <label>供应商名称<span class="sp-required-mark">*</span></label>
                            <select id="spOaSupplierSelect" class="sp-input-text" style="width:100%" onchange="_onSupplierChanged()">
                                <option value="">-- 选择或手动输入 --</option>
                            </select>
                            <input id="spSupplierName" class="sp-input-text" style="margin-top:6px" placeholder="手动输入供应商名称（非OA供应商）" value="${escapeHtml(p.supplier || '')}">
                        </div>
                    </div>
                </div>

                <!-- 供应商报价设置 -->
                <div class="sp-card">
                    <div class="sp-card-title-bar">
                        <h3>供应商报价设置<span class="sp-required-mark">*</span><span class="sp-required-tip">至少填写一种报价</span></h3>
                    </div>
                    <div id="spTaxRateRow" class="sp-tax-rate-row hide">
                        <span class="sp-tax-rate-label">供应商税率：</span>
                        <span class="sp-tax-rate-item">含专票 <strong id="spTaxSpecial">—</strong>%</span>
                        <span class="sp-tax-rate-item">含普票 <strong id="spTaxNormal">—</strong>%</span>
                    </div>

                    <!-- 多报价区域 -->
                    <div id="spMultiPriceBox" class="sp-row-main">
                        <!-- 不含票单价 -->
                        <div class="sp-col-item">
                            <div class="sp-title-row">
                                <label>不含票单价<span class="sp-required-mark">*</span></label>
                                <label class="sp-ext-mini">
                                    <span class="sp-toggle">
                                        <input id="spExtNoTax" type="checkbox" ${extNoTax ? 'checked' : ''} data-was-checked="${extNoTax ? '1' : ''}" data-oa-disabled="" onchange="_limitExtFields()">
                                        <span class="sp-toggle-track"></span>
                                    </span>
                                    <small>展示</small>
                                </label>
                            </div>
                            <input id="spInputNoTax" class="sp-input-money" type="text" value="${p.no_tax_price ?? ''}" placeholder="0.00" onblur="_autoCalcPrices('noTax')">
                        </div>

                        <!-- 含专票 -->
                        <div class="sp-col-item">
                            <div class="sp-title-row">
                                <label>含专票<span class="sp-required-mark">*</span></label>
                                <label class="sp-ext-mini">
                                    <span class="sp-toggle">
                                        <input id="spExtSpecial" type="checkbox" ${extSpecial ? 'checked' : ''} data-was-checked="${extSpecial ? '1' : ''}" data-oa-disabled="" onchange="_limitExtFields()">
                                        <span class="sp-toggle-track"></span>
                                    </span>
                                    <small>展示</small>
                                </label>
                            </div>
                            <input id="spSpecialVal" class="sp-input-money" type="text" value="${p.purchase_special_invoice ?? ''}" placeholder="0.00" onblur="_autoCalcPrices('special')">
                        </div>

                        <!-- 含普票 -->
                        <div class="sp-col-item">
                            <div class="sp-title-row">
                                <label>含普票<span class="sp-required-mark">*</span></label>
                                <label class="sp-ext-mini">
                                    <span class="sp-toggle">
                                        <input id="spExtNormal" type="checkbox" ${extNormal ? 'checked' : ''} data-was-checked="${extNormal ? '1' : ''}" data-oa-disabled="" onchange="_limitExtFields()">
                                        <span class="sp-toggle-track"></span>
                                    </span>
                                    <small>展示</small>
                                </label>
                            </div>
                            <input id="spNormalVal" class="sp-input-money" type="text" value="${p.purchase_general_invoice ?? ''}" placeholder="0.00" onblur="_autoCalcPrices('normal')">
                        </div>
                    </div>
                    </div>

                    <!-- 报价有效期 -->
                    <div class="sp-section-gap">
                        <div class="sp-col-item">
                            <label>报价有效期</label>
                            <input id="spValidTime" class="sp-input-text" type="text" value="${escapeHtml(p.expire_date || '')}" placeholder="如：2024-12-31 或 30天">
                        </div>
                    </div>
                </div>

                <!-- 运费 + 发货 -->
                <div class="sp-row-main">
                    <!-- 供应商运费设置 -->
                    <div class="sp-card">
                        <h3>供应商运费设置<span class="sp-required-mark">*</span><span class="sp-required-tip">请选择含运费或不含运费</span></h3>
                        <div class="sp-radio-group" style="margin-top:12px;">
                            <input type="radio" id="spShip-include" name="spShipType" value="include" ${freightChoice === 'include' ? 'checked' : ''} onchange="toggleSupplierFreight()">
                            <label for="spShip-include">含运费</label>
                            <input type="radio" id="spShip-exclude" name="spShipType" value="exclude" ${freightChoice === 'exclude' ? 'checked' : ''} onchange="toggleSupplierFreight()">
                            <label for="spShip-exclude">不含运费</label>
                        </div>
                        <!-- 含运费区域 -->
                        <div id="spShipIncludeBox" class="${freightChoice === 'include' ? '' : 'hide'}">
                            <div class="sp-col-item">
                                <div class="sp-remark-label-row">
                                    <label>运费备注说明</label>
                                    <span class="sp-tag" onclick="document.getElementById('spShipRemarkInclude').value='偏远地区不包邮(偏远地区包括:青海、新疆、云南、内蒙、海南、西藏)'">偏远地区不包邮</span>
                                </div>
                                <textarea id="spShipRemarkInclude" placeholder="可填写包邮物流公司、不包邮地区等">${escapeHtml(p.freight_remark && p.freight_remark !== '不含运费' ? p.freight_remark : '')}</textarea>
                            </div>
                        </div>
                        <!-- 不含运费区域 -->
                        <div id="spShipExcludeBox" class="${freightChoice === 'exclude' ? '' : 'hide'}">
                            <div class="sp-col-item">
                                <div class="sp-remark-label-row">
                                    <label>运费备注说明</label>
                                    <span class="sp-tag" onclick="document.getElementById('spShipRemarkExclude').value='偏远地区不包邮(偏远地区包括:青海、新疆、云南、内蒙、海南、西藏)'">偏远地区不包邮</span>
                                </div>
                                <textarea id="spShipRemarkExclude" placeholder="运费相关约定备注"></textarea>
                            </div>
                        </div>
                    </div>

                    <!-- 发货设置 -->
                    <div class="sp-card">
                        <h3>发货设置</h3>
                        <div class="sp-form-stack">
                            <div class="sp-col-item">
                                <label>发货时间</label>
                                <input id="spDeliveryTime" class="sp-input-text" type="text" value="${escapeHtml(p.shipping_time || '')}">
                            </div>
                            <div class="sp-col-item">
                                <label>发货地</label>
                                <input id="spDeliveryPlace" class="sp-input-text" placeholder="省/市/仓库" value="${escapeHtml(p.shipping_origin || '')}">
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 质保设置 + 备注 -->
                <div class="sp-row-main">
                    <!-- 质保设置 -->
                    <div class="sp-card">
                        <h3>质保设置<span class="sp-required-mark">*</span></h3>
                        <div class="sp-col-item" style="margin-top:12px;">
                            <div class="sp-label-row">
                                <label>质保时间<span class="sp-required-mark">*</span></label>
                                <div class="sp-tag-group">
                                    <span class="sp-tag" onclick="document.getElementById('spWarrantyTime').value='6个月'">6个月</span>
                                    <span class="sp-tag" onclick="document.getElementById('spWarrantyTime').value='12个月'">12个月</span>
                                    <span class="sp-tag" onclick="document.getElementById('spWarrantyTime').value='无质保'">无质保</span>
                                </div>
                            </div>
                            <input id="spWarrantyTime" class="sp-input-text" placeholder="如：质保1年、终身质保" value="${escapeHtml(p.warranty_time || '')}">
                        </div>
                    </div>

                    <!-- 备注 -->
                    <div class="sp-card">
                        <h3>备注</h3>
                        <div class="sp-col-item" style="margin-top:12px;">
                            <textarea id="spRemark" placeholder="请输入相关补充说明">${escapeHtml(p.remark || '')}</textarea>
                        </div>
                    </div>
                </div>

                <!-- 保存按钮 -->
                <div class="sp-form-actions">
                    <button class="sp-save-btn" onclick="savePanelSupplier(${p.id || 'null'})">${isNew ? '保存新增' : '保存修改'}</button>
                </div>
            </div>`;
        }

        function selectPanelSupplier(priceId) {
            currentPanelPriceId = priceId;
            isNewSupplierMode = false; // 退出新增模式
            renderPanelContent();
        }

        async function addPanelSupplier() {
            // 进入新增模式，显示空表单但不入库
            isNewSupplierMode = true;
            currentPanelPriceId = null;
            renderPanelContent();
        }

        let supplierSaveInProgress = false;

        // 对外展示限制：1) 每个价格类型只能被一个供应商展示；2) 同规格组合下最多展示 3 个价格
        function _limitExtFields() {
            const ids = ['spExtNoTax', 'spExtSpecial', 'spExtNormal'];
            const fieldMap = { spExtNoTax: 'no_tax', spExtSpecial: 'special', spExtNormal: 'general' };
            // 统计同规格组合下其他供应商已对外展示的价格
            const matchingPrices = JSON.parse(document.getElementById('spDetailArea')?.dataset.matchingPrices || '[]');
            const currentPriceId = document.getElementById('spDetailArea')?.dataset.currentPriceId || null;
            const otherExtTypes = new Set();
            let savedExtCount = 0;
            for (const p of matchingPrices) {
                if (currentPriceId && String(p.id) === String(currentPriceId)) continue;
                const fields = (p.external_price_fields || '').split(',').filter(Boolean);
                fields.forEach(f => otherExtTypes.add(f));
                savedExtCount += fields.length;
            }
            // 当前表单勾选的开关
            let checked = ids.filter(id => document.getElementById(id)?.checked);
            const total = savedExtCount + checked.length;
            // 找到刚被勾选的那个（本次点击触发而非之前已勾选的），回滚并提示
            if (total > 3) {
                const clicked = ids.find(id => {
                    const el = document.getElementById(id);
                    return el && el.checked && el.dataset.wasChecked !== '1';
                });
                if (clicked) {
                    document.getElementById(clicked).checked = false;
                    showToast(`该规格组合已对外展示 ${savedExtCount} 个价格，最多 3 个`, 'error');
                    checked = ids.filter(id => document.getElementById(id)?.checked); // 回滚后重新统计
                }
            }
            // 根据剩余额度禁用/启用未勾选的开关 + 其他供应商已展示的类型禁用
            const remaining = Math.max(0, 3 - savedExtCount);
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (!el || el.dataset.oaDisabled === '1') return;
                // 该价格类型已被其他供应商对外展示 → 禁用并取消勾选
                if (otherExtTypes.has(fieldMap[id])) {
                    el.disabled = true;
                    el.checked = false;
                } else if (!el.checked && checked.length >= remaining) {
                    el.disabled = true;
                } else {
                    el.disabled = false;
                }
            });
            // 记录当前勾选状态供下次对比
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.dataset.wasChecked = el.checked ? '1' : '';
            });
        }

        // 收集 external_price_fields 值（逗号分隔的 SET 字符串）
        function _collectExtPriceFields() {
            const fields = [];
            if (document.getElementById('spExtNoTax')?.checked) fields.push('no_tax');
            if (document.getElementById('spExtSpecial')?.checked) fields.push('special');
            if (document.getElementById('spExtNormal')?.checked) fields.push('general');
            return fields.join(',') || null;
        }

        // 初始化供应商下拉（OA供应商 + 本地兜底）
        async function _initSupplierSelect(currentOaId, currentName) {
            const sel = document.getElementById('spOaSupplierSelect');
            if (!sel) return;
            sel.innerHTML = '<option value="">-- 选择或手动输入 --</option>';
            const list = await _loadOaSuppliers();
            for (const s of list) {
                const opt = document.createElement('option');
                opt.value = s.oa_supplier_id ?? '';
                opt.text = s.supplier_name;
                if (s.oa_supplier_id && s.oa_supplier_id === currentOaId) opt.selected = true;
                sel.appendChild(opt);
            }
            // 选中 OA 供应商后自动触发能力校验
            if (currentOaId) _onSupplierChanged();
        }

        async function savePanelSupplier(priceId) {
            // 获取供应商名称
            const supplierInput = document.getElementById('spSupplierName');
            const supplierName = supplierInput?.value.trim() || '';
            if (!supplierName) { showSupplierRequiredError(supplierInput, '请填写供应商名称'); return; }

            // 报价设置：至少填写一项
            let noTaxPrice = null;
            let specialPrice = null;
            let normalPrice = null;
            // 读取三个价格输入框的值（有值才校验格式，无值视为未填写）
            const noTaxRaw = document.getElementById('spInputNoTax')?.value.trim() || '';
            const specialRaw = document.getElementById('spSpecialVal')?.value.trim() || '';
            const normalRaw = document.getElementById('spNormalVal')?.value.trim() || '';
            if (!noTaxRaw && !specialRaw && !normalRaw) {
                document.getElementById('spMultiPriceBox')?.scrollIntoView({behavior:'smooth', block:'center'});
                showToast('供应商报价设置至少填写一种报价', 'error');
                return;
            }
            if (noTaxRaw) { noTaxPrice = Number(noTaxRaw); if (!Number.isFinite(noTaxPrice) || noTaxPrice < 0) { showSupplierRequiredError(document.getElementById('spInputNoTax'), '请填写正确的不含票单价'); return; } }
            if (specialRaw) { specialPrice = Number(specialRaw); if (!Number.isFinite(specialPrice) || specialPrice < 0) { showSupplierRequiredError(document.getElementById('spSpecialVal'), '请填写正确的含专票价格'); return; } }
            if (normalRaw) { normalPrice = Number(normalRaw); if (!Number.isFinite(normalPrice) || normalPrice < 0) { showSupplierRequiredError(document.getElementById('spNormalVal'), '请填写正确的含普票价格'); return; } }

            // 运费设置为必填，必须明确选择含运费或不含运费
            const shipType = document.querySelector('input[name="spShipType"]:checked')?.value || '';
            if (!shipType) {
                document.querySelector('.sp-radio-group')?.scrollIntoView({behavior:'smooth', block:'center'});
                showToast('请选择供应商运费设置', 'error');
                return;
            }
            let freightRemark = '';
            if (shipType === 'include') {
                freightRemark = document.getElementById('spShipRemarkInclude')?.value.trim() || '含运费';
            } else {
                freightRemark = '不含运费';
            }

            // 质保设置为必填，“无质保”也需要明确填写
            const warrantyInput = document.getElementById('spWarrantyTime');
            const warrantyTime = warrantyInput?.value.trim() || '';
            if (!warrantyTime) { showSupplierRequiredError(warrantyInput, '请填写质保时间，若无质保请选择“无质保”'); return; }

            // OA 供应商：从下拉取值，同时写入 supplier 字段（用OA名称）
            const oaSel = document.getElementById('spOaSupplierSelect');
            const oaId = oaSel ? Number(oaSel.value) : null;
            const oaName = oaId ? oaSel.options[oaSel.selectedIndex].text : '';
            const finalSupplier = oaId ? oaName : supplierName;

            // external_price_fields：收集勾选的对外展示开关
            const extFields = _collectExtPriceFields();

            const payload = {
                supplier: finalSupplier,
                no_tax_price: noTaxPrice,
                purchase_special_invoice: specialPrice,
                purchase_general_invoice: normalPrice,
                purchase_shipping: null,
                freight_remark: freightRemark || null,
                warranty_time: warrantyTime,
                shipping_time: document.getElementById('spDeliveryTime')?.value.trim() || null,
                shipping_origin: document.getElementById('spDeliveryPlace')?.value.trim() || null,
                remark: document.getElementById('spRemark')?.value.trim() || null,
                expire_date: document.getElementById('spValidTime')?.value || null,
                oa_supplier_id: oaId || null,
                external_price_fields: extFields,
            };

            if (supplierSaveInProgress) return;
            const savingNewSupplier = isNewSupplierMode;
            const saveButton = document.querySelector('#spDetailArea .sp-save-btn');
            supplierSaveInProgress = true;
            if (saveButton) {
                saveButton.disabled = true;
                saveButton.textContent = '保存中...';
            }

            try {
                if (savingNewSupplier) {
                    // 新增模式：先获取 variant_group_id，然后创建
                    const specsForGroup = currentPanelSpecs.map(s => ({ spec_name: s.name, spec_value: s.value }));
                    const groupRes = await fetch(`/api/products/${currentProductId}/variant-groups`, {
                        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ specs: specsForGroup })
                    });
                    if (!groupRes.ok) {
                        const err = await groupRes.json().catch(() => ({}));
                        throw new Error(err.detail || '规格组合获取失败');
                    }
                    const { variant_group_id } = await groupRes.json();

                    const createPayload = { ...payload, variant_group_id: variant_group_id };
                    const res = await fetch(`/api/products/${currentProductId}/variant-prices`, {
                        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(createPayload)
                    });
                    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || '服务器暂时无法保存'); }
                    isNewSupplierMode = false;
                } else {
                    // 编辑模式：更新现有记录
                    const res = await fetch(`/api/products/${currentProductId}/variant-prices/${priceId}`, {
                        method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
                    });
                    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || '服务器暂时无法保存'); }
                }
                await refreshPanelData();
                renderPanelContent();
                showToast(savingNewSupplier ? '新增成功' : '修改成功', 'success');
            } catch (e) {
                showToast(`${savingNewSupplier ? '新增' : '修改'}失败：${e.message || '请稍后重试'}`, 'error');
            } finally {
                supplierSaveInProgress = false;
                const currentButton = document.querySelector('#spDetailArea .sp-save-btn');
                if (currentButton) {
                    currentButton.disabled = false;
                    currentButton.textContent = isNewSupplierMode ? '保存新增' : '保存修改';
                }
            }
        }

        async function deletePanelSupplier(priceId) {
            if (!confirm('确定删除此供应商？')) return;
            try {
                const res = await fetch(`/api/products/${currentProductId}/variant-prices/${priceId}`, { method: 'DELETE' });
                if (!res.ok) throw new Error('删除失败');
                if (currentPanelPriceId === priceId) currentPanelPriceId = null;
                showToast('已删除', 'success');
                await refreshPanelData();
                renderPanelContent();
            } catch (e) { showToast(e.message, 'error'); }
        }

        async function refreshPanelData() {
            const pRes = await fetch(`/api/products/${currentProductId}/variant-prices`);
            currentVariantPrices = pRes.ok ? await pRes.json() : [];
        }

        function updateSupplierSelector() {
            const selector = document.getElementById('variantSupplierSelector');
            if (!selector) return;
            const matches = currentVariantPrices.filter(p => matchSpecs(p.specs, selectedVariantValues));
            selector.innerHTML = matches.length
                ? matches.map(m => `<option value="${m.id}">${escapeHtml(m.supplier || '未命名供应商')}</option>`).join('')
                : '<option value="">无匹配供应商</option>';
            selector.disabled = !matches.length;
            applySelectedVariant();
        }

        function selectVariantValue(button) {
            const name = button.dataset.specName;
            const value = button.dataset.specValue;
            // 更新数组格式
            const existing = selectedVariantValues.find(v => v.name === name);
            if (existing) {
                existing.value = value;
            } else {
                selectedVariantValues.push({ name, value });
            }
            document.querySelectorAll('.variant-choice-btn').forEach(item => {
                if (item.dataset.specName === name) item.classList.toggle('active', item === button);
            });
            refreshVariantSuppliers();
        }

        function variantMatchesSelection(price) {
            if (!price.specs || price.specs.length !== currentVariantSpecs.length) return false;
            return price.specs.every(spec => {
                const selected = selectedVariantValues.find(v => v.name === spec.name);
                return selected && selected.value === spec.value;
            });
        }

        function refreshVariantSuppliers() {
            const selector = document.getElementById('variantSupplierSelector');
            const hint = document.getElementById('variantMatchHint');
            if (!selector) return;
            const complete = currentVariantSpecs.every(spec => selectedVariantValues.some(v => v.name === spec.spec_name));
            if (!complete) {
                currentSelectedVariantPrice = null;
                selector.disabled = true;
                selector.innerHTML = '<option value="">请先选择完整规格</option>';
                if (hint) hint.textContent = '请继续选择其余规格。';
                return;
            }
            const matches = currentVariantPrices.filter(variantMatchesSelection);
            currentSelectedVariantPrice = null;
            selector.disabled = matches.length === 0;
            selector.innerHTML = matches.length ? `<option value="">请选择供应商</option>${matches.map(row => `<option value="${row.id}">${escapeHtml(row.supplier)}</option>`).join('')}` : '<option value="">此规格组合尚未配置供应商价格</option>';
            hint.textContent = matches.length ? `找到 ${matches.length} 个供应商，请选择供应商查看价格。` : '此规格组合尚未设置价格，请点击“供应商价格”新增。';
            if (matches.length === 1) {
                selector.value = String(matches[0].id);
                applySelectedVariant();
            }
        }

        function setVariantText(id, value, emptyText = '未填写') {
            const element = document.getElementById(id);
            if (!element) return;
            const number = element.querySelector('.number');
            const text = value === null || value === undefined || value === '' ? emptyText : String(value);
            if (number) number.textContent = text; else element.textContent = text;
        }

        function applySelectedVariant() {
            const selector = document.getElementById('variantSupplierSelector');
            const hint = document.getElementById('variantMatchHint');
            if (!selector || !selector.value) return;
            const row = currentVariantPrices.find(item => String(item.id) === selector.value);
            if (!row) return;
            currentSelectedVariantPrice = row;
            const cap = row.oa_supplier_id ? _oaSupplierCapability[row.oa_supplier_id] : null;
            setVariantText('fv-retail_price', row.retail_price, '0');
            setVariantText(
                'fv-purchase_special_invoice',
                (!cap || cap.is_special) ? supplierInvoicePriceText(row.purchase_special_invoice, '专票') : '不支持'
            );
            setVariantText(
                'fv-purchase_general_invoice',
                (!cap || cap.is_normal) ? supplierInvoicePriceText(row.purchase_general_invoice, '普票') : '不支持'
            );
            setVariantText('fv-purchase_shipping', row.purchase_shipping);
            setVariantText('fv-retail_ladder_price', row.retail_ladder_price);
            setVariantText('fv-retail_tax', row.retail_tax);
            setVariantText('fv-retail_shipping', row.retail_shipping);
            setVariantText('fv-shipping_origin', row.shipping_origin);
            setVariantText('fv-shipping_time', row.shipping_time);
            hint.textContent = `当前：${row.specs.map(spec => spec.name + '=' + spec.value).join('，')}；供应商：${row.supplier}`;
        }

        const VARIANT_NUMBER_FIELDS = new Set([
            'purchase_special_invoice','purchase_general_invoice','purchase_shipping',
            'retail_price','retail_ladder_price','retail_tax','retail_shipping'
        ]);



        async function openSpecManager() {
            let modal = document.getElementById('variantSpecManagerModal');
            if (!modal) {
                modal = document.createElement('div'); modal.id = 'variantSpecManagerModal'; modal.className = 'variant-modal';
                modal.innerHTML = `<div class="variant-dialog">
                    <div class="variant-drawer-header">
                        <div><h3 style="margin:0">规格配置</h3><div style="font-size:12px;color:#94a3b8;margin-top:4px">管理当前产品的规格名称和规格值</div></div>
                        <button class="variant-close-btn" onclick="closeVariantManager('variantSpecManagerModal')">×</button>
                    </div>
                    <div class="variant-drawer-body">
                        <section class="variant-panel">
                            <div class="variant-panel-title">规格配置</div>
                            <div class="spec-config-table">
                                <div class="spec-config-header">
                                    <div class="spec-col-name">规格名称</div>
                                    <div class="spec-col-values">规格值 <span style="font-weight:400;color:#94a3b8;font-size:12px">（新增时按 Tab/回车添加；双击已有规格值可直接修改）</span></div>
                                    <div class="spec-col-actions"></div>
                                </div>
                                <div id="variantSpecRows"></div>
                                <div class="spec-config-row spec-new-row" id="specNewRow">
                                    <div class="spec-col-name"><input id="newSpecName" placeholder="如：成色" class="spec-name-input"></div>
                                    <div class="spec-col-values">
                                        <div class="spec-value-input-wrap">
                                            <input id="newSpecValue" placeholder="输入规格值后按 Tab 或 回车添加" class="spec-value-input" onkeydown="handleSpecValueKeydown(event)">
                                            <div id="newSpecValueTags" class="spec-value-tags-inline"></div>
                                        </div>
                                    </div>
                                    <div class="spec-col-actions"><button class="spec-save-btn" onclick="saveNewSpec()">保存</button></div>
                                </div>
                            </div>
                        </section>
                        <section class="variant-panel">
                            <div class="variant-panel-title">规格组合与供应商价格</div>
                            <div style="margin:-5px 0 12px;color:#94a3b8;font-size:12px">
                                已配置组合优先显示；新增规格产生的其他组合显示“待配置”。点击输入框或配置按钮可完善供应商报价。
                            </div>
                            <div id="variantCombinationList"></div>
                        </section>
                    </div>
                </div>`;
                modal.addEventListener('click', e => { if (e.target === modal) closeVariantManager('variantSpecManagerModal'); });
                document.body.appendChild(modal);
            }
            modal.classList.add('open');
            await loadVariantManager();
        }

        async function closeVariantManager(modalId) {
            const m=document.getElementById(modalId); if(m) m.classList.remove('open');
            if (!currentProductId) return;
            const [sRes,pRes,cRes] = await Promise.all([
                fetch(`/api/products/${currentProductId}/variant-specs`),
                fetch(`/api/products/${currentProductId}/variant-prices`),
                fetch(`/api/products/${currentProductId}/variant-combinations`)
            ]);
            currentVariantSpecs = sRes.ok ? await sRes.json() : [];
            currentVariantPrices = pRes.ok ? await pRes.json() : [];
            currentVariantCombinations = cRes.ok ? await cRes.json() : [];
            selectedVariantValues = [];
            if (currentData) renderDetail(currentData);
        }
        // 新增行待保存的规格值列表
        let pendingSpecValues = [];
        async function loadVariantManager() {
            const [sRes,pRes,cRes] = await Promise.all([
                fetch(`/api/products/${currentProductId}/variant-specs`),
                fetch(`/api/products/${currentProductId}/variant-prices`),
                fetch(`/api/products/${currentProductId}/variant-combinations`)
            ]);
            const specs = await sRes.json();
            const prices = await pRes.json();
            const combinations = cRes.ok ? await cRes.json() : [];
            currentVariantSpecs = specs;
            currentVariantPrices = prices;
            currentVariantCombinations = combinations;
            pendingSpecValues = [];
            if (document.getElementById('variantSpecRows')) {
                renderSpecConfigRows(specs);
                document.getElementById('newSpecValueTags').innerHTML = '';
            }
            renderVariantCombinationList(specs, combinations);
            const selectionFields = document.getElementById('variantSelectionFields');
            if (selectionFields) {
                selectionFields.innerHTML = specs.length ? specs.map(s => `<div class="manager-spec-group" data-spec-name="${escapeHtml(s.spec_name)}">
                    <div class="manager-spec-name">${escapeHtml(s.spec_name)}</div>
                    <div class="manager-spec-options">${s.values.length
                        ? s.values.map(v=>`<button type="button" class="manager-spec-option" data-spec-value="${escapeHtml(v.value)}" onclick="selectManagerSpecValue(this)">${escapeHtml(v.value)}</button>`).join('')
                        : '<span class="spec-pending-value">待填写规格值</span>'}</div>
                </div>`).join('') : '<div style="color:#999">请先在“规格配置”中新增规格名和规格值</div>';
                document.getElementById('variantPriceRows').innerHTML = prices.length ? prices.map(p => `<div class="variant-spec-row"><div style="flex:1"><strong>${p.specs.map(s=>escapeHtml(s.name+'='+s.value)).join('，')||'未配置规格'}</strong><br><small>${escapeHtml(p.supplier)} · ${escapeHtml(p.shipping_origin||'未填发货地')} · ${escapeHtml(p.shipping_time||'未填发货时间')}</small></div><strong style="margin-right:12px">¥${p.retail_price ?? 0}</strong><button onclick="deleteVariantPrice(${p.id})" style="border:1px solid #e53e3e;background:#fff;color:#e53e3e;border-radius:4px;padding:4px 10px;cursor:pointer;font-size:12px;white-space:nowrap">删除</button></div>`).join('') : '<div style="color:#999">暂无供应商价格组合</div>';
                refreshManagerExistingPrices();
            }
        }

        function combinationPriceText(price) {
            if (!price) return '';
            const value = price.no_tax_price
                ?? price.purchase_special_invoice ?? price.purchase_general_invoice
                ?? price.retail_price;
            return value === null || value === undefined || value === '' ? '已配置报价' : String(value);
        }

        function renderVariantCombinationList(specs, combinations) {
            const container = document.getElementById('variantCombinationList');
            if (!container) return;
            const specNames = [...new Set([
                ...specs.map(item => item.spec_name),
                ...combinations.flatMap(combo => (combo.specs || []).map(item => item.name)),
            ])];
            const pendingSpecNames = new Set(
                specs.filter(item => item.is_required && (!item.values || !item.values.length))
                    .map(item => item.spec_name)
            );
            if (!combinations.length) {
                container.innerHTML = '<div class="combination-empty">暂无规格组合</div>';
                return;
            }
            const header = [
                ...specNames.map(name => `<th>${escapeHtml(name)}</th>`),
                '<th>供应商</th>',
                '<th>价格</th>',
                '<th>操作</th>',
            ].join('');
            const rows = combinations.map(combo => {
                const valueMap = Object.fromEntries((combo.specs || []).map(item => [
                    item.name,
                    item.is_active === false ? `${item.value}（已删除）` : item.value,
                ]));
                const prices = combo.prices || [];
                const suppliers = prices.map(item => item.supplier || '未命名供应商').join(' / ');
                const priceText = prices.map(combinationPriceText).join(' / ');
                const encodedSpecs = encodeURIComponent(JSON.stringify(
                    (combo.specs || []).map(item => ({name:item.name, value:item.value}))
                )).replace(/'/g, '%27');
                const groupId = encodeURIComponent(combo.variant_group_id).replace(/'/g, '%27');
                const configured = prices.length > 0;
                const rowClass = combo.is_active === false
                    ? 'combination-history'
                    : (configured ? 'combination-configured' : 'combination-pending');
                return `<tr class="${rowClass}">
                    ${specNames.map(name => `<td class="combination-spec-value">${escapeHtml(
                        valueMap[name] || (pendingSpecNames.has(name) ? '待填写' : '-')
                    )}</td>`).join('')}
                    <td><input class="combination-display-input" readonly
                        value="${escapeHtml(suppliers)}" placeholder="待配置：请输入供应商"
                        onclick="openCombinationSupplier('${encodedSpecs}')"></td>
                    <td><input class="combination-display-input" readonly
                        value="${escapeHtml(priceText)}" placeholder="待配置：请输入价格"
                        onclick="openCombinationSupplier('${encodedSpecs}')"></td>
                    <td><div class="combination-actions">
                        <button class="combination-edit-btn" onclick="openCombinationSupplier('${encodedSpecs}')">${configured ? '修改' : '配置'}</button>
                        <button class="combination-delete-btn" onclick="deleteVariantCombination('${groupId}',${prices.length})">删除组合</button>
                    </div></td>
                </tr>`;
            }).join('');
            container.innerHTML = `<div class="combination-table-wrap"><table class="combination-table">
                <thead><tr>${header}</tr></thead><tbody>${rows}</tbody>
            </table></div>`;
        }

        function openCombinationSupplier(encodedSpecs) {
            const specs = JSON.parse(decodeURIComponent(encodedSpecs));
            const specsJson = JSON.stringify(specs).replace(/"/g, '&quot;');
            openSupplierPanel(specsJson);
        }

        async function deleteVariantCombination(encodedGroupId, priceCount) {
            const groupId = decodeURIComponent(encodedGroupId);
            const message = priceCount
                ? `该组合已有 ${priceCount} 条供应商价格，删除组合会同时删除这些报价，确定继续吗？`
                : '确定删除这个待配置组合吗？';
            if (!confirm(message)) return;
            try {
                const res = await fetch(
                    `/api/products/${currentProductId}/variant-groups/${encodeURIComponent(groupId)}`,
                    {method:'DELETE'}
                );
                const result = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(result.detail || '删除组合失败');
                await loadVariantManager();
                showToast('规格组合已删除', 'success');
            } catch (error) {
                showToast(`删除失败：${error.message}`, 'error');
            }
        }

        const MANAGER_PRICE_INPUTS = {
            retail_price:'variantRetailPrice',
            purchase_special_invoice:'variantPurchaseSpecialInvoice', purchase_general_invoice:'variantPurchaseGeneralInvoice',
            purchase_shipping:'variantPurchaseShipping', retail_ladder_price:'variantRetailLadderPrice',
            retail_tax:'variantRetailTax', retail_shipping:'variantRetailShipping',
            shipping_origin:'variantShippingOrigin', shipping_time:'variantShippingTime'
        };

        function clearManagerPriceInputs() {
            Object.values(MANAGER_PRICE_INPUTS).forEach(id => { const input=document.getElementById(id); if(input) { input.value=''; input.disabled=false; input.classList.remove('sp-input-disabled'); } });
        }

        function managerSelectedSpecs() {
            return [...document.querySelectorAll('#variantSelectionFields .manager-spec-group')].map(group => ({
                name: group.dataset.specName,
                value: group.querySelector('.manager-spec-option.active')?.dataset.specValue || '',
                hasValues: Boolean(group.querySelector('.manager-spec-option'))
            }));
        }

        function selectManagerSpecValue(button) {
            const group = button.closest('.manager-spec-group');
            group.querySelectorAll('.manager-spec-option').forEach(item => item.classList.toggle('active', item === button));
            refreshManagerExistingPrices();
        }

        function refreshManagerExistingPrices() {
            const allSpecs = managerSelectedSpecs();
            const selectableSpecs = allSpecs.filter(item => item.hasValues);
            const selected = selectableSpecs.filter(item => item.value);
            const supplierSelect = document.getElementById('variantExistingSupplier');
            const supplierInput = document.getElementById('variantSupplier');
            const hint = document.getElementById('variantManagerPriceHint');
            if (!supplierSelect || !supplierInput || !hint) return;
            clearManagerPriceInputs();
            supplierInput.value = '';
            if (!selected.length || selected.length !== selectableSpecs.length) {
                supplierSelect.style.display='none'; supplierInput.style.display='';
                hint.style.display='block'; hint.textContent='请选择所有已有规格值，未填写的固定规格不会影响供应商价格配置。';
                return;
            }
            const matches = currentVariantPrices.filter(price => price.specs && price.specs.length === selected.length && price.specs.every(spec => selected.some(item => item.name === spec.name && item.value === spec.value)));
            if (!matches.length) {
                supplierSelect.style.display='none'; supplierInput.style.display='';
                hint.style.display='block'; hint.textContent='该规格组合还没有价格，可以直接新增供应商并填写价格。';
                return;
            }
            supplierSelect.style.display=''; supplierInput.style.display='none';
            supplierSelect.innerHTML = `${matches.length > 1 ? '<option value="">请选择已有供应商</option>' : ''}${matches.map(row=>`<option value="${row.id}">${escapeHtml(row.supplier)}</option>`).join('')}<option value="__new__">+ 新增供应商</option>`;
            hint.style.display='block'; hint.textContent=`该规格组合已有 ${matches.length} 个供应商，选择供应商后会自动回填全部价格。`;
            if (matches.length === 1) {
                supplierSelect.value=String(matches[0].id);
                selectManagerSupplierPrice();
            }
        }

        function selectManagerSupplierPrice() {
            const supplierSelect = document.getElementById('variantExistingSupplier');
            const supplierInput = document.getElementById('variantSupplier');
            const hint = document.getElementById('variantManagerPriceHint');
            if (!supplierSelect || !supplierInput) return;
            if (supplierSelect.value === '__new__') {
                supplierSelect.style.display='none'; supplierInput.style.display=''; supplierInput.value='';
                clearManagerPriceInputs(); supplierInput.focus();
                if(hint) hint.textContent='正在为该规格组合新增供应商价格。';
                return;
            }
            const row = currentVariantPrices.find(item => String(item.id) === supplierSelect.value);
            if (!row) { supplierInput.value=''; clearManagerPriceInputs(); return; }
            supplierInput.value=row.supplier;
            const cap = row.oa_supplier_id ? _oaSupplierCapability[row.oa_supplier_id] : null;
            Object.entries(MANAGER_PRICE_INPUTS).forEach(([field,id]) => {
                const input=document.getElementById(id); if(!input) return;
                // 含专票/含普票：供应商不支持时清空并禁用
                if(field === 'purchase_special_invoice' && cap && !cap.is_special) { input.value=''; input.disabled=true; input.classList.add('sp-input-disabled'); return; }
                if(field === 'purchase_general_invoice' && cap && !cap.is_normal) { input.value=''; input.disabled=true; input.classList.add('sp-input-disabled'); return; }
                input.disabled=false; input.classList.remove('sp-input-disabled');
                input.value=row[field] ?? '';
            });
            if(hint) hint.textContent=`已载入供应商“${row.supplier}”的价格，可直接修改后保存。`;
        }
        function renderSpecConfigRows(specs) {
            const container = document.getElementById('variantSpecRows');
            if (!specs.length) { container.innerHTML = '<div style="color:#999;padding:16px 14px">暂无规格，请在下方新增</div>'; return; }
            container.innerHTML = specs.map(s => `<div class="spec-config-row" data-spec-name="${escapeHtml(s.spec_name)}">
                <div class="spec-col-name" id="specNameCell_${escapeHtml(s.spec_name)}">${escapeHtml(s.spec_name)}</div>
                <div class="spec-col-values">${s.values.map(v => `<span class="spec-tag spec-tag-editable" id="specValTag_${v.id}" title="双击修改规格值" ondblclick="editSpecValue(event,${v.id},'${escapeHtml(s.spec_name)}','${escapeHtml(v.value)}')">${escapeHtml(v.value)}<span class="tag-remove" title="删除规格值" onclick="event.stopPropagation();removeSpecValue(${v.id},'${escapeHtml(s.spec_name)}')">&times;</span></span>`).join('')}${s.values.length ? '' : '<span class="spec-pending-value">待填写规格值</span>'}<span id="addValWrap_${escapeHtml(s.spec_name)}"><button class="spec-add-btn" onclick="showAddValueInput('${escapeHtml(s.spec_name)}')">+ 添加规格值</button></span></div>
                <div class="spec-col-actions">${s.is_locked
                    ? '<span class="spec-locked-label" title="该规格名称由产品规则固定">固定规格</span>'
                    : `<button class="spec-edit-btn" onclick="editSpecName('${escapeHtml(s.spec_name)}')">修改</button>`}</div>
            </div>`).join('');
        }
        function handleSpecValueKeydown(e) {
            if (e.key === 'Tab' || e.key === 'Enter') {
                e.preventDefault();
                const val = e.target.value.trim();
                if (!val) return;
                if (pendingSpecValues.includes(val)) { e.target.value = ''; return; }
                pendingSpecValues.push(val);
                e.target.value = '';
                renderPendingSpecTags();
            }
        }
        function renderPendingSpecTags() {
            const container = document.getElementById('newSpecValueTags');
            container.innerHTML = pendingSpecValues.map((v, i) => `<span class="spec-tag">${escapeHtml(v)}<span class="tag-remove" onclick="removePendingSpecValue(${i})">&times;</span></span>`).join('');
        }
        function removePendingSpecValue(idx) {
            pendingSpecValues.splice(idx, 1);
            renderPendingSpecTags();
        }
        async function removeSpecValue(specId, specName) {
            if (!confirm(`确定从规格配置中删除这个规格值吗？\n\n已经形成的组合、供应商和价格会继续保留在下方组合列表中，并标记为“已删除规格”。`)) return;
            try {
                const res = await fetch(`/api/products/${currentProductId}/variant-specs/${specId}`, {method:'DELETE'});
                const result = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(result.detail || '删除失败');
                await loadVariantManager();
                showToast(`规格值已删除，已保留 ${result.preserved_groups || 0} 个组合和 ${result.preserved_prices || 0} 条供应商报价`,'success');
            } catch (error) {
                showToast(`删除失败：${error.message}`,'error');
            }
        }
        function editSpecValue(event, specId, specName, oldValue) {
            event.preventDefault();
            event.stopPropagation();
            const tag = document.getElementById('specValTag_' + specId);
            if (!tag || tag.querySelector('input')) return;
            tag.classList.remove('spec-tag-editable');
            tag.innerHTML = `<input class="spec-tag-edit-input" value="${escapeHtml(oldValue)}" data-old-value="${escapeHtml(oldValue)}" onkeydown="handleSpecValueEditKeydown(event,${specId},'${escapeHtml(specName)}',this)" onblur="confirmEditSpecValue(${specId},'${escapeHtml(specName)}',this)">`;
            const input = tag.querySelector('input');
            input.focus();
            input.select();
        }

        function handleSpecValueEditKeydown(event, specId, specName, inputEl) {
            if (event.key === 'Enter') {
                event.preventDefault();
                inputEl.blur();
            } else if (event.key === 'Escape') {
                event.preventDefault();
                inputEl.dataset.cancelled = '1';
                loadVariantManager();
            }
        }

        async function confirmEditSpecValue(specId, specName, inputEl) {
            if (inputEl.dataset.cancelled === '1' || inputEl.dataset.saving === '1') return;
            const newVal = inputEl.value.trim();
            const oldVal = inputEl.dataset.oldValue || '';
            if (!newVal) {
                inputEl.classList.add('sp-input-error');
                showToast('规格值不能为空', 'error');
                inputEl.focus();
                return;
            }
            if (newVal === oldVal) { await loadVariantManager(); return; }
            inputEl.dataset.saving = '1';
            inputEl.disabled = true;
            try {
                const res = await fetch(`/api/products/${currentProductId}/variant-specs/${specId}`, {
                    method:'PUT', headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({spec_name:specName, spec_value:newVal})
                });
                const result = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(result.detail || '修改失败');
                await loadVariantManager();
                showToast('规格值修改成功', 'success');
            } catch (error) {
                inputEl.dataset.saving = '0';
                inputEl.disabled = false;
                inputEl.classList.add('sp-input-error');
                showToast(`修改失败：${error.message}`, 'error');
                inputEl.focus();
                inputEl.select();
            }
        }
        async function saveNewSpec() {
            const name = document.getElementById('newSpecName').value.trim();
            if (!name) { showToast('请输入规格名称','error'); return; }
            if (!pendingSpecValues.length) { showToast('请至少添加一个规格值','error'); return; }
            let success = 0;
            for (const val of pendingSpecValues) {
                const res = await fetch(`/api/products/${currentProductId}/variant-specs`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({spec_name:name, spec_value:val})});
                if (res.ok) success++;
            }
            if (success === 0) { showToast('保存失败','error'); return; }
            document.getElementById('newSpecName').value = '';
            pendingSpecValues = [];
            renderPendingSpecTags();
            await loadVariantManager();
            showToast(`已保存 ${success} 个规格值`,'success');
        }
        let _specValueSaving = false;
        let _specAddClicked = false;
        function showAddValueInput(specName) {
            const wrap = document.getElementById('addValWrap_' + specName);
            if (!wrap) return;
            wrap.innerHTML = `<input class="spec-inline-input" placeholder="输入规格值" onkeydown="if(event.key==='Enter')confirmAddValueInline(this,'${escapeHtml(specName)}');if(event.key==='Escape')cancelAddValueInline('${escapeHtml(specName)}');" onblur="if(!_specValueSaving&&!_specAddClicked)cancelAddValueInline('${escapeHtml(specName)}')"><button class="spec-save-btn" style="padding:4px 10px;font-size:12px" onmousedown="_specAddClicked=true;confirmAddValueInline(this.previousElementSibling,'${escapeHtml(specName)}');_specAddClicked=false">确定</button>`;
            wrap.querySelector('input').focus();
        }
        function cancelAddValueInline(specName) {
            const wrap = document.getElementById('addValWrap_' + specName);
            if (!wrap) return;
            wrap.innerHTML = `<button class="spec-add-btn" onclick="showAddValueInput('${escapeHtml(specName)}')">+ 添加规格值</button>`;
        }
        async function confirmAddValueInline(inputEl, specName) {
            const val = inputEl.value.trim();
            if (!val) return;
            _specValueSaving = true;
            const res = await fetch(`/api/products/${currentProductId}/variant-specs`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({spec_name:specName, spec_value:val})});
            if (!res.ok) { _specValueSaving = false; showToast('添加失败','error'); return; }
            await loadVariantManager();
            _specValueSaving = false;
            showToast('规格值已添加','success');
        }
        function editSpecName(oldName) {
            const cell = document.getElementById('specNameCell_' + oldName);
            if (!cell) return;
            cell.innerHTML = `<input class="spec-name-edit-input" value="${escapeHtml(oldName)}"
                data-old-value="${escapeHtml(oldName)}"
                onkeydown="handleSpecNameEditKeydown(event,this,'${escapeHtml(oldName)}')"
                onblur="confirmEditSpecName(this,'${escapeHtml(oldName)}')">`;
            const input = cell.querySelector('input');
            input.focus();
            input.select();
        }
        function handleSpecNameEditKeydown(event, inputEl, oldName) {
            if (event.key === 'Enter') {
                event.preventDefault();
                inputEl.blur();
            } else if (event.key === 'Escape') {
                event.preventDefault();
                inputEl.dataset.cancelled = '1';
                loadVariantManager();
            }
        }
        async function confirmEditSpecName(inputEl, oldName) {
            if (inputEl.dataset.cancelled === '1' || inputEl.dataset.saving === '1') return;
            const newName = inputEl.value.trim();
            if (!newName) {
                inputEl.classList.add('sp-input-error');
                showToast('规格名称不能为空', 'error');
                inputEl.focus();
                return;
            }
            if (newName === oldName) { await loadVariantManager(); return; }
            inputEl.dataset.saving = '1';
            inputEl.disabled = true;
            try {
                const res = await fetch(`/api/products/${currentProductId}/variant-spec-name`, {
                    method:'PUT',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({old_name:oldName, new_name:newName})
                });
                const result = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(result.detail || '修改失败');
                await loadVariantManager();
                showToast(`规格名称已修改，${result.updated_count || 0} 个规格值及供应商价格关联已保留`, 'success');
            } catch (error) {
                inputEl.dataset.saving = '0';
                inputEl.disabled = false;
                inputEl.classList.add('sp-input-error');
                showToast(`修改失败：${error.message}`, 'error');
                inputEl.focus();
                inputEl.select();
            }
        }
        async function saveVariantPriceFromModal() {
            const allSpecs=managerSelectedSpecs();
            const selectableSpecs=allSpecs.filter(item=>item.hasValues);
            const selectedSpecs=selectableSpecs.filter(item=>item.value);
            if(!selectedSpecs.length||selectedSpecs.length!==selectableSpecs.length){
                showToast('请选择所有已有规格值；未填写的固定规格可以跳过','error');return;
            }
            const specs=selectedSpecs.map(item=>({spec_name:item.name,spec_value:item.value}));
            const supplier=document.getElementById('variantSupplier').value.trim();
            if(!supplier){showToast('请输入供应商','error');return;}
            const groupRes=await fetch(`/api/products/${currentProductId}/variant-groups`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({specs})});
            if(!groupRes.ok){showToast('规格组合保存失败','error');return;}
            const {variant_group_id}=await groupRes.json();
            const numberOrNull=id=>{const value=document.getElementById(id).value;return value===''?null:Number(value)};
            const payload={variant_group_id,supplier,
                retail_price:numberOrNull('variantRetailPrice'),
                purchase_special_invoice:numberOrNull('variantPurchaseSpecialInvoice'),purchase_general_invoice:numberOrNull('variantPurchaseGeneralInvoice'),
                purchase_shipping:numberOrNull('variantPurchaseShipping'),retail_ladder_price:numberOrNull('variantRetailLadderPrice'),
                retail_tax:numberOrNull('variantRetailTax'),retail_shipping:numberOrNull('variantRetailShipping'),
                shipping_origin:document.getElementById('variantShippingOrigin').value.trim(),shipping_time:document.getElementById('variantShippingTime').value.trim()};
            const res=await fetch(`/api/products/${currentProductId}/variant-prices`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            if(!res.ok){showToast('供应商价格保存失败','error');return;} await loadVariantManager(); showToast('供应商价格已保存','success');
        }
        async function deleteVariantPrice(priceId) {
            if(!confirm('确定删除该供应商价格记录？')) return;
            const res = await fetch(`/api/products/${currentProductId}/variant-prices/${priceId}`, {method:'DELETE'});
            if(!res.ok){showToast('删除失败','error');return;}
            await loadVariantManager(); showToast('已删除','success');
        }

        function renderVal(v) {
            if (v === null || v === '' || v === undefined) return '<span style="color:#ccc;font-style:italic">空</span>';
            return escapeHtml(String(v));
        }

        function renderTechnicalParams(value) {
            if (value === null || value === '' || value === undefined) {
                return '<span style="color:#ccc;font-style:italic">空，点击填写技术参数</span>';
            }
            const lines = String(value).replace(/\r\n?/g, '\n').split('\n').map(line => line.trim()).filter(Boolean);
            if (!lines.length) return '<span style="color:#ccc;font-style:italic">空，点击填写技术参数</span>';
            return `<div class="technical-param-list">${lines.map((line, index) => `<div class="technical-param-line"><span class="technical-param-index">${index + 1}</span><span class="technical-param-text">${escapeHtml(line)}</span></div>`).join('')}</div>`;
        }
