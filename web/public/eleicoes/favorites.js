(() => {
    "use strict";

    const STORAGE_KEY =
        "election-results:favorites:v1";

    const VERSION_URL =
        "/data/version.json";

    const MANIFEST_URL =
        "/data/manifest.json";

    const REFRESH_MS = 5000;

    const OFFICE_ORDER = [
        1,
        3,
        5,
        6,
        7,
        8
    ];

    let manifest = null;
    let publishedVersion = null;
    let refreshTimer = null;
    let rendering = false;

    const resultCache =
        new Map();


    function loadFavorites() {
        try {
            const raw =
                localStorage.getItem(
                    STORAGE_KEY
                );

            if (!raw) {
                return [];
            }

            const parsed =
                JSON.parse(raw);

            return Array.isArray(parsed)
                ? parsed
                : [];

        } catch (error) {
            console.error(
                "Could not load favorites:",
                error
            );

            return [];
        }
    }


    function saveFavorites(
        favorites
    ) {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify(favorites)
        );
    }


    function favoriteKey(
        favorite
    ) {
        return [
            favorite.scope,
            favorite.office,
            favorite.candidate_id
        ].join(":");
    }


    function isFavorite(
        favorite
    ) {
        const key =
            favoriteKey(favorite);

        return loadFavorites().some(
            item =>
                favoriteKey(item)
                === key
        );
    }


    function updateCount() {
        const counter =
            document.getElementById(
                "favorites-count"
            );

        if (!counter) {
            return;
        }

        counter.textContent =
            String(
                loadFavorites().length
            );
    }


    function toggle(
        favorite
    ) {
        const favorites =
            loadFavorites();

        const key =
            favoriteKey(favorite);

        const index =
            favorites.findIndex(
                item =>
                    favoriteKey(item)
                    === key
            );

        let selected;

        if (index >= 0) {
            favorites.splice(
                index,
                1
            );

            selected = false;
        } else {
            favorites.push(
                favorite
            );

            selected = true;
        }

        saveFavorites(
            favorites
        );

        updateCount();

        if (isOpen()) {
            void renderPanel();
        }

        return selected;
    }


    function removeFavorite(
        favorite
    ) {
        const key =
            favoriteKey(favorite);

        const favorites =
            loadFavorites().filter(
                item =>
                    favoriteKey(item)
                    !== key
            );

        saveFavorites(
            favorites
        );

        updateCount();

        void renderPanel();
    }


    function setManifest(
        value,
        version = null
    ) {
        const changed = (
            version !== null
            && version
                !== publishedVersion
        );

        manifest = value;

        if (version !== null) {
            publishedVersion =
                version;
        }

        if (changed) {
            resultCache.clear();

            if (isOpen()) {
                void renderPanel();
            }
        }
    }
    function isOpen() {
        const backdrop =
            document.getElementById(
                "favorites-backdrop"
            );

        return Boolean(
            backdrop
            && !backdrop.hidden
        );
    }


    function openPanel() {
        const backdrop =
            document.getElementById(
                "favorites-backdrop"
            );

        if (!backdrop) {
            return;
        }

        backdrop.hidden = false;

        document.body.classList.add(
            "favorites-opened"
        );

        void renderPanel();

        if (!refreshTimer) {
            refreshTimer =
                window.setInterval(
                    () => {
                        void checkForPublication();
                    },
                    REFRESH_MS
                );
        }
    }


    function closePanel() {
        const backdrop =
            document.getElementById(
                "favorites-backdrop"
            );

        if (!backdrop) {
            return;
        }

        backdrop.hidden = true;

        document.body.classList.remove(
            "favorites-opened"
        );

        if (refreshTimer) {
            clearInterval(
                refreshTimer
            );

            refreshTimer = null;
        }
    }


    function updateRefreshStatus(
        message,
        state = ""
    ) {
        const status =
            document.getElementById(
                "favorites-refresh-status"
            );

        if (!status) {
            return;
        }

        status.textContent =
            message;

        status.className =
            "favorites-refresh-status";

        if (state) {
            status.classList.add(
                state
            );
        }
    }


    function formatCheckTime() {
        return new Date()
            .toLocaleTimeString(
                "pt-BR",
                {
                    timeZone:
                        "America/Sao_Paulo",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit"
                }
            );
    }


    function publicationToken(
        version
    ) {
        return [
            version.environment,
            version.generated_at
        ].join(":");
    }


    async function loadVersion() {
        const response =
            await fetch(
                VERSION_URL,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `Version HTTP ${
                    response.status
                }`
            );
        }

        return response.json();
    }


    async function refreshManifest() {
        const response =
            await fetch(
                MANIFEST_URL,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `Manifest HTTP ${response.status}`
            );
        }

        manifest =
            await response.json();

        return manifest;
    }


    async function checkForPublication() {
        if (
            rendering
            || !isOpen()
        ) {
            return;
        }

        try {
            const version =
                await loadVersion();

            const nextVersion =
                publicationToken(
                    version
                );

            if (
                publishedVersion
                === nextVersion
            ) {
                updateRefreshStatus(
                    `Sem nova publicação · verificado às ${
                        formatCheckTime()
                    }`,
                    "synced"
                );

                return;
            }

            updateRefreshStatus(
                "Nova publicação detectada. Atualizando favoritos...",
                "checking"
            );

            await refreshManifest();

            publishedVersion =
                nextVersion;

            resultCache.clear();

            await renderPanel();

        } catch (error) {
            console.error(
                "Favorites publication check failed:",
                error
            );

            updateRefreshStatus(
                "Não foi possível verificar a atualização agora.",
                "error"
            );
        }
    }


    function isPublishedSnapshotCurrent(
        item,
        result
    ) {
        if (
            !item
            || !result
            || !result.snapshot
        ) {
            return false;
        }

        return (
            String(
                item.tse_idg
            )
            ===
            String(
                result.snapshot.tse_idg
            )
            &&
            String(
                item.captured_at
            )
            ===
            String(
                result.snapshot.captured_at
            )
        );
    }


    function manifestItem(
        favorite
    ) {
        if (!manifest) {
            return null;
        }

        return manifest.results.find(
            item =>
                item.scope
                    === favorite.scope
                &&
                item.office
                    === Number(
                        favorite.office
                    )
        ) ?? null;
    }


    function formatNumber(
        value
    ) {
        return new Intl.NumberFormat(
            "pt-BR"
        ).format(
            value ?? 0
        );
    }


    function formatPercentage(
        value
    ) {
        return new Intl.NumberFormat(
            "pt-BR",
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }
        ).format(
            value ?? 0
        );
    }


    function formatDate(
        value
    ) {
        if (!value) {
            return "--";
        }

        return new Date(
            value
        ).toLocaleString(
            "pt-BR",
            {
                timeZone:
                    "America/Sao_Paulo"
            }
        );
    }


    async function loadFavoriteData(
        favorite
    ) {
        const item =
            manifestItem(
                favorite
            );

        if (!item) {
            return {
                favorite,
                item: null,
                result: null,
                candidate: null,
                synced: false
            };
        }

        let resultPromise =
            resultCache.get(
                item.path
            );

        if (!resultPromise) {
            resultPromise = (
                fetch(
                    `/data/${item.path}`,
                    {
                        cache: "no-store"
                    }
                )
                .then(
                    response => {
                        if (!response.ok) {
                            throw new Error(
                                `HTTP ${
                                    response.status
                                } for ${item.path}`
                            );
                        }

                        return response.json();
                    }
                )
            );

            resultCache.set(
                item.path,
                resultPromise
            );
        }

        let result;

        try {
            result =
                await resultPromise;

        } catch (error) {
            resultCache.delete(
                item.path
            );

            throw error;
        }

        const candidate =
            result.candidates.find(
                item =>
                    String(
                        item.tse_candidate_seq
                    )
                    === String(
                        favorite.candidate_id
                    )
            ) ?? null;

        return {
            favorite,
            item,
            result,
            candidate,
            synced:
                isPublishedSnapshotCurrent(
                    item,
                    result
                )
        };
    }
    function createCard(
        entry
    ) {
        const {
            favorite,
            result,
            candidate,
            synced
        } = entry;

        const card =
            document.createElement(
                "article"
            );

        card.className =
            "favorite-card";

        const header =
            document.createElement(
                "div"
            );

        header.className =
            "favorite-card-header";


        const context =
            document.createElement(
                "div"
            );

        context.className =
            "favorite-context";

        context.textContent = [
            favorite.scope_name
                ?? favorite.scope
                    .toUpperCase(),

            favorite.office_name
                ?? `Cargo ${
                    favorite.office
                }`
        ].join(" · ");


        const remove =
            document.createElement(
                "button"
            );

        remove.type = "button";
        remove.className =
            "favorite-remove";

        remove.textContent = "\u2605";

        remove.title =
            "Remover dos favoritos";

        remove.setAttribute(
            "aria-label",
            "Remover dos favoritos"
        );

        remove.addEventListener(
            "click",
            () => {
                removeFavorite(
                    favorite
                );
            }
        );

        header.append(
            context,
            remove
        );

        card.appendChild(
            header
        );


        const syncBadge =
            document.createElement(
                "div"
            );

        syncBadge.className =
            synced
                ? "favorite-sync synced"
                : "favorite-sync pending";

        syncBadge.textContent =
            synced
                ? "● Sincronizado com a publicação atual"
                : "● Atualizando dados publicados";

        card.appendChild(
            syncBadge
        );


        if (
            !candidate
            || !result
        ) {
            const unavailable =
                document.createElement(
                    "div"
                );

            unavailable.className =
                "favorite-unavailable";

            unavailable.textContent =
                favorite.candidate_name
                ?? "Candidato indisponível";

            card.appendChild(
                unavailable
            );

            return card;
        }


        const name =
            document.createElement(
                "strong"
            );

        name.className =
            "favorite-name";

        name.textContent =
            candidate.ballot_name
            || candidate.name;


        const meta =
            document.createElement(
                "div"
            );

        meta.className =
            "favorite-meta";

        meta.textContent =
            `Nº ${
                candidate.ballot_number
                ?? "-"
            } · ${
                candidate.party_acronym
                ?? "-"
            }`;


        const numbers =
            document.createElement(
                "div"
            );

        numbers.className =
            "favorite-numbers";


        const votes =
            document.createElement(
                "div"
            );

        votes.innerHTML =
            `<strong>${
                formatNumber(
                    candidate.votes
                )
            }</strong><span> votos</span>`;


        const percentage =
            document.createElement(
                "div"
            );

        percentage.innerHTML =
            `<strong>${
                formatPercentage(
                    candidate
                        .vote_percentage
                )
            }%</strong>`;


        numbers.append(
            votes,
            percentage
        );


        card.append(
            name,
            meta,
            numbers
        );


        if (
            candidate.result_status
        ) {
            const status =
                document.createElement(
                    "div"
                );

            status.className =
                "favorite-status";

            status.textContent =
                candidate.result_status;

            card.appendChild(
                status
            );
        }


        const details =
            document.createElement(
                "div"
            );

        details.className =
            "favorite-details";


        const detailItems = [
            [
                "Localidade",
                favorite.scope_name
                    ?? favorite.scope
                        .toUpperCase()
            ],
            [
                "Cargo",
                favorite.office_name
                    ?? result.office
                        ?.name
                    ?? `Cargo ${favorite.office}`
            ],
            [
                "Apuração",
                `${
                    formatPercentage(
                        result.snapshot
                            .sections
                            ?.percentage
                        ?? 0
                    )
                }%`
            ],
            [
                "Atualizado",
                formatDate(
                    result.snapshot
                        .captured_at
                )
            ]
        ];


        for (
            const [
                labelText,
                valueText
            ]
            of detailItems
        ) {
            const detail =
                document.createElement(
                    "div"
                );

            detail.className =
                "favorite-detail";


            const label =
                document.createElement(
                    "span"
                );

            label.textContent =
                labelText;


            const value =
                document.createElement(
                    "strong"
                );

            value.textContent =
                valueText;


            detail.append(
                label,
                value
            );

            details.appendChild(
                detail
            );
        }


        card.appendChild(
            details
        );

        return card;
    }


    async function renderPanel() {
        if (
            rendering
            || !isOpen()
        ) {
            return;
        }

        const list =
            document.getElementById(
                "favorites-list"
            );

        if (!list) {
            return;
        }

        rendering = true;

        try {
            updateRefreshStatus(
                "Verificando dados publicados...",
                "checking"
            );

            if (!manifest) {
                await refreshManifest();
            }

            const favorites =
                loadFavorites();

            list.innerHTML = "";

            if (
                favorites.length === 0
            ) {
                const empty =
                    document.createElement(
                        "div"
                    );

                empty.className =
                    "favorites-empty";

                empty.innerHTML =
                    "<strong>Nenhum favorito ainda.</strong>"
                    + "<span>Use a estrela ao lado de um candidato para adicioná-lo.</span>";

                list.appendChild(
                    empty
                );

                updateRefreshStatus(
                    `Dados publicados verificados às ${
                        formatCheckTime()
                    }`,
                    "synced"
                );

                return;
            }

            const loading =
                document.createElement(
                    "div"
                );

            loading.className =
                "favorites-loading";

            loading.textContent =
                "Atualizando favoritos...";

            list.appendChild(
                loading
            );


            const ordered =
                [...favorites].sort(
                    (a, b) => {
                        const officeA =
                            OFFICE_ORDER.indexOf(
                                Number(a.office)
                            );

                        const officeB =
                            OFFICE_ORDER.indexOf(
                                Number(b.office)
                            );

                        if (
                            officeA
                            !== officeB
                        ) {
                            return (
                                officeA
                                - officeB
                            );
                        }

                        return String(
                            a.candidate_name
                            ?? ""
                        ).localeCompare(
                            String(
                                b.candidate_name
                                ?? ""
                            ),
                            "pt-BR"
                        );
                    }
                );


            const entries =
                await Promise.all(
                    ordered.map(
                        async favorite => {
                            try {
                                return await loadFavoriteData(
                                    favorite
                                );
                            } catch (error) {
                                console.error(
                                    "Favorite refresh failed:",
                                    error
                                );

                                return {
                                    favorite,
                                    item: null,
                                    result: null,
                                    candidate: null,
                                    synced: false
                                };
                            }
                        }
                    )
                );


            list.innerHTML = "";

            for (
                const entry
                of entries
            ) {
                list.appendChild(
                    createCard(
                        entry
                    )
                );
            }


            const allSynced =
                entries.every(
                    entry =>
                        entry.synced
                );

            if (allSynced) {
                updateRefreshStatus(
                    `Sincronizado com a publicação atual · verificado às ${
                        formatCheckTime()
                    }`,
                    "synced"
                );
            } else {
                updateRefreshStatus(
                    "Atualização em andamento. Nova verificação em até 10s.",
                    "pending"
                );
            }

        } catch (error) {
            console.error(
                "Favorites refresh failed:",
                error
            );

            updateRefreshStatus(
                "Não foi possível verificar a atualização agora.",
                "error"
            );

        } finally {
            rendering = false;
        }
    }


    function init() {
        const open =
            document.getElementById(
                "favorites-open"
            );

        const close =
            document.getElementById(
                "favorites-close"
            );

        const backdrop =
            document.getElementById(
                "favorites-backdrop"
            );

        open?.addEventListener(
            "click",
            openPanel
        );

        close?.addEventListener(
            "click",
            closePanel
        );

        backdrop?.addEventListener(
            "click",
            event => {
                if (
                    event.target
                    === backdrop
                ) {
                    closePanel();
                }
            }
        );

        document.addEventListener(
            "keydown",
            event => {
                if (
                    event.key === "Escape"
                    && isOpen()
                ) {
                    closePanel();
                }
            }
        );

        updateCount();
    }


    window.Favorites = {
        isFavorite,
        toggle,
        setManifest,
        renderPanel
    };


    init();
})();