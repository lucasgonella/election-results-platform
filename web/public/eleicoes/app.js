const VERSION_URL =
    "/data/version.json";

const MANIFEST_URL =
    "/data/manifest.json";

const REFRESH_MS = 30000;

const PAGE_SIZE = 20;

const OFFICE_ORDER = [
    1,
    3,
    5,
    6,
    7,
    8
];

const SCOPE_NAMES = {
    br: "Brasil",
    ac: "Acre",
    al: "Alagoas",
    ap: "Amapá",
    am: "Amazonas",
    ba: "Bahia",
    ce: "Ceará",
    df: "Distrito Federal",
    es: "Espírito Santo",
    go: "Goiás",
    ma: "Maranhão",
    mt: "Mato Grosso",
    ms: "Mato Grosso do Sul",
    mg: "Minas Gerais",
    pa: "Pará",
    pb: "Paraíba",
    pr: "Paraná",
    pe: "Pernambuco",
    pi: "Piauí",
    rj: "Rio de Janeiro",
    rn: "Rio Grande do Norte",
    rs: "Rio Grande do Sul",
    ro: "Rondônia",
    rr: "Roraima",
    sc: "Santa Catarina",
    sp: "São Paulo",
    se: "Sergipe",
    to: "Tocantins",
    zz: "Exterior"
};


let manifest = null;
let publishedVersion = null;

let selectedScope = null;
let selectedOffice = null;

let currentResult = null;

let allCandidates = [];
let filteredCandidates = [];

let currentPage = 1;


function formatNumber(value) {
    return new Intl.NumberFormat(
        "pt-BR"
    ).format(
        value ?? 0
    );
}


