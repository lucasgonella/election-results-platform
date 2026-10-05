const MANIFEST_URL =
    "/data/manifest.json";

const ALERTS_URL =
    "/data/alerts.json";

const CAMERA_TOTAL = 513;
const SENATE_TOTAL = 81;
const SENATE_ELECTED_2026 = 54;

const CAMERA_CURRENT = {
    "PL": 98,
    "PT": 65,
    "UNIAO": 52,
    "PSD": 48,
    "PP": 46,
    "REPUBLICANOS": 42,
    "MDB": 38,
    "PODE": 27,
    "PSB": 17,
    "PSDB": 15,
    "PSOL": 13,
    "PCDOB": 11,
    "PDT": 10,
    "PV": 6,
    "AVANTE": 5,
    "NOVO": 5,
    "CIDADANIA": 4,
    "SOLIDARIEDADE": 4,
    "PRD": 3,
    "REDE": 3,
    "MISSAO": 1
};

const SENATE_CURRENT = {
    "AVANTE": 1,
    "MDB": 9,
    "PDT": 2,
    "PL": 15,
    "PODE": 3,
    "PP": 8,
    "PSB": 6,
    "PSDB": 4,
    "PSD": 14,
    "PT": 9,
    "REPUBLICANOS": 6,
    "S/PARTIDO": 1,
    "UNIAO": 3
};

/*
 * Mandatos 2023-2031, já considerando as substituições
 * definidas no primeiro turno de 2026:
 * - Sergio Moro (PL) -> Luis Felipe Cunha (UNIÃO)
 * - Cleitinho (REPUBLICANOS) -> Alex Diniz (PL)
 */
const SENATE_HOLDOVER_2027 = {
    "MDB": 1,
    "PL": 9,
    "PP": 3,
    "PSB": 1,
    "PSD": 3,
    "PT": 3,
    "REPUBLICANOS": 3,
    "S/PARTIDO": 1,
    "UNIAO": 3
};

const LABELS = {
    "PCDOB": "PCdoB",
    "MISSAO": "MISSÃO",
    "S/PARTIDO": "Sem partido",
    "UNIAO": "UNIÃO",
    "PENDENTE": "Pendente"
};

const COLORS = {
    "PSD": "#a5ad31",
    "REPUBLICANOS": "#5c7180",
    "MDB": "#58a37b",
    "PODE": "#735fa7",
    "PL": "#32326f",
    "PSB": "#df702d",
    "PDT": "#324f82",
    "AVANTE": "#7eaf98",
    "SOLIDARIEDADE": "#bd826d",
    "PRD": "#9c83be",
    "NOVO": "#eb7b25",
    "MISSAO": "#29384f",
    "PP": "#4f9e87",
    "PSDB": "#4492b6",
    "CIDADANIA": "#68a6bd",
    "PT": "#cf4141",
    "PCDOB": "#b93232",
    "PV": "#4f9a55",
    "PSOL": "#c43b59",
    "REDE": "#6ca98a",
    "UNIAO": "#55a897",
    "S/PARTIDO": "#555b62",
    "PENDENTE": "#d8dce2"
};

function normalized(value) {
    return String(
        value ?? ""
    )
        .normalize("NFD")
        .replace(
            /[\u0300-\u036f]/g,
            ""
        )
        .trim()
        .toUpperCase();
}

function displayLabel(key) {
    return (
        LABELS[key]
        || key
    );
}

function colorFor(key) {
    if (COLORS[key]) {
        return COLORS[key];
    }

    let hash = 0;

    for (
        const char
        of String(key)
    ) {
        hash =
            (
                hash * 31
                + char.charCodeAt(0)
            )
            >>> 0;
    }

    const hue =
        hash % 360;

    return `hsl(${hue} 42% 48%)`;
}

function addCount(
    target,
    key,
    value
) {
    const amount =
        Number(value ?? 0);

    if (
        !key
        || !Number.isFinite(amount)
        || amount <= 0
    ) {
        return;
    }

    target[key] =
        (
            target[key]
            || 0
        )
        + amount;
}

function sumComposition(
    composition
) {
    return Object.values(
        composition
    ).reduce(
        (sum, value) =>
            sum + Number(value || 0),
        0
    );
}

function sortedComposition(
    composition
) {
    return Object.entries(
        composition
    )
        .filter(
            ([, seats]) =>
                Number(seats) > 0
        )
        .sort(
            (a, b) =>
                Number(b[1])
                - Number(a[1])
                ||
                displayLabel(a[0])
                    .localeCompare(
                        displayLabel(b[0]),
                        "pt-BR"
                    )
        );
}

