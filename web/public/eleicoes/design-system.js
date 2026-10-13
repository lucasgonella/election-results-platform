/* Shared presentation only. Electoral data and selected round belong to app.js. */
(function () {
    "use strict";
    const root = document.documentElement;
    const storageKey = "election-results:theme:v1";
    const scheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    let preference = null;
    try { preference = localStorage.getItem(storageKey); } catch (_) { /* Private mode remains usable. */ }
    if (preference !== "light" && preference !== "dark") preference = null;

    function applyTheme(theme) {
        root.setAttribute("data-theme", theme);
        document.querySelectorAll("[data-theme-toggle]").forEach(button => {
            const dark = theme === "dark";
            button.setAttribute("aria-label", dark ? "Ativar tema claro" : "Ativar tema escuro");
            button.setAttribute("aria-pressed", String(dark));
            button.textContent = dark ? "☀" : "☾";
        });
    }

    applyTheme(preference || (scheme && scheme.matches ? "dark" : "light"));
    if (scheme && scheme.addEventListener) scheme.addEventListener("change", event => {
        if (!preference) applyTheme(event.matches ? "dark" : "light");
    });
    window.addEventListener("storage", event => {
        if (event.key !== storageKey) return;
        preference = event.newValue === "light" || event.newValue === "dark" ? event.newValue : null;
        applyTheme(preference || (scheme && scheme.matches ? "dark" : "light"));
    });

    function initNavigation() {
        document.querySelectorAll("[data-theme-toggle]").forEach(button => button.addEventListener("click", () => {
            preference = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
            try { localStorage.setItem(storageKey, preference); } catch (_) { /* Theme works without persistence. */ }
            applyTheme(preference);
        }));
        applyTheme(root.getAttribute("data-theme"));
        document.querySelectorAll("[data-nav-toggle]").forEach(button => {
            const nav = document.getElementById(button.getAttribute("aria-controls"));
            if (!nav) return;
            function close() {
                nav.classList.remove("is-open");
                button.setAttribute("aria-expanded", "false");
            }
            button.addEventListener("click", () => {
                const open = nav.classList.toggle("is-open");
                button.setAttribute("aria-expanded", String(open));
            });
            nav.addEventListener("click", event => { if (event.target.closest("a")) close(); });
            document.addEventListener("keydown", event => {
                if (event.key === "Escape" && nav.classList.contains("is-open")) { close(); button.focus(); }
            });
        });
    }

    function initDialogs() {
        document.querySelectorAll("[data-dialog-open]").forEach(button => button.addEventListener("click", () => {
            const dialog = document.getElementById(button.getAttribute("data-dialog-open"));
            if (dialog && !dialog.open && typeof dialog.showModal === "function") dialog.showModal();
        }));
        document.querySelectorAll("[data-dialog-close]").forEach(button => button.addEventListener("click", () => {
            button.closest("dialog")?.close();
        }));
        document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("click", event => {
            if (event.target !== dialog) return;
            const rect = dialog.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
        }));
        document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("keydown", event => {
            // Search inputs may consume the first Escape to clear their text.
            // Closing at capture keeps the dialog's keyboard action consistent.
            if (event.key === "Escape" && dialog.open) { event.preventDefault(); dialog.close(); }
        }, true));
    }

    function initScrollableTables() {
        document.querySelectorAll(".table-scroll").forEach(region => {
            if (!region.hasAttribute("tabindex")) region.setAttribute("tabindex", "0");
            if (!region.hasAttribute("role")) region.setAttribute("role", "region");
            if (!region.hasAttribute("aria-label") && !region.hasAttribute("aria-labelledby")) region.setAttribute("aria-label", "Tabela de resultados com rolagem horizontal");
        });
    }

    /* Upgrade the existing favorites drawer without changing its reader or refresh cycle. */
    function initFavoritesFocus() {
        const backdrop = document.getElementById("favorites-backdrop");
        const opener = document.getElementById("favorites-open");
        if (!backdrop || !opener) return;
        const panel = backdrop.querySelector(".favorites-panel");
        if (!panel) return;
        panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-modal", "true");
        panel.setAttribute("tabindex", "-1");
        opener.setAttribute("aria-haspopup", "dialog");
        opener.setAttribute("aria-label", "Abrir candidatos favoritos");
        opener.setAttribute("aria-expanded", "false");
        let returnFocus = null;
        const inerted = new Map();
        function sync() {
            const open = !backdrop.hidden;
            opener.setAttribute("aria-expanded", String(open));
            if (open) {
                returnFocus = document.activeElement;
                for (const sibling of document.body.children) {
                    if (sibling === backdrop || sibling.tagName === "SCRIPT" || sibling.tagName === "STYLE") continue;
                    inerted.set(sibling, sibling.inert);
                    sibling.inert = true;
                }
                (document.getElementById("favorites-close") || panel).focus();
            } else {
                inerted.forEach((inert, element) => { element.inert = inert; });
                inerted.clear();
                if (returnFocus && returnFocus.isConnected) returnFocus.focus();
                returnFocus = null;
            }
        }
        new MutationObserver(sync).observe(backdrop, { attributes: true, attributeFilter: ["hidden"] });
        panel.addEventListener("keydown", event => {
            if (event.key !== "Tab") return;
            const focusable = [...panel.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex="0"]')]
                .filter(element => element.getClientRects().length);
            if (!focusable.length) { event.preventDefault(); panel.focus(); return; }
            const first = focusable[0], last = focusable[focusable.length - 1];
            if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        });
    }

    /* Composition filters inspect rendered table rows; the official calculation stays unchanged. */
    function initComposition() {
        const page = document.querySelector(".composition-page");
        if (!page) return;
        const query = document.getElementById("composition-party-search");
        const houseSelect = document.getElementById("composition-house-select");
        const filterStatus = document.getElementById("composition-filter-status");
        function normalize(text) { return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR"); }
        function filter() {
            const term = normalize(query ? query.value.trim() : "");
            let found = 0;
            page.querySelectorAll(".composition-house").forEach(house => {
                const visible = !houseSelect || houseSelect.value === "all" || houseSelect.value === house.id;
                house.hidden = !visible;
                house.querySelectorAll(".composition-table").forEach(table => {
                    table.setAttribute("aria-label", `${house.querySelector(".composition-kicker")?.textContent || "Composição"}: cadeiras por partido`);
                    table.querySelectorAll("thead th").forEach(header => header.setAttribute("scope", "col"));
                });
                house.querySelectorAll(".composition-table tbody tr").forEach(row => {
                    row.hidden = !!term && !normalize(row.querySelector("td")?.textContent || "").includes(term);
                    if (visible && !row.hidden) found++;
                });
                const empty = house.querySelector("[data-composition-empty]");
                if (empty) empty.hidden = !term || !!house.querySelector("tbody tr:not([hidden])");
            });
            if (filterStatus) filterStatus.textContent = term ? `${found} partidos ou grupos encontrados. Os gráficos mostram a composição completa.` : "Os gráficos mostram todas as cadeiras; a busca filtra as tabelas.";
        }
        query?.addEventListener("input", filter);
        houseSelect?.addEventListener("change", filter);
        document.getElementById("composition-reset")?.addEventListener("click", () => {
            if (query) query.value = "";
            if (houseSelect) houseSelect.value = "all";
            filter();
        });
        for (const table of page.querySelectorAll(".composition-table-wrap")) {
            new MutationObserver(filter).observe(table, { childList: true });
        }
        document.querySelectorAll("[data-composition-view]").forEach(button => button.addEventListener("click", () => {
            const view = button.getAttribute("data-composition-view");
            page.setAttribute("data-view", view);
            document.querySelectorAll("[data-composition-view]").forEach(control => control.setAttribute("aria-pressed", String(control === button)));
        }));
        filter();
    }

    function init() { initNavigation(); initDialogs(); initScrollableTables(); initFavoritesFocus(); initComposition(); }
    window.PortalDesign = Object.freeze({ applyTheme });
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
    else init();
})();