function formatPercentage(value) {
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


function formatDate(value) {

    if (!value) {
        return "--";
    }

    const date =
        new Date(value);

    return date.toLocaleString(
        "pt-BR",
        {
            timeZone:
                "America/Sao_Paulo"
        }
    );
}


function scopeName(scope) {
    return (
        SCOPE_NAMES[scope]
        ?? scope.toUpperCase()
    );
}


function createElement(
    tag,
    className,
    text
) {
    const element =
        document.createElement(tag);

    if (className) {
        element.className =
            className;
    }

    if (text !== undefined) {
        element.textContent =
            text;
    }

    return element;
}


function getResultsForScope(
    scope
) {
    return manifest.results
        .filter(
            item =>
                item.scope === scope
        )
        .sort(
            (a, b) =>
                OFFICE_ORDER.indexOf(
                    a.office
                )
                -
                OFFICE_ORDER.indexOf(
                    b.office
                )
        );
}


function updateUrl() {

    const url =
        new URL(
            window.location.href
        );

    url.searchParams.set(
        "scope",
        selectedScope
    );

    url.searchParams.set(
        "office",
        selectedOffice
    );

    history.replaceState(
        {},
        "",
        url
    );
}


function selectInitialRoute() {

    const params =
        new URLSearchParams(
            window.location.search
        );

    const requestedScope =
        params.get("scope");

    const requestedOffice =
        Number(
            params.get("office")
        );

    const scopes =
        new Set(
            manifest.results.map(
                item => item.scope
            )
        );

    selectedScope =
        scopes.has(requestedScope)
            ? requestedScope
            : (
                scopes.has("br")
                    ? "br"
                    : [...scopes][0]
            );

    const results =
        getResultsForScope(
            selectedScope
        );

    const officeExists =
        results.some(
            item =>
                item.office
                === requestedOffice
        );

    selectedOffice =
        officeExists
            ? requestedOffice
            : results[0].office;
}


function renderEnvironment() {

    const badge =
        document.getElementById(
            "environment-badge"
        );

    if (
        manifest.environment
        .toLowerCase()
        .includes("simulado")
    ) {
        badge.textContent =
            "● Simulado";

        badge.className =
            "environment-badge simulator";
    } else {
        badge.textContent =
            "● Dados oficiais";

        badge.className =
            "environment-badge official";
    }
}


function renderScopeSelector() {

    const select =
        document.getElementById(
            "scope-select"
        );

    select.innerHTML = "";

    const scopes = [
        ...new Set(
            manifest.results.map(
                item => item.scope
            )
        )
    ];

    scopes.sort(
        (a, b) => {

            if (a === "br") {
                return -1;
            }

            if (b === "br") {
                return 1;
            }

            if (a === "zz") {
                return 1;
            }

            if (b === "zz") {
                return -1;
            }

            return scopeName(a)
                .localeCompare(
                    scopeName(b),
                    "pt-BR"
                );
        }
    );

    for (const scope of scopes) {

        const option =
            document.createElement(
                "option"
            );

        option.value =
            scope;

        option.textContent =
            scopeName(scope);

        option.selected =
            scope === selectedScope;

        select.appendChild(
            option
        );
    }
}


function renderOfficeTabs() {

    const container =
        document.getElementById(
            "office-tabs"
        );

    container.innerHTML = "";

    const results =
        getResultsForScope(
            selectedScope
        );

    if (
        !results.some(
            item =>
                item.office
                === selectedOffice
        )
    ) {
        selectedOffice =
            results[0].office;
    }

    for (const item of results) {

        const button =
            createElement(
                "button",
                "office-tab",
                item.office_name
            );

        if (
            item.office
            === selectedOffice
        ) {
            button.classList.add(
                "active"
            );
        }

        button.addEventListener(
            "click",
            async () => {

                selectedOffice =
                    item.office;

                currentPage = 1;

                updateUrl();
                renderOfficeTabs();

                await loadSelectedResult();
            }
        );

        container.appendChild(
            button
        );
    }
}


function currentManifestItem() {

    return manifest.results.find(
        item =>
            item.scope
                === selectedScope
            &&
            item.office
                === selectedOffice
    );
}


function renderSummary() {

    const data =
        currentResult;

    const percentage =
        data.snapshot
            .sections
            .percentage
        ?? 0;

    document.getElementById(
        "location-summary"
    ).textContent =
        scopeName(
            selectedScope
        );

    document.getElementById(
        "office-summary"
    ).textContent =
        data.office.name;

    document.getElementById(
        "sections-summary"
    ).textContent =
        `${formatPercentage(
            percentage
        )}%`;

    document.getElementById(
        "candidate-count-summary"
    ).textContent =
        formatNumber(
            data.candidate_count
        );

    document.getElementById(
        "progress-label"
    ).textContent =
        `${formatPercentage(
            percentage
        )}%`;

    document.getElementById(
        "progress-bar"
    ).style.width =
        `${Math.min(
            Math.max(
                percentage,
                0
            ),
            100
        )}%`;

    document.getElementById(
        "page-title"
    ).textContent =
        `${data.office.name} — ${
            scopeName(
                selectedScope
            )
        }`;

    document.getElementById(
        "updated-at"
    ).textContent =
        `Atualizado em ${
            formatDate(
                data.snapshot
                    .captured_at
            )
        }`;
}


function candidateSearchText(
    candidate
) {
    return [
        candidate.ballot_name,
        candidate.name,
        candidate.ballot_number,
        candidate.party_acronym,
        candidate.party_name
    ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase(
            "pt-BR"
        );
}


function renderCandidateCard(
    candidate,
    position,
    majorOffice
) {

    const card =
        createElement(
            "article",
            majorOffice
                ? "candidate major"
                : "candidate"
        );

    const positionElement =
        createElement(
            "div",
            "position",
            String(position)
        );

    const main =
        createElement(
            "div",
            "candidate-main"
        );

    const name =
        createElement(
            "div",
            "candidate-name",
            candidate.ballot_name
                || candidate.name
        );

    const meta =
        createElement(
            "div",
            "candidate-meta"
        );

    const number =
        candidate.ballot_number
            ?? "-";

    const party =
        candidate.party_acronym
            ?? "-";

    meta.textContent =
        `Nº ${number} · ${party}`;

    const favoriteRef = {
        scope: selectedScope,
        scope_name: scopeName(
            selectedScope
        ),
        office: selectedOffice,
        office_name:
            currentResult
                ?.office
                ?.name
            ?? `Cargo ${selectedOffice}`,
        candidate_id: String(
            candidate.tse_candidate_seq
        ),
        candidate_name:
            candidate.ballot_name
            || candidate.name,
        ballot_number:
            candidate.ballot_number,
        party_acronym:
            candidate.party_acronym
    };


    const favoriteButton =
        createElement(
            "button",
            "favorite-toggle",
            window.Favorites
                .isFavorite(
                    favoriteRef
                )
                ? "\u2605"
                : "\u2606"
        );

    favoriteButton.type =
        "button";

    favoriteButton.title =
        "Adicionar ou remover dos favoritos";

    favoriteButton.setAttribute(
        "aria-label",
        "Adicionar ou remover dos favoritos"
    );

    favoriteButton.addEventListener(
        "click",
        () => {
            const selected =
                window.Favorites.toggle(
                    favoriteRef
                );

            favoriteButton.textContent =
                selected
                    ? "\u2605"
                    : "\u2606";
        }
    );


    const titleRow =
        createElement(
            "div",
            "candidate-title-row"
        );

    titleRow.append(
        name,
        favoriteButton
    );


    main.append(
        titleRow,
        meta
    );

    if (
        candidate.result_status
    ) {
        main.appendChild(
            createElement(
                "div",
                "candidate-status",
                candidate.result_status
            )
        );
    }

    const votes =
        createElement(
            "div",
            "votes"
        );

    const votesNumber =
        createElement(
            "strong",
            null,
            formatNumber(
                candidate.votes
            )
        );

    const votesLabel =
        createElement(
            "span",
            null,
            " votos"
        );

    const percentage =
        createElement(
            "div",
            "vote-percentage",
            `${
                formatPercentage(
                    candidate
                        .vote_percentage
                )
            }%`
        );

    votes.append(
        votesNumber,
        votesLabel,
        percentage
    );

    card.append(
        positionElement,
        main,
        votes
    );

    if (majorOffice) {

        const barTrack =
            createElement(
                "div",
                "candidate-bar-track"
            );

        const bar =
            createElement(
                "div",
                "candidate-bar"
            );

        bar.style.width =
            `${Math.min(
                candidate.vote_percentage
                    ?? 0,
                100
            )}%`;

        barTrack.appendChild(
            bar
        );

        card.appendChild(
            barTrack
        );
    }

    return card;
}


function renderResults() {

    const container =
        document.getElementById(
            "results"
        );

    const pagination =
        document.getElementById(
            "pagination"
        );

    container.innerHTML = "";
    pagination.innerHTML = "";

    const majorOffice =
        [1, 3, 5].includes(
            selectedOffice
        );

    container.className =
        majorOffice
            ? "results major-results"
            : "results";

    const pageSize =
        majorOffice
            ? 50
            : PAGE_SIZE;

    const start =
        (currentPage - 1)
        * pageSize;

    const candidates =
        filteredCandidates.slice(
            start,
            start + pageSize
        );

    candidates.forEach(
        (candidate, index) => {

            container.appendChild(
                renderCandidateCard(
                    candidate,
                    start + index + 1,
                    majorOffice
                )
            );
        }
    );

    const totalPages =
        Math.max(
            1,
            Math.ceil(
                filteredCandidates.length
                / pageSize
            )
        );

    if (
        majorOffice
        || totalPages <= 1
    ) {
        return;
    }

    const previous =
        createElement(
            "button",
            null,
            "Anterior"
        );

    previous.disabled =
        currentPage === 1;

    previous.addEventListener(
        "click",
        () => {
            currentPage--;
            renderResults();
        }
    );

    const info =
        createElement(
            "span",
            null,
            `Página ${
                currentPage
            } de ${
                totalPages
            }`
        );

    const next =
        createElement(
            "button",
            null,
            "Próxima"
        );

    next.disabled =
        currentPage
        >= totalPages;

    next.addEventListener(
        "click",
        () => {
            currentPage++;
            renderResults();
        }
    );

    pagination.append(
        previous,
        info,
        next
    );
}


async function loadSelectedResult() {

    const item =
        currentManifestItem();

    if (!item) {
        throw new Error(
            "Resultado não encontrado no manifest."
        );
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
            `HTTP ${response.status}`
        );
    }

    currentResult =
        await response.json();

    allCandidates = [
        ...currentResult.candidates
    ].sort(
        (a, b) =>
            (b.votes ?? 0)
            -
            (a.votes ?? 0)
    );

    filteredCandidates =
        allCandidates;

    currentPage = 1;

    document.getElementById(
        "search"
    ).value = "";

    renderSummary();
    renderResults();
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


async function loadManifest() {

    const response =
        await fetch(
            MANIFEST_URL,
            {
                cache: "no-store"
            }
        );

    if (!response.ok) {
        throw new Error(
            `Manifest HTTP ${
                response.status
            }`
        );
    }

    manifest =
        await response.json();

    return manifest;
}
async function refreshIfChanged() {

    try {
        const version =
            await loadVersion();

        const nextVersion =
            publicationToken(
                version
            );

        if (
            nextVersion
            === publishedVersion
        ) {
            return;
        }

        const oldItem =
            currentManifestItem();

        await loadManifest();

        const newItem =
            currentManifestItem();

        publishedVersion =
            nextVersion;

        window.Favorites.setManifest(
            manifest,
            publishedVersion
        );

        if (
            newItem
            &&
            oldItem
            &&
            (
                newItem.tse_idg
                    !== oldItem.tse_idg
                ||
                newItem.captured_at
                    !== oldItem.captured_at
            )
        ) {
            renderOfficeTabs();

            await loadSelectedResult();
        }

    } catch (error) {
        console.error(
            "Refresh failed:",
            error
        );
    }
}
async function initialize() {

    const version =
        await loadVersion();

    await loadManifest();

    publishedVersion =
        publicationToken(
            version
        );

    window.Favorites.setManifest(
        manifest,
        publishedVersion
    );

    selectInitialRoute();

    renderEnvironment();
    renderScopeSelector();
    renderOfficeTabs();

    updateUrl();

    await loadSelectedResult();

    setInterval(
        refreshIfChanged,
        REFRESH_MS
    );
}


document.getElementById(
    "scope-select"
).addEventListener(
    "change",
    async event => {

        selectedScope =
            event.target.value;

        const results =
            getResultsForScope(
                selectedScope
            );

        selectedOffice =
            results[0].office;

        currentPage = 1;

        renderOfficeTabs();
        updateUrl();

        await loadSelectedResult();
    }
);


document.getElementById(
    "search"
).addEventListener(
    "input",
    event => {

        const term =
            event.target.value
                .trim()
                .toLocaleLowerCase(
                    "pt-BR"
                );

        if (!term) {
            filteredCandidates =
                allCandidates;
        } else {
            filteredCandidates =
                allCandidates.filter(
                    candidate =>
                        candidateSearchText(
                            candidate
                        ).includes(term)
                );
        }

        currentPage = 1;

        renderResults();
    }
);


initialize().catch(
    error => {

        console.error(error);

        document.getElementById(
            "results"
        ).innerHTML =
            `
            <div class="error">
                Não foi possível carregar
                os resultados.
            </div>
            `;
    }
);