(() => {
    const state = {
        page: 1,
        pageSize: 20,
        pages: 1,
        operation: "",
        loading: false,
    };

    const el = {
        form: document.getElementById("filterForm"),
        keyword: document.getElementById("keywordInput"),
        user: document.getElementById("userFilter"),
        module: document.getElementById("moduleFilter"),
        startDate: document.getElementById("startDate"),
        endDate: document.getElementById("endDate"),
        body: document.getElementById("logTableBody"),
        tableState: document.getElementById("tableState"),
        total: document.getElementById("totalCount"),
        pageSize: document.getElementById("pageSize"),
        pageInfo: document.getElementById("pageInfo"),
        prev: document.getElementById("prevPage"),
        next: document.getElementById("nextPage"),
        drawer: document.getElementById("detailDrawer"),
        drawerMask: document.getElementById("drawerMask"),
        drawerContent: document.getElementById("drawerContent"),
        drawerTitle: document.getElementById("drawerTitle"),
        toast: document.getElementById("toast"),
    };

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function formatTime(value) {
        if (!value) return "-";
        const date = new Date(String(value).replace(" ", "T"));
        if (Number.isNaN(date.getTime())) return escapeHtml(value);
        const pad = number => String(number).padStart(2, "0");
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}<br>${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    }

    function avatarHtml(item) {
        if (item.avatar) {
            return `<span class="avatar"><img src="${escapeHtml(item.avatar)}" alt=""></span>`;
        }
        return `<span class="avatar">${escapeHtml((item.operator_name || "员").slice(0, 1))}</span>`;
    }

    function imageHtml(item, className = "") {
        if (item.image_url) {
            return `<div class="product-thumb ${className}"><img src="${escapeHtml(item.image_url)}" alt="" onerror="this.parentElement.innerHTML='▧'"></div>`;
        }
        return `<div class="product-thumb ${className}">▧</div>`;
    }

    function operationClass(type) {
        return ({CREATE: "create", UPDATE: "update", DELETE: "delete"})[type] || "update";
    }

    function operationBadges(item) {
        const types = item.operation_types?.length ? item.operation_types : [item.operation_type];
        const labels = item.operation_labels?.length ? item.operation_labels : [item.operation_label];
        return types.map((type, index) => `
            <span class="operation-badge ${operationClass(type)}">${escapeHtml(labels[index] || type)}</span>
        `).join("");
    }

    function moduleBadges(item) {
        const labels = item.module_labels?.length ? item.module_labels : [item.module_label];
        return labels.filter(Boolean).map(label => `
            <span class="module-badge">${escapeHtml(label)}</span>
        `).join("");
    }

    function setTableState(message, icon = "⌛") {
        el.tableState.innerHTML = `<div class="state-icon">${icon}</div><div>${escapeHtml(message)}</div>`;
        el.tableState.classList.remove("hidden");
    }

    function hideTableState() {
        el.tableState.classList.add("hidden");
    }

    function showToast(message) {
        el.toast.textContent = message;
        el.toast.classList.add("show");
        window.setTimeout(() => el.toast.classList.remove("show"), 2200);
    }

    function queryParams() {
        const params = new URLSearchParams({
            page: state.page,
            page_size: state.pageSize,
        });
        if (state.operation) params.set("operation", state.operation);
        if (el.keyword.value.trim()) params.set("keyword", el.keyword.value.trim());
        if (el.user.value) params.set("user_id", el.user.value);
        if (el.module.value) params.set("module", el.module.value);
        if (el.startDate.value) params.set("start_date", el.startDate.value);
        if (el.endDate.value) params.set("end_date", el.endDate.value);
        return params;
    }

    function renderRows(items) {
        if (!items.length) {
            el.body.innerHTML = "";
            setTableState("没有找到符合条件的操作记录", "◎");
            return;
        }
        hideTableState();
        el.body.innerHTML = items.map((item, index) => `
            <tr>
                <td class="seq-cell">${(state.page - 1) * state.pageSize + index + 1}</td>
                <td>${imageHtml(item)}</td>
                <td>
                    <div class="product-name">${escapeHtml(item.product_name || `配件 #${item.part_id || "-"}`)}</div>
                    <div class="product-sub">
                        <span>型号：${escapeHtml(item.model || "-")}</span>
                    </div>
                </td>
                <td><div class="badge-list">${operationBadges(item)}</div></td>
                <td><div class="badge-list">${moduleBadges(item)}</div></td>
                <td>
                    <div class="change-summary-count">共 ${Number(item.log_count) || 1} 条变更</div>
                    <div class="detail-text" title="${escapeHtml(item.detail)}">最近：${escapeHtml(item.detail)}</div>
                </td>
                <td>
                    <div class="operator">${avatarHtml(item)}<span>${escapeHtml(item.operator_name)}</span></div>
                </td>
                <td><div class="time-text">${formatTime(item.created_at)}</div></td>
                <td><button class="view-button" type="button" data-log-id="${item.id}">查看</button></td>
            </tr>
        `).join("");
    }

    function renderStats(stats) {
        document.getElementById("statAll").textContent = stats.all || 0;
        document.getElementById("statCreate").textContent = stats.create || 0;
        document.getElementById("statUpdate").textContent = stats.update || 0;
        document.getElementById("statDelete").textContent = stats.delete || 0;
    }

    async function loadLogs() {
        if (state.loading) return;
        state.loading = true;
        setTableState("正在加载操作日志...");
        try {
            const response = await fetch(`/api/logs?${queryParams()}`);
            if (!response.ok) throw new Error((await response.json()).detail || "日志加载失败");
            const data = await response.json();
            state.pages = data.pages;
            renderRows(data.items);
            renderStats(data.stats);
            el.total.textContent = data.total;
            el.pageInfo.textContent = `第 ${data.page} / ${data.pages} 页`;
            el.prev.disabled = data.page <= 1;
            el.next.disabled = data.page >= data.pages;
        } catch (error) {
            el.body.innerHTML = "";
            setTableState(error.message || "日志加载失败", "!");
            showToast(error.message || "日志加载失败");
        } finally {
            state.loading = false;
        }
    }

    async function loadUsers() {
        try {
            const response = await fetch("/api/logs/users");
            if (!response.ok) throw new Error("操作人加载失败");
            const data = await response.json();
            el.user.insertAdjacentHTML(
                "beforeend",
                data.items.map(user => `<option value="${user.id}">${escapeHtml(user.display_name)}${user.username && user.username !== user.display_name ? `（${escapeHtml(user.username)}）` : ""}</option>`).join("")
            );
        } catch (error) {
            showToast(error.message);
        }
    }

    async function openDetail(logId) {
        el.drawer.classList.add("open");
        el.drawerMask.classList.add("open");
        el.drawer.setAttribute("aria-hidden", "false");
        el.drawerContent.innerHTML = `<div class="detail-card">正在加载详情...</div>`;
        try {
            const response = await fetch(`/api/logs/${logId}`);
            if (!response.ok) throw new Error((await response.json()).detail || "详情加载失败");
            const item = await response.json();
            const entries = item.entries || [];
            el.drawerTitle.textContent = item.product_name || `配件 #${item.part_id || "-"}`;
            el.drawerContent.innerHTML = `
                <section class="detail-card">
                    <h3>产品信息</h3>
                    <div class="product-summary">
                        ${imageHtml(item)}
                        <div>
                            <div class="summary-name">${escapeHtml(item.product_name || `配件 #${item.part_id || "-"}`)}</div>
                            <div class="summary-meta">
                                型号：${escapeHtml(item.model || "-")}<br>
                                品牌：${escapeHtml(item.product_brand || "-")}　分类：${escapeHtml(item.product_type || "-")}<br>
                                共 ${entries.length} 条操作记录
                            </div>
                        </div>
                    </div>
                </section>
                <section class="detail-card">
                    <h3>全部变更内容</h3>
                    <div class="change-history">
                        ${entries.map(entry => `
                            <article class="change-history-item">
                                <div class="change-history-head">
                                    <div class="badge-list">
                                        <span class="operation-badge ${operationClass(entry.operation_type)}">${escapeHtml(entry.operation_label)}</span>
                                        <span class="module-badge">${escapeHtml(entry.module_label)}</span>
                                    </div>
                                    <time>${formatTime(entry.created_at)}</time>
                                </div>
                                <div class="change-content">${escapeHtml(entry.detail)}</div>
                                <div class="change-history-operator">操作人：${escapeHtml(entry.operator_name)}</div>
                            </article>
                        `).join("") || '<div class="change-history-empty">暂无变更明细</div>'}
                    </div>
                </section>
            `;
        } catch (error) {
            el.drawerContent.innerHTML = `<div class="detail-card">${escapeHtml(error.message)}</div>`;
        }
    }

    function closeDetail() {
        el.drawer.classList.remove("open");
        el.drawerMask.classList.remove("open");
        el.drawer.setAttribute("aria-hidden", "true");
    }

    document.getElementById("operationTabs").addEventListener("click", event => {
        const button = event.target.closest(".operation-tab");
        if (!button) return;
        document.querySelectorAll(".operation-tab").forEach(tab => tab.classList.remove("active"));
        button.classList.add("active");
        state.operation = button.dataset.operation;
        state.page = 1;
        loadLogs();
    });

    el.form.addEventListener("submit", event => {
        event.preventDefault();
        state.page = 1;
        loadLogs();
    });

    document.getElementById("resetButton").addEventListener("click", () => {
        el.form.reset();
        state.operation = "";
        state.page = 1;
        document.querySelectorAll(".operation-tab").forEach(tab => tab.classList.remove("active"));
        document.querySelector('.operation-tab[data-operation=""]').classList.add("active");
        loadLogs();
    });

    document.getElementById("refreshButton").addEventListener("click", loadLogs);
    el.pageSize.addEventListener("change", () => {
        state.pageSize = Number(el.pageSize.value);
        state.page = 1;
        loadLogs();
    });
    el.prev.addEventListener("click", () => {
        if (state.page > 1) { state.page -= 1; loadLogs(); }
    });
    el.next.addEventListener("click", () => {
        if (state.page < state.pages) { state.page += 1; loadLogs(); }
    });
    el.body.addEventListener("click", event => {
        const button = event.target.closest("[data-log-id]");
        if (button) openDetail(button.dataset.logId);
    });
    document.getElementById("drawerClose").addEventListener("click", closeDetail);
    el.drawerMask.addEventListener("click", closeDetail);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") closeDetail();
    });

    Promise.all([loadUsers(), loadLogs()]);
})();
