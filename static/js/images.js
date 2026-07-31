// ========== 图片画廊（左缩略图+右大图） ==========
        let galleryImages = [];
        let galleryCurrentIndex = 0;
        let imglibModalRotation = 0;

        function renderGallery(data) {
            galleryImages = [];
            IMAGE_FIELDS.forEach(field => {
                const urls = parseImageUrls(data[field]);
                urls.forEach(u => galleryImages.push({ url: u, field, label: fieldLabels[field] || field }));
            });
            galleryCurrentIndex = 0;

            const mainEl = document.getElementById('galleryMain');
            const thumbsEl = document.getElementById('galleryThumbsScroll');

            if (galleryImages.length === 0) {
                mainEl.innerHTML = '<span class="no-img">暂无图片</span>';
                if (thumbsEl) thumbsEl.innerHTML = '';
                return;
            }

            // 主图
            mainEl.innerHTML = `<div class="gallery-img-wrap">
                <button class="gallery-nav-btn gallery-nav-left" onclick="navGalleryImg(-1)">&#10094;</button>
                <img src="${escapeHtml(galleryImages[0].url)}" alt="产品图片" id="galleryMainImg" onclick="showModal(this.src)" style="cursor:pointer">
                <button class="gallery-nav-btn gallery-nav-right" onclick="navGalleryImg(1)">&#10095;</button>
            </div>`;

            // 缩略图
            if (thumbsEl) {
                thumbsEl.innerHTML = galleryImages.map((img, i) =>
                    `<div class="gallery-thumb ${i === 0 ? 'active' : ''}" onclick="switchGalleryImg(${i})">
                        <img src="${escapeHtml(img.url)}" alt="${escapeHtml(img.label)}" onerror="this.parentElement.style.display='none'">
                    </div>`
                ).join('');
            }
        }

        function switchGalleryImg(index) {
            if (index < 0 || index >= galleryImages.length) return;
            galleryCurrentIndex = index;
            document.querySelectorAll('.gallery-thumb').forEach((t, i) => t.classList.toggle('active', i === index));
            const mainImg = document.getElementById('galleryMainImg');
            if (mainImg) mainImg.src = galleryImages[index].url;
            // 滚动缩略图到可见区域
            const thumbsEl = document.getElementById('galleryThumbsScroll');
            if (thumbsEl) {
                const thumb = thumbsEl.children[index];
                if (thumb) thumb.scrollIntoView({ block: 'nearest' });
            }
        }

        function navGalleryImg(dir) {
            if (!galleryImages.length) return;
            let next = galleryCurrentIndex + dir;
            if (next < 0) next = galleryImages.length - 1;
            if (next >= galleryImages.length) next = 0;
            switchGalleryImg(next);
        }

        function scrollThumbs(dir) {
            const thumbsEl = document.getElementById('galleryThumbsScroll');
            if (!thumbsEl) return;
            thumbsEl.scrollBy({ top: dir * 140, behavior: 'smooth' });
        }

        // ========== 图片网格（标签页） ==========
        function renderImageGrid(data) {
            const gridEl = document.getElementById('imageGrid');
            let html = '';
            IMAGE_FIELDS.forEach(field => {
                const urls = parseImageUrls(data[field]);
                const label = fieldLabels[field] || field;
                html += `<div class="image-grid-item" data-image-field="${field}" style="position:relative" tabindex="0"
                    onpaste="pasteEditImages(event, '${field}')"
                    ondragover="allowImageDrop(event)" ondragleave="leaveImageDrop(event)" ondrop="dropImage(event, '${field}')"
                    title="点击此列后可粘贴图片，也可从微信、飞书或本地拖入；已有图片可拖到其他图片类型">
                    <div class="img-label">${label}</div>`;
                if (urls.length > 0) {
                    urls.forEach((u, idx) => {
                        html += `<div draggable="true" ondragstart="startImageDrag(event, '${field}', ${idx})" ondragend="endImageDrag(event)"
                            style="position:relative;display:block;width:100%;margin-bottom:3px;cursor:grab" title="拖动到其他图片类型">
                            <img src="${escapeHtml(u)}" alt="${label}" draggable="false" onclick="showModal(this.src)" onerror="this.style.display='none'" style="width:100%;height:48px;object-fit:cover;border-radius:3px;cursor:pointer">
                            <span onclick="event.stopPropagation();deleteImage('${field}', ${idx})" style="position:absolute;top:-4px;right:-4px;width:14px;height:14px;background:#ea4335;color:#fff;border-radius:50%;font-size:9px;display:flex;align-items:center;justify-content:center;cursor:pointer;line-height:1" title="删除此图片">&#10005;</span>
                        </div>`;
                    });
                } else {
                    html += `<div style="color:#ccc;font-size:12px;padding:10px 0">无图片</div>`;
                }
                // 本地上传到七牛云，或从图片库选择
                html += `<div class="edit-image-paste-hint" onclick="event.stopPropagation();this.closest('.image-grid-item').focus()" title="点击后按 Ctrl+V 粘贴图片">
                    <span>粘贴 / 拖入</span>
                </div>
                <div class="image-source-actions">
                    <button class="local-upload-btn" data-upload-field="${field}" onclick="event.stopPropagation();openLocalImageUpload('${field}')" title="${imageUploadConfig.configured ? '从本地选择图片并上传到七牛云' : '请先配置七牛云环境变量'}" ${imageUploadConfig.configured ? '' : 'disabled'}>&#8679; 本地</button>
                    <button class="lib-pick-btn" onclick="event.stopPropagation();openImgLib('${field}')" title="从图片库选择">&#128247; 图片库</button>
                </div>`;
                html += `</div>`;
            });
            gridEl.innerHTML = html;
        }

        function openLocalImageUpload(field) {
            if (!currentProductId || !currentData) {
                showToast('请先选择产品', 'error');
                return;
            }
            if (!imageUploadConfig.configured) {
                showToast('七牛云尚未配置，请先配置服务端环境变量', 'error');
                return;
            }
            if (localImageUploading) return;
            localImageTargetField = field;
            const input = document.getElementById('localImageInput');
            input.value = '';
            input.click();
        }

        async function uploadLocalImages(fileList, targetField = null) {
            const files = normalizeCreateImageFiles(fileList);
            const field = targetField || localImageTargetField;
            if (!field || !files.length || localImageUploading) return;
            if (!currentProductId || !currentData) {
                showToast('请先选择产品', 'error');
                return;
            }
            if (!imageUploadConfig.configured) {
                showToast('七牛云尚未配置，请先配置服务端环境变量', 'error');
                return;
            }
            const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp'];
            const maxFileSizeMb = imageUploadConfig.max_file_size_mb || 10;
            const invalid = files.find(file =>
                !allowedTypes.includes(file.type)
                || file.size > maxFileSizeMb * 1024 * 1024
            );
            if (invalid) {
                showToast(`仅支持不超过 ${maxFileSizeMb}MB 的 JPG、PNG、GIF、WebP、BMP 图片`, 'error');
                return;
            }
            if (files.length > (imageUploadConfig.max_file_count || 20)) {
                showToast(`一次最多上传 ${imageUploadConfig.max_file_count || 20} 张图片`, 'error');
                return;
            }
            const form = new FormData();
            form.append('image_field', field);
            files.forEach(file => form.append('files', file));
            localImageUploading = true;
            document.querySelectorAll('.local-upload-btn').forEach(btn => btn.disabled = true);
            showToast(`正在上传 ${files.length} 张图片到七牛云...`, 'success');
            try {
                const res = await fetch(`/api/products/${currentProductId}/images/upload`, {
                    method: 'POST',
                    body: form,
                });
                const result = await res.json();
                if (!res.ok) throw new Error(result.detail || '上传失败');
                currentData[field] = result.value;
                currentData.update_time_2 = result.update_time_2;
                renderGallery(currentData);
                renderImageGrid(currentData);
                await loadProducts();
                showToast(result.message || '图片上传成功', 'success');
            } catch (e) {
                showToast('图片上传失败：' + e.message, 'error');
            } finally {
                localImageUploading = false;
                localImageTargetField = null;
                document.getElementById('localImageInput').value = '';
                document.querySelectorAll('.local-upload-btn').forEach(btn => {
                    btn.disabled = !imageUploadConfig.configured;
                });
            }
        }

        function pasteEditImages(event, field) {
            event.stopPropagation();
            const files = Array.from(event.clipboardData?.items || [])
                .filter(item => item.kind === 'file')
                .map(item => item.getAsFile())
                .filter(Boolean);
            const images = normalizeCreateImageFiles(files);
            if (!images.length) {
                showToast('剪贴板中没有图片', 'error');
                return;
            }
            event.preventDefault();
            uploadLocalImages(images, field);
        }

        // ========== 全屏图片查看（动态创建/销毁，不干扰拖放） ==========
        let fullImgDragData = null;   // {field, index}
        let fullImgDropTarget = null;  // {cellEl, position: 'before'|'after'|'append'}

        let _fullImgScrollTop = null; // 保存滚动位置
        function openFullImageView() {
            if (!currentData) return;
            const old = document.getElementById('fullImgOverlay');
            // 保存旧弹窗的滚动位置
            if (old) {
                const oldBody = old.querySelector('.fullimg-body');
                if (oldBody) _fullImgScrollTop = oldBody.scrollTop;
                old.remove();
            }
            const overlay = document.createElement('div');
            overlay.id = 'fullImgOverlay';
            overlay.className = 'fullimg-overlay open';
            overlay.onclick = function(e) { if (e.target === overlay) closeFullImageView(); };
            let html = '<div class="fullimg-modal" onclick="event.stopPropagation()">';
            html += '<div class="fullimg-header"><h3>全部图片</h3><button class="fullimg-close" onclick="closeFullImageView()">&#10005;</button></div>';
            html += '<div class="fullimg-body">';
            let hasImages = false;
            IMAGE_FIELDS.forEach(field => {
                const urls = parseImageUrls(currentData[field]);
                if (!urls.length) return; // 没有图片的列不显示
                hasImages = true;
                const label = fieldLabels[field] || field;
                html += `<div><div class="fullimg-group-title">${escapeHtml(label)}（${urls.length}张）<button class="fullimg-group-add" onclick="openFullImgLib('${field}')">+ 从图片库添加</button></div>`;
                html += `<div class="fullimg-grid" data-field="${field}" ondragover="fullImgGridDragOver(event)" ondragleave="fullImgGridDragLeave(event)" ondrop="fullImgGridDrop(event,'${field}')">`;
                urls.forEach((u, idx) => {
                    html += `<div class="fullimg-cell" data-field="${field}" data-index="${idx}" draggable="true"
                        ondragstart="fullImgCellDragStart(event,'${field}',${idx})"
                        ondragend="fullImgCellDragEnd(event)"
                        onclick="showModal('${escapeHtml(u)}')">
                        <img src="${escapeHtml(u)}" alt="${escapeHtml(label)}" onerror="this.parentElement.style.display='none'">
                        <button class="cell-add-btn" onclick="event.stopPropagation();openFullImgLibAt('${field}',${idx})" title="在此位置后插入图片">+</button>
                        <button class="cell-del-btn" onclick="event.stopPropagation();deleteFullImg('${field}',${idx})" title="删除此图片">&#10005;</button>
                    </div>`;
                });
                html += `</div></div>`;
            });
            if (!hasImages) html += '<div style="color:#999;text-align:center;padding:60px 0">暂无图片</div>';
            html += '</div></div>';
            overlay.innerHTML = html;
            document.body.appendChild(overlay);
            // 恢复滚动位置
            if (_fullImgScrollTop !== null) {
                const newBody = overlay.querySelector('.fullimg-body');
                if (newBody) newBody.scrollTop = _fullImgScrollTop;
                _fullImgScrollTop = null;
            }
        }
        function closeFullImageView() {
            const el = document.getElementById('fullImgOverlay');
            if (el) el.remove();
            fullImgDragData = null;
            fullImgDropTarget = null;
        }
        async function deleteFullImg(field, index) {
            if (!confirm('确定删除此图片？')) return;
            const urls = parseImageUrls(currentData[field]);
            if (index < 0 || index >= urls.length) return;
            urls.splice(index, 1);
            const newValue = urls.length ? JSON.stringify(urls) : null;
            try {
                const res = await fetch(`/api/products/${currentProductId}/images`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields: { [field]: newValue } })
                });
                if (!res.ok) throw new Error('fail');
                currentData[field] = newValue;
                openFullImageView();
                renderGallery(currentData);
                renderImageGrid(currentData);
                showToast('已删除', 'success');
            } catch (e) {
                showToast('删除失败', 'error');
            }
        }

        // 全屏拖放：开始拖动
        function fullImgCellDragStart(event, field, index) {
            fullImgDragData = { field, index };
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', `fullimg:${field}:${index}`);
            event.currentTarget.classList.add('dragging');
        }
        function fullImgCellDragEnd(event) {
            event.currentTarget.classList.remove('dragging');
            clearFullImgDropIndicators();
            fullImgDragData = null;
            fullImgDropTarget = null;
        }

        // 全屏拖放：网格区域 dragover（判断插入位置）
        function fullImgGridDragOver(event) {
            if (!fullImgDragData) return;
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = 'move';
            clearFullImgDropIndicators();

            const grid = event.currentTarget;
            const cells = [...grid.querySelectorAll('.fullimg-cell:not(.dragging)')];
            const rect = grid.getBoundingClientRect();

            // 找到鼠标下方的 cell
            let targetCell = null;
            for (const cell of cells) {
                const cr = cell.getBoundingClientRect();
                if (event.clientX >= cr.left && event.clientX <= cr.right && event.clientY >= cr.top && event.clientY <= cr.bottom) {
                    targetCell = cell;
                    break;
                }
            }

            if (targetCell) {
                const cr = targetCell.getBoundingClientRect();
                const midX = cr.left + cr.width / 2;
                if (event.clientX < midX) {
                    targetCell.classList.add('drop-before');
                    fullImgDropTarget = { cell: targetCell, position: 'before' };
                } else {
                    targetCell.classList.add('drop-after');
                    fullImgDropTarget = { cell: targetCell, position: 'after' };
                }
            } else if (cells.length === 0) {
                // 空网格，标记为 append
                grid.classList.add('drop-append-target');
                fullImgDropTarget = { cell: null, position: 'append', grid: grid };
            } else {
                // 鼠标在网格内但不在任何 cell 上 → append 到末尾
                const lastCell = cells[cells.length - 1];
                lastCell.classList.add('drop-after');
                fullImgDropTarget = { cell: lastCell, position: 'after' };
            }
        }

        function fullImgGridDragLeave(event) {
            // 只在真正离开网格时清除
            if (!event.currentTarget.contains(event.relatedTarget)) {
                clearFullImgDropIndicators();
                fullImgDropTarget = null;
            }
        }

        function clearFullImgDropIndicators() {
            document.querySelectorAll('.fullimg-cell.drop-before,.fullimg-cell.drop-after,.fullimg-cell.drop-append').forEach(el => {
                el.classList.remove('drop-before', 'drop-after', 'drop-append');
            });
            document.querySelectorAll('.drop-append-target').forEach(el => el.classList.remove('drop-append-target'));
        }

        // 全屏拖放：drop
        async function fullImgGridDrop(event, targetField) {
            event.preventDefault();
            event.stopPropagation();
            clearFullImgDropIndicators();

            const source = fullImgDragData;
            fullImgDragData = null;
            if (!source || !currentProductId || !currentData) return;

            // 计算插入位置
            let insertIndex = -1;
            if (fullImgDropTarget && fullImgDropTarget.cell) {
                const targetIdx = parseInt(fullImgDropTarget.cell.dataset.index);
                const targetField2 = fullImgDropTarget.cell.dataset.field;
                if (fullImgDropTarget.position === 'before') {
                    insertIndex = targetIdx;
                } else {
                    insertIndex = targetIdx + 1;
                }
                // 如果是同字段拖动，且从后面拖到前面，需要调整索引
                if (source.field === targetField2 && source.index < insertIndex) {
                    insertIndex--;
                }
            } else {
                // append 到末尾
                insertIndex = parseImageUrls(currentData[targetField]).length;
            }

            fullImgDropTarget = null;

            const sourceUrls = parseImageUrls(currentData[source.field]);
            if (source.index < 0 || source.index >= sourceUrls.length) return;
            const [movedUrl] = sourceUrls.splice(source.index, 1);

            // 同列移动：直接在已删除的数组上插入（避免重复）
            // 跨列移动：在目标列的原始数组上插入
            const targetUrls = (source.field === targetField) ? sourceUrls : parseImageUrls(currentData[targetField]);
            targetUrls.splice(insertIndex, 0, movedUrl);

            const fields = {};
            if (source.field === targetField) {
                // 同列：只需保存一个字段
                fields[targetField] = targetUrls.length ? JSON.stringify(targetUrls) : null;
            } else {
                // 跨列：分别保存源和目标
                fields[source.field] = sourceUrls.length ? JSON.stringify(sourceUrls) : null;
                fields[targetField] = JSON.stringify(targetUrls);
            }

            try {
                const res = await fetch(`/api/products/${currentProductId}/images`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields })
                });
                if (!res.ok) throw new Error('fail');
                currentData = { ...currentData, ...fields };
                // 刷新全屏视图
                openFullImageView();
                // 也刷新标签页的图片网格
                renderImageGrid(currentData);
            } catch (e) {
                showToast('移动失败', 'error');
            }
        }

        // 全屏：从图片库添加（追加到末尾，不关闭全屏弹窗）
        function openFullImgLib(field) {
            openImgLib(field);
        }
        // 全屏：从图片库添加到指定位置之后（不关闭全屏弹窗）
        function openFullImgLibAt(field, index) {
            fullImgLibInsertField = field;
            fullImgLibInsertIndex = index;
            openImgLib(field);
        }
        let fullImgLibInsertField = null;
        let fullImgLibInsertIndex = -1;

        // 图片类型之间拖放：拖动单张图片到另一类型，会从来源字段移除并追加到目标字段。
        let draggedImage = null;
        let imageDropInProgress = false;

        function startImageDrag(event, field, index) {
            if (imageDropInProgress) {
                event.preventDefault();
                return;
            }
            event.stopPropagation();
            draggedImage = { field, index };
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', `${field}:${index}`);
            event.currentTarget.classList.add('image-dragging');
        }

        function endImageDrag(event) {
            event.stopPropagation();
            event.currentTarget.classList.remove('image-dragging');
            document.querySelectorAll('.image-drop-target').forEach(el => el.classList.remove('image-drop-target'));
            draggedImage = null;
        }

        function allowImageDrop(event) {
            const hasExternalFiles = Array.from(event.dataTransfer?.types || []).includes('Files');
            if ((!draggedImage && !hasExternalFiles) || imageDropInProgress) return;
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = hasExternalFiles && !draggedImage ? 'copy' : 'move';
            if (!event.currentTarget.classList.contains('image-drop-target')) {
                event.currentTarget.classList.add('image-drop-target');
            }
            event.currentTarget.classList.toggle('image-file-drop-target', hasExternalFiles && !draggedImage);
        }

        function leaveImageDrop(event) {
            event.stopPropagation();
            if (event.currentTarget.contains(event.relatedTarget)) return;
            event.currentTarget.classList.remove('image-drop-target');
            event.currentTarget.classList.remove('image-file-drop-target');
        }

        async function dropImage(event, targetField) {
            event.preventDefault();
            event.stopPropagation();
            event.currentTarget.classList.remove('image-drop-target');
            event.currentTarget.classList.remove('image-file-drop-target');
            if (imageDropInProgress) return;

            // 从微信、飞书或本地拖入的是文件，直接上传到当前图片类型。
            // 页面内部已有图片的拖动仍继续走下面的换列逻辑。
            const hasExternalFiles = !draggedImage
                && Array.from(event.dataTransfer?.types || []).includes('Files');
            const externalFiles = hasExternalFiles
                ? normalizeCreateImageFiles(event.dataTransfer?.files || [])
                : [];
            if (hasExternalFiles) {
                if (!externalFiles.length) {
                    showToast('拖入的内容中没有可用图片', 'error');
                    return;
                }
                await uploadLocalImages(externalFiles, targetField);
                return;
            }

            let source = draggedImage;
            if (!source) {
                const raw = event.dataTransfer.getData('text/plain');
                const match = /^([^:]+):(\d+)$/.exec(raw || '');
                if (match) source = { field: match[1], index: Number(match[2]) };
            }
            draggedImage = null;
            if (!source || source.field === targetField || !currentProductId || !currentData) return;

            const oldSourceValue = currentData[source.field];
            const oldTargetValue = currentData[targetField];
            const sourceUrls = parseImageUrls(currentData[source.field]);
            if (source.index < 0 || source.index >= sourceUrls.length) return;
            const [movedUrl] = sourceUrls.splice(source.index, 1);
            const targetUrls = parseImageUrls(currentData[targetField]);
            targetUrls.push(movedUrl);
            const fields = {
                [source.field]: sourceUrls.length ? JSON.stringify(sourceUrls) : null,
                [targetField]: JSON.stringify(targetUrls),
            };

            imageDropInProgress = true;
            Object.entries(fields).forEach(([field, value]) => { currentData[field] = value; });
            // 等当前原生拖放生命周期（尤其是 dragend）结束后再替换 DOM，
            // 避免拖动中的节点被立即销毁导致浏览器进入卡死状态。
            await new Promise(resolve => setTimeout(resolve, 0));
            renderGallery(currentData);
            renderImageGrid(currentData);
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 12000);
            try {
                const res = await fetch(`/api/products/${currentProductId}/images`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ fields }),
                    signal: controller.signal,
                });
                if (!res.ok) {
                    const error = await res.json();
                    throw new Error(error.detail || '图片移动失败');
                }
                const result = await res.json();
                currentData.update_time_2 = result.update_time_2;
                showToast('图片类型已更新', 'success');
            } catch (e) {
                currentData[source.field] = oldSourceValue;
                currentData[targetField] = oldTargetValue;
                renderGallery(currentData);
                renderImageGrid(currentData);
                const message = e.name === 'AbortError' ? '保存超时，请检查后端服务' : e.message;
                showToast('图片移动失败: ' + message, 'error');
            } finally {
                clearTimeout(timeoutId);
                imageDropInProgress = false;
            }
        }

        // 删除图片
        async function deleteImage(field, index) {
            if (!currentProductId || !currentData) return;
            const urls = parseImageUrls(currentData[field]);
            if (index < 0 || index >= urls.length) return;
            if (!confirm(`确定删除第 ${index + 1} 张图片？`)) return;

            urls.splice(index, 1);
            const newValue = urls.length > 0 ? JSON.stringify(urls) : null;

            try {
                const res = await fetch(`/api/products/${currentProductId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ field, value: newValue }),
                });
                if (!res.ok) throw new Error('删除失败');
                const result = await res.json();
                currentData[field] = newValue;
                currentData.update_time_2 = result.update_time_2;
                renderGallery(currentData);
                renderImageGrid(currentData);
                await loadProducts();
                showToast('图片已删除', 'success');
            } catch (e) {
                showToast('删除失败: ' + e.message, 'error');
            }
        }

        // 新增图片
        async function addImage(field) {
            if (!currentProductId || !currentData) return;
            const inputEl = document.getElementById(`add-img-${field}`);
            if (!inputEl) return;
            const url = inputEl.value.trim();
            if (!url) { showToast('请输入图片URL', 'error'); return; }

            const urls = parseImageUrls(currentData[field]);
            urls.push(url);
            const newValue = JSON.stringify(urls);

            try {
                const res = await fetch(`/api/products/${currentProductId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ field, value: newValue }),
                });
                if (!res.ok) throw new Error('添加失败');
                const result = await res.json();
                currentData[field] = newValue;
                currentData.update_time_2 = result.update_time_2;
                inputEl.value = '';
                renderGallery(currentData);
                renderImageGrid(currentData);
                await loadProducts();
                showToast('图片已添加', 'success');
            } catch (e) {
                showToast('添加失败: ' + e.message, 'error');
            }
        }

        // ========== 全部字段表格 ==========
        function renderAllFieldsTable(data) {
            const tableEl = document.getElementById('allFieldsTable');
            const allFields = Object.keys(fieldLabels).filter(f => f !== 'id');
            let html = '';
            for (let i = 0; i < allFields.length; i += 2) {
                html += '<tr>';
                const f1 = allFields[i];
                html += `<td>${fieldLabels[f1]}</td>`;
                html += `<td>${f1 === 'update_time_2' ? renderVal(data[f1]) : `<span class="field-value" id="fv-${f1}" onclick="editField('${f1}')">${renderVal(data[f1])}</span>`}</td>`;
                if (allFields[i + 1]) {
                    const f2 = allFields[i + 1];
                    html += `<td>${fieldLabels[f2]}</td>`;
                    html += `<td>${f2 === 'update_time_2' ? renderVal(data[f2]) : `<span class="field-value" id="fv-${f2}" onclick="editField('${f2}')">${renderVal(data[f2])}</span>`}</td>`;
                } else {
                    html += '<td></td><td></td>';
                }
                html += '</tr>';
            }
            tableEl.innerHTML = html;
        }

        // ========== 标签页切换 ==========
        function switchTab(tabEl, paneId) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            tabEl.classList.add('active');
            document.getElementById(paneId).classList.add('active');
        }

        // ========== 工具函数 ==========
        function parseImageUrls(value) {
            if (!value) return [];
            let urls = [];
            try {
                const parsed = JSON.parse(value);
                urls = Array.isArray(parsed) ? parsed : [String(value)];
            } catch { urls = [String(value)]; }
            return urls.filter(u => u && u.trim());
        }

        function isImageField(field) { return IMAGE_FIELDS.includes(field); }

        function showModal(url) {
            document.getElementById('modalImage').src = url;
            document.getElementById('imageModal').classList.add('show');

            // 添加 ESC 键监听
            document.addEventListener('keydown', handleEscapeKey);
        }

        function closeModal() {
            document.getElementById('imageModal').classList.remove('show');
            // 移除 ESC 键监听
            document.removeEventListener('keydown', handleEscapeKey);
        }

        // 处理 ESC 键关闭弹窗
        function handleEscapeKey(event) {
            if (event.key === 'Escape') {
                closeModal();
            }
        }

        // ========== 行内编辑 ==========
        function editField(field) {
            // 防止默认的焦点样式
            document.addEventListener('focusin', function(e) {
                if (e.target.matches('.field-edit input, .field-edit textarea')) {
                    e.target.style.outline = 'none';
                    e.target.style.boxShadow = 'none';
                }
            }, true);
            const fvEl = document.getElementById(`fv-${field}`);
            if (!fvEl || fvEl.querySelector('.field-edit')) return;
            const currentValue = currentData[field] || '';
            const isLongText = isImageField(field) || String(currentValue).length > 80;
            const originalHtml = fvEl.innerHTML;

            if (field === 'product_type') {
                fvEl.innerHTML = `<div class="field-edit" id="edit-wrapper-${field}">
                    <div class="edit-product-type-combobox">
                        <input id="edit-product_type-search" type="text" value="${escapeHtml(String(currentValue))}"
                            placeholder="输入关键词搜索三级分类" autocomplete="off"
                            onclick="event.stopPropagation()"
                            onfocus="filterEditProductTypes(this.value, true)"
                            oninput="filterEditProductTypes(this.value, true)"
                            onkeydown="if(event.key==='Escape'){event.stopPropagation();cancelEdit('product_type')}"
                            onblur="setTimeout(closeEditProductTypeDropdown, 180)">
                        <input id="edit-input-${field}" type="hidden" value="${escapeHtml(String(currentValue))}">
                        <div class="edit-product-type-dropdown" id="editProductTypeDropdown"></div>
                    </div>
                    <div class="edit-actions">
                        <button class="btn-confirm" onclick="event.stopPropagation();saveField('${field}')" title="确认">&#10003;</button>
                        <button class="btn-cancel" onclick="event.stopPropagation();cancelEdit('${field}')" title="取消">&#10005;</button>
                    </div></div>`;
            } else if (field === 'technical_params') {
                fvEl.innerHTML = `<div class="field-edit" id="edit-wrapper-${field}">
                    <div class="technical-param-editor">
                        <textarea id="edit-input-${field}" placeholder="每行填写一项技术参数" onclick="event.stopPropagation()" onkeydown="if(event.key==='Escape'){event.stopPropagation();cancelEdit('${field}')}">${escapeHtml(String(currentValue))}</textarea>
                        <div class="technical-param-edit-tip">每行填写一项参数，按 Enter 换行；填写完成后点击右侧对号保存。</div>
                    </div>
                    <div class="edit-actions">
                        <button class="btn-confirm" onclick="event.stopPropagation();saveField('${field}')" title="保存技术参数">&#10003;</button>
                        <button class="btn-cancel" onclick="event.stopPropagation();cancelEdit('${field}')" title="取消">&#10005;</button>
                    </div></div>`;
            } else if (isLongText) {
                fvEl.innerHTML = `<div class="field-edit" id="edit-wrapper-${field}">
                    <textarea id="edit-input-${field}">${escapeHtml(String(currentValue))}</textarea>
                    <div class="edit-actions">
                        <button class="btn-confirm" onclick="event.stopPropagation();saveField('${field}')" title="确认">&#10003;</button>
                        <button class="btn-cancel" onclick="event.stopPropagation();cancelEdit('${field}')" title="取消">&#10005;</button>
                    </div></div>`;
            } else {
                fvEl.innerHTML = `<div class="field-edit" id="edit-wrapper-${field}">
                    <input type="text" id="edit-input-${field}" value="${escapeHtml(String(currentValue))}"
                           onkeydown="if(event.key==='Enter'){event.stopPropagation();saveField('${field}')}if(event.key==='Escape'){event.stopPropagation();cancelEdit('${field}')}"
                           onclick="event.stopPropagation()">
                    <div class="edit-actions">
                        <button class="btn-confirm" onclick="event.stopPropagation();saveField('${field}')" title="确认">&#10003;</button>
                        <button class="btn-cancel" onclick="event.stopPropagation();cancelEdit('${field}')" title="取消">&#10005;</button>
                    </div></div>`;
            }
            fvEl.dataset.originalHtml = originalHtml;
            const inputEl = document.getElementById(`edit-input-${field}`);
            const focusEl = field === 'product_type'
                ? document.getElementById('edit-product_type-search')
                : inputEl;
            if (focusEl) {
                focusEl.focus();
                // 根据内容长度动态设置输入框宽度（em单位适配中英文）
                const len = String(currentValue).length;
                const widthEm = Math.max(3, Math.min(len + 2, 25));
                if (field !== 'product_type') focusEl.style.width = widthEm + 'em';
            }
        }

        function filterEditProductTypes(keyword, showDropdown = true) {
            const query = (keyword || '').trim().toLowerCase();
            const hidden = document.getElementById('edit-input-product_type');
            const exact = productTypeValues.find(value => value.toLowerCase() === query);
            if (hidden) hidden.value = exact || '';
            const matches = productTypeValues
                .filter(value => !query || value.toLowerCase().includes(query))
                .slice(0, 80);
            const dropdown = document.getElementById('editProductTypeDropdown');
            if (!dropdown) return;
            dropdown.innerHTML = matches.length
                ? matches.map(value => {
                    const encoded = encodeURIComponent(value).replace(/'/g, '%27');
                    return `<div class="edit-product-type-option" onmousedown="event.preventDefault()" onclick="selectEditProductType('${encoded}')">${escapeHtml(value)}</div>`;
                }).join('')
                : '<div class="edit-product-type-empty">没有匹配的三级分类</div>';
            dropdown.classList.toggle('show', showDropdown);
        }

        function selectEditProductType(encodedValue) {
            const value = decodeURIComponent(encodedValue);
            document.getElementById('edit-product_type-search').value = value;
            document.getElementById('edit-input-product_type').value = value;
            closeEditProductTypeDropdown();
        }

        function closeEditProductTypeDropdown() {
            document.getElementById('editProductTypeDropdown')?.classList.remove('show');
        }

        async function saveField(field) {
            const inputEl = document.getElementById(`edit-input-${field}`);
            if (!inputEl) return;
            if (field === 'product_type') {
                const searchValue = document.getElementById('edit-product_type-search')?.value.trim() || '';
                if (searchValue && !inputEl.value) {
                    showToast('请从搜索结果中选择三级分类', 'error');
                    document.getElementById('edit-product_type-search')?.focus();
                    return;
                }
            }
            const newValue = field === 'technical_params'
                ? inputEl.value.replace(/\r\n?/g, '\n').split('\n').map(line => line.trim()).filter(Boolean).join('\n')
                : inputEl.value;
            try {
                const res = await fetch(`/api/products/${currentProductId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ field, value: newValue || null }),
                });
                if (!res.ok) { const err = await res.json(); throw new Error(err.detail || '更新失败'); }
                const result = await res.json();
                currentData[field] = newValue || null;
                currentData.update_time_2 = result.update_time_2;
                // 重新渲染整个详情以保持一致性
                renderDetail(currentData);
                await loadProducts();
                if (field === 'product_type') {
                    await refreshProductClassifications();
                }
                showToast('修改成功', 'success');
            } catch (e) { showToast('修改失败: ' + e.message, 'error'); }
        }

        function cancelEdit(field) {
            const fvEl = document.getElementById(`fv-${field}`);
            if (fvEl && fvEl.dataset.originalHtml !== undefined) {
                fvEl.innerHTML = fvEl.dataset.originalHtml;
                delete fvEl.dataset.originalHtml;
            }
        }

        let toastHideTimer = null;
        function showToast(msg, type) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.className = `toast ${type} show`;
            toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
            toast.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
            if (toastHideTimer) clearTimeout(toastHideTimer);
            toastHideTimer = setTimeout(() => toast.classList.remove('show'), type === 'error' ? 3600 : 2400);
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        // ========== 图片库选择功能 ==========
        let imgLibTargetField = null;   // 当前目标图片字段
        let imgLibSelectedUrls = [];    // 已选中的图片 URL 列表
        let imgLibCategories = [];      // 分类列表
        let imgLibCurrentCategory = null;
        let imgLibCurrentPage = 1;
        let imgLibPageTotal = 0;
        let imgLibSearchTimer = null;

        async function openImgLib(field) {
            if (!currentProductId) { showToast('请先选择一个产品', 'error'); return; }
            imgLibCreateMode = false;
            imgLibTargetField = field;
            imgLibSelectedUrls = [];
            imgLibCurrentCategory = null;
            imgLibCurrentPage = 1;

            const label = fieldLabels[field] || field;
            document.getElementById('imglibTitle').textContent = `图片库 - 选择到「${label}」`;
            document.getElementById('imglibSearch').value = '';
            updateImgLibSelCount();

            // 显示弹窗
            document.getElementById('imglibOverlay').classList.add('show');

            // 加载分类
            await loadImgLibCategories();
            // 加载全部产品
            await loadImgLibProducts();
        }

        async function openCreateImgLib(field) {
            imgLibCreateMode = true;
            imgLibTargetField = field;
            imgLibSelectedUrls = [];
            imgLibCurrentCategory = null;
            imgLibCurrentPage = 1;
            const label = fieldLabels[field] || field;
            document.getElementById('imglibTitle').textContent = `新增产品 - 选择到「${label}」`;
            document.getElementById('imglibSearch').value = '';
            updateImgLibSelCount();
            document.getElementById('imglibOverlay').classList.add('show');
            await loadImgLibCategories();
            await loadImgLibProducts();
        }

        function closeImgLib() {
            document.getElementById('imglibOverlay').classList.remove('show');
            imgLibTargetField = null;
            imgLibSelectedUrls = [];
            imgLibCreateMode = false;
            fullImgLibInsertField = null;
            fullImgLibInsertIndex = -1;
        }

        async function loadImgLibCategories() {
            try {
                const res = await fetch('/api/image-library/categories');
                imgLibCategories = await res.json();
                renderImgLibSidebar();
            } catch (e) {
                console.error('加载分类失败', e);
            }
        }

        function renderImgLibSidebar() {
            const sidebar = document.getElementById('imglibSidebar');
            const totalCount = imgLibCategories.reduce((s, c) => s + c.count, 0);
            let html = `<div class="cat-item ${!imgLibCurrentCategory ? 'active' : ''}" onclick="selectImgLibCategory(null)">
                <span>全部</span><span class="cat-cnt">${totalCount}</span>
            </div>`;
            imgLibCategories.forEach(cat => {
                const isActive = imgLibCurrentCategory === cat.name;
                html += `<div class="cat-item ${isActive ? 'active' : ''}" onclick="selectImgLibCategory('${escapeHtml(cat.name)}')">
                    <span>${escapeHtml(cat.name)}</span><span class="cat-cnt">${cat.count}</span>
                </div>`;
            });
            sidebar.innerHTML = html;
        }

        async function selectImgLibCategory(catName) {
            imgLibCurrentCategory = catName;
            imgLibCurrentPage = 1;
            renderImgLibSidebar();
            await loadImgLibProducts();
        }

        async function loadImgLibProducts() {
            const grid = document.getElementById('imglibGrid');
            grid.innerHTML = '<div style="text-align:center;padding:40px;color:#aaa">加载中...</div>';

            try {
                let url = `/api/image-library/products?page=${imgLibCurrentPage}&page_size=20`;
                if (imgLibCurrentCategory) url += `&category=${encodeURIComponent(imgLibCurrentCategory)}`;
                const keyword = document.getElementById('imglibSearch').value.trim();
                if (keyword) url += `&keyword=${encodeURIComponent(keyword)}`;

                const res = await fetch(url);
                const data = await res.json();
                imgLibPageTotal = Math.ceil(data.total / data.page_size);
                renderImgLibGrid(data.items);
                renderImgLibPagination(data.page, data.total);
            } catch (e) {
                grid.innerHTML = '<div style="text-align:center;padding:40px;color:#ea4335">加载失败</div>';
                console.error(e);
            }
        }

        function renderImgLibGrid(items) {
            const grid = document.getElementById('imglibGrid');
            if (!items || items.length === 0) {
                grid.innerHTML = '<div style="text-align:center;padding:40px;color:#aaa">暂无数据</div>';
                return;
            }

            // 过滤掉id字段和图片相关字段
            const displayFields = Object.keys(imgLibFieldLabels).filter(field =>
                field !== 'id' && !field.startsWith('product_image_') && !['key_part_images', 'actual_photos', 'product_detail_images'].includes(field)
            );

            let html = '';
            items.forEach(product => {
                html += `<div class="imglib-product">
                    <div class="prod-header">
                        <span class="prod-name">${escapeHtml(product.product_name || '未命名产品')}</span>
                        ${product.product_brand ? `<span class="prod-brand">${escapeHtml(product.product_brand)}</span>` : ''}
                        ${product.model ? `<span class="prod-model">${escapeHtml(product.model)}</span>` : ''}
                    </div>`;

                // 显示所有有数据的字段
                let hasVisibleFields = false;
                let fieldsHtml = '';
                displayFields.forEach(field => {
                    const value = product[field];
                    if (value && value !== '' && value !== null && value !== undefined) {
                        const label = imgLibFieldLabels[field] || field;
                        // 格式化显示值
                        let displayValue = value;
                        if (typeof value === 'string' && value.length > 30) {
                            displayValue = value.substring(0, 30) + '...';
                        }
                        fieldsHtml += `<div class="field-row">
                            <span class="field-label">${label}:</span>
                            <span class="field-value">${escapeHtml(displayValue)}</span>
                        </div>`;
                        hasVisibleFields = true;
                    }
                });

                // 如果有其他字段，显示在一个字段区域
                if (hasVisibleFields) {
                    html += `<div class="fields-container">
                        ${fieldsHtml}
                    </div>`;
                }

                // 图片网格
                html += `<div class="imglib-img-grid">`;
                (product.images || []).forEach((imgUrl, idx) => {
                    const isSelected = imgLibSelectedUrls.includes(imgUrl);
                    html += `<div class="imglib-img-cell ${isSelected ? 'selected' : ''}" data-url="${escapeHtml(imgUrl)}" onclick="toggleImgLibSelect(this, '${escapeHtml(imgUrl).replace(/'/g, "\\'")}')">
                        <div class="check-mark">&#10003;</div>
                        <img src="${escapeHtml(imgUrl)}" alt="图片${idx+1}" onerror="this.parentElement.style.display='none'">
                        <div class="imglib-preview-btn" onclick="event.stopPropagation(); showImglibModal('${escapeHtml(imgUrl)}')" title="点击查看大图">🔍</div>
                    </div>`;
                });
                html += `</div></div>`;
            });
            grid.innerHTML = html;
        }

        function toggleImgLibSelect(cell, url) {
            const idx = imgLibSelectedUrls.indexOf(url);
            if (idx >= 0) {
                imgLibSelectedUrls.splice(idx, 1);
                cell.classList.remove('selected');
            } else {
                imgLibSelectedUrls.push(url);
                cell.classList.add('selected');
            }
            updateImgLibSelCount();
        }

        function updateImgLibSelCount() {
            document.getElementById('imglibSelCount').textContent = `已选 ${imgLibSelectedUrls.length} 张`;
        }

        function renderImgLibPagination(currentPage, total) {
            const el = document.getElementById('imglibPagination');
            if (imgLibPageTotal <= 1) { el.innerHTML = ''; return; }

            let html = `<button ${currentPage <= 1 ? 'disabled' : ''} onclick="imgLibGoPage(${currentPage - 1})">&#8249;</button>`;

            const pages = [];
            if (imgLibPageTotal <= 7) {
                for (let i = 1; i <= imgLibPageTotal; i++) pages.push(i);
            } else {
                pages.push(1);
                if (currentPage > 3) pages.push('...');
                for (let i = Math.max(2, currentPage - 1); i <= Math.min(imgLibPageTotal - 1, currentPage + 1); i++) {
                    pages.push(i);
                }
                if (currentPage < imgLibPageTotal - 2) pages.push('...');
                pages.push(imgLibPageTotal);
            }

            pages.forEach(p => {
                if (p === '...') {
                    html += `<span style="padding:0 4px;color:#aaa">...</span>`;
                } else {
                    html += `<button class="${p === currentPage ? 'active' : ''}" onclick="imgLibGoPage(${p})">${p}</button>`;
                }
            });

            html += `<button ${currentPage >= imgLibPageTotal ? 'disabled' : ''} onclick="imgLibGoPage(${currentPage + 1})">&#8250;</button>`;
            html += `<span style="margin-left:8px;font-size:11px;color:#888">共 ${total} 条</span>`;
            el.innerHTML = html;
        }

        async function imgLibGoPage(page) {
            imgLibCurrentPage = page;
            await loadImgLibProducts();
            document.getElementById('imglibGrid').scrollTop = 0;
        }

        function imglibSearchDebounce() {
            clearTimeout(imgLibSearchTimer);
            imgLibSearchTimer = setTimeout(async () => {
                imgLibCurrentPage = 1;
                await loadImgLibProducts();
            }, 400);
        }

        async function confirmImgLibSelection() {
            if (!imgLibTargetField || imgLibSelectedUrls.length === 0) {
                showToast('请至少选择一张图片', 'error');
                return;
            }

            const field = imgLibTargetField;
            if (imgLibCreateMode) {
                const existing = pendingCreateLibraryUrls[field] || [];
                imgLibSelectedUrls.forEach(url => {
                    if (!existing.includes(url)) existing.push(url);
                });
                pendingCreateLibraryUrls[field] = existing;
                const addedCount = imgLibSelectedUrls.length;
                closeImgLib();
                renderCreateImageSection();
                showToast(`已为新增产品选择 ${addedCount} 张「${fieldLabels[field] || field}」`, 'success');
                return;
            }
            const existingUrls = parseImageUrls(currentData ? currentData[field] : null);

            // 判断是否从全屏弹窗指定位置插入
            const isFullImgInsert = fullImgLibInsertField === field && fullImgLibInsertIndex >= 0;
            let newUrls;
            if (isFullImgInsert) {
                // 在指定位置之后插入
                const insertPos = fullImgLibInsertIndex + 1;
                newUrls = [...existingUrls];
                let actualPos = insertPos;
                imgLibSelectedUrls.forEach(url => {
                    if (!newUrls.includes(url)) {
                        newUrls.splice(actualPos, 0, url);
                        actualPos++;
                    }
                });
            } else {
                // 追加到末尾
                newUrls = [...existingUrls];
                imgLibSelectedUrls.forEach(url => {
                    if (!newUrls.includes(url)) newUrls.push(url);
                });
            }

            const newValue = newUrls.length > 0 ? JSON.stringify(newUrls) : null;

            try {
                const res = await fetch(`/api/products/${currentProductId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ field, value: newValue }),
                });
                if (!res.ok) throw new Error('保存失败');
                currentData[field] = newValue;
                renderGallery(currentData);
                renderImageGrid(currentData);
                const addedCount = imgLibSelectedUrls.length;
                closeImgLib();
                // 如果全屏弹窗还开着，刷新它
                if (document.getElementById('fullImgOverlay')) {
                    setTimeout(() => openFullImageView(), 300);
                }
                showToast(`已添加 ${addedCount} 张图片到「${fieldLabels[field] || field}」`, 'success');
            } catch (e) {
                showToast(e.message, 'error');
            }
        }

        // 显示图片放大弹窗
        function showImglibModal(url) {
            const image = document.getElementById('imglibModalImage');
            imglibModalRotation = 0;
            image.style.transform = 'rotate(0deg)';
            image.onload = fitImglibModalImage;
            image.src = url;
            document.getElementById('imglibModalOverlay').classList.add('show');
            if (image.complete && image.naturalWidth) {
                fitImglibModalImage();
            }
            // 添加 ESC 键监听
            document.addEventListener('keydown', handleImglibEscapeKey);
        }

        // 旋转后根据图片实际宽高重新缩放，避免横图转成竖图时超出屏幕。
        function fitImglibModalImage() {
            const image = document.getElementById('imglibModalImage');
            const content = document.querySelector('.imglib-modal-content');
            if (!image || !content || !image.naturalWidth || !image.naturalHeight) return;

            const quarterTurn = Math.abs(imglibModalRotation / 90) % 2 === 1;
            const rotatedWidth = quarterTurn ? image.naturalHeight : image.naturalWidth;
            const rotatedHeight = quarterTurn ? image.naturalWidth : image.naturalHeight;
            const scale = Math.min(
                content.clientWidth / rotatedWidth,
                content.clientHeight / rotatedHeight,
                1
            );

            image.style.width = `${Math.max(1, image.naturalWidth * scale)}px`;
            image.style.height = `${Math.max(1, image.naturalHeight * scale)}px`;
            image.style.maxWidth = 'none';
            image.style.maxHeight = 'none';
            image.style.transform = `rotate(${imglibModalRotation}deg)`;
        }

        function rotateImglibModal() {
            imglibModalRotation = (imglibModalRotation + 90) % 360;
            fitImglibModalImage();
        }

        // 关闭图片放大弹窗
        function closeImglibModal() {
            const image = document.getElementById('imglibModalImage');
            document.getElementById('imglibModalOverlay').classList.remove('show');
            imglibModalRotation = 0;
            image.onload = null;
            image.removeAttribute('style');
            image.src = '';
            // 移除 ESC 键监听
            document.removeEventListener('keydown', handleImglibEscapeKey);
        }

        // 处理 ESC 键关闭图片弹窗
        function handleImglibEscapeKey(event) {
            if (event.key === 'Escape') {
                closeImglibModal();
            }
        }

        window.addEventListener('resize', () => {
            if (document.getElementById('imglibModalOverlay')?.classList.contains('show')) {
                fitImglibModalImage();
            }
        });

        init();
