const dataFetch = (...args) => window.LiveData ? window.LiveData.fetch(...args) : fetch(...args);
const SELECTED_ROUND = new URLSearchParams(window.location.search).get("turno") === "1" ? 1 : 2;
const ROUND_DATA_ROOT = SELECTED_ROUND === 2 ? "/data/turnos/2" : "/data";
const VERSION_URL = ROUND_DATA_ROOT + "/version.json";

const MANIFEST_URL = ROUND_DATA_ROOT + "/manifest.json";

const ALERTS_URL = ROUND_DATA_ROOT + "/alerts.json";

const REFRESH_MS = 5000;

// Legacy /data remains the default until version.json advertises a verified release.
let activeDataBase = ROUND_DATA_ROOT;
function dataBaseForVersion(version) {
    const id = version?.snapshot_id;
    if (id == null) return ROUND_DATA_ROOT;
    if (typeof id !== "string" || !/^[a-f0-9]{32,64}$/.test(id)) {
        throw new Error("Invalid snapshot_id");
    }
    return `${ROUND_DATA_ROOT}/releases/${id}`;
}


const PAGE_SIZE = 20;

const PROPORTIONAL_OFFICES =
    new Set([
        6,
        7,
        8
    ]);

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
let alerts = [];
let publishedVersion = null;
let roundTwoWaitingTimer = null;
let roundTwoRetryPending = false;

let selectedScope = null;
let selectedOffice = null;

let currentResult = null;

let allCandidates = [];
let filteredCandidates = [];

let currentPage = 1;
let portalMarker = null;
let selectedPresidentialCandidate = new URLSearchParams(window.location.search).get("candidate") || "";
let resultRequestNumber = 0;
let portalRefreshPending = false;
let resultState = "loading";
let initializationRetryPending = false;

function portalContext() {
    return {round: SELECTED_ROUND, manifest, version: portalMarker, dataBase: activeDataBase,
        scope: selectedScope, office: selectedOffice, result: currentResult,
        candidate: selectedPresidentialCandidate, status: resultState,
        selectionRevision: resultRequestNumber};
}

function announcePortalContext() {
    if (typeof document.dispatchEvent === "function" && typeof CustomEvent === "function") {
        document.dispatchEvent(new CustomEvent("election:context", {detail: portalContext()}));
    }
}


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


function alertKind(item) {
    return (
        item.kind
        || "elected"
    );
}


function electedStateGroups() {
    const grouped =
        new Map();

    for (const item of alerts) {
        const scope =
            String(
                item.scope
                ?? ""
            ).toLowerCase();

        const office =
            Number(
                item.office
            );

        const kind =
            alertKind(item);

        const definedGovernor =
            office === 3
            && [
                "elected",
                "mathematically_elected",
                "second_round"
            ].includes(kind);

        const definedSenator =
            office === 5
            && kind === "elected";

        if (
            !(
                definedGovernor
                || definedSenator
            )
            || !SCOPE_NAMES[scope]
            || scope === "br"
            || scope === "zz"
        ) {
            continue;
        }

        if (!grouped.has(scope)) {
            grouped.set(
                scope,
                {
                    governors: [],
                    senators: []
                }
            );
        }

        const state =
            grouped.get(scope);

        const target =
            office === 3
                ? state.governors
                : state.senators;

        const candidateId =
            String(
                item.candidate_id
                ?? item.candidate_name
                ?? (
                    alertKind(item)
                    + ":"
                    + (
                        item.result_status
                        ?? ""
                    )
                )
            );

        if (
            target.some(
                candidate =>
                    String(
                        candidate.candidate_id
                        ?? candidate.candidate_name
                        ?? (
                            alertKind(candidate)
                            + ":"
                            + (
                                candidate.result_status
                                ?? ""
                            )
                        )
                    )
                    === candidateId
            )
        ) {
            continue;
        }

        target.push(item);
    }

    return [
        ...grouped.entries()
    ].sort(
        (a, b) =>
            scopeName(a[0])
                .localeCompare(
                    scopeName(b[0]),
                    "pt-BR"
                )
    );
}