function seatPositions(
    total,
    rows
) {
    const centerX = 310;
    const centerY = 296;

    const inner = 92;
    const outer = 286;

    const radii =
        Array.from(
            {length: rows},
            (_, index) =>
                inner
                + (
                    (
                        outer - inner
                    )
                    * index
                    / Math.max(
                        rows - 1,
                        1
                    )
                )
        );

    const weightTotal =
        radii.reduce(
            (sum, value) =>
                sum + value,
            0
        );

    const raw =
        radii.map(
            radius =>
                total
                * radius
                / weightTotal
        );

    const counts =
        raw.map(
            value =>
                Math.max(
                    1,
                    Math.floor(value)
                )
        );

    let assigned =
        counts.reduce(
            (sum, value) =>
                sum + value,
            0
        );

    const order =
        raw
            .map(
                (value, index) => ({
                    index,
                    fraction:
                        value
                        - Math.floor(value)
                })
            )
            .sort(
                (a, b) =>
                    b.fraction
                    - a.fraction
            );

    let cursor = 0;

    while (assigned < total) {
        counts[
            order[
                cursor
                % order.length
            ].index
        ] += 1;

        assigned += 1;
        cursor += 1;
    }

    while (assigned > total) {
        const index =
            order[
                cursor
                % order.length
            ].index;

        if (counts[index] > 1) {
            counts[index] -= 1;
            assigned -= 1;
        }

        cursor += 1;
    }

    const positions = [];

    radii.forEach(
        (radius, row) => {
            const count =
                counts[row];

            const start =
                Math.PI * 1.04;

            const end =
                -Math.PI * .04;

            for (
                let index = 0;
                index < count;
                index += 1
            ) {
                const ratio =
                    count === 1
                        ? .5
                        : (
                            index
                            / (
                                count - 1
                            )
                        );

                const angle =
                    start
                    + (
                        end - start
                    )
                    * ratio;

                positions.push({
                    x:
                        centerX
                        + radius
                        * Math.cos(angle),
                    y:
                        centerY
                        - radius
                        * Math.sin(angle),
                    angle
                });
            }
        }
    );

    return positions.sort(
        (a, b) =>
            b.angle - a.angle
    );
}

function seatKeys(
    composition,
    total
) {
    const keys = [];

    for (
        const [key, seats]
        of sortedComposition(
            composition
        )
    ) {
        for (
            let index = 0;
            index < seats;
            index += 1
        ) {
            keys.push(key);
        }
    }

    while (
        keys.length < total
    ) {
        keys.push("PENDENTE");
    }

    return keys.slice(
        0,
        total
    );
}

function renderHemicycle(
    elementId,
    composition,
    total,
    rows
) {
    const container =
        document.getElementById(
            elementId
        );

    if (!container) {
        return;
    }

    const namespace =
        "http://www.w3.org/2000/svg";

    const svg =
        document.createElementNS(
            namespace,
            "svg"
        );

    svg.setAttribute(
        "viewBox",
        "0 0 620 330"
    );

    svg.setAttribute(
        "role",
        "img"
    );

    svg.setAttribute(
        "aria-label",
        `Distribuição de ${total} cadeiras`
    );

    const positions =
        seatPositions(
            total,
            rows
        );

    const keys =
        seatKeys(
            composition,
            total
        );

    const radius =
        total > 100
            ? 4.1
            : 7.1;

    positions.forEach(
        (position, index) => {
            const key =
                keys[index];

            const circle =
                document.createElementNS(
                    namespace,
                    "circle"
                );

            circle.setAttribute(
                "cx",
                position.x
            );

            circle.setAttribute(
                "cy",
                position.y
            );

            circle.setAttribute(
                "r",
                radius
            );

            circle.setAttribute(
                "fill",
                colorFor(key)
            );

            circle.setAttribute(
                "class",
                "hemicycle-seat"
            );

            const title =
                document.createElementNS(
                    namespace,
                    "title"
                );

            title.textContent =
                displayLabel(key);

            circle.appendChild(
                title
            );

            svg.appendChild(
                circle
            );
        }
    );

    const value =
        document.createElementNS(
            namespace,
            "text"
        );

    value.setAttribute(
        "x",
        "310"
    );

    value.setAttribute(
        "y",
        "266"
    );

    value.setAttribute(
        "class",
        "hemicycle-center-value"
    );

    value.textContent =
        total;

    const label =
        document.createElementNS(
            namespace,
            "text"
        );

    label.setAttribute(
        "x",
        "310"
    );

    label.setAttribute(
        "y",
        "286"
    );

    label.setAttribute(
        "class",
        "hemicycle-center-label"
    );

    label.textContent =
        "cadeiras";

    svg.append(
        value,
        label
    );

    container.innerHTML = "";
    container.appendChild(svg);
}

