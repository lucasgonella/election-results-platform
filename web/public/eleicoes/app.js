const VERSION_URL =
    "/data/version.json";

const MANIFEST_URL =
    "/data/manifest.json";

const ALERTS_URL =
    "/data/alerts.json";

const REFRESH_MS = 5000;

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

        if (
            alertKind(item)
                !== "elected"
            || !SCOPE_NAMES[scope]
            || scope === "br"
            || scope === "zz"
            || ![3, 5].includes(office)
            || !item.candidate_name
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
            );

        if (
            target.some(
                candidate =>
                    String(
                        candidate.candidate_id
                        ?? candidate.candidate_name
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


function electedOfficeRow(
    label,
    candidates
) {
    const row =
        createElement(
            "div",
            "elected-state-office"
        );

    const officeLabel =
        createElement(
            "span",
            "elected-state-office-label",
            label
        );

    const values =
        createElement(
            "div",
            "elected-state-office-values"
        );

    if (!candidates.length) {
        values.appendChild(
            createElement(
                "span",
                "elected-state-pending",
                "Aguardando definição do TSE"
            )
        );
    } else {
        for (
            const candidate
            of candidates
        ) {
            const value =
                createElement(
                    "div",
                    "elected-state-candidate"
                );

            value.appendChild(
                createElement(
                    "strong",
                    null,
                    candidate.candidate_name
                )
            );

            if (
                candidate.party_acronym
            ) {
                value.appendChild(
                    createElement(
                        "span",
                        null,
                        candidate.party_acronym
                    )
                );
            }

            values.appendChild(
                value
            );
        }
    }

    row.append(
        officeLabel,
        values
    );

    return row;
}


function renderElectedByState() {
    const grid =
        document.getElementById(
            "elected-by-state-grid"
        );

    const empty =
        document.getElementById(
            "elected-by-state-empty"
        );

    const count =
        document.getElementById(
            "elected-by-state-count"
        );

    if (
        !grid
        || !empty
        || !count
    ) {
        return;
    }

    const groups =
        electedStateGroups();

    grid.innerHTML = "";

    count.textContent =
        groups.length
        + " "
        + (
            groups.length === 1
                ? "UF com resultado definido"
                : "UFs com resultado definido"
        );

    empty.hidden =
        groups.length > 0;

    for (
        const [
            scope,
            state
        ]
        of groups
    ) {
        const card =
            createElement(
                "article",
                "elected-state-card"
            );

        const title =
            createElement(
                "h3",
                null,
                scopeName(scope)
            );

        card.append(
            title,
            electedOfficeRow(
                "Governador",
                state.governors
            ),
            electedOfficeRow(
                "Senado",
                state.senators
            )
        );

        grid.appendChild(card);
    }
}


function renderElectedAlerts() {
    const container =
        document.getElementById(
            "elected-alerts"
        );

    if (!container) {
        return;
    }

    if (!alerts.length) {
        container.hidden = true;
        container.innerHTML = "";
        return;
    }

    container.hidden = false;
    container.innerHTML = "";

    const header =
        createElement(
            "div",
            "elected-alerts-header"
        );

    const title =
        createElement(
            "strong",
            null,
            "Resultados definidos pelo TSE"
        );

    const source =
        createElement(
            "span",
            null,
            "Avisos exibidos somente quando o dado oficial define eleição ou classificação para o 2º turno."
        );

    header.append(
        title,
        source
    );

    const list =
        createElement(
            "div",
            "elected-alerts-list"
        );

    const visible =
        alerts.slice(
            0,
            4
        );

    for (
        const item
        of visible
    ) {
        const card =
            createElement(
                "div",
                "elected-alert"
            );

        const context =
            createElement(
                "span",
                "elected-alert-context",
                scopeName(
                    item.scope
                )
                + " · "
                + item.office_name
            );

        const candidate =
            createElement(
                "strong",
                "elected-alert-candidate",
                item.candidate_name
            );

        const secondRound =
            alertKind(item)
            === "second_round";

        const resultText =
            secondRound
                ? "Classificado(a) para o 2º turno segundo o dado publicado pelo TSE"
                : "Eleito(a) segundo o dado publicado pelo TSE";

        const detail =
            createElement(
                "span",
                "elected-alert-detail",
                (
                    item.party_acronym
                    || "Partido não informado"
                )
                + " · "
                + resultText
            );

        card.append(
            context,
            candidate,
            detail
        );

        list.appendChild(
            card
        );
    }

    if (
        alerts.length
        > visible.length
    ) {
        list.appendChild(
            createElement(
                "div",
                "elected-alert-more",
                "+"
                + (
                    alerts.length
                    - visible.length
                )
                + " outros resultados definidos"
            )
        );
    }

    container.append(
        header,
        list
    );
}


async function loadAlerts() {
    const response =
        await fetch(
            ALERTS_URL,
            {
                cache: "no-store"
            }
        );

    if (
        response.status
        === 404
    ) {
        alerts = [];
        return alerts;
    }

    if (!response.ok) {
        throw new Error(
            "Alerts HTTP "
            + response.status
        );
    }

    const payload =
        await response.json();

    alerts =
        Array.isArray(
            payload.alerts
        )
            ? payload.alerts
            : [];

    return alerts;
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
    renderSeatAllocation();
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

        await Promise.all([
            loadManifest(),
            loadAlerts()
        ]);

        renderElectedAlerts();
        renderElectedByState();

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
        publishedVersion
    );

    selectInitialRoute();

    renderEnvironment();
    renderElectedAlerts();
    renderElectedByState();
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