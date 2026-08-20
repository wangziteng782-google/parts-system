async function init() {
            const [labelsRes, imgLibLabelsRes, classificationRes, uploadConfigRes] = await Promise.all([
                fetch('/api/field-labels'),
                fetch('/api/field-labels'),
                fetch('/api/product-classifications'),
                fetch('/api/image-upload/config')
            ]);
            fieldLabels = await labelsRes.json();
            imgLibFieldLabels = await imgLibLabelsRes.json(); // 图片库专用字段标签
            const classificationData = await classificationRes.json();
            if (uploadConfigRes.ok) imageUploadConfig = await uploadConfigRes.json();
            applyClassificationData(classificationData);
            loadProducts();
        }

        function openProductCreate() {
            Object.values(pendingCreateLocalFiles).flat().forEach(file => {
                const previewUrl = createImagePreviewUrls.get(file);
                if (previewUrl) URL.revokeObjectURL(previewUrl);
                createImagePreviewUrls.delete(file);
            });
            pendingCreateLocalFiles = {};
            pendingCreateLibraryUrls = {};
            createLocalImageTargetField = null;
            const body = document.getElementById('productCreateBody');
            body.innerHTML = PRODUCT_CREATE_SECTIONS.map(section => `
                <section class="product-create-section">
                    <div class="product-create-section-title">${escapeHtml(section.title)}</div>
                    <div class="product-create-grid">
                        ${section.fields.map(([field, label, type]) => renderProductCreateField(field, label, type)).join('')}
                    </div>
                </section>
            `).join('') + `
                <section class="product-create-section">
                    <div class="product-create-section-title">产品图片 <span style="font-weight:400;color:#94a3b8">（仅新增关键部位图片、实物图照片和商品详情图片）</span></div>
                    <div class="create-image-grid" id="createImageGrid"></div>
                </section>`;
            renderCreateImageSection();
            document.getElementById('productCreateOverlay').classList.add('open');
            setTimeout(() => document.getElementById('create-product_name')?.focus(), 80);
        }

        function renderProductCreateField(field, label, type) {
            const full = type === 'textarea' ? ' full' : '';
            let control = '';
            if (type === 'product_type') {
                control = `<div class="create-product-type-combobox">
                    <input id="create-${field}-search" type="text" value="${escapeHtml(selectedProductType || '')}"
                        placeholder="输入关键词搜索产品分类" autocomplete="off"
                        onfocus="filterCreateProductTypes(this.value, true)"
                        oninput="filterCreateProductTypes(this.value, true)"
                        onblur="setTimeout(closeCreateProductTypeDropdown, 180)">
                    <input id="create-${field}" data-create-field="${field}" type="hidden" value="${escapeHtml(selectedProductType || '')}">
                    <div class="create-product-type-dropdown" id="createProductTypeDropdown"></div>
                </div>`;
            } else if (type === 'textarea') {
                const placeholder = field === 'technical_params' ? '每行填写一项技术参数' : `请输入${label}`;
                control = `<textarea id="create-${field}" data-create-field="${field}" placeholder="${escapeHtml(placeholder)}"></textarea>`;
            } else {
                control = `<input id="create-${field}" data-create-field="${field}" type="text" placeholder="请输入${escapeHtml(label)}">`;
            }
            return `<div class="product-create-field${full}"><label for="create-${field}">${escapeHtml(label)}</label>${control}</div>`;
        }

        function filterCreateProductTypes(keyword, showDropdown = true) {
            const query = (keyword || '').trim().toLowerCase();
            const hidden = document.getElementById('create-product_type');
            const exact = productTypeValues.find(value => value.toLowerCase() === query);
            if (hidden) hidden.value = exact || '';
            const matches = productTypeValues.filter(value => !query || value.toLowerCase().includes(query)).slice(0, 80);
            const dropdown = document.getElementById('createProductTypeDropdown');
            if (!dropdown) return;
            dropdown.innerHTML = matches.length
                ? matches.map(value => {
                    const encoded = encodeURIComponent(value).replace(/'/g, '%27');
                    return `<div class="create-product-type-option" onmousedown="event.preventDefault()" onclick="selectCreateProductType('${encoded}')">${escapeHtml(value)}</div>`;
                }).join('')
                : '<div class="create-product-type-empty">没有匹配的产品分类</div>';
            dropdown.classList.toggle('show', showDropdown);
        }

        function selectCreateProductType(encodedValue) {
            const value = decodeURIComponent(encodedValue);
            document.getElementById('create-product_type-search').value = value;
            document.getElementById('create-product_type').value = value;
            closeCreateProductTypeDropdown();
        }

        function closeCreateProductTypeDropdown() {
            document.getElementById('createProductTypeDropdown')?.classList.remove('show');
        }

        function renderCreateImageSection() {
            const grid = document.getElementById('createImageGrid');
            if (!grid) return;
            grid.innerHTML = CREATE_PRODUCT_IMAGE_FIELDS.map(field => {
                const label = fieldLabels[field] || field;
                const files = pendingCreateLocalFiles[field] || [];
                const libraryUrls = pendingCreateLibraryUrls[field] || [];
                const localPreviews = files.map((file, index) => `
                    <div class="create-image-preview" title="${escapeHtml(file.name || '粘贴图片')}">
                        <img src="${escapeHtml(getCreateImagePreviewUrl(file))}" alt="${escapeHtml(label)}">
                        <button type="button" onclick="event.stopPropagation();removeCreateLocalImage('${field}',${index})" title="移除">×</button>
                    </div>`).join('');
                const libraryPreviews = libraryUrls.map((url, index) => `
                    <div class="create-image-preview" title="来自图片库">
                        <img src="${escapeHtml(url)}" alt="${escapeHtml(label)}">
                        <button type="button" onclick="event.stopPropagation();removeCreateLibraryImage('${field}',${index})" title="移除">×</button>
                    </div>`).join('');
                const previews = localPreviews + libraryPreviews;
                return `<div class="create-image-card">
                    <div class="create-image-card-title">${escapeHtml(label)}</div>
                    <div class="create-image-dropbox" tabindex="0"
                        onclick="event.currentTarget.focus()"
                        onpaste="pasteCreateImages(event,'${field}')"
                        ondragover="allowCreateImageDrop(event)"
                        ondragleave="leaveCreateImageDrop(event)"
                        ondrop="dropCreateImages(event,'${field}')">
                        ${previews
                            ? `<div class="create-image-preview-grid">${previews}</div>`
                            : `<div class="create-image-empty"><strong>本次上传图片将在这里预览</strong><span>点击框后可 Ctrl+V 粘贴</span><span>也可从微信、飞书拖入图片</span></div>`}
                        <div class="create-image-help">已选择 ${files.length + libraryUrls.length} 张图片</div>
                    </div>
                    <div class="create-image-actions">
                        <button type="button" data-create-local-field="${field}" onclick="openCreateLocalImage('${field}')" ${imageUploadConfig.configured ? '' : 'disabled'}>选择本地图片</button>
                        <button type="button" data-create-library-field="${field}" onclick="openCreateImgLib('${field}')">&#128247; 图片库</button>
                    </div>
                </div>`;
            }).join('');
        }

        function getCreateImagePreviewUrl(file) {
            if (!createImagePreviewUrls.has(file)) {
                createImagePreviewUrls.set(file, URL.createObjectURL(file));
            }
            return createImagePreviewUrls.get(file);
        }

        function openCreateLocalImage(field) {
            if (!imageUploadConfig.configured) {
                showToast('七牛云配置未生效，请重启后端后再试', 'error');
                return;
            }
            createLocalImageTargetField = field;
            const input = document.getElementById('createLocalImageInput');
            input.value = '';
            input.click();
        }

        function normalizeCreateImageFiles(fileList) {
            const mimeByExtension = {
                jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
                gif: 'image/gif', webp: 'image/webp', bmp: 'image/bmp',
            };
            return Array.from(fileList || []).map(file => {
                if (!file) return null;
                if (file.type && file.type.startsWith('image/')) return file;
                const extension = String(file.name || '').split('.').pop().toLowerCase();
                const type = mimeByExtension[extension];
                return type ? new File([file], file.name, { type, lastModified: file.lastModified }) : null;
            }).filter(Boolean);
        }

        function stageCreateLocalImages(fileList, targetField = null) {
            const files = normalizeCreateImageFiles(fileList);
            const field = targetField || createLocalImageTargetField;
            if (!field || !files.length) return;
            if (!imageUploadConfig.configured) {
                showToast('七牛云配置未生效，请重启后端后再试', 'error');
                return;
            }
            const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'];
            const invalid = files.find(file => !allowedTypes.includes(file.type) || file.size > 10 * 1024 * 1024);
            if (invalid) {
                showToast('仅支持不超过10MB的 JPG、PNG、GIF、WebP、BMP 图片', 'error');
                return;
            }
            const existing = pendingCreateLocalFiles[field] || [];
            if (existing.length + files.length > (imageUploadConfig.max_file_count || 20)) {
                showToast(`每个图片类型一次最多选择 ${imageUploadConfig.max_file_count || 20} 张`, 'error');
                return;
            }
            pendingCreateLocalFiles[field] = [...existing, ...files];
            createLocalImageTargetField = null;
            renderCreateImageSection();
        }

        function pasteCreateImages(event, field) {
            event.stopPropagation();
            const files = Array.from(event.clipboardData?.items || [])
                .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
                .map(item => item.getAsFile())
                .filter(Boolean);
            if (!files.length) {
                showToast('剪贴板中没有图片', 'error');
                return;
            }
            event.preventDefault();
            stageCreateLocalImages(files, field);
        }

        function allowCreateImageDrop(event) {
            if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return;
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = 'copy';
            event.currentTarget.classList.add('drag-active');
        }

        function leaveCreateImageDrop(event) {
            event.stopPropagation();
            if (event.currentTarget.contains(event.relatedTarget)) return;
            event.currentTarget.classList.remove('drag-active');
        }

        function dropCreateImages(event, field) {
            event.preventDefault();
            event.stopPropagation();
            event.currentTarget.classList.remove('drag-active');
            const files = normalizeCreateImageFiles(event.dataTransfer?.files || []);
            if (!files.length) {
                showToast('拖入的内容中没有可用图片', 'error');
                return;
            }
            stageCreateLocalImages(files, field);
        }

        function removeCreateLocalImage(field, index) {
            const files = pendingCreateLocalFiles[field] || [];
            const removed = files[index];
            const previewUrl = removed ? createImagePreviewUrls.get(removed) : null;
            if (previewUrl) URL.revokeObjectURL(previewUrl);
            if (removed) createImagePreviewUrls.delete(removed);
            files.splice(index, 1);
            pendingCreateLocalFiles[field] = files;
            renderCreateImageSection();
        }

        function removeCreateLibraryImage(field, index) {
            const urls = pendingCreateLibraryUrls[field] || [];
            urls.splice(index, 1);
            pendingCreateLibraryUrls[field] = urls;
            renderCreateImageSection();
        }

        function closeProductCreate(event) {
            if (event && event.target !== document.getElementById('productCreateOverlay')) return;
            document.getElementById('productCreateOverlay').classList.remove('open');
        }

        async function submitProductCreate() {
            const saveBtn = document.getElementById('productCreateSave');
            const fields = {};
            document.querySelectorAll('[data-create-field]').forEach(control => {
                fields[control.dataset.createField] = control.value.trim() || null;
            });
            CREATE_PRODUCT_IMAGE_FIELDS.forEach(field => {
                const urls = pendingCreateLibraryUrls[field] || [];
                if (urls.length) fields[field] = JSON.stringify(urls);
            });
            saveBtn.disabled = true;
            saveBtn.textContent = '正在保存并上传图片...';
            let createdProduct = null;
            try {
                const res = await fetch('/api/products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ fields }),
                });
                const result = await res.json();
                if (!res.ok) throw new Error(result.detail || '新增失败');
                createdProduct = result.product;
                const uploadFailures = [];
                for (const field of CREATE_PRODUCT_IMAGE_FIELDS) {
                    const files = pendingCreateLocalFiles[field] || [];
                    if (!files.length) continue;
                    const form = new FormData();
                    form.append('image_field', field);
                    files.forEach(file => form.append('files', file));
                    try {
                        const uploadRes = await fetch(`/api/products/${createdProduct.id}/images/upload`, {
                            method: 'POST',
                            body: form,
                        });
                        const uploadResult = await uploadRes.json();
                        if (!uploadRes.ok) throw new Error(uploadResult.detail || '上传失败');
                    } catch (uploadError) {
                        uploadFailures.push(`${fieldLabels[field] || field}：${uploadError.message}`);
                    }
                }
                closeProductCreate();
                await refreshProductClassifications();
                await loadProducts();
                await selectProduct(createdProduct.id);
                if (uploadFailures.length) {
                    showToast(`产品已新增，但部分图片上传失败：${uploadFailures.join('；')}`, 'error');
                } else {
                    showToast(`产品“${createdProduct.product_name}”新增成功`, 'success');
                }
            } catch (e) {
                if (createdProduct) {
                    closeProductCreate();
                    await selectProduct(createdProduct.id);
                    showToast('产品已新增，但后续页面刷新失败：' + e.message, 'error');
                } else {
                    showToast('新增失败：' + e.message, 'error');
                }
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = '保存新增';
            }
        }

        function applyClassificationData(data) {
            classificationTree = data.tree || [];
            productTypeValues = data.values || [];
            productTypeCounts = data.counts || {};
            unclassifiedProductCount = data.unclassified_count || 0;
            correctionProductCount = data.correction_count || 0;
            renderClassificationTree();
        }

        async function refreshProductClassifications() {
            const res = await fetch('/api/product-classifications');
            if (!res.ok) return;
            applyClassificationData(await res.json());
        }

        function renderClassificationTree() {
            const treeEl = document.getElementById('classificationTree');
            let html = `<div class="tree-all ${!selectedProductType && !showUnclassified && !showCorrection ? 'active' : ''}" onclick="clearProductTypeFilter()">
                <span>全部产品</span>
            </div>`;
            html += `<div class="tree-unclassified ${showUnclassified ? 'active' : ''}" onclick="selectUnclassified()">
                <span>待重新分类</span><span class="tree-count">${unclassifiedProductCount}</span>
            </div>`;
            html += `<div class="tree-correction ${showCorrection ? 'active' : ''}" onclick="selectCorrection()">
                <span>待改正</span><span class="tree-count">${correctionProductCount}</span>
            </div>`;
            classificationTree.forEach(first => {
                const firstEncoded = encodeURIComponent(first.name);
                if (!first.children.length) {
                    html += `<details class="tree-first"><summary>${escapeHtml(first.name)}
                        <span class="tree-actions"><button class="tree-add-btn" onclick="event.stopPropagation();addSecondLevel('${firstEncoded}')" title="新增二级分类">＋</button><button class="tree-add-btn tree-edit-btn" onclick="event.stopPropagation();editFirstLevel('${firstEncoded}')" title="编辑一级分类">✎</button></span>
                    </summary><div class="tree-empty">暂无二级分类</div></details>`;
                    return;
                }
                html += `<details class="tree-first" open><summary>${escapeHtml(first.name)}
                    <span class="tree-actions"><button class="tree-add-btn" onclick="event.stopPropagation();addSecondLevel('${firstEncoded}')" title="新增二级分类">＋</button><button class="tree-add-btn tree-edit-btn" onclick="event.stopPropagation();editFirstLevel('${firstEncoded}')" title="编辑一级分类">✎</button></span>
                </summary>`;
                first.children.forEach(second => {
                    const secondEncoded = encodeURIComponent(second.name);
                    html += `<details class="tree-second" open><summary>${escapeHtml(second.name)}
                        <span class="tree-actions"><button class="tree-add-btn" onclick="event.stopPropagation();addThirdLevel('${firstEncoded}', '${secondEncoded}')" title="新增三级分类">＋</button><button class="tree-add-btn tree-edit-btn" onclick="event.stopPropagation();editSecondLevel('${firstEncoded}', '${secondEncoded}')" title="编辑二级分类">✎</button></span>
                    </summary>`;
                    second.children.forEach(third => {
                        const encoded = encodeURIComponent(third);
                        html += `<div class="tree-leaf ${selectedProductType === third ? 'active' : ''}" onclick="selectProductType('${encoded}')">
                            <span>${escapeHtml(third)} <button class="tree-add-btn tree-edit-btn" onclick="event.stopPropagation();editThirdLevel('${firstEncoded}', '${secondEncoded}', '${encoded}')" title="编辑三级分类">✎</button></span><span class="tree-count">${productTypeCounts[third] || 0}</span>
                        </div>`;
                    });
                    html += `</details>`;
                });
                html += `</details>`;
            });
            treeEl.innerHTML = html;
        }

        async function addSecondLevel(firstEncoded) {
            const firstName = decodeURIComponent(firstEncoded);
            const name = window.prompt(`在「${firstName}」下新增二级分类：`);
            if (!name || !name.trim()) return;
            await createClassification({ level: 'second', first_level: firstName, name: name.trim() });
        }

        async function addThirdLevel(firstEncoded, secondEncoded) {
            const firstName = decodeURIComponent(firstEncoded);
            const secondName = decodeURIComponent(secondEncoded);
            const name = window.prompt(`在「${firstName} / ${secondName}」下新增三级产品分类：`);
            if (!name || !name.trim()) return;
            await createClassification({ level: 'third', first_level: firstName, second_level: secondName, name: name.trim() });
        }

        async function editFirstLevel(encoded) {
            const oldName = decodeURIComponent(encoded);
            const newName = window.prompt('修改一级分类名称：', oldName);
            if (!newName || !newName.trim() || newName.trim() === oldName) return;
            await editClassification({ level: 'first', first_level: oldName, name: oldName, new_name: newName.trim() });
        }

        async function editSecondLevel(firstEncoded, secondEncoded) {
            const firstName = decodeURIComponent(firstEncoded);
            const oldName = decodeURIComponent(secondEncoded);
            const newName = window.prompt('修改二级分类名称：', oldName);
            if (!newName || !newName.trim() || newName.trim() === oldName) return;
            await editClassification({ level: 'second', first_level: firstName, name: oldName, new_name: newName.trim() });
        }

        async function editThirdLevel(firstEncoded, secondEncoded, thirdEncoded) {
            const firstName = decodeURIComponent(firstEncoded);
            const secondName = decodeURIComponent(secondEncoded);
            const oldName = decodeURIComponent(thirdEncoded);
            const newName = window.prompt('修改三级产品分类名称：', oldName);
            if (!newName || !newName.trim() || newName.trim() === oldName) return;
            await editClassification({ level: 'third', first_level: firstName, second_level: secondName, name: oldName, new_name: newName.trim() });
        }

        async function createClassification(payload) {
            try {
                const res = await fetch('/api/product-classifications', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const result = await res.json();
                if (!res.ok) throw new Error(result.detail || '分类新增失败');
                await refreshProductClassifications();
                showToast('分类新增成功', 'success');
            } catch (e) {
                showToast(e.message, 'error');
            }
        }

        async function editClassification(payload) {
            try {
                const res = await fetch('/api/product-classifications', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const result = await res.json();
                if (!res.ok) throw new Error(result.detail || '分类编辑失败');
                if (selectedProductType === payload.name && payload.level === 'third') {
                    selectedProductType = payload.new_name;
                }
                await refreshProductClassifications();
                await loadProducts();
                showToast('分类编辑成功', 'success');
            } catch (e) {
                showToast(e.message, 'error');
            }
        }

        function selectProductType(encodedValue) {
            selectedProductType = decodeURIComponent(encodedValue);
            showUnclassified = false;
            showCorrection = false;
            updateDuplicateFilterState(false);
            currentPage = 1;
            renderClassificationTree();
            loadProducts();
        }

        function selectUnclassified() {
            selectedProductType = '';
            showUnclassified = true;
            showCorrection = false;
            updateDuplicateFilterState(false);
            currentPage = 1;
            document.querySelectorAll('.tree-all, .tree-unclassified, .tree-correction, .tree-leaf').forEach(el => el.classList.remove('active'));
            document.querySelector('.tree-unclassified')?.classList.add('active');
            loadProducts();
        }

        function selectCorrection() {
            selectedProductType = '';
            showUnclassified = false;
            showCorrection = true;
            updateDuplicateFilterState(false);
            currentPage = 1;
            document.querySelectorAll('.tree-all, .tree-unclassified, .tree-correction, .tree-leaf').forEach(el => el.classList.remove('active'));
            document.querySelector('.tree-correction')?.classList.add('active');
            loadProducts();
        }

        function clearProductTypeFilter() {
            selectedProductType = '';
            showUnclassified = false;
            showCorrection = false;
            updateDuplicateFilterState(false);
            currentPage = 1;
            document.querySelectorAll('.tree-all, .tree-unclassified, .tree-correction, .tree-leaf').forEach(el => el.classList.remove('active'));
            document.querySelector('.tree-all')?.classList.add('active');
            loadProducts();
        }

        async function loadProducts(page) {
            if (page) currentPage = page;
            const keyword = document.getElementById('searchInput').value.trim();
            let url = `/api/products?page=${currentPage}&page_size=${PAGE_SIZE}`;
            if (keyword) url += `&keyword=${encodeURIComponent(keyword)}`;
            if (showDuplicatesOnly) url += '&duplicates_only=true';
            if (selectedProductType) url += `&product_type=${encodeURIComponent(selectedProductType)}`;
            if (showUnclassified) url += `&classification_status=unclassified`;
            if (showCorrection) url += `&feedback_status=pending`;
            const res = await fetch(url);
            const data = await res.json();
            totalRecords = data.total;
            const products = data.items;
            const totalPages = Math.ceil(totalRecords / PAGE_SIZE);
            const countEl = document.getElementById('productCount');
            const start = totalRecords ? (currentPage - 1) * PAGE_SIZE + 1 : 0;
            const end = Math.min(currentPage * PAGE_SIZE, totalRecords);
            countEl.textContent = `显示 ${start}-${end} / 共 ${totalRecords} 条`;
            const classificationLabel = showDuplicatesOnly
                ? '全部重复产品'
                : (showCorrection ? '待改正' : (showUnclassified ? '待重新分类' : (selectedProductType || '全部产品')));
            document.getElementById('headerSubtitle').textContent = `${classificationLabel} · 共 ${totalRecords} 条 / 每页 ${PAGE_SIZE} 条`;
            const listEl = document.getElementById('productList');
            listEl.innerHTML = products.map((p, idx) => {
                const seq = (currentPage - 1) * PAGE_SIZE + idx + 1;
                const duplicateMark = p.is_duplicate
                    ? `<button class="duplicate-mark ${p.duplicate_marked ? 'marked' : ''}" onclick="event.stopPropagation();toggleDuplicateMark(${p.id}, this)" title="${p.duplicate_marked ? '点击取消待删除标记' : '点击标记为待删除'}">${p.duplicate_marked ? '已标记删除' : '待删除'}</button>`
                    : '';
                return `<div class="product-item ${p.id === currentProductId ? 'active' : ''}" data-product-id="${p.id}" onclick="selectProduct(${p.id}, this)">
                    <div class="p-seq">${seq}</div>
                    <div class="p-info">
                        <div class="p-name">${escapeHtml(p.product_name || '未命名产品')}${duplicateMark}</div>
                        ${showCorrection ? `<span class="p-feedback-count">${Number(p.pending_feedback_count) || 0} 条待处理反馈</span>` : ''}
                        <div class="p-model">${escapeHtml(p.model || '无型号')}</div>
                        <span class="p-type">${escapeHtml(p.product_type || '待重新分类')}</span>
                        ${p.product_brand ? `<span class="p-brand">${escapeHtml(p.product_brand)}</span>` : ''}
                        <div class="p-updated">最后修改：${escapeHtml(formatUpdateTime(p.update_time_2))}${Number(p.modification_completed) === 1 ? '<span class="p-completed-tag">已完成</span>' : ''}</div>
                    </div>
                </div>`;
            }).join('');
            renderPagination(totalPages);
        }

        async function toggleDuplicateMark(productId, button) {
            if (!button) return;
            // 从按钮 class 动态判断当前状态，不依赖渲染时硬编码的值
            const isMarked = button.classList.contains('marked');
            button.disabled = true;
            try {
                if (isMarked) {
                    // 取消标记 → 变回"待删除"
                    const res = await fetch(`/api/products/${productId}/duplicate-mark`, { method: 'DELETE' });
                    if (!res.ok) throw new Error('取消标记失败');
                    button.textContent = '待删除';
                    button.classList.remove('marked');
                    button.title = '点击标记为待删除';
                    showToast('已取消待删除标记', 'success');
                } else {
                    // 添加标记 → 变为"已标记删除"
                    const res = await fetch(`/api/products/${productId}/duplicate-mark`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ marked_by: '当前员工' }),
                    });
                    const result = await res.json();
                    if (!res.ok) throw new Error(result.detail || '标记失败');
                    button.textContent = '已标记删除';
                    button.classList.add('marked');
                    button.title = '点击取消待删除标记';
                    showToast('已标记为待删除', 'success');
                }
            } catch (e) {
                showToast(e.message, 'error');
            } finally {
                button.disabled = false;
            }
        }

        function renderPagination(totalPages) {
            const pagEl = document.getElementById('pagination');
            if (totalPages <= 1) { pagEl.innerHTML = ''; return; }
            let html = `<button ${currentPage <= 1 ? 'disabled' : ''} onclick="loadProducts(${currentPage - 1})">&#8249;</button>`;
            const pages = buildPageNumbers(currentPage, totalPages);
            pages.forEach(p => {
                if (p === '...') html += `<span class="dots">...</span>`;
                else html += `<button class="${p === currentPage ? 'active' : ''}" onclick="loadProducts(${p})">${p}</button>`;
            });
            html += `<button ${currentPage >= totalPages ? 'disabled' : ''} onclick="loadProducts(${currentPage + 1})">&#8250;</button>`;
            pagEl.innerHTML = html;
        }

        function buildPageNumbers(current, total) {
            const pages = [];
            const delta = 2;
            if (total <= 7) { for (let i = 1; i <= total; i++) pages.push(i); return pages; }
            pages.push(1);
            const rangeStart = Math.max(2, current - delta);
            const rangeEnd = Math.min(total - 1, current + delta);
            if (rangeStart > 2) pages.push('...');
            for (let i = rangeStart; i <= rangeEnd; i++) pages.push(i);
            if (rangeEnd < total - 1) pages.push('...');
            pages.push(total);
            return pages;
        }

        function debounceSearch() {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => { currentPage = 1; loadProducts(); }, 300);
        }

        function updateDuplicateFilterState(enabled) {
            showDuplicatesOnly = Boolean(enabled);
            const button = document.getElementById('duplicateFilterButton');
            if (!button) return;
            button.classList.toggle('active', showDuplicatesOnly);
            button.setAttribute('aria-pressed', String(showDuplicatesOnly));
            button.textContent = showDuplicatesOnly ? '正在查看全部重复' : '只看重复';
        }

        function toggleDuplicateFilter() {
            const enableDuplicates = !showDuplicatesOnly;
            updateDuplicateFilterState(enableDuplicates);
            currentPage = 1;
            selectedProductType = '';
            showUnclassified = false;
            showCorrection = false;
            const searchInput = document.getElementById('searchInput');
            if (enableDuplicates && searchInput) {
                searchInput.value = '';
            }
            document.querySelectorAll('.tree-all, .tree-unclassified, .tree-correction, .tree-leaf')
                .forEach(el => el.classList.remove('active'));
            if (!enableDuplicates) document.querySelector('.tree-all')?.classList.add('active');
            loadProducts();
        }

        async function selectProduct(id, sourceElement = null) {
            currentProductId = id;
            document.querySelectorAll('.product-item').forEach(el => el.classList.remove('active'));
            if (sourceElement) sourceElement.classList.add('active');
            const main = document.getElementById('mainContent');
            main.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
            main.scrollTop = 0;
            try {
                const [prodRes, specsRes, pricesRes, combinationsRes, feedbackRes, feedbackHistoryRes] = await Promise.all([
                    fetch(`/api/products/${id}`),
                    fetch(`/api/products/${id}/variant-specs`),
                    fetch(`/api/products/${id}/variant-prices`),
                    fetch(`/api/products/${id}/variant-combinations`),
                    fetch(`/api/products/${id}/feedback?status=pending`),
                    fetch(`/api/products/${id}/feedback`)
                ]);
                if (!prodRes.ok) throw new Error('加载失败');
                currentData = await prodRes.json();
                currentVariantSpecs = specsRes.ok ? await specsRes.json() : [];
                currentVariantPrices = pricesRes.ok ? await pricesRes.json() : [];
                currentVariantCombinations = combinationsRes.ok ? await combinationsRes.json() : [];
                currentProductFeedback = feedbackRes.ok ? await feedbackRes.json() : [];
                currentProductFeedbackHistory = feedbackHistoryRes.ok ? await feedbackHistoryRes.json() : [];
                // 预加载所有供应商的开票能力，用于价格展示过滤
                const oaIds = [...new Set(currentVariantPrices.map(p => p.oa_supplier_id).filter(Boolean))];
                await Promise.all(oaIds.map(id => _loadOaSupplierCapability(id)));
                selectedVariantValues = [];
                currentSelectedVariantPrice = null;
                renderDetail(currentData);
                loadRelations(currentData.id);
            } catch (e) {
                main.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
            }
        }

        function formatUpdateTime(value) {
            if (!value) return '暂无记录';
            const text = String(value).replace('T', ' ');
            return text.length > 16 ? text.slice(0, 16) : text;
        }

        function feedbackStatusMeta(status) {
            const normalized = String(status || '').toLowerCase();
            if (normalized === 'completed') return {label: '已完成', className: 'completed'};
            if (normalized === 'ignored') return {label: '已忽略', className: 'ignored'};
            return {label: '待处理', className: 'pending'};
        }

        function renderProductCorrectionLogs() {
            if (!currentProductFeedbackHistory.length) {
                return `<div class="correction-log-empty">
                    <span class="correction-log-empty-icon">&#128221;</span>
                    <strong>暂无改正记录</strong>
                    <p>销售提交的产品问题会记录在这里。</p>
                </div>`;
            }
            return `<div class="correction-log-list">${currentProductFeedbackHistory.map(feedback => {
                const status = feedbackStatusMeta(feedback.status);
                const typeText = (feedback.issue_type_labels || []).map(label => `【${escapeHtml(label)}】`).join('');
                const handler = `<span><b>处理人：</b>${escapeHtml(feedback.handled_by_name || '暂未处理')}</span>`;
                const handledAt = `<span><b>处理时间：</b>${feedback.handled_at
                    ? escapeHtml(formatUpdateTime(feedback.handled_at))
                    : '暂未处理'}</span>`;
                const handleRemark = feedback.handle_remark
                    ? `<div class="correction-log-remark"><span>处理说明</span>${escapeHtml(feedback.handle_remark)}</div>`
                    : '';
                return `<article class="correction-log-card">
                    <div class="correction-log-head">
                        <div>
                            <span class="correction-log-reporter"><b>反馈人：</b>${escapeHtml(feedback.feedback_user_name || '未知用户')}</span>
                            <time><b>反馈时间：</b>${escapeHtml(formatUpdateTime(feedback.created_at))}</time>
                        </div>
                        <span class="correction-log-status ${status.className}">${status.label}</span>
                    </div>
                    <div class="correction-log-body">
                        <div class="correction-log-types">${typeText || '【其他问题】'}</div>
                        <div class="correction-log-description">${escapeHtml(feedback.description || '')}</div>
                        <div class="correction-log-handler">${handler}${handledAt}</div>
                        ${handleRemark}
                    </div>
                </article>`;
            }).join('')}</div>`;
        }

        async function updateProductFeedbackStatus(feedbackId, status) {
            const actionText = status === 'completed' ? '完成' : '忽略';
            try {
                const res = await fetch(`/api/feedback/${feedbackId}/status`, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({status}),
                });
                const result = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(result.detail || `标记${actionText}失败`);
                const [feedbackRes, feedbackHistoryRes] = await Promise.all([
                    fetch(`/api/products/${currentProductId}/feedback?status=pending`),
                    fetch(`/api/products/${currentProductId}/feedback`),
                ]);
                currentProductFeedback = feedbackRes.ok ? await feedbackRes.json() : [];
                currentProductFeedbackHistory = feedbackHistoryRes.ok ? await feedbackHistoryRes.json() : [];
                await refreshProductClassifications();
                await loadProducts();
                if (showCorrection && currentProductFeedback.length === 0) {
                    currentProductId = null;
                    currentData = null;
                    document.getElementById('mainContent').innerHTML = `<div class="empty-state"><div class="icon">&#128214;</div><p>该产品反馈已处理完成，请继续选择其他待改正产品</p></div>`;
                } else if (currentData) {
                    renderDetail(currentData);
                }
                showToast(`已标记${actionText}`, 'success');
            } catch (error) {
                showToast(error.message || `标记${actionText}失败`, 'error');
            }
        }

        async function markProductModificationComplete() {
            if (!currentProductId) {
                showToast('请先选择产品', 'error');
                return;
            }
            const button = document.getElementById('productCompletionButton');
            if (button?.disabled) return;
            const wasCompleted = Boolean(currentData?.modification_completed);
            if (button) {
                button.disabled = true;
                button.textContent = wasCompleted ? '正在撤销...' : '正在标记...';
            }
            try {
                const res = await fetch(`/api/products/${currentProductId}/complete-modification`, {
                    method: 'POST',
                });
                const result = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(result.detail || '标记修改完成失败');
                const completed = Boolean(result.completed);
                if (currentData) {
                    currentData.modification_completed = completed;
                    currentData.modification_completed_by = '';
                    currentData.modification_completed_at = completed ? new Date().toISOString() : null;
                }
                if (button) {
                    button.classList.toggle('completed', completed);
                    button.textContent = completed ? '✓ 已标记修改完成' : '标记修改完成';
                }
                const listItem = document.querySelector(`.product-item[data-product-id="${currentProductId}"]`);
                const updated = listItem?.querySelector('.p-updated');
                const existingTag = updated?.querySelector('.p-completed-tag');
                if (completed && updated && !existingTag) {
                    updated.insertAdjacentHTML('beforeend', '<span class="p-completed-tag">已完成</span>');
                } else if (!completed) {
                    existingTag?.remove();
                }
                showToast(result.message || (completed ? '已标记修改完成' : '已撤销修改完成标记'), 'success');
            } catch (error) {
                if (button) {
                    button.textContent = currentData?.modification_completed
                        ? '✓ 已标记修改完成'
                        : '标记修改完成';
                }
                showToast(error.message || '标记修改完成失败', 'error');
            } finally {
                if (button) button.disabled = false;
            }
        }

        // ========== 渲染详情 ==========
        function renderDetail(data) {
            const main = document.getElementById('mainContent');
            let html = '';

            // 面包屑
            html += `<div class="breadcrumb">
                <span>配件管理</span><span>/</span>
                <span>${escapeHtml(data.product_type || '待重新分类')}</span><span>/</span>
                <span class="bc-current">${escapeHtml(data.product_name || '未命名产品')}</span>
                <div class="breadcrumb-actions">
                </div>
            </div>`;

            if (showCorrection && currentProductFeedback.length) {
                html += `<section class="product-feedback-list">
                    ${currentProductFeedback.map(feedback => {
                        const typeText = (feedback.issue_type_labels || []).map(label => `【${escapeHtml(label)}】`).join('');
                        return `<article class="product-feedback-card" data-feedback-id="${feedback.id}">
                            <div class="product-feedback-content">
                                <strong>${escapeHtml(formatUpdateTime(feedback.created_at))} ${escapeHtml(feedback.feedback_user_name || '未知用户')}：</strong>
                                <span class="product-feedback-types">${typeText}</span>
                                <span>${escapeHtml(feedback.description || '')}</span>
                            </div>
                            <div class="product-feedback-actions">
                                <button type="button" class="complete" onclick="updateProductFeedbackStatus(${feedback.id}, 'completed')">标记完成</button>
                                <button type="button" class="ignore" onclick="updateProductFeedbackStatus(${feedback.id}, 'ignored')">标记忽略</button>
                            </div>
                        </article>`;
                    }).join('')}
                </section>`;
            }

            // 注意事项（已移到产品头部，此处隐藏）

            // 两列布局
            html += `<div class="detail-container">`;

            // 左列：图片画廊 + 价格 + 技术参数
            html += `<div class="detail-left-col">`;

            // 图片画廊（左缩略图+右大图）
            html += `<div class="gallery-section">
                <div class="gallery-thumbs-col">
                    <div class="gallery-thumbs-scroll" id="galleryThumbsScroll"></div>
                </div>
                <div class="gallery-main-col">
                    <div class="gallery-main" id="galleryMain">
                        <div class="gallery-img-wrap">
                            <button class="gallery-nav-btn gallery-nav-left" onclick="navGalleryImg(-1)">&#10094;</button>
                            <span class="no-img">点击左侧缩略图查看</span>
                            <button class="gallery-nav-btn gallery-nav-right" onclick="navGalleryImg(1)">&#10095;</button>
                        </div>
                    </div>
                </div>
            </div>`;

            // 技术参数 + 替代型号 & 备注（左列）
            html += `<div class="spec-section">
                <table class="spec-table">
                    <tr><td>技术参数</td><td><span class="field-value" id="fv-technical_params" onclick="editField('technical_params')">${renderTechnicalParams(data.technical_params)}</span></td></tr>
                    <tr><td>${fieldLabels['substitute_model']}</td><td><span class="field-value" id="fv-substitute_model" onclick="editField('substitute_model')">${renderVal(data.substitute_model)}</span></td></tr>
                    <tr><td>${fieldLabels['remark']}</td><td><span class="field-value" id="fv-remark" onclick="editField('remark')">${renderVal(data.remark)}</span></td></tr>
                    <tr><td>${fieldLabels['remark_2']}</td><td><span class="field-value" id="fv-remark_2" onclick="editField('remark_2')">${renderVal(data.remark_2)}</span></td></tr>
                </table>
                <div style="margin-top:12px;padding-top:12px;border-top:1px solid #e5e7eb">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                        <span style="font-size:14px;font-weight:600;color:#111827">关联产品</span>
                        <button class="product-completion-button" style="margin-left:0;padding:0 10px" onclick="openRelationModal(${data.id}, '${escapeHtml(data.product_name || '').replace(/'/g, "\\'")}')">+ 关联</button>
                    </div>
                    <div id="relationList" class="relation-list"></div>
                </div>
            </div>`;

            html += `</div>`; // 关闭 detail-left-col

            // 右列：信息区
            html += `<div class="info-section">`;

            // 产品头部
            html += `<div class="product-header">
                <div class="header-row">
                    <span class="sku-tag" style="display:none"><span style="opacity:0.7;font-size:11px">SKU编码：</span><span class="field-value" id="fv-sku_code" onclick="editField('sku_code')">${escapeHtml(data.sku_code || '无SKU')}</span></span>
                    <span class="warning-bar-inline">
                        <span class="icon" style="color:#d97706">&#9888;</span>
                        <span style="color:#92400e;font-weight:500;margin-right:4px;font-size:12px">注意事项：</span>
                        <span class="field-value" id="fv-precautions" onclick="editField('precautions')" style="font-size:12px;color:#92400e">${escapeHtml(data.precautions || '暂无，点击添加')}</span>
                    </span>
                    <button class="product-completion-button" style="margin-left:0" onclick="copyProduct()">一键复制</button>
                    <button type="button" id="productCompletionButton"
                        class="product-completion-button ${data.modification_completed ? 'completed' : ''}"
                        onclick="markProductModificationComplete()">
                        ${data.modification_completed ? '✓ 已标记修改完成' : '标记修改完成'}
                    </button>
                </div>
                <div style="margin-bottom:10px">
                    <span style="color:var(--text-light);font-size:13px;margin-right:4px">产品名称：</span>
                    <h1 style="display:inline;font-size:20px" class="field-value" id="fv-product_name" onclick="editField('product_name')">${escapeHtml(data.product_name || '未命名产品')}</h1>
                </div>
                <div class="product-meta">
                    <span><span class="meta-label">型号：</span><span class="meta-value field-value" id="fv-model" onclick="editField('model')">${escapeHtml(data.model || '无型号')}</span></span>
                    <span><span class="meta-label">产品品牌：</span><span class="meta-value field-value" id="fv-product_brand" onclick="editField('product_brand')">${escapeHtml(data.product_brand || '无品牌')}</span></span>
                    <span><span class="meta-label">质保：</span><span class="meta-value field-value" id="fv-warranty" onclick="editField('warranty')">${escapeHtml(data.warranty || '无')}</span></span>
                    <span><span class="meta-label">适用电梯品牌：</span><span class="meta-value field-value" id="fv-applicable_elevator_brand" onclick="editField('applicable_elevator_brand')">${escapeHtml(data.applicable_elevator_brand || '无')}</span></span>
                </div>
                <div class="product-tags">
                    <span class="tag tag-primary"><span style="opacity:0.7">产品分类：</span><span class="field-value" id="fv-product_type" onclick="editField('product_type')">${escapeHtml(data.product_type || '点击设置三级分类')}</span></span>
                    <span class="tag tag-primary" style="display:none"><span style="opacity:0.7">品类归属：</span><span class="field-value" id="fv-category" onclick="editField('category')">${escapeHtml(data.category || '未分类')}</span></span>
                    <span class="tag tag-success"><span style="opacity:0.7">性质：</span><span class="field-value" id="fv-nature" onclick="editField('nature')">${escapeHtml(data.nature || '未标注')}</span></span>
                    <span class="tag tag-warning"><span style="opacity:0.7">供应商：</span><span class="field-value" id="fv-supplier" onclick="editField('supplier')">${escapeHtml(data.supplier || '无供应商')}</span></span>
                </div>
                <div class="main-price-meta">
                    <div class="main-price-item purchase-cost-highlight">
                        <span class="main-price-label">采购成本价</span>
                        <span class="main-price-value field-value" id="fv-purchase_cost" onclick="editField('purchase_cost')">${escapeHtml(data.purchase_cost || '-')}</span>
                    </div>
                    <div class="main-price-item">
                        <span class="main-price-label">进项专票</span>
                        <span class="main-price-value field-value" id="fv-purchase_special_invoice" onclick="editField('purchase_special_invoice')">${escapeHtml(data.purchase_special_invoice || '-')}</span>
                    </div>
                    <div class="main-price-item">
                        <span class="main-price-label">进项普票</span>
                        <span class="main-price-value field-value" id="fv-purchase_general_invoice" onclick="editField('purchase_general_invoice')">${escapeHtml(data.purchase_general_invoice || '-')}</span>
                    </div>
                    <div class="main-price-item">
                        <span class="main-price-label">采购运费</span>
                        <span class="main-price-value field-value" id="fv-purchase_shipping" onclick="editField('purchase_shipping')">${escapeHtml(data.purchase_shipping || '-')}</span>
                    </div>
                </div>
            </div>`;

            // 选择规格与供应商（层级卡片布局）
            const manageBtns = `<div class="variant-manage-actions">
                <button class="variant-manage-btn" onclick="openSpecManager()">规格配置</button>
            </div>`;

            if (currentVariantSpecs.length) {
                html += `<div class="variant-selector-card">`;
                html += `<div class="variant-selector-header"><span class="variant-selector-title">选择规格与供应商</span>${manageBtns}</div>`;
                html += renderVariantHierarchy();
                html += `</div>`;
            } else {
                html += `<div class="variant-selector-card">
                    <div class="variant-selector-header"><span class="variant-selector-title">选择规格与供应商</span>${manageBtns}</div>
                    <div class="vs-no-data">暂无规格数据，请先点击"规格配置"添加规格名和规格值。</div>
                </div>`;
            }

            html += `</div></div>`; // 关闭 info-section 和 detail-container

            // 下方标签页
            html += `<div class="tabs-section">
                <div class="tabs">
                    <div class="tab active" onclick="switchTab(this, 'tab-images')">图片资料</div>
                    <div class="tab" onclick="switchTab(this, 'tab-records')">操作记录</div>
                    <div class="tab" onclick="switchTab(this, 'tab-corrections')">改正日志</div>
                </div>
                <div class="tab-content">
                    <div class="tab-pane active" id="tab-images">
                        <div style="display:flex;justify-content:flex-end;margin-bottom:10px">
                            <button class="lib-pick-btn" onclick="openFullImageView()" style="font-size:13px;padding:6px 14px">&#128065; 全屏查看</button>
                        </div>
                        <div class="image-grid" id="imageGrid"></div>
                    </div>
                    <div class="tab-pane" id="tab-records">
                        <div class="record-list">
                            <div class="record-item"><span class="r-label">${fieldLabels['updater'] || '更新人'}</span><span class="r-value field-value" id="fv-updater" onclick="editField('updater')">${renderVal(data.updater)}</span></div>
                            <div class="record-item"><span class="r-label">${fieldLabels['update_time'] || '更新时间'}</span><span class="r-value field-value" id="fv-update_time" onclick="editField('update_time')">${renderVal(data.update_time)}</span></div>
                            <div class="record-item"><span class="r-label">${fieldLabels['filler'] || '填报人'}</span><span class="r-value field-value" id="fv-filler" onclick="editField('filler')">${renderVal(data.filler)}</span></div>
                            <div class="record-item"><span class="r-label">${fieldLabels['filler_2'] || '填报人(2)'}</span><span class="r-value field-value" id="fv-filler_2" onclick="editField('filler_2')">${renderVal(data.filler_2)}</span></div>
                            <div class="record-item"><span class="r-label">${fieldLabels['update_time_2'] || '更新时间(2)'}</span><span class="r-value" id="fv-update_time_2">${renderVal(data.update_time_2)}</span></div>
                            <div class="record-item"><span class="r-label">${fieldLabels['filler_ip'] || '填报IP'}</span><span class="r-value field-value" id="fv-filler_ip" onclick="editField('filler_ip')">${renderVal(data.filler_ip)}</span></div>
                            <div class="record-item"><span class="r-label">${fieldLabels['quote_validity'] || '报价有效期'}</span><span class="r-value field-value" id="fv-quote_validity" onclick="editField('quote_validity')">${renderVal(data.quote_validity)}</span></div>
                        </div>
                    </div>
                    <div class="tab-pane" id="tab-corrections">
                        ${renderProductCorrectionLogs()}
                    </div>
                </div>
            </div>`;

            main.innerHTML = html;

            // 渲染图片画廊和标签页内容
            renderGallery(data);
            renderImageGrid(data);
        }


        function editParam(paramId) {
            const valEl = document.querySelector(`.param-val-${paramId}`);
            const editEl = document.querySelector(`.param-edit-${paramId}`);
            if (!valEl || !editEl) return;
            valEl.style.display = 'none';
            editEl.style.display = 'flex';
            const input = document.getElementById(`param-input-${paramId}`);
            if (input) {
                input.focus();
                const len = input.value.length;
                input.style.width = Math.max(3, Math.min(len + 2, 25)) + 'em';
            }
        }

        function cancelEditParam(paramId) {
            const valEl = document.querySelector(`.param-val-${paramId}`);
            const editEl = document.querySelector(`.param-edit-${paramId}`);
            if (!valEl || !editEl) return;
            valEl.style.display = '';
            editEl.style.display = 'none';
            // 恢复原始值
            const p = currentParams.find(x => x.id === paramId);
            const input = document.getElementById(`param-input-${paramId}`);
            if (p && input) input.value = p.param_value || '';
        }

        async function saveParam(paramId) {
            const input = document.getElementById(`param-input-${paramId}`);
            if (!input) return;
            const value = input.value.trim();
            if (!value) { showToast('参数值不能为空', 'error'); return; }
            try {
                const res = await fetch(`/api/products/${currentProductId}/params/${paramId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ param_value: value }),
                });
                if (!res.ok) throw new Error('保存失败');
                const p = currentParams.find(x => x.id === paramId);
                if (p) p.param_value = value;
                renderParams();
                await loadProducts();
                showToast('参数已更新', 'success');
            } catch (e) { showToast(e.message, 'error'); }
        }

        function addParam() {
            const tbody = document.getElementById('paramsBody');
            const noMsg = document.getElementById('noParamsMsg');
            if (!tbody) return;
            if (noMsg) noMsg.style.display = 'none';

            // 添加一行内编辑行
            const tempId = 'new';
            const tr = document.createElement('tr');
            tr.id = 'param-row-new';
            const idx = (currentParams || []).length + 1;
            tr.innerHTML = `
                <td style="width:30px;color:var(--text-muted);font-size:12px">${idx}.</td>
                <td>
                    <div class="field-edit param-edit-new" style="display:flex">
                        <input type="text" id="param-input-new" placeholder="输入参数值"
                               onkeydown="if(event.key==='Enter'){event.stopPropagation();confirmAddParam()}if(event.key==='Escape'){event.stopPropagation();cancelAddParam()}"
                               onclick="event.stopPropagation()" style="width:10em">
                        <div class="edit-actions">
                            <button class="btn-confirm" onclick="event.stopPropagation();confirmAddParam()" title="确认">&#10003;</button>
                            <button class="btn-cancel" onclick="event.stopPropagation();cancelAddParam()" title="取消">&#10005;</button>
                        </div>
                    </div>
                </td>
                <td></td>
            `;
            tbody.appendChild(tr);
            const input = document.getElementById('param-input-new');
            if (input) input.focus();
        }

        function cancelAddParam() {
            const tr = document.getElementById('param-row-new');
            if (tr) tr.remove();
            // 如果没有参数，显示提示消息
            if (!currentParams || currentParams.length === 0) {
                const noMsg = document.getElementById('noParamsMsg');
                if (noMsg) noMsg.style.display = 'block';
            }
        }

        async function confirmAddParam() {
            const input = document.getElementById('param-input-new');
            if (!input) return;
            const value = input.value.trim();
            if (!value) { showToast('参数值不能为空', 'error'); return; }
            try {
                const res = await fetch(`/api/products/${currentProductId}/params`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ param_value: value }),
                });
                if (!res.ok) throw new Error('新增失败');
                const newParam = await res.json();
                currentParams.push(newParam);
                renderParams();
                await loadProducts();
                showToast('参数已添加', 'success');
            } catch (e) { showToast(e.message, 'error'); }
        }

        async function deleteParam(paramId) {
            if (!confirm('确定删除此参数？')) return;
            try {
                const res = await fetch(`/api/products/${currentProductId}/params/${paramId}`, {
                    method: 'DELETE',
                });
                if (!res.ok) throw new Error('删除失败');
                currentParams = currentParams.filter(x => x.id !== paramId);
                renderParams();
                await loadProducts();
                showToast('参数已删除', 'success');
            } catch (e) { showToast(e.message, 'error'); }
        }

        // ========== 关联产品 ==========

        async function loadRelations(productId) {
            const listEl = document.getElementById('relationList');
            if (!listEl) return;
            try {
                const res = await fetch(`/api/products/${productId}/relations`);
                const data = await res.json();
                if (!data.relations?.length) {
                    listEl.innerHTML = '<div class="relation-list-empty">暂无关联产品</div>';
                    return;
                }
                listEl.innerHTML = data.relations.map(p => `
                    <div class="relation-list-item">
                        <span>${escapeHtml(p.product_name || '')} ${escapeHtml(p.model ? '(' + p.model + ')' : '')}</span>
                        <span class="relation-item-del" onclick="deleteRelation(${productId}, ${p.id})">删除</span>
                    </div>
                `).join('');
            } catch (e) {
                listEl.innerHTML = '<div class="relation-list-empty relation-error">加载失败</div>';
            }
        }

        let relationSelectedIds = new Set();
        let currentRelationProductId = null;

        function openRelationModal(productId, productName) {
            relationSelectedIds = new Set();
            currentRelationProductId = productId;
            const modal = document.createElement('div');
            modal.className = 'imglib-overlay';
            modal.id = 'relationModal';
            modal.innerHTML = `
                <div class="imglib-modal relation-modal" onclick="event.stopPropagation()">
                    <div class="imglib-header">
                        <h3>选择关联产品</h3>
                        <button class="close-btn" onclick="closeRelationModal()">&#10005;</button>
                    </div>
                    <div class="imglib-body">
                        <div class="imglib-content">
                            <div class="imglib-toolbar">
                                <input id="relationSearch" type="text" placeholder="搜索产品名称/型号..." oninput="searchRelationProduct()">
                            </div>
                            <div class="imglib-grid-wrap" id="relationSearchResults"></div>
                            <div class="imglib-pagination" id="relationPagination"></div>
                        </div>
                    </div>
                    <div class="imglib-footer">
                        <button class="lib-btn lib-btn-secondary" onclick="closeRelationModal()">取消</button>
                        <button class="lib-btn lib-btn-primary" id="relationConfirmBtn" onclick="confirmAddRelations()" disabled>确认添加</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            modal.classList.add('show');
            const searchInput = document.getElementById('relationSearch');
            searchInput.focus();
            if (productName) {
                searchInput.value = productName;
                doSearchRelation(productName);
            }
        }

        function closeRelationModal() {
            document.getElementById('relationModal')?.remove();
            relationSelectedIds = new Set();
            currentRelationProductId = null;
        }

        function toggleRelationSelect(id, element) {
            relationSelectedIds.has(id) ? relationSelectedIds.delete(id) : relationSelectedIds.add(id);
            element.classList.toggle('selected', relationSelectedIds.has(id));
            element.querySelector('.relation-item-check').textContent = relationSelectedIds.has(id) ? '✓' : '';
            const n = relationSelectedIds.size;
            const btn = document.getElementById('relationConfirmBtn');
            btn.disabled = n === 0;
            btn.textContent = n > 0 ? `确认添加 (${n})` : '确认添加';
        }

        async function confirmAddRelations() {
            const productId = currentRelationProductId;
            const results = await Promise.all([...relationSelectedIds].map(id =>
                fetch(`/api/products/${productId}/relations`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ related_product_id: id }),
                }).then(r => r.ok).catch(() => false)
            ));
            const success = results.filter(Boolean).length;
            const fail = results.length - success;
            closeRelationModal();
            loadRelations(productId);
            if (success > 0) showToast(`成功关联 ${success} 个产品${fail > 0 ? `，${fail} 个失败` : ''}`, fail > 0 ? 'warning' : 'success');
            else showToast('关联失败', 'error');
        }

        let relationSearchTimer;
        let relationCurrentPage = 1;
        const relationPageSize = 20;

        function searchRelationProduct() {
            clearTimeout(relationSearchTimer);
            relationSearchTimer = setTimeout(() => {
                relationCurrentPage = 1;
                doSearchRelation();
            }, 300);
        }

        async function doSearchRelation(keywordOverride) {
            const keyword = keywordOverride || document.getElementById('relationSearch').value.trim();
            const resultEl = document.getElementById('relationSearchResults');
            if (!keyword) { resultEl.innerHTML = ''; return; }
            try {
                const res = await fetch(`/api/products?keyword=${encodeURIComponent(keyword)}&page=${relationCurrentPage}&page_size=${relationPageSize}`);
                const data = await res.json();
                const products = (data.items || []).filter(p => p.id !== currentRelationProductId);
                if (!products.length) {
                    resultEl.innerHTML = '<div class="relation-empty">无匹配产品</div>';
                    document.getElementById('relationPagination').innerHTML = '';
                    return;
                }
                const totalPages = Math.ceil(data.total / relationPageSize);
                const countHtml = `<div class="relation-result-count">共 ${data.total} 个产品${totalPages > 1 ? `，第 ${relationCurrentPage}/${totalPages} 页` : ''}</div>`;
                const listHtml = products.map(p => {
                    const isSelected = relationSelectedIds.has(p.id);
                    return `
                    <div class="relation-search-item${isSelected ? ' selected' : ''}" onclick="toggleRelationSelect(${p.id}, this)">
                        <div class="relation-item-check">${isSelected ? '✓' : ''}</div>
                        <div class="relation-item-info">
                            <div class="relation-item-title">${escapeHtml(p.product_name || '')}${p.model ? ' <span class="relation-item-model">' + escapeHtml(p.model) + '</span>' : ''}</div>
                            <div class="relation-item-meta">
                                ${p.product_brand ? '<span>' + escapeHtml(p.product_brand) + '</span>' : ''}
                                ${p.category ? '<span>' + escapeHtml(p.category) + '</span>' : ''}
                            </div>
                        </div>
                    </div>`;
                }).join('');
                resultEl.innerHTML = countHtml + listHtml;
                document.getElementById('relationPagination').innerHTML = totalPages > 1 ? `
                    <button class="relation-page-btn" ${relationCurrentPage <= 1 ? 'disabled' : ''} onclick="relationGoPage(${relationCurrentPage - 1})">上一页</button>
                    <span class="relation-page-info">${relationCurrentPage} / ${totalPages}</span>
                    <button class="relation-page-btn" ${relationCurrentPage >= totalPages ? 'disabled' : ''} onclick="relationGoPage(${relationCurrentPage + 1})">下一页</button>
                ` : '';
            } catch (e) {
                resultEl.innerHTML = '<div class="relation-empty relation-error">搜索失败</div>';
            }
        }

        function relationGoPage(page) {
            relationCurrentPage = page;
            doSearchRelation();
            document.getElementById('relationSearchResults').scrollTop = 0;
        }

        async function deleteRelation(productId, relatedId) {
            if (!confirm('确定删除此关联？')) return;
            try {
                const res = await fetch(`/api/products/${productId}/relations/${relatedId}`, {
                    method: 'DELETE',
                });
                if (!res.ok) throw new Error('删除失败');
                loadRelations(productId);
                showToast('删除成功', 'success');
            } catch (e) { showToast(e.message, 'error'); }
        }
