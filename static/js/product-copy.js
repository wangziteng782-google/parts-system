/**
 * 一键复制产品功能
 * 复用新增产品弹窗，预填充当前产品数据
 */

// 复制产品入口
function copyProduct() {
    if (!currentData) return;

    // 打开新增产品弹窗
    openProductCreate();

    // 填充表单字段
    fillCreateForm(currentData);

    // 复制图片
    copyProductImages(currentData);
}

// 填充表单
function fillCreateForm(data) {
    PRODUCT_CREATE_SECTIONS.forEach(section => {
        section.fields.forEach(([field]) => {
            const value = data[field];
            if (value == null) return;

            const el = document.getElementById(`create-${field}`);
            if (!el) return;

            if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                el.value = value;
            }

            // product_type 是隐藏字段，只需同步搜索框显示
            if (field === 'product_type') {
                const searchInput = document.getElementById(`create-${field}-search`);
                if (searchInput) searchInput.value = value;
            }
        });
    });
}

// 复制图片
function copyProductImages(data) {
    CREATE_PRODUCT_IMAGE_FIELDS.forEach(field => {
        const urls = parseImageUrls(data[field]);
        if (urls.length) pendingCreateLibraryUrls[field] = urls;
    });
    renderCreateImageSection();
}