function electedCandidateList(
    candidates
) {
    const values =
        createElement(
            "div",
            "elected-state-office-values"
        );

    for (
        const candidate
        of candidates
    ) {
        const value =
            createElement(
                "div",
                "elected-state-candidate"
            );

        const kind =
            alertKind(candidate);

        const mathematicallyElected =
            kind
            === "mathematically_elected";

        const secondRound =
            kind === "second_round";

        const headline =
            candidate.candidate_name
            || (
                secondRound
                    ? "2º turno definido pelo TSE"
                    : (
                        mathematicallyElected
                            ? "Eleição matematicamente definida (Eleito)"
                            : "Resultado definido pelo TSE"
                    )
            );

        value.appendChild(
            createElement(
                "strong",
                null,
                headline
            )
        );

        const metaParts = [];

        if (
            candidate.party_acronym
        ) {
            metaParts.push(
                candidate.party_acronym
            );
        }

        if (
            candidate.result_status
            && candidate.candidate_name
        ) {
            metaParts.push(
                candidate.result_status
            );
        }

        if (
            !candidate.candidate_name
            && mathematicallyElected
        ) {
            metaParts.push(
                "Nome ainda não individualizado pelo TSE"
            );
        }

        if (secondRound) {
            metaParts.push(
                "Eleição segue para o 2º turno"
            );
        }

        if (metaParts.length) {
            value.appendChild(
                createElement(
                    "span",
                    null,
                    metaParts.join(
                        " · "
                    )
                )
            );
        }

        values.appendChild(
            value
        );
    }

    return values;
}


function electedStateCard(
    scope,
    candidates
) {
    const card =
        createElement(
            "article",
            "elected-state-card"
        );

    card.append(
        createElement(
            "h4",
            null,
            scopeName(scope)
        ),
        electedCandidateList(
            candidates
        )
    );

    return card;
}


function renderOfficeResultGrid({
    groups,
    field,
    gridId,
    emptyId,
    countId
}) {
    const grid =
        document.getElementById(
            gridId
        );

    const empty =
        document.getElementById(
            emptyId
        );

    const count =
        document.getElementById(
            countId
        );

    if (
        !grid
        || !empty
        || !count
    ) {
        return;
    }

    const defined =
        groups.filter(
            ([, state]) =>
                state[field]
                    .length > 0
        );

    grid.innerHTML = "";

    count.textContent =
        defined.length
        + " "
        + (
            defined.length === 1
                ? "UF"
                : "UFs"
        );

    empty.hidden =
        defined.length > 0;

    for (
        const [
            scope,
            state
        ]
        of defined
    ) {
        grid.appendChild(
            electedStateCard(
                scope,
                state[field]
            )
        );
    }
}


function renderElectedByState() {
    const groups =
        electedStateGroups();

    renderOfficeResultGrid({
        groups,
        field: "governors",
        gridId: "governor-results-grid",
        emptyId: "governor-results-empty",
        countId: "governor-results-count"
    });

    renderOfficeResultGrid({
        groups,
        field: "senators",
        gridId: "senate-results-grid",
        emptyId: "senate-results-empty",
        countId: "senate-results-count"
    });
}

