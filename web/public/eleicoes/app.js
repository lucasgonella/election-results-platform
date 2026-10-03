const DATA_URL =
    "/data/go/state-deputy.json";

const PAGE_SIZE = 20;

let allCandidates = [];
let filteredCandidates = [];
let currentPage = 1;


function formatNumber(value) {
    return new Intl.NumberFormat(
        "pt-BR"
    ).format(value ?? 0);
}


function formatPercentage(value) {
    return new Intl.NumberFormat(
        "pt-BR",
        {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }
    ).format(value ?? 0);
}


function render() {
    const container =
        document.getElementById("results");

    const pagination =
        document.getElementById("pagination");

    container.innerHTML = "";
    pagination.innerHTML = "";

    const start =
        (currentPage - 1) * PAGE_SIZE;

    const pageCandidates =
        filteredCandidates.slice(
            start,
            start + PAGE_SIZE
        );

    pageCandidates.forEach(
        (candidate, index) => {

            const position =
                start + index + 1;

            const card =
                document.createElement("article");

            card.className = "candidate";

            card.innerHTML = `
                <div class="position">
                    ${position}
                </div>

                <div class="candidate-main">
                    <div class="candidate-name">
                        ${candidate.ballot_name
                            || candidate.name}
                    </div>

                    <div class="candidate-meta">
                        Nº ${candidate.ballot_number ?? "-"}
                        ·
                        ${candidate.party_acronym ?? "-"}
                    </div>

                    ${
                        candidate.result_status
                        ? `
                        <div class="candidate-status">
                            ${candidate.result_status}
                        </div>
                        `
                        : ""
                    }
                </div>

                <div class="votes">
                    <strong>
                        ${formatNumber(
                            candidate.votes
                        )}
                    </strong>

                    <span>
                        ${formatPercentage(
                            candidate.vote_percentage
                        )}%
                    </span>
                </div>
            `;

            container.appendChild(card);
        }
    );

    const totalPages =
        Math.max(
            1,
            Math.ceil(
                filteredCandidates.length
                / PAGE_SIZE
            )
        );

    const previous =
        document.createElement("button");

    previous.textContent = "Anterior";
    previous.disabled =
        currentPage === 1;

    previous.onclick = () => {
        currentPage -= 1;
        render();
        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    };

    const info =
        document.createElement("span");

    info.textContent =
        `Página ${currentPage} de ${totalPages}`;

    const next =
        document.createElement("button");

    next.textContent = "Próxima";
    next.disabled =
        currentPage >= totalPages;

    next.onclick = () => {
        currentPage += 1;
        render();
        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    };

    pagination.append(
        previous,
        info,
        next
    );
}


async function loadResults() {
    const response =
        await fetch(
            DATA_URL,
            {
                cache: "no-store"
            }
        );

    if (!response.ok) {
        throw new Error(
            `HTTP ${response.status}`
        );
    }

    const data =
        await response.json();

    document.getElementById(
        "sections"
    ).textContent =
        `${formatPercentage(
            data.snapshot.sections.percentage
        )}%`;

    document.getElementById(
        "candidate-count"
    ).textContent =
        formatNumber(
            data.candidate_count
        );

    document.getElementById(
        "updated-at"
    ).textContent =
        `Atualizado em ${new Date(
            data.snapshot.captured_at
        ).toLocaleString("pt-BR")}`;

    allCandidates =
        [...data.candidates].sort(
            (a, b) =>
                (b.votes ?? 0)
                -
                (a.votes ?? 0)
        );

    filteredCandidates =
        allCandidates;

    render();
}


document.getElementById(
    "search"
).addEventListener(
    "input",
    event => {

        const term =
            event.target.value
                .trim()
                .toLowerCase();

        filteredCandidates =
            allCandidates.filter(
                candidate => {

                    const searchable = [
                        candidate.ballot_name,
                        candidate.name,
                        candidate.ballot_number,
                        candidate.party_acronym,
                        candidate.party_name
                    ]
                        .filter(Boolean)
                        .join(" ")
                        .toLowerCase();

                    return searchable.includes(
                        term
                    );
                }
            );

        currentPage = 1;

        render();
    }
);


loadResults().catch(
    error => {

        console.error(error);

        document.getElementById(
            "results"
        ).innerHTML =
            `<div class="error">
                Não foi possível carregar os resultados.
            </div>`;
    }
);
