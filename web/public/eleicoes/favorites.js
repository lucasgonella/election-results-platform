(() => {
    "use strict";

    const STORAGE_KEY =
        "election-results:favorites:v1";

    const REFRESH_MS = 30000;

    const OFFICE_ORDER = [
        1,
        3,
        5,
        6,
        7
    ];

    let manifest = null;
    let refreshTimer = null;
    let rendering = false;


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
        value
    ) {
        manifest = value;

        if (isOpen()) {
            void renderPanel();
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
                        void renderPanel();
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
                candidate: null
            };
        }

        const response =
            await fetch(
                `/data/${item.path}`,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `HTTP ${
                    response.status
                } for ${item.path}`
            );
        }

        const result =
            await response.json();

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
            candidate
        };
    }


    function createCard(
        entry
    ) {
        const {
            favorite,
            result,
            candidate
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

        remove.textContent = "★";

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


        const updated =
            document.createElement(
                "div"
            );

        updated.className =
            "favorite-updated";

        updated.textContent =
            `Atualizado em ${
                formatDate(
                    result.snapshot
                        .captured_at
                )
            }`;

        card.appendChild(
            updated
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
                                    candidate: null
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
