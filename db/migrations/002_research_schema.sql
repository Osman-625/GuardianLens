-- GuardianLens P-6 research schema. No application process may fabricate rows here.
begin;

create schema if not exists research;

create table if not exists research.listings (
    id uuid primary key default gen_random_uuid(),
    platform text not null check (platform in ('mudah', 'carousell')),
    collected_on date not null,
    collected_by text not null,
    title_scrubbed text not null,
    description_scrubbed text not null,
    category text not null,
    price numeric(12,2) not null check (price >= 0),
    language text not null check (language in ('ms', 'en', 'mixed')),
    account_age_days integer check (account_age_days >= 0),
    rating numeric(3,2) check (rating between 0 and 5),
    review_count integer check (review_count >= 0),
    active_listing_count integer check (active_listing_count >= 0),
    location_granularity text check (location_granularity in ('state', 'city', 'none')),
    notes text
);

create table if not exists research.listing_images (
    id uuid primary key default gen_random_uuid(),
    listing_id uuid not null references research.listings(id) on delete cascade,
    storage_path text not null,
    sha256 char(64) not null,
    position smallint not null check (position >= 0),
    unique (listing_id, position)
);

create table if not exists research.annotations (
    id uuid primary key default gen_random_uuid(),
    listing_id uuid not null references research.listings(id) on delete cascade,
    annotator_code text not null check (annotator_code in ('A1', 'A2')),
    label text not null check (label in ('fraudulent', 'legitimate', 'uncertain')),
    evidence_type text not null,
    evidence_is_decisive boolean not null,
    evidence_note text not null,
    confidence smallint not null check (confidence between 1 and 5),
    created_at timestamptz not null default now(),
    unique (listing_id, annotator_code)
);

create table if not exists research.adjudications (
    listing_id uuid primary key references research.listings(id) on delete cascade,
    final_label text not null check (final_label in ('fraudulent', 'legitimate', 'excluded')),
    label_source text not null check (label_source in ('agreement', 'adjudicated')),
    decisive_evidence_independent boolean not null check (decisive_evidence_independent = true),
    rationale text not null,
    resolved_at timestamptz not null default now()
);

create table if not exists research.splits (
    listing_id uuid primary key references research.listings(id) on delete cascade,
    split text not null check (split in ('train', 'val', 'test', 'clean_validation')),
    split_version text not null
);

create table if not exists research.study_participants (
    id uuid primary key default gen_random_uuid(),
    participant_code text not null unique,
    group_assignment text not null check (group_assignment in ('G1', 'G2')),
    consent_recorded boolean not null check (consent_recorded = true),
    session_date date not null,
    c2c_experience boolean not null
);

create table if not exists research.study_trials (
    id uuid primary key default gen_random_uuid(),
    participant_id uuid not null references research.study_participants(id) on delete cascade,
    condition text not null check (condition in ('unaided', 'assisted')),
    trial_order smallint not null check (trial_order > 0),
    listing_id uuid not null references research.listings(id),
    participant_judgement text not null check (participant_judgement in ('fraudulent', 'legitimate')),
    correct boolean not null,
    decision_ms integer not null check (decision_ms >= 0),
    confidence smallint not null check (confidence between 1 and 5),
    shown_score smallint check (shown_score between 0 and 100),
    shown_band text check (shown_band in ('low', 'moderate', 'high')),
    unique (participant_id, trial_order)
);

create table if not exists research.study_responses (
    id uuid primary key default gen_random_uuid(),
    participant_id uuid not null references research.study_participants(id) on delete cascade,
    item_key text not null,
    likert smallint not null check (likert between 1 and 5),
    free_text_scrubbed text,
    unique (participant_id, item_key)
);

create or replace function research.enforce_holdout_study_listing()
returns trigger
language plpgsql
security definer
set search_path = research, public
as $$
begin
    if not exists (
        select 1 from research.splits
        where listing_id = new.listing_id and split = 'test'
    ) then
        raise exception 'Study listings must come from the frozen test split';
    end if;
    return new;
end;
$$;

drop trigger if exists study_trials_holdout_only on research.study_trials;
create trigger study_trials_holdout_only
before insert or update of listing_id on research.study_trials
for each row execute function research.enforce_holdout_study_listing();

alter table research.listings enable row level security;
alter table research.listing_images enable row level security;
alter table research.annotations enable row level security;
alter table research.adjudications enable row level security;
alter table research.splits enable row level security;
alter table research.study_participants enable row level security;
alter table research.study_trials enable row level security;
alter table research.study_responses enable row level security;

revoke all on schema research from anon, authenticated;
revoke all on all tables in schema research from anon, authenticated;
grant usage on schema research to authenticated;
grant all on all tables in schema research to authenticated;
grant usage, select on all sequences in schema research to authenticated;

drop policy if exists listings_admin_all on research.listings;
drop policy if exists listing_images_admin_all on research.listing_images;
drop policy if exists annotations_admin_all on research.annotations;
drop policy if exists adjudications_admin_all on research.adjudications;
drop policy if exists splits_admin_all on research.splits;
drop policy if exists study_participants_admin_all on research.study_participants;
drop policy if exists study_trials_admin_all on research.study_trials;
drop policy if exists study_responses_admin_all on research.study_responses;

do $$
declare
    table_name text;
begin
    foreach table_name in array array[
        'listings', 'listing_images', 'annotations', 'adjudications', 'splits',
        'study_participants', 'study_trials', 'study_responses'
    ]
    loop
        execute format(
            'create policy %I on research.%I for all to authenticated using (public.is_guardianlens_admin()) with check (public.is_guardianlens_admin())',
            table_name || '_admin_all', table_name
        );
    end loop;
end
$$;

commit;