async function loadAlerts(base = activeDataBase, apply = true) {
    const response =
        await dataFetch(
            `${base}/alerts.json`,
            {
                cache: "no-store"
            }
        );

    if (
        response.status
        === 404
    ) {
        if (apply) alerts = [];
        return [];
    }

    if (!response.ok) {
        throw new Error(
            "Alerts HTTP "
            + response.status
        );
    }

    const payload =
        await response.json();

    const nextAlerts =
        Array.isArray(
            payload.alerts
        )
            ? payload.alerts
            : [];

    if (apply) alerts = nextAlerts;
    return nextAlerts;
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

    url.searchParams.set("turno", String(SELECTED_ROUND));
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


function awaitingSecondRoundCount(result = currentResult) {
    return result?.election?.round === 2 && result?.snapshot?.sections?.totalized === 0;
}

function renderSummary() {

    const data =
        currentResult;
    const awaiting = awaitingSecondRoundCount(data);

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
        awaiting ? "Aguardando apuração" : `${formatPercentage(
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
        awaiting ? "Aguardando apuração" : `${formatPercentage(
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


function seatGroupTitle(group) {
    const parties =
        Array.isArray(
            group.parties
        )
            ? group.parties
            : [];

    if (
        group.type === "i"
        && parties.length === 1
    ) {
        return (
            parties[0].acronym
            || group.name
            || "Partido"
        );
    }

    return (
        group.name
        || (
            parties
                .map(
                    party =>
                        party.acronym
                )
                .filter(Boolean)
                .join(" / ")
        )
        || "Agregação"
    );
}


function seatGroupDetail(group) {
    const parties =
        Array.isArray(
            group.parties
        )
            ? group.parties
            : [];

    const acronyms =
        parties
            .map(
                party =>
                    party.acronym
            )
            .filter(Boolean)
            .join(" / ");

    if (group.type === "f") {
        return acronyms
            ? `Federação · ${acronyms}`
            : "Federação";
    }

    if (group.type === "c") {
        return acronyms
            ? `Coligação · ${acronyms}`
            : "Coligação";
    }

    if (
        group.type === "i"
        && parties.length === 1
    ) {
        return (
            parties[0].name
            || "Partido isolado"
        );
    }

    return (
        group.composition
        || acronyms
        || "Partido/federação"
    );
}


function candidateIsOfficiallyElected(
    candidate
) {
    if (
        candidate.elected
        === true
    ) {
        return true;
    }

    const status =
        String(
            candidate.result_status
            ?? ""
        )
            .trim()
            .toLocaleLowerCase(
                "pt-BR"
            );

    return (
        status === "eleito"
        || status.startsWith(
            "eleito por "
        )
    );
}


function allocationCandidateMatches(
    group,
    candidate
) {
    const parties =
        Array.isArray(
            group.parties
        )
            ? group.parties
            : [];

    const partyAcronyms =
        new Set(
            parties
                .map(
                    party =>
                        String(
                            party.acronym
                            ?? ""
                        )
                        .trim()
                        .toUpperCase()
                )
                .filter(Boolean)
        );

    const candidateParty =
        String(
            candidate.party_acronym
            ?? ""
        )
            .trim()
            .toUpperCase();

    if (
        candidateParty
        && partyAcronyms.has(
            candidateParty
        )
    ) {
        return true;
    }

    const groupName =
        String(
            group.name
            ?? ""
        )
            .trim()
            .toLocaleLowerCase(
                "pt-BR"
            );

    const candidateAlliance =
        String(
            candidate.alliance_name
            ?? ""
        )
            .trim()
            .toLocaleLowerCase(
                "pt-BR"
            );

    return (
        groupName
        && candidateAlliance
        && groupName
            === candidateAlliance
    );
}


function electedCandidatesForGroup(
    group
) {
    const candidates =
        Array.isArray(
            currentResult
                ?.candidates
        )
            ? currentResult
                .candidates
            : [];

    return candidates
        .filter(
            candidate =>
                allocationCandidateMatches(
                    group,
                    candidate
                )
                &&
                candidateIsOfficiallyElected(
                    candidate
                )
        )
        .sort(
            (a, b) =>
                (b.votes ?? 0)
                -
                (a.votes ?? 0)
        );
}


function renderSeatAllocation() {
    const section =
        document.getElementById(
            "seat-allocation"
        );

    const grid =
        document.getElementById(
            "seat-allocation-grid"
        );

    const empty =
        document.getElementById(
            "seat-allocation-empty"
        );

    const summary =
        document.getElementById(
            "seat-allocation-summary"
        );

    if (
        !section
        || !grid
        || !empty
        || !summary
    ) {
        return;
    }

    const officeCode =
        Number(
            currentResult
                ?.office
                ?.code
        );

    if (
        !PROPORTIONAL_OFFICES
            .has(officeCode)
    ) {
        section.hidden = true;
        grid.innerHTML = "";
        return;
    }

    section.hidden = false;
    grid.innerHTML = "";

    const allocations =
        Array.isArray(
            currentResult
                ?.office
                ?.seat_allocations
        )
            ? currentResult
                .office
                .seat_allocations
            : [];

    const groups =
        allocations
            .filter(
                item =>
                    Number(
                        item.seats
                        ?? 0
                    ) > 0
            )
            .sort(
                (a, b) =>
                    Number(
                        b.seats
                        ?? 0
                    )
                    -
                    Number(
                        a.seats
                        ?? 0
                    )
                    ||
                    seatGroupTitle(a)
                        .localeCompare(
                            seatGroupTitle(b),
                            "pt-BR"
                        )
            );

    const allocated =
        groups.reduce(
            (total, item) =>
                total
                + Number(
                    item.seats
                    ?? 0
                ),
            0
        );

    const totalSeats =
        Number(
            currentResult
                ?.office
                ?.seats
            ?? 0
        );

    summary.textContent =
        totalSeats > 0
            ? `${allocated} de ${totalSeats} vagas atribuídas`
            : `${allocated} vagas atribuídas`;

    empty.hidden =
        groups.length > 0;

    if (!groups.length) {
        return;
    }

    for (const group of groups) {
        const card =
            createElement(
                "article",
                "seat-allocation-card"
            );

        const identity =
            createElement(
                "div",
                "seat-allocation-identity"
            );

        identity.append(
            createElement(
                "strong",
                null,
                seatGroupTitle(group)
            ),
            createElement(
                "span",
                null,
                seatGroupDetail(group)
            )
        );

        const seats =
            Number(
                group.seats
                ?? 0
            );

        const value =
            createElement(
                "strong",
                "seat-allocation-value",
                `${formatNumber(seats)} ${
                    seats === 1
                        ? "vaga"
                        : "vagas"
                }`
            );

        const elected =
            electedCandidatesForGroup(
                group
            );

        const electedBlock =
            createElement(
                "div",
                "seat-allocation-elected"
            );

        const electedTitle =
            createElement(
                "span",
                "seat-allocation-elected-title",
                "Eleitos pelo TSE"
            );

        electedBlock.appendChild(
            electedTitle
        );

        if (!elected.length) {
            electedBlock.appendChild(
                createElement(
                    "span",
                    "seat-allocation-elected-pending",
                    "Nenhum nome definido até o momento"
                )
            );
        } else {
            for (
                const candidate
                of elected
            ) {
                const item =
                    createElement(
                        "div",
                        "seat-allocation-elected-candidate"
                    );

                const name =
                    createElement(
                        "strong",
                        null,
                        candidate.ballot_name
                        || candidate.name
                    );

                const status =
                    createElement(
                        "span",
                        null,
                        candidate.result_status
                        || "Eleito"
                    );

                item.append(
                    name,
                    status
                );

                electedBlock.appendChild(
                    item
                );
            }
        }

        const expectedSeats =
            Number(
                group.seats
                ?? 0
            );

        const defined =
            elected.length;

        const definedLabel =
            createElement(
                "span",
                "seat-allocation-defined",
                `${defined} de ${expectedSeats} nomes definidos`
            );

        electedBlock.appendChild(
            definedLabel
        );

        card.append(
            identity,
            value,
            electedBlock
        );

        grid.appendChild(card);
    }
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

    const awaiting = awaitingSecondRoundCount();
    if (card.style && typeof card.style.setProperty === "function" && window.ElectionPortal) {
        card.style.setProperty("--candidate-color", window.ElectionPortal.candidateColor(candidate.ballot_number));
    }
    const positionElement =
        createElement(
            "div",
            "position",
            awaiting ? "—" : String(position)
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
        "Adicionar ou remover " + (candidate.ballot_name || candidate.name) + " dos favoritos"
    );
    favoriteButton.setAttribute("aria-pressed", String(window.Favorites.isFavorite(favoriteRef)));

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
            favoriteButton.setAttribute("aria-pressed", String(selected));
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
        awaiting || candidate.result_status
    ) {
        main.appendChild(
            createElement(
                "div",
                "candidate-status",
                awaiting ? "Aguardando apuração" : candidate.result_status
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
            awaiting ? "—" : candidate.votes == null ? "Não informado" : formatNumber(
                candidate.votes
            )
        );

    const votesLabel =
        createElement(
            "span",
            null,
            awaiting ? " votos ainda não apurados" : " votos"
        );

    const percentage =
        createElement(
            "div",
            "vote-percentage",
            awaiting ? "—" : candidate.vote_percentage == null ? "Não informado" : `${
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

    if (majorOffice && !awaiting) {

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
    if (!currentResult) return;

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

    if (typeof document.dispatchEvent === "function" && typeof CustomEvent === "function") {
        document.dispatchEvent(new CustomEvent("election:results"));
    }

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


function showResultState(state, retry = () => { void loadSelectedResult(); }) {
    clearRefreshNotice();
    resultState = state;
    currentResult = null;
    allCandidates = [];
    filteredCandidates = [];
    currentPage = 1;
    const message = state === "error" ? "Não foi possível carregar os resultados desta seleção." : "Carregando os resultados desta seleção…";
    const labels = {"location-summary": selectedScope ? scopeName(selectedScope) : "—",
        "office-summary": manifest?.results?.find(item => item.scope === selectedScope && item.office === selectedOffice)?.office_name || "—",
        "sections-summary": state === "error" ? "Dados indisponíveis" : "Carregando…",
        "candidate-count-summary": "—", "progress-label": "—", "updated-at": message,
        "page-title": selectedScope ? `${scopeName(selectedScope)} · Resultados` : "Resultados"};
    for (const [id, value] of Object.entries(labels)) {
        const node = document.getElementById(id);
        if (node) node.textContent = value;
    }
    const progress = document.getElementById("progress-bar");
    if (progress) progress.style.width = "0%";
    const track = document.getElementById("sections-progress");
    track?.removeAttribute("aria-valuenow");
    track?.setAttribute("aria-valuetext", message);
    const search = document.getElementById("search");
    if (search) { search.value = ""; search.disabled = true; }
    const download = document.getElementById("download-results");
    if (download) download.disabled = true;
    for (const id of ["results-table", "pagination"]) {
        const node = document.getElementById(id);
        if (node) node.replaceChildren();
    }
    const table = document.getElementById("results-table");
    if (table) table.hidden = true;
    renderSeatAllocation();
    const root = document.getElementById("results");
    if (root) {
        root.hidden = false;
        root.setAttribute("aria-busy", String(state === "loading"));
        const notice = createElement("div", state === "error" ? "error" : "skeleton", message);
        if (state === "error") {
            const button = createElement("button", "text-button", "Tentar novamente");
            button.type = "button";
            button.addEventListener("click", retry);
            notice.appendChild(button);
        }
        root.replaceChildren(notice);
    }
    announcePortalContext();
}

async function readSelectedResult({scope, office, sourceManifest, base}) {
    const item = sourceManifest?.results?.find(row => row.scope === scope && row.office === office);
    if (!item) throw new Error("Resultado não encontrado no manifest.");
    const response = await dataFetch(`${base}/${item.path}`, {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const nextResult = await response.json();
    if (window.PortalBridge) window.PortalBridge.validateResult(nextResult, item, SELECTED_ROUND, sourceManifest.environment);
    return nextResult;
}

function applySelectedResult(nextResult) {
    clearRefreshNotice();
    currentResult = nextResult;
    resultState = "ready";

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
    document.getElementById("search").disabled = false;
    const download = document.getElementById("download-results");
    if (download) download.disabled = false;

    renderSummary();
    renderSeatAllocation();
    renderResults();
    document.getElementById("results")?.setAttribute("aria-busy", "false");
    announcePortalContext();
}

async function loadSelectedResult(stagedPublication = null) {
    // Refresh reads a complete candidate publication without changing the visible selection.
    if (stagedPublication) return readSelectedResult(stagedPublication);
    const requestNumber = ++resultRequestNumber;
    const request = {scope: selectedScope, office: selectedOffice, sourceManifest: manifest, base: activeDataBase};
    const isCurrent = () => requestNumber === resultRequestNumber && request.scope === selectedScope
        && request.office === selectedOffice && request.base === activeDataBase && request.sourceManifest === manifest;
    showResultState("loading");
    try {
        const nextResult = await readSelectedResult(request);
        if (!isCurrent()) return false;
        applySelectedResult(nextResult);
        return true;
    } catch (error) {
        if (!isCurrent()) return false;
        console.error("Result read failed:", error);
        showResultState("error");
        return false;
    } finally {
        if (isCurrent()) document.getElementById("results")?.setAttribute("aria-busy", "false");
    }
}


function publicationToken(
    version
) {
    return [
        version.environment,
        version.generated_at,
        version.snapshot_id || "",
        version.activation_revision || ""
    ].join(":");
}


async function loadVersion() {
    const response =
        await dataFetch(
            VERSION_URL,
            {
                cache: "no-store"
            }
        );

    if (!response.ok) {
        const error = new Error(
            `Version HTTP ${
                response.status
            }`
        );
        error.publicationMissing = response.status === 404;
        throw error;
    }

    const version = await response.json();
    if (SELECTED_ROUND === 2 && (version.environment !== "oficial" || version.round !== 2
        || typeof version.snapshot_id !== "string" || !/^[a-f0-9]{64}$/.test(version.snapshot_id))) {
        throw new Error("second_round_marker_not_official");
    }
    return version;
}


async function loadManifest(base = activeDataBase, apply = true) {

    const response =
        await dataFetch(
            `${base}/manifest.json`,
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

    const nextManifest = await response.json();
    if (window.PortalBridge) window.PortalBridge.validateManifest(nextManifest, SELECTED_ROUND);
    if (SELECTED_ROUND === 2 && (nextManifest.environment !== "oficial"
        || !Array.isArray(nextManifest.results) || !nextManifest.results.length
        || nextManifest.results.some(row => Number(row.round) !== 2))) {
        throw new Error("second_round_not_official");
    }
    if (!apply) return nextManifest;
    manifest = nextManifest;
    renderRoundGuide();
    return manifest;
}

function renderRoundGuide() {
    // Only announce a second-round dataset when it is actually present.
    const guideTitle = document.getElementById("round-guide-title");
    const guideDescription = document.getElementById("round-guide-description");
    if (guideTitle && guideDescription) {
        const results = Array.isArray(manifest?.results) ? manifest.results : [];
        const rounds = new Set(results.map(item => Number(item.round)));
        if (rounds.has(2) && manifest.publication_phase === "candidate_roster") {
            guideTitle.textContent = "Candidatos do 2º turno";
            guideDescription.textContent = "Candidaturas divulgadas oficialmente pelo TSE. Aguardando o início da apuração; votos e percentuais serão atualizados automaticamente.";
        } else if (rounds.has(2)) {
            guideTitle.textContent = "Dados do 2º turno disponíveis";
            guideDescription.textContent =
                "O conjunto publicado pelo TSE inclui resultados do segundo turno. Consulte a localidade e o cargo para acompanhar a apuração.";
        } else {
            guideTitle.textContent = "Preparado para o 2º turno";
            guideDescription.textContent =
                "O portal continuará acompanhando as publicações oficiais. Dados do segundo turno serão identificados quando disponíveis, sem projeções.";
        }
    }
}
function clearRefreshNotice() {
    const notice = document.getElementById("publication-update-status");
    if (notice) { notice.hidden = true; notice.replaceChildren(); }
}

function showRefreshFailure() {
    const notice = document.getElementById("publication-update-status");
    if (!notice) return;
    const message = createElement("span", null, "Não foi possível verificar a atualização. Exibindo a publicação anterior, já conferida. ");
    const retry = createElement("button", "text-button", "Tentar novamente");
    retry.type = "button";
    retry.addEventListener("click", async () => {
        retry.disabled = true;
        try { await refreshIfChanged(); }
        finally { retry.disabled = false; }
    });
    notice.replaceChildren(message, retry);
    notice.hidden = false;
}

async function refreshIfChanged() {

    if (portalRefreshPending || document.hidden || (window.LiveData
        && (window.LiveData.paused(ROUND_DATA_ROOT) || !window.LiveData.shouldPoll(activeDataBase, ROUND_DATA_ROOT)))) return;
    const previous = {manifest, alerts, base: activeDataBase, marker: portalMarker, result: currentResult,
        scope: selectedScope, office: selectedOffice, requestNumber: resultRequestNumber, status: resultState};
    // Serialize the marker request too: slow reads must not start competing refreshes.
    portalRefreshPending = true;

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
            clearRefreshNotice();
            return;
        }

        const candidateBase = dataBaseForVersion(version);
        const [nextManifest, nextAlerts] = await Promise.all([
            loadManifest(candidateBase, false),
            loadAlerts(candidateBase, false)
        ]);
        const nextResult = await loadSelectedResult({scope: previous.scope, office: previous.office,
            sourceManifest: nextManifest, base: candidateBase});
        if (previous.requestNumber !== resultRequestNumber || previous.scope !== selectedScope
            || previous.office !== selectedOffice || previous.result !== currentResult || previous.status !== resultState) return;

        manifest = nextManifest;
        alerts = nextAlerts;
        activeDataBase = candidateBase;
        portalMarker = version;

        renderRoundGuide();
        renderElectedByState();
        renderScopeSelector();

        renderOfficeTabs();
        ++resultRequestNumber;
        applySelectedResult(nextResult);

        // A failed result read must leave the publication token retryable.
        publishedVersion = nextVersion;
        window.Favorites.setManifest(manifest, publishedVersion, activeDataBase);
    } catch (error) {
        // Only publication metadata belongs to this transaction; navigation never rolls back.
        manifest = previous.manifest;
        alerts = previous.alerts;
        activeDataBase = previous.base;
        portalMarker = previous.marker;
        if (previous.requestNumber === resultRequestNumber && previous.scope === selectedScope
            && previous.office === selectedOffice && previous.result && previous.result === currentResult
            && resultState === "ready") showRefreshFailure();
        console.error(
            "Refresh failed:",
            error
        );
    } finally {
        portalRefreshPending = false;
    }
}
async function initialize() {
    document.getElementById("round-first")?.setAttribute("aria-current", SELECTED_ROUND === 1 ? "page" : "false");
    document.getElementById("round-second")?.setAttribute("aria-current", SELECTED_ROUND === 2 ? "page" : "false");

    if (SELECTED_ROUND === 2) {
        // Never fall back to /data (round one). Round two has a separate,
        // explicitly published pointer and must advertise round=2 itself.
        try {
            const candidateVersion = await loadVersion();
            const candidateBase = dataBaseForVersion(candidateVersion);
            const candidateResponse = await dataFetch(candidateBase + "/manifest.json", {cache:"no-store"});
            if (!candidateResponse.ok) throw new Error("second_round_manifest_unavailable");
            const candidateManifest = await candidateResponse.json();
            if (!Array.isArray(candidateManifest.results)
                || !candidateManifest.results.length
                || candidateManifest.results.some(row => Number(row.round) !== 2)
                || candidateManifest.environment !== "oficial") {
                throw new Error("second_round_not_official");
            }
        } catch (error) {
            if (!error.publicationMissing) {
                document.body.classList.remove("round-two-unavailable");
                document.getElementById("round-unavailable").hidden = true;
                if (roundTwoWaitingTimer) {
                    clearInterval(roundTwoWaitingTimer);
                    roundTwoWaitingTimer = null;
                }
                throw error;
            }
            document.body.classList.add("round-two-unavailable");
            document.getElementById("round-unavailable").hidden = false;
            document.getElementById("environment-badge").textContent = "Aguardando dados oficiais";
            if (!roundTwoWaitingTimer) {
                roundTwoWaitingTimer = setInterval(async () => {
                    if (roundTwoRetryPending || document.hidden || (window.LiveData
                        && (window.LiveData.paused(ROUND_DATA_ROOT) || !window.LiveData.shouldPoll(activeDataBase, ROUND_DATA_ROOT)))) return;
                    roundTwoRetryPending = true;
                    try { await initialize(); }
                    catch (retryError) { initializationFailed(retryError); }
                    finally { roundTwoRetryPending = false; }
                }, REFRESH_MS);
            }
            return;
        }
    }

    const version =
        await loadVersion();

    activeDataBase = dataBaseForVersion(version);
    portalMarker = version;
    await Promise.all([
        loadManifest(),
        loadAlerts()
    ]);

    publishedVersion =
        publicationToken(
            version
        );

    window.Favorites.setManifest(
        manifest,
        publishedVersion,
        activeDataBase
    );

    selectInitialRoute();

    renderEnvironment();
    renderElectedByState();
    renderScopeSelector();
    renderOfficeTabs();

    updateUrl();

    await loadSelectedResult();

    if (roundTwoWaitingTimer) {
        clearInterval(roundTwoWaitingTimer);
        roundTwoWaitingTimer = null;
    }
    document.body.classList.remove("round-two-unavailable");
    document.getElementById("round-unavailable").hidden = true;

    setInterval(
        refreshIfChanged,
        REFRESH_MS
    );
}


if (window.PortalBridge) window.PortalBridge.install({
    getContext: portalContext,
    scopeName,
    getCandidates: () => filteredCandidates.slice(),
    getResultPage: () => {
        const size = [1, 3, 5].includes(selectedOffice) ? 50 : PAGE_SIZE;
        return {candidates: filteredCandidates.slice((currentPage - 1) * size, currentPage * size),
            total: filteredCandidates.length, page: currentPage, pageSize: size};
    },
    async selectScope(scope, office = 1) {
        if (!manifest) return false;
        const rows = getResultsForScope(scope);
        const item = rows.find(row => Number(row.office) === Number(office));
        if (!item) return false;
        selectedScope = scope;
        selectedOffice = Number(office);
        currentPage = 1;
        renderScopeSelector();
        renderOfficeTabs();
        updateUrl();
        return loadSelectedResult();
    },
    setCandidate(number) {
        selectedPresidentialCandidate = number == null ? "" : String(number);
        const url = new URL(window.location.href);
        if (selectedPresidentialCandidate) url.searchParams.set("candidate", selectedPresidentialCandidate);
        else url.searchParams.delete("candidate");
        history.replaceState({}, "", url);
        announcePortalContext();
    }
});

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


function initializationFailed(error) {
    console.error(error);
    ++resultRequestNumber;
    showResultState("error", () => {
        if (initializationRetryPending) return;
        initializationRetryPending = true;
        showResultState("loading");
        void initialize().catch(initializationFailed).finally(() => { initializationRetryPending = false; });
    });
}

initialize().catch(initializationFailed);
