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
                    return `<div class="vs-supplier-price-card">
                        <div class="vs-supplier-price-name">${name}</div>
                        <div class="vs-supplier-price-list">
                            <div class="vs-supplier-price-row">
                                <span class="vs-price-label">不含票单价</span>
                                ${formatSpecSupplierPrice(p.no_tax_price)}
                            </div>
                            <div class="vs-supplier-price-row">
                                <span class="vs-price-label">含专票</span>
                                ${formatSpecSupplierPrice(p.purchase_special_invoice, '专票')}
                            </div>
                            <div class="vs-supplier-price-row">
                                <span class="vs-price-label">含普票</span>
                                ${formatSpecSupplierPrice(p.purchase_general_invoice, '普票')}
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
        function renderPanelContent() {
            if (!currentPanelSpecs) return;

            const matchingPrices = currentVariantPrices.filter(p => matchSpecs(p.specs, currentPanelSpecs));

            // 更新供应商数量
            const countEl = document.getElementById('spSupplierCount');
            if (countEl) countEl.textContent = matchingPrices.length;

            // 左侧供应商列表
            const listEl = document.getElementById('spSupplierList');
            if (listEl) {
                if (matchingPrices.length > 0) {
                    listEl.innerHTML = matchingPrices.map(p => {
                        const isActive = currentPanelPriceId === p.id;
                        const noTax = hasConfiguredSupplierPrice(p.no_tax_price) ? `¥${escapeHtml(String(p.no_tax_price))}` : '-';
                        const specialTax = supplierInvoicePriceText(p.purchase_special_invoice, '专票');
                        const normalTax = supplierInvoicePriceText(p.purchase_general_invoice, '普票');
                        return `<div class="sp-supplier-card ${isActive ? 'active' : ''}" onclick="selectPanelSupplier(${p.id})">
                            <div class="sp-card-header">
                                <span class="sp-card-name">${escapeHtml(p.supplier || '未命名')}</span>
                                <button class="sp-card-del" onclick="event.stopPropagation();deletePanelSupplier(${p.id})" title="删除">×</button>
                            </div>
                            <div class="sp-card-info">
                                <div class="sp-info-row"><span class="sp-label">不含票单价</span><span class="sp-val">${noTax}</span></div>
                                <div class="sp-info-row"><span class="sp-label">含专票</span><span class="sp-val">${escapeHtml(specialTax || '-')}</span></div>
                                <div class="sp-info-row"><span class="sp-label">含普票</span><span class="sp-val">${escapeHtml(normalTax || '-')}</span></div>
                            </div>
                        </div>`;
                    }).join('');
                } else {
                    listEl.innerHTML = '<div class="sp-empty">暂无供应商，点击上方按钮添加</div>';
                }
            }

            // 右侧详情表单
            const detailEl = document.getElementById('spDetailArea');
            if (detailEl) {
                if (isNewSupplierMode) {
                    detailEl.innerHTML = renderSupplierDetailForm({ isNew: true });
                    loadSupplierDropdown(''); // 加载供应商列表
                } else if (currentPanelPriceId) {
                    const p = matchingPrices.find(x => x.id === currentPanelPriceId);
                    if (p) {
                        detailEl.innerHTML = renderSupplierDetailForm(p);
                        loadSupplierDropdown(p.supplier); // 加载并选中当前供应商
                    }
                } else {
                    detailEl.innerHTML = '<div class="sp-detail-empty">请选择左侧供应商查看详情，或点击上方按钮新增供应商</div>';
                }
            }
        }

        // 切换统一价显示
        function toggleUnifiedPrice() {
            const isUnified = document.getElementById('spCkUnified')?.checked;
            const multiBox = document.getElementById('spMultiPriceBox');
            const unifiedBox = document.getElementById('spUnifiedPriceBox');
            if (multiBox) multiBox.classList.toggle('hide', isUnified);
            if (unifiedBox) unifiedBox.classList.toggle('hide', !isUnified);
        }

        function toggleSupplierQuoteInput(checkboxId, inputId) {
            const checkbox = document.getElementById(checkboxId);
            const input = document.getElementById(inputId);
            if (!checkbox || !input) return;
            input.disabled = !checkbox.checked;
            input.classList.remove('sp-input-error');
            if (checkbox.checked) input.focus();
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

        function renderSupplierDetailForm(p) {
            const isNew = p.isNew || false;
            const hasNoTax = !isNew && p.no_tax_price !== null && p.no_tax_price !== undefined && p.no_tax_price !== '';
            const hasSpecial = !isNew && p.purchase_special_invoice !== null && p.purchase_special_invoice !== undefined && p.purchase_special_invoice !== '';
            const hasNormal = !isNew && p.purchase_general_invoice !== null && p.purchase_general_invoice !== undefined && p.purchase_general_invoice !== '';
            // 判断是否为统一价：三个价格字段均有值且相同（0 元也是有效价格）
            const isUnified = hasNoTax && hasSpecial && hasNormal && Number(p.no_tax_price) === Number(p.purchase_special_invoice) && Number(p.no_tax_price) === Number(p.purchase_general_invoice);
            const unifiedValue = isUnified ? p.no_tax_price : '';
            const freightChoice = p.freight_remark === '不含运费' ? 'exclude' : (p.freight_remark ? 'include' : '');
            return `<div class="sp-detail-form">
                <!-- 基础信息 -->
                <div class="sp-card">
                    <h3>基础信息</h3>
                    <div class="sp-row-main" style="margin-top:12px;">
                        <div class="sp-col-item" style="flex:2">
                            <label>供应商名称<span class="sp-required-mark">*</span></label>
                            <input id="spSupplierName" class="sp-input-text" list="spSupplierNameList" autocomplete="off" placeholder="输入名称搜索，或直接填写新供应商" value="${escapeHtml(p.supplier || '')}">
                            <datalist id="spSupplierNameList"></datalist>
                        </div>
                    </div>
                </div>

                <!-- 供应商报价设置 -->
                <div class="sp-card">
                    <div class="sp-card-title-bar">
                        <h3>供应商报价设置<span class="sp-required-mark">*</span><span class="sp-required-tip">至少选择并填写一种报价</span></h3>
                        <label class="sp-unified-check">
                            <input id="spCkUnified" type="checkbox" ${isUnified ? 'checked' : ''} onchange="toggleUnifiedPrice()">
                            <span>统一价（无票 / 专票 / 普票同价）</span>
                        </label>
                    </div>
                    <div class="sp-tip-desc">说明：此处仅记录供应商多套报价，正式下单采购时需保证发票、合同、结算价格一致。</div>

                    <!-- 多报价区域 -->
                    <div id="spMultiPriceBox" class="sp-row-main ${isUnified ? 'hide' : ''}">
                        <!-- 不含票单价 -->
                        <div class="sp-col-item">
                            <div class="sp-title-row">
                                <input id="spCkNoTax" type="checkbox" ${hasNoTax ? 'checked' : ''} onchange="toggleSupplierQuoteInput('spCkNoTax','spInputNoTax')">
                                <label for="spCkNoTax">不含票单价<span class="sp-required-mark sp-conditional-required">*</span></label>
                            </div>
                            <input id="spInputNoTax" class="sp-input-money" type="text" value="${p.no_tax_price ?? ''}" placeholder="0.00" ${hasNoTax ? '' : 'disabled'}>
                        </div>

                        <!-- 含专票 -->
                        <div class="sp-col-item">
                            <div class="sp-title-row">
                                <input id="spCkSpecial" type="checkbox" ${hasSpecial ? 'checked' : ''} onchange="toggleSupplierQuoteInput('spCkSpecial','spSpecialVal')">
                                <label for="spCkSpecial">含专票<span class="sp-required-mark sp-conditional-required">*</span></label>
                            </div>
                            <input id="spSpecialVal" class="sp-input-money" type="text" value="${p.purchase_special_invoice ?? ''}" placeholder="0.00" ${hasSpecial ? '' : 'disabled'}>
                            <div class="sp-price-zero-tip">填写 0 表示可以开专票，但价格待定</div>
                        </div>

                        <!-- 含普票 -->
                        <div class="sp-col-item">
                            <div class="sp-title-row">
                                <input id="spCkNormal" type="checkbox" ${hasNormal ? 'checked' : ''} onchange="toggleSupplierQuoteInput('spCkNormal','spNormalVal')">
                                <label for="spCkNormal">含普票<span class="sp-required-mark sp-conditional-required">*</span></label>
                            </div>
                            <input id="spNormalVal" class="sp-input-money" type="text" value="${p.purchase_general_invoice ?? ''}" placeholder="0.00" ${hasNormal ? '' : 'disabled'}>
                            <div class="sp-price-zero-tip">填写 0 表示可以开普票，但价格待定</div>
                        </div>
                    </div>
                    </div>

                    <!-- 统一价区域 -->
                    <div id="spUnifiedPriceBox" class="${isUnified ? '' : 'hide'}">
                        <div class="sp-col-item sp-unified-col">
                            <label>统一单价<span class="sp-required-mark">*</span></label>
                            <input id="spInputUnified" class="sp-input-money" type="text" value="${unifiedValue || ''}" placeholder="0.00">
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
                                    <span class="sp-tag" onclick="document.getElementById('spShipRemarkInclude').value='偏远地区不包邮'">偏远地区不包邮</span>
                                </div>
                                <textarea id="spShipRemarkInclude" placeholder="可填写包邮物流公司、不包邮地区等">${escapeHtml(p.freight_remark && p.freight_remark !== '不含运费' ? p.freight_remark : '')}</textarea>
                            </div>
                        </div>
                        <!-- 不含运费区域 -->
                        <div id="spShipExcludeBox" class="${freightChoice === 'exclude' ? '' : 'hide'}">
                            <div class="sp-col-item">
                                <div class="sp-remark-label-row">
                                    <label>运费备注说明</label>
                                    <span class="sp-tag" onclick="document.getElementById('spShipRemarkExclude').value='偏远地区不包邮'">偏远地区不包邮</span>
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

        async function savePanelSupplier(priceId) {
            // 获取供应商名称
            const supplierInput = document.getElementById('spSupplierName');
            const supplierName = supplierInput?.value.trim() || '';
            if (!supplierName) { showSupplierRequiredError(supplierInput, '请填写供应商名称'); return; }

            // 获取统一价状态
            const isUnified = document.getElementById('spCkUnified')?.checked || false;

            // 报价设置为必填：统一价需填写统一单价；多报价中勾选几项就必须填写几项
            let unifiedPrice = null;
            let noTaxPrice = null;
            let specialPrice = null;
            let normalPrice = null;
            if (isUnified) {
                unifiedPrice = requiredSupplierPrice('spInputUnified', '统一单价');
                if (unifiedPrice === null) return;
                noTaxPrice = specialPrice = normalPrice = unifiedPrice;
            } else {
                const quoteOptions = [
                    {checkbox:'spCkNoTax', input:'spInputNoTax', label:'不含票单价', key:'noTax'},
                    {checkbox:'spCkSpecial', input:'spSpecialVal', label:'含专票价格', key:'special'},
                    {checkbox:'spCkNormal', input:'spNormalVal', label:'含普票价格', key:'normal'}
                ];
                const selectedQuotes = quoteOptions.filter(item => document.getElementById(item.checkbox)?.checked);
                if (!selectedQuotes.length) {
                    document.getElementById('spMultiPriceBox')?.scrollIntoView({behavior:'smooth', block:'center'});
                    showToast('供应商报价设置至少勾选一种报价', 'error');
                    return;
                }
                for (const item of selectedQuotes) {
                    const value = requiredSupplierPrice(item.input, item.label);
                    if (value === null) return;
                    if (item.key === 'noTax') noTaxPrice = value;
                    if (item.key === 'special') specialPrice = value;
                    if (item.key === 'normal') normalPrice = value;
                }
            }

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

            const payload = {
                supplier: supplierName,
                purchase_cost: isUnified ? unifiedPrice : null,
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
            setVariantText('fv-retail_price', row.retail_price, '0');
            setVariantText('fv-purchase_cost', row.purchase_cost, '0');
            setVariantText(
                'fv-purchase_special_invoice',
                supplierInvoicePriceText(row.purchase_special_invoice, '专票')
            );
            setVariantText(
                'fv-purchase_general_invoice',
                supplierInvoicePriceText(row.purchase_general_invoice, '普票')
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
            'purchase_cost','purchase_special_invoice','purchase_general_invoice','purchase_shipping',
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
            const value = price.purchase_cost ?? price.no_tax_price
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
            retail_price:'variantRetailPrice', purchase_cost:'variantPurchaseCost',
            purchase_special_invoice:'variantPurchaseSpecialInvoice', purchase_general_invoice:'variantPurchaseGeneralInvoice',
            purchase_shipping:'variantPurchaseShipping', retail_ladder_price:'variantRetailLadderPrice',
            retail_tax:'variantRetailTax', retail_shipping:'variantRetailShipping',
            shipping_origin:'variantShippingOrigin', shipping_time:'variantShippingTime'
        };

        function clearManagerPriceInputs() {
            Object.values(MANAGER_PRICE_INPUTS).forEach(id => { const input=document.getElementById(id); if(input) input.value=''; });
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
            Object.entries(MANAGER_PRICE_INPUTS).forEach(([field,id]) => {
                const input=document.getElementById(id); if(input) input.value=row[field] ?? '';
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
                retail_price:numberOrNull('variantRetailPrice'),purchase_cost:numberOrNull('variantPurchaseCost'),
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
