from __future__ import annotations

from dataclasses import dataclass
import os

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

from .parser import ParsedResult
from .tse_client import TseFetchResult


load_dotenv()


@dataclass(frozen=True, slots=True)
class PersistenceSummary:
    collector_run_id: int
    election_id: int
    scope_id: int
    snapshots_created: int
    candidates_processed: int


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(
            os.getenv(
                "POSTGRES_PORT",
                "5432",
            )
        ),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
        application_name="election-results-collector",
    )


def persist_result(
    fetch_result: TseFetchResult,
    result: ParsedResult,
    *,
    environment: str,
) -> PersistenceSummary:
    candidates_processed = sum(
        len(office.candidates)
        for office in result.offices
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------------------------------
            # Collector run
            # -------------------------------------------------

            office_code = (
                result.offices[0].code
                if len(result.offices) == 1
                else None
            )

            cursor.execute(
                """
                INSERT INTO collector_runs (
                    status,
                    source_url,
                    election_code,
                    scope_code,
                    office_code,
                    http_status,
                    tse_idg,
                    etag,
                    last_modified,
                    payload_sha256,
                    candidates_processed,
                    finished_at
                )
                VALUES (
                    'success',
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW()
                )
                RETURNING id
                """,
                (
                    fetch_result.url,
                    result.election_code,
                    result.scope_code,
                    office_code,
                    fetch_result.status_code,
                    result.tse_idg,
                    fetch_result.etag,
                    fetch_result.last_modified,
                    fetch_result.sha256,
                    candidates_processed,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not create collector run."
                )

            collector_run_id = row[0]

            # -------------------------------------------------
            # Election
            # -------------------------------------------------

            cursor.execute(
                """
                INSERT INTO elections (
                    tse_election_code,
                    round_number,
                    environment
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (
                    tse_election_code,
                    environment
                )
                DO UPDATE SET
                    round_number = EXCLUDED.round_number
                RETURNING id
                """,
                (
                    result.election_code,
                    result.round_number,
                    environment,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not upsert election."
                )

            election_id = row[0]

            # -------------------------------------------------
            # Scope
            # -------------------------------------------------

            uf = None

            if (
                result.scope_type == "uf"
                and len(result.scope_code) == 2
            ):
                uf = result.scope_code.upper()

            cursor.execute(
                """
                INSERT INTO scopes (
                    scope_type,
                    code,
                    uf
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (
                    scope_type,
                    code
                )
                DO UPDATE SET
                    uf = EXCLUDED.uf
                RETURNING id
                """,
                (
                    result.scope_type,
                    result.scope_code,
                    uf,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not upsert scope."
                )

            scope_id = row[0]

            snapshots_created = 0

            # -------------------------------------------------
            # Offices
            # -------------------------------------------------

            for office in result.offices:

                cursor.execute(
                    """
                    INSERT INTO offices (
                        tse_code,
                        name,
                        seats
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (tse_code)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        seats = EXCLUDED.seats
                    RETURNING id
                    """,
                    (
                        office.code,
                        office.name,
                        office.seats,
                    ),
                )

                row = cursor.fetchone()

                if row is None:
                    raise RuntimeError(
                        "Could not upsert office."
                    )

                office_id = row[0]

                # ---------------------------------------------
                # Scope snapshot
                # ---------------------------------------------

                stats = result.stats

                cursor.execute(
                    """
                    INSERT INTO scope_snapshots (
                        election_id,
                        scope_id,
                        office_id,
                        collector_run_id,
                        tse_idg,

                        generated_at,
                        totalized_at,

                        sections_total,
                        sections_totalized,
                        sections_percentage,

                        electorate_total,
                        electorate_totalized,

                        turnout,
                        turnout_percentage,

                        abstentions,
                        abstention_percentage,

                        votes_total,
                        candidate_valid_votes,
                        valid_votes,

                        blank_votes,
                        null_votes
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (
                        election_id,
                        scope_id,
                        office_id,
                        tse_idg
                    )
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        election_id,
                        scope_id,
                        office_id,
                        collector_run_id,
                        result.tse_idg,

                        result.generated_at,
                        result.totalized_at,

                        stats.sections_total,
                        stats.sections_totalized,
                        stats.sections_percentage,

                        stats.electorate_total,
                        stats.electorate_totalized,

                        stats.turnout,
                        stats.turnout_percentage,

                        stats.abstentions,
                        stats.abstention_percentage,

                        stats.votes_total,
                        stats.candidate_valid_votes,
                        stats.valid_votes,

                        stats.blank_votes,
                        stats.null_votes,
                    ),
                )

                row = cursor.fetchone()

                if row is None:
                    cursor.execute(
                        """
                        SELECT id
                        FROM scope_snapshots
                        WHERE election_id = %s
                          AND scope_id = %s
                          AND office_id = %s
                          AND tse_idg = %s
                        """,
                        (
                            election_id,
                            scope_id,
                            office_id,
                            result.tse_idg,
                        ),
                    )

                    row = cursor.fetchone()

                    if row is None:
                        raise RuntimeError(
                            "Could not find existing snapshot."
                        )

                    scope_snapshot_id = row[0]

                else:
                    scope_snapshot_id = row[0]
                    snapshots_created += 1

                # ---------------------------------------------
                # Candidates
                # ---------------------------------------------

                for candidate in office.candidates:

                    cursor.execute(
                        """
                        INSERT INTO candidates (
                            election_id,
                            scope_id,
                            office_id,

                            tse_candidate_seq,
                            display_order,
                            ballot_number,

                            name,
                            ballot_name,
                            birth_date,

                            party_number,
                            party_acronym,
                            party_name,

                            alliance_name,

                            candidate_status,
                            result_status,
                            elected,

                            running_mates
                        )
                        VALUES (
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s,
                            %s, %s, %s,
                            %s
                        )
                        ON CONFLICT (
                            election_id,
                            scope_id,
                            office_id,
                            tse_candidate_seq
                        )
                        DO UPDATE SET
                            display_order =
                                EXCLUDED.display_order,

                            ballot_number =
                                EXCLUDED.ballot_number,

                            name =
                                EXCLUDED.name,

                            ballot_name =
                                EXCLUDED.ballot_name,

                            birth_date =
                                EXCLUDED.birth_date,

                            party_number =
                                EXCLUDED.party_number,

                            party_acronym =
                                EXCLUDED.party_acronym,

                            party_name =
                                EXCLUDED.party_name,

                            alliance_name =
                                EXCLUDED.alliance_name,

                            candidate_status =
                                EXCLUDED.candidate_status,

                            result_status =
                                EXCLUDED.result_status,

                            elected =
                                EXCLUDED.elected,

                            running_mates =
                                EXCLUDED.running_mates,

                            updated_at = NOW()

                        RETURNING id
                        """,
                        (
                            election_id,
                            scope_id,
                            office_id,

                            candidate.tse_candidate_seq,
                            candidate.display_order,
                            candidate.ballot_number,

                            candidate.name,
                            candidate.ballot_name,
                            candidate.birth_date,

                            candidate.party_number,
                            candidate.party_acronym,
                            candidate.party_name,

                            candidate.alliance_name,

                            candidate.candidate_status,
                            candidate.result_status,
                            candidate.elected,

                            Jsonb(
                                list(
                                    candidate.running_mates
                                )
                            ),
                        ),
                    )

                    row = cursor.fetchone()

                    if row is None:
                        raise RuntimeError(
                            "Could not upsert candidate."
                        )

                    candidate_id = row[0]

                    # -----------------------------------------
                    # Candidate snapshot
                    # -----------------------------------------

                    cursor.execute(
                        """
                        INSERT INTO candidate_result_snapshots (
                            scope_snapshot_id,
                            candidate_id,

                            votes,
                            vote_percentage,

                            candidate_status,
                            result_status,
                            elected
                        )
                        VALUES (
                            %s, %s,
                            %s, %s,
                            %s, %s, %s
                        )
                        ON CONFLICT (
                            scope_snapshot_id,
                            candidate_id
                        )
                        DO UPDATE SET
                            votes =
                                EXCLUDED.votes,

                            vote_percentage =
                                EXCLUDED.vote_percentage,

                            candidate_status =
                                EXCLUDED.candidate_status,

                            result_status =
                                EXCLUDED.result_status,

                            elected =
                                EXCLUDED.elected
                        """,
                        (
                            scope_snapshot_id,
                            candidate_id,

                            candidate.votes,
                            candidate.vote_percentage,

                            candidate.candidate_status,
                            candidate.result_status,
                            candidate.elected,
                        ),
                    )

        connection.commit()

    return PersistenceSummary(
        collector_run_id=collector_run_id,
        election_id=election_id,
        scope_id=scope_id,
        snapshots_created=snapshots_created,
        candidates_processed=candidates_processed,
    )