function deltaText(value) {
    if (value > 0) {
        return `+${value}`;
    }

    if (value < 0) {
        return String(value);
    }

    return "—";
}

function renderTable(
    elementId,
    current,
    future
) {
    const container =
        document.getElementById(
            elementId
        );

    if (!container) {
        return;
    }

    const keys =
        [
            ...new Set([
                ...Object.keys(current),
                ...Object.keys(future)
            ])
        ]
            .filter(
                key =>
                    key !== "PENDENTE"
            )
            .sort(
                (a, b) =>
                    (
                        Number(future[b] || 0)
                        - Number(future[a] || 0)
                    )
                    ||
                    displayLabel(a)
                        .localeCompare(
                            displayLabel(b),
                            "pt-BR"
                        )
            );

    const table =
        document.createElement(
            "table"
        );

    table.className =
        "composition-table";

    table.innerHTML =
        `
        <thead>
            <tr>
                <th>Partido</th>
                <th>Atual</th>
                <th>2027</th>
                <th>Variação</th>
            </tr>
        </thead>
        `;

    const tbody =
        document.createElement(
            "tbody"
        );

    for (const key of keys) {
        const now =
            Number(
                current[key]
                || 0
            );

        const next =
            Number(
                future[key]
                || 0
            );

        const delta =
            next - now;

        const row =
            document.createElement(
                "tr"
            );

        const deltaClass =
            delta > 0
                ? "positive"
                : (
                    delta < 0
                        ? "negative"
                        : ""
                );

        row.innerHTML =
            `
            <td>
                <div class="composition-party">
                    <span
                        class="composition-party-dot"
                        style="background:${colorFor(key)}"
                    ></span>
                    <strong>${displayLabel(key)}</strong>
                </div>
            </td>
            <td>${now}</td>
            <td><strong>${next}</strong></td>
            <td class="composition-delta ${deltaClass}">
                ${deltaText(delta)}
            </td>
            `;

        tbody.appendChild(row);
    }

    if (
        Number(
            future.PENDENTE
            || 0
        ) > 0
    ) {
        const row =
            document.createElement(
                "tr"
            );

        row.innerHTML =
            `
            <td>
                <div class="composition-party">
                    <span
                        class="composition-party-dot"
                        style="background:${colorFor("PENDENTE")}"
                    ></span>
                    <strong>Pendente</strong>
                </div>
            </td>
            <td>—</td>
            <td><strong>${future.PENDENTE}</strong></td>
            <td>—</td>
            `;

        tbody.appendChild(row);
    }

    table.appendChild(tbody);

    container.innerHTML = "";
    container.appendChild(table);
}

async function fetchJson(url) {
    const response =
        await fetch(
            url,
            {
                cache: "no-store"
            }
        );

    if (!response.ok) {
        throw new Error(
            `${url}: HTTP ${response.status}`
        );
    }

    return response.json();
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
        normalized(
            candidate.result_status
        );

    return (
        status === "ELEITO"
        || status.startsWith(
            "ELEITO POR "
        )
    );
}


async function cameraFutureComposition(
    manifest
) {
    const targets =
        manifest.results
            .filter(
                item =>
                    Number(
                        item.office
                    ) === 6
                    && item.scope !== "br"
                    && item.scope !== "zz"
            );

    const payloads =
        await Promise.all(
            targets.map(
                target =>
                    fetchJson(
                        "/data/"
                        + target.path
                    )
            )
        );

    const result = {};
    const electedIds =
        new Set();

    for (const payload of payloads) {
        const candidates =
            Array.isArray(
                payload?.candidates
            )
                ? payload.candidates
                : [];

        for (
            const candidate
            of candidates
        ) {
            if (
                !candidateIsOfficiallyElected(
                    candidate
                )
                || !candidate.party_acronym
            ) {
                continue;
            }

            const candidateId =
                String(
                    candidate
                        .tse_candidate_seq
                    ?? (
                        payload
                            ?.scope
                            ?.code
                        + ":"
                        + candidate
                            .ballot_number
                    )
                );

            if (
                electedIds.has(
                    candidateId
                )
            ) {
                continue;
            }

            electedIds.add(
                candidateId
            );

            addCount(
                result,
                normalized(
                    candidate
                        .party_acronym
                ),
                1
            );
        }
    }

    const elected =
        sumComposition(result);

    if (elected < CAMERA_TOTAL) {
        result.PENDENTE =
            CAMERA_TOTAL
            - elected;
    }

    return result;
}

function senateElectedComposition(
    alerts
) {
    const result = {};

    for (const item of alerts) {
        if (
            Number(
                item.office
            ) !== 5
            || (
                item.kind
                && item.kind !== "elected"
            )
            || !item.party_acronym
        ) {
            continue;
        }

        addCount(
            result,
            normalized(
                item.party_acronym
            ),
            1
        );
    }

    return result;
}

function governorWinner(
    alerts,
    scope,
    name
) {
    const expected =
        normalized(name);

    return alerts.some(
        item =>
            normalized(
                item.scope
            )
            === normalized(scope)
            && Number(
                item.office
            ) === 3
            && [
                "elected",
                "mathematically_elected"
            ].includes(
                item.kind
                || "elected"
            )
            && normalized(
                item.candidate_name
            )
                .includes(expected)
    );
}

function senateHoldovers(
    alerts
) {
    const result = {
        ...SENATE_HOLDOVER_2027
    };

    /*
     * Se esses senadores vencerem os governos
     * no 2º turno, seus suplentes alteram a
     * composição partidária do Senado.
     */
    if (
        governorWinner(
            alerts,
            "ac",
            "ALAN RICK"
        )
    ) {
        result.REPUBLICANOS -= 1;
        addCount(
            result,
            "PSD",
            1
        );
    }

    if (
        governorWinner(
            alerts,
            "am",
            "OMAR AZIZ"
        )
    ) {
        result.PSD -= 1;
        addCount(
            result,
            "PT",
            1
        );
    }

    return result;
}

function senateFutureComposition(
    alerts
) {
    const future =
        senateHoldovers(
            alerts
        );

    const elected =
        senateElectedComposition(
            alerts
        );

    for (
        const [key, seats]
        of Object.entries(elected)
    ) {
        addCount(
            future,
            key,
            seats
        );
    }

    const electedCount =
        sumComposition(
            elected
        );

    if (
        electedCount
        < SENATE_ELECTED_2026
    ) {
        future.PENDENTE =
            SENATE_ELECTED_2026
            - electedCount;
    }

    return {
        future,
        electedCount
    };
}

function setStatus(
    text,
    className
) {
    const status =
        document.getElementById(
            "composition-status"
        );

    status.textContent =
        text;

    status.className =
        "composition-status"
        + (
            className
                ? " " + className
                : ""
        );
}

async function initializeComposition() {
    const [
        manifest,
        alertPayload
    ] =
        await Promise.all([
            fetchJson(
                MANIFEST_URL
            ),
            fetchJson(
                ALERTS_URL
            )
        ]);

    const alerts =
        Array.isArray(
            alertPayload.alerts
        )
            ? alertPayload.alerts
            : [];

    const [
        cameraFuture,
        senate
    ] =
        await Promise.all([
            cameraFutureComposition(
                manifest
            ),
            Promise.resolve(
                senateFutureComposition(
                    alerts
                )
            )
        ]);

    const cameraDefined =
        CAMERA_TOTAL
        - Number(
            cameraFuture.PENDENTE
            || 0
        );

    const senateDefined =
        senate.electedCount;

    renderHemicycle(
        "camera-current-chart",
        CAMERA_CURRENT,
        CAMERA_TOTAL,
        13
    );

    renderHemicycle(
        "camera-future-chart",
        cameraFuture,
        CAMERA_TOTAL,
        13
    );

    renderTable(
        "camera-table",
        CAMERA_CURRENT,
        cameraFuture
    );

    renderHemicycle(
        "senate-current-chart",
        SENATE_CURRENT,
        SENATE_TOTAL,
        7
    );

    renderHemicycle(
        "senate-future-chart",
        senate.future,
        SENATE_TOTAL,
        7
    );

    renderTable(
        "senate-table",
        SENATE_CURRENT,
        senate.future
    );

    document.getElementById(
        "camera-progress"
    ).textContent =
        `${cameraDefined} de ${CAMERA_TOTAL} cadeiras definidas`;

    document.getElementById(
        "camera-2027-total"
    ).textContent =
        `${cameraDefined} definidas`;

    document.getElementById(
        "senate-progress"
    ).textContent =
        `${senateDefined} de 54 eleitos definidos`;

    document.getElementById(
        "senate-2027-total"
    ).textContent =
        `${sumComposition(senate.future) - Number(senate.future.PENDENTE || 0)} de 81 definidas`;

    const complete =
        cameraDefined
        === CAMERA_TOTAL
        && senateDefined
        === SENATE_ELECTED_2026;

    setStatus(
        complete
            ? "Composição carregada com todas as cadeiras da eleição de 2026 já definidas."
            : "Composição carregada. Cadeiras ainda não definidas pelo TSE aparecem como pendentes.",
        complete
            ? "ready"
            : "warning"
    );
}

initializeComposition().catch(
    error => {
        console.error(error);

        setStatus(
            "Não foi possível carregar a composição neste momento.",
            "warning"
        );
    }
);
